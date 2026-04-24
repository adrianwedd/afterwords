"""Afterwords — local voice-cloning TTS server for Claude Code.

Zero-shot voice cloning via Qwen3-TTS on Apple Silicon (MLX).
Serves WAV audio over HTTP. Auto-discovers voices from voices/ directory.

Usage:
    source .venv/bin/activate
    python server.py [--port 7860]
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import logging
import os
import threading
import time
import warnings

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import backends
from backends.base import PreparedVoice, RefTextPolicy, _read_only


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    backend: str
    ref_audio: str
    ref_text: str | None
    session_id: str | None
    emotion: str
    quality: str | None
    duration_s: float | None
    confidence: float | None
    sequence: int | None
    extras: Mapping[str, object]
    prepared: PreparedVoice

    def __post_init__(self):
        if not isinstance(self.extras, MappingProxyType):
            object.__setattr__(self, "extras", _read_only(self.extras))


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tts")

# Suppress known harmless warnings from mlx-audio model loading
warnings.filterwarnings("ignore", message=".*model of type.*qwen3_tts.*")
warnings.filterwarnings("ignore", message=".*incorrect regex pattern.*")
logging.getLogger("transformers.modeling_utils").setLevel(logging.ERROR)
logging.getLogger("transformers.tokenization_utils_base").setLevel(logging.ERROR)

import tempfile
from contextlib import asynccontextmanager


def _cleanup_current_voices():
    """Delete cleanup_paths + owned temp audio for all currently-loaded voices.
    Called during shutdown only — never inline during reload (see Item 3 design)."""
    for profile in VOICES.values():
        for path in profile.prepared.cleanup_paths:
            try:
                os.remove(path)
            except OSError:
                pass
        if (profile.prepared.owns_temp_audio
                and profile.prepared.ref_audio_path.startswith(tempfile.gettempdir())):
            try:
                os.remove(profile.prepared.ref_audio_path)
            except OSError:
                pass


def _sweep_orphaned_temp_files():
    """Delete VoxCPM-resample temp files from any prior crashed run. Best-effort.
    MUST run before _load_voice_profiles to avoid deleting fresh temps."""
    for path in glob.glob(os.path.join(tempfile.gettempdir(), "voxcpm-ref-*.wav")):
        try:
            os.remove(path)
        except OSError:
            pass


@asynccontextmanager
async def lifespan(app):
    # startup body runs after main()'s sync setup — no-op here
    yield
    # shutdown body
    _cleanup_current_voices()


app = FastAPI(title="Afterwords TTS", lifespan=lifespan)

_VOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")

# Voice registry: name → (ref_audio_path, ref_text)
# Adding voices costs zero extra memory — the model is loaded once,
# each voice is just a ~700KB WAV + transcript string.
# All voices are auto-discovered from JSON profiles in voices/.
VOICES: dict[str, VoiceProfile] = {}


def _build_voice_profile(profile_path: str) -> VoiceProfile | None:
    """Build a single VoiceProfile from a JSON path. Returns None if the profile
    should be skipped (missing ref, invalid extras, etc.) — logs the reason.
    Raises if `prepare_voice()` itself fails — callers decide recovery policy."""
    try:
        with open(profile_path) as f:
            p = json.load(f)
    except Exception as exc:
        log.warning("voice profile unreadable: %s: %s", profile_path, exc)
        return None

    stem = os.path.splitext(os.path.basename(profile_path))[0]
    if stem.endswith("-profile"):
        stem = stem[:-8]
    name = p.get("name") or stem
    backend_name = p.get("backend", "qwen3-0.6b")

    try:
        backend = backends.get(backend_name)
    except KeyError:
        log.warning(
            "voice %r references unregistered backend %r — skipping",
            name, backend_name,
        )
        return None

    ref_rel = p.get("reference_audio", f"{stem}-ref.wav")
    ref_audio = os.path.join(_VOICES_DIR, ref_rel)
    if not os.path.exists(ref_audio):
        log.warning("voice %r missing ref audio %s — skipping", name, ref_audio)
        return None

    ref_text = p.get("reference_text") or None
    if backend.ref_text_policy == RefTextPolicy.REQUIRED and not ref_text:
        log.warning(
            "voice %r: backend %r REQUIRES ref_text but profile has none — skipping",
            name, backend_name,
        )
        return None

    extras = p.get("synthesis_extras", {}) or {}
    try:
        backend.validate_extras(extras)
    except ValueError as exc:
        log.warning("voice %r: invalid extras: %s — skipping", name, exc)
        return None

    prepared = backend.prepare_voice(ref_audio, ref_text, extras)

    return VoiceProfile(
        name=name,
        backend=backend_name,
        ref_audio=ref_audio,
        ref_text=ref_text,
        session_id=p.get("session_id"),
        emotion=p.get("emotion", "neutral"),
        quality=p.get("quality"),
        duration_s=p.get("duration_s"),
        confidence=p.get("transcript_confidence"),
        sequence=p.get("sequence"),
        extras=_read_only(extras),
        prepared=prepared,
    )


def _load_voice_profiles() -> None:
    """Walk voices/*.json and populate VOICES. Called after backends are loaded."""
    for profile_path in glob.glob(os.path.join(_VOICES_DIR, "*.json")):
        try:
            profile = _build_voice_profile(profile_path)
        except Exception as exc:
            log.warning("voice profile %s: prepare_voice failed: %s", profile_path, exc)
            continue
        if profile is not None:
            VOICES[profile.name] = profile

DEFAULT_VOICE = "galadriel"

# Locks for thread-safe VOICES access and serialised synthesis.
_model_lock = threading.Lock()
_synth_lock = threading.Lock()  # serialise synthesis — MLX/Metal is not thread-safe
_ready = threading.Event()
_clone_enabled = False

def _register_voice(
    name: str,
    backend_name: str,
    ref_audio: str,
    ref_text: str | None,
    prepared: PreparedVoice,
    emotion: str = "neutral",
    metadata: dict | None = None,
):
    """Thread-safe runtime voice registration. Builds a VoiceProfile."""
    meta = metadata or {}
    profile = VoiceProfile(
        name=name,
        backend=backend_name,
        ref_audio=ref_audio,
        ref_text=ref_text,
        session_id=meta.get("session_id") or (name.rsplit("-", 1)[0] if "-" in name else name),
        emotion=emotion,
        quality=meta.get("quality"),
        duration_s=meta.get("duration_s"),
        confidence=meta.get("confidence"),
        sequence=meta.get("sequence"),
        extras=_read_only(meta.get("extras", {})),
        prepared=prepared,
    )
    with _model_lock:
        VOICES[name] = profile


def _unregister_session(session_id: str):
    """Remove all voice profiles for a session + their files + any backend cleanup artifacts."""
    with _model_lock:
        to_remove = [
            name for name, profile in VOICES.items()
            if profile.session_id == session_id
        ]
        for name in to_remove:
            profile = VOICES.pop(name)
            # Delete backend-created temp artifacts (resampled refs, cached embeddings).
            for path in profile.prepared.cleanup_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
            if profile.prepared.owns_temp_audio:
                try:
                    os.remove(profile.prepared.ref_audio_path)
                except OSError:
                    pass
            # Delete the checked-in voice assets (unchanged behaviour).
            for ext in ("-ref.wav", ".json"):
                path = os.path.join(_VOICES_DIR, f"{name}{ext}")
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass



def _resolve_voice(voice: str, emotion: str | None = None) -> VoiceProfile | None:
    """Return VoiceProfile for a voice name, honouring session palettes + emotion fallback."""
    with _model_lock:
        # Exact match first
        if voice in VOICES:
            profile = VOICES[voice]
            if emotion is None or profile.emotion == emotion:
                return profile

        # Session palette lookup — match by VoiceProfile.session_id field
        if emotion:
            candidates = [
                p for p in VOICES.values()
                if p.session_id == voice and p.emotion == emotion
            ]
            if candidates:
                return max(
                    candidates,
                    key=lambda p: (p.duration_s or 0, p.confidence or 0),
                )
            session_entries = [p for p in VOICES.values() if p.session_id == voice]
            if session_entries:
                return max(
                    session_entries,
                    key=lambda p: (p.duration_s or 0, p.confidence or 0),
                )

        return VOICES.get(voice)


def _warmup():
    """Prime MLX caches by generating a tiny synth against the default voice."""
    profile = VOICES.get(DEFAULT_VOICE)
    if profile is None:
        log.warning("default voice '%s' not loaded — skipping warmup", DEFAULT_VOICE)
        return
    backend = backends.get(profile.backend)
    log.info("warming up with %s (backend=%s)...", DEFAULT_VOICE, profile.backend)
    t0 = time.time()
    try:
        with _synth_lock:
            backend.synthesize("Hello.", profile.prepared, lang="en")
        log.info("warmup done in %.1fs", time.time() - t0)
    except Exception as exc:
        log.warning("warmup failed (non-fatal): %s", exc)


@app.get("/health")
def health():
    with _model_lock:
        voice_names = sorted(VOICES.keys())
        backend_counts: dict[str, int] = {}
        for profile in VOICES.values():
            backend_counts[profile.backend] = backend_counts.get(profile.backend, 0) + 1
        default_profile = VOICES.get(DEFAULT_VOICE)

    loaded_backends = {}
    for bname in backends.names():
        b = backends.get(bname)
        loaded_backends[bname] = {
            "loaded": True,
            "voice_count": backend_counts.get(bname, 0),
            "sample_rate": b.sample_rate,
            "display_name": b.display_name,
            "supported_langs": list(b.supported_langs),
        }

    default_backend_name = default_profile.backend if default_profile else "qwen3-0.6b"
    try:
        default_model_id = getattr(
            backends.get(default_backend_name), "model_id", default_backend_name
        )
    except KeyError:
        default_model_id = default_backend_name

    return {
        "status": "ok",
        "model": default_model_id,
        "backend": "mlx",
        "model_loaded": _ready.is_set(),
        "ready": _ready.is_set(),
        "voices": voice_names,
        "default_voice": DEFAULT_VOICE,
        "loaded_backends": loaded_backends,
    }


def _synthesize_audio(text: str, profile: VoiceProfile, lang: str) -> Response:
    """Core synthesis — dispatches to the voice's pinned backend."""
    log.info("synthesize: %d chars, voice=%s, backend=%s",
             len(text), profile.name, profile.backend)
    try:
        backend = backends.get(profile.backend)
    except KeyError:
        log.error("voice %r references unknown backend %r at dispatch time",
                  profile.name, profile.backend)
        return JSONResponse(
            {"error": f"backend not loaded: {profile.backend}"},
            status_code=500,
        )

    t0 = time.time()
    try:
        with _synth_lock:
            data, sr = backend.synthesize(text, profile.prepared, lang)
    except ValueError as exc:
        return JSONResponse(
            {"error": str(exc),
             "voice_backend": profile.backend,
             "supported_langs": list(backend.supported_langs)},
            status_code=400,
        )
    except Exception as exc:
        log.error("synthesis failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "synthesis failed"}, status_code=500)

    elapsed = time.time() - t0
    duration = len(data) / sr if sr else 0

    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV", subtype="PCM_16")
    buf.seek(0)
    log.info(
        "done: %.1fs audio in %.1fs (RTF=%.2fx)",
        duration, elapsed, elapsed / duration if duration > 0 else 0,
    )
    return Response(
        content=buf.read(),
        media_type="audio/wav",
        headers={
            "X-Synthesis-Time": f"{elapsed:.3f}",
            "X-Duration": f"{duration:.3f}",
            "X-Sample-Rate": str(sr),
            "X-Backend": profile.backend,
        },
    )


@app.get("/synthesize")
def synthesize(
    text: str = Query(..., description="Text to speak"),
    voice: str = Query(DEFAULT_VOICE, description="Voice name"),
    lang: str = Query("en", description="BCP-47 language code; must be supported by the voice's backend"),
):
    """Generate speech from text using cloned voice, return WAV audio."""
    if not text.strip():
        return JSONResponse({"error": "text is empty"}, status_code=400)
    if len(text) > 5000:
        return JSONResponse({"error": "text too long (max 5000 chars)"}, status_code=400)

    if not _ready.is_set():
        return JSONResponse({"error": "server warming up, try again shortly"}, status_code=503)

    profile = _resolve_voice(voice)
    if profile is None:
        return JSONResponse(
            {"error": f"unknown voice: {voice}", "available": sorted(VOICES.keys())},
            status_code=400)

    return _synthesize_audio(text, profile, lang)


class SynthesizeRequest(BaseModel):
    text: str
    voice: str
    emotion: str | None = None
    lang: str = "en"


@app.post("/synthesize")
def synthesize_post(body: SynthesizeRequest):
    """POST version of /synthesize — accepts JSON body for sensitive text."""
    if not _clone_enabled:
        return JSONResponse({"error": "clone not enabled (start with --allow-clone)"}, status_code=404)
    if not body.text.strip():
        return JSONResponse({"error": "text is empty"}, status_code=400)
    if len(body.text) > 5000:
        return JSONResponse({"error": "text too long (max 5000 chars)"}, status_code=400)
    if not _ready.is_set():
        return JSONResponse({"error": "server warming up, try again shortly"}, status_code=503)

    profile = _resolve_voice(body.voice, emotion=body.emotion)
    if profile is None:
        return JSONResponse(
            {"error": f"unknown voice: {body.voice}", "available": sorted(VOICES.keys())},
            status_code=400)

    return _synthesize_audio(body.text, profile, body.lang)


@app.post("/clone")
async def clone_voice_endpoint(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    emotion: str = Form("neutral"),
    transcript: str | None = Form(None),
    backend: str = Form("qwen3-1.7b"),
):
    """Create a voice profile from raw audio. Denoises, optionally transcribes, registers."""
    if not _clone_enabled:
        return JSONResponse({"error": "clone not enabled (start with --allow-clone)"}, status_code=404)

    audio_bytes = await audio.read()
    if len(audio_bytes) < 1000:
        return JSONResponse({"error": "audio too short"}, status_code=400)

    try:
        backend_obj = backends.get(backend)
    except KeyError:
        return JSONResponse(
            {"error": f"unknown backend: {backend}", "available": backends.names()},
            status_code=400,
        )

    try:
        import tempfile
        import noisereduce as nr

        # Save uploaded audio to temp file.
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
            tmp_in.write(audio_bytes)
            tmp_in_path = tmp_in.name

        # --- Phase 1: denoise under _synth_lock (noisereduce may touch Metal) ---
        with _synth_lock:
            data, sr_in = sf.read(tmp_in_path)
            if data.ndim > 1:
                data = data.mean(axis=1)
            reduced = nr.reduce_noise(y=data, sr=sr_in, stationary=True, prop_decrease=0.7)
            peak = np.max(np.abs(reduced))
            if peak > 0:
                reduced = reduced * (0.9 / peak)
        # --- lock released ---

        duration_s = len(reduced) / sr_in
        if duration_s < 1.0:
            os.unlink(tmp_in_path)
            return JSONResponse(
                {"error": "audio too short after processing (< 1s)"},
                status_code=400,
            )

        quality = "rough" if duration_s < 5 else "developing" if duration_s < 15 else "good"

        # --- Phase 2: CPU-only work (no lock for heavy work) — write WAV + transcribe ---
        # Compute seq + reserve ref_path under _model_lock so concurrent clones for the same
        # session_id don't collide. We reserve by touching an empty file before releasing the lock.
        with _model_lock:
            seq = len([k for k in VOICES if k.startswith(f'{session_id}-')]) + 1
            ref_path = os.path.join(_VOICES_DIR, f"{session_id}-{seq:03d}-ref.wav")
            # Bump seq while the chosen ref_path already exists on disk (e.g. from a failed
            # clone that didn't clean up). Rare but cheap.
            while os.path.exists(ref_path):
                seq += 1
                ref_path = os.path.join(_VOICES_DIR, f"{session_id}-{seq:03d}-ref.wav")
            voice_name = os.path.basename(ref_path)[:-len("-ref.wav")]
            # Reserve the path so a concurrent clone won't pick the same seq.
            open(ref_path, "wb").close()
        # Lock released — heavy CPU work (sf.write, whisper) runs unlocked.

        tmp_ref = ref_path + ".tmp"
        sf.write(tmp_ref, reduced, sr_in, format="WAV", subtype="PCM_16")
        os.rename(tmp_ref, ref_path)

        transcript_confidence = 0.0
        if not transcript:
            try:
                from faster_whisper import WhisperModel
                whisper = WhisperModel("base.en", compute_type="int8")
                segments, _ = whisper.transcribe(tmp_in_path)
                words = []
                for seg in segments:
                    for w in seg.words or []:
                        words.append(w.word.strip())
                transcript = " ".join(words)
                transcript_confidence = 0.8
            except Exception as exc:
                log.warning("transcription failed, using empty transcript: %s", exc)
                transcript = ""
        else:
            transcript_confidence = 0.9

        # REQUIRED-policy backends need a transcript.
        if backend_obj.ref_text_policy == RefTextPolicy.REQUIRED and not transcript:
            os.unlink(tmp_in_path)
            try:
                os.unlink(ref_path)
            except OSError:
                pass
            return JSONResponse(
                {"error": f"backend {backend} requires ref_text; transcription failed"},
                status_code=400,
            )

        # --- Phase 3: validate_extras + prepare_voice under _synth_lock (both may touch Metal) ---
        extras: dict = {}
        with _synth_lock:
            try:
                backend_obj.validate_extras(extras)
            except ValueError as exc:
                os.unlink(tmp_in_path)
                try:
                    os.unlink(ref_path)
                except OSError:
                    pass
                return JSONResponse(
                    {"error": f"invalid extras for backend {backend}: {exc}"},
                    status_code=400,
                )
            try:
                prepared = backend_obj.prepare_voice(ref_path, transcript or None, extras)
            except Exception as exc:
                log.error("prepare_voice failed: %s", exc, exc_info=True)
                os.unlink(tmp_in_path)
                try:
                    os.unlink(ref_path)
                except OSError:
                    pass
                return JSONResponse(
                    {"error": f"prepare_voice failed: {exc}"},
                    status_code=500,
                )
        # --- lock released ---

        # Save profile JSON with backend field.
        profile_path = os.path.join(_VOICES_DIR, f"{voice_name}.json")
        tmp_profile = profile_path + ".tmp"
        with open(tmp_profile, "w") as f:
            json.dump({
                "name": voice_name,
                "backend": backend,
                "session_id": session_id,
                "emotion": emotion,
                "reference_audio": os.path.basename(ref_path),
                "reference_text": transcript,
                "quality": quality,
                "duration_s": round(duration_s, 1),
                "transcript_confidence": round(transcript_confidence, 2),
                "sequence": seq,
            }, f, indent=2)
        os.rename(tmp_profile, profile_path)

        # Register in runtime registry.
        _register_voice(
            voice_name,
            backend_name=backend,
            ref_audio=ref_path,
            ref_text=transcript or None,
            prepared=prepared,
            emotion=emotion,
            metadata={
                "session_id": session_id,
                "quality": quality,
                "duration_s": duration_s,
                "confidence": transcript_confidence,
                "sequence": seq,
            },
        )

        os.unlink(tmp_in_path)
        log.info(
            "cloned: %s (backend=%s, session=%s, emotion=%s, quality=%s, %.1fs)",
            voice_name, backend, session_id, emotion, quality, duration_s,
        )

        return {
            "voice": voice_name,
            "backend": backend,
            "emotion": emotion,
            "quality": quality,
            "transcript_confidence": round(transcript_confidence, 2),
            "duration_s": round(duration_s, 1),
            "sequence": seq,
        }
    except Exception as exc:
        log.error("clone failed: %s", exc, exc_info=True)
        # Best-effort cleanup of any artifacts created before the failure.
        try:
            if 'tmp_in_path' in locals():
                os.unlink(tmp_in_path)
        except OSError:
            pass
        try:
            if 'ref_path' in locals():
                os.unlink(ref_path)
        except OSError:
            pass
        return JSONResponse({"error": f"clone failed: {exc}"}, status_code=500)


@app.delete("/session/{session_id}")
def delete_session(session_id: str):
    """Remove all voice palette entries and files for a session."""
    if not _clone_enabled:
        return JSONResponse({"error": "clone not enabled (start with --allow-clone)"}, status_code=404)
    _unregister_session(session_id)
    log.info("session cleaned up: %s", session_id)
    return {"status": "ok", "session_id": session_id}


def main():
    parser = argparse.ArgumentParser(description="Afterwords TTS server (MLX)")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--no-warmup", action="store_true", help="Skip warmup synthesis")
    parser.add_argument(
        "--allow-clone",
        action="store_true",
        help="Enable /clone, POST /synthesize, DELETE /session (binds to 127.0.0.1)",
    )
    args = parser.parse_args()

    global DEFAULT_VOICE, _clone_enabled
    if args.allow_clone:
        _clone_enabled = True
        if args.host == "0.0.0.0":
            args.host = "127.0.0.1"
            log.info("--allow-clone: binding to 127.0.0.1 for security")
    # 1. Register all backends.
    backends.register_all()
    log.info("registered backends: %s", backends.names())

    # 2. Load all backend weights (unconditional preload, per design D6).
    #    Sequential + logged — takes 60-180s cold; operator visibility matters.
    for bname in backends.names():
        b = backends.get(bname)
        t0 = time.time()
        log.info("loading backend %s (%s)...", bname, b.display_name)
        try:
            b.load()
        except Exception as exc:
            log.error("backend %s failed to load: %s", bname, exc, exc_info=True)
            raise SystemExit(1)
        log.info("backend %s loaded in %.1fs", bname, time.time() - t0)

    # Clean up any VoxCPM temp files orphaned by a previous crashed run.
    _sweep_orphaned_temp_files()

    # 3. Walk voices/*.json — profile loader calls prepare_voice() (can need loaded weights).
    _load_voice_profiles()

    # 4. Prune voices whose ref audio vanished between load attempts (defensive).
    missing = [v for v, p in VOICES.items() if not os.path.exists(p.ref_audio)]
    for vname in missing:
        log.warning("Reference audio not found for '%s' — skipping", vname)
        del VOICES[vname]
    if not VOICES:
        log.error("No voices available — add ref WAVs to voices/")
        raise SystemExit(1)
    if DEFAULT_VOICE not in VOICES:
        DEFAULT_VOICE = next(iter(VOICES))
        log.warning("Default voice pruned — using '%s'", DEFAULT_VOICE)

    log.info("afterwords starting on %s:%d", args.host, args.port)
    log.info("voices: %d loaded (default: %s)", len(VOICES), DEFAULT_VOICE)

    # 5. Warmup (skippable via --no-warmup; does NOT skip backend loads — those are mandatory per D6).
    if not args.no_warmup:
        try:
            _warmup()
        except Exception as exc:
            log.warning("warmup encountered an error: %s", exc)
    _ready.set()
    log.info("ready — %d voices, accepting requests", len(VOICES))

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
