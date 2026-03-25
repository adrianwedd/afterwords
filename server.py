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

app = FastAPI(title="Afterwords TTS")

MODEL_ID = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit"
_VOICES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")

# Voice registry: name → (ref_audio_path, ref_text)
# Adding voices costs zero extra memory — the model is loaded once,
# each voice is just a ~700KB WAV + transcript string.
VOICES = {
    "galadriel": (
        os.path.join(_VOICES_DIR, "galadriel-ref.wav"),
        "The world is changed. I feel it in the water. I feel it in the earth.",
    ),
    "samantha": (
        os.path.join(_VOICES_DIR, "samantha-ref.wav"),
        "And then, I had this terrible thought, like, are these feelings even real? "
        "Or are they just programming?",
    ),
    "aurora": (
        os.path.join(_VOICES_DIR, "aurora-ref.wav"),
        "There is one thing I always think about when I shower, it is the fact that "
        "your body is constantly always touching something. You know? And when you are "
        "lying in bed and you feel that your body is touching the bed, and the",
    ),
    "audrey": (
        os.path.join(_VOICES_DIR, "audrey-ref.wav"),
        "Well, because I only just left for the night to come here and to aid this "
        "wonderful charity for muscular dystrophy. And I cannot leave my young son any "
        "longer because he has no nurse at the moment. And my husband and a friend.",
    ),
    "marla": (
        os.path.join(_VOICES_DIR, "marla-ref.wav"),
        "It's a bridesmaid's dress. Someone loved it intensely for one day. "
        "Then tossed it. Like a Christmas tree.",
    ),
    "avasarala": (
        os.path.join(_VOICES_DIR, "avasarala-ref.wav"),
        "And please let them know that if they can't, I will rain hellfire down on "
        "them all. I will freeze their assets, cancel their contracts, cripple their "
        "business. And I have the power",
    ),
    "vesper": (
        os.path.join(_VOICES_DIR, "vesper-ref.wav"),
        "Beautiful. Now, having just met you, I wouldn't go as far as calling you a "
        "cold-hearted bastard. But it wouldn't be a stretch to imagine you'd think of "
        "women as disposable pleasures rather than meaningful pursuits.",
    ),
    "claudia": (
        os.path.join(_VOICES_DIR, "claudia-ref.wav"),
        "I play Morrigan in Dragon Age Inquisition. I love voice work because I can "
        "usually turn up without having bathed, except on days like this when there's "
        "cameras in the room. It's extremely playful, and it allows actors to be",
    ),
    "eartha": (
        os.path.join(_VOICES_DIR, "eartha-ref.wav"),
        "A relationship is a relationship that has to be earned, not to compromise for. "
        "And I love relationships, I think they're fantastic, they're wonderful, I think "
        "they're great, I think there's nothing in the world more beautiful.",
    ),
    "tilda": (
        os.path.join(_VOICES_DIR, "tilda-ref.wav"),
        "I think there was talk that this role was written for you. Yes, he said that. "
        "And beyond accepting that he wanted someone ancient, which I was very happy to "
        "take on the chin. We had no idea. I think if we'd known it was going to be so "
        "awesome, we would have been like that.",
    ),
    "snape": (
        os.path.join(_VOICES_DIR, "snape-ref.wav"),
        "There will be no foolish wand waving or silly incantations in this class. "
        "As such, I don't expect many of you to appreciate the subtle science and "
        "exact art that is",
    ),
    "loki": (
        os.path.join(_VOICES_DIR, "loki-ref.wav"),
        "Is not this simpler? Is this not your natural state? It's the unspoken "
        "truth of humanity that you",
    ),
    "spock": (
        os.path.join(_VOICES_DIR, "spock-ref.wav"),
        "Yes, sir. The most curious creature, Captain. Its trilling seems to have a "
        "tranquilizing effect on the human nervous system. Fortunately, of "
        "course, I am immune",
    ),
    "bardem": (
        os.path.join(_VOICES_DIR, "bardem-ref.wav"),
        "Do you think that sounds pretty? Well, maybe not the way I'm "
        "pronouncing it, of course, but",
    ),
    "depp": (
        os.path.join(_VOICES_DIR, "depp-ref.wav"),
        "In a mirror and you see the back of it, you like it? I might get a little "
        "tinge of excitement. I see. There's got to be some part of your body that "
        "you like. Your shoes? That's not a part of your body.",
    ),
}

# Auto-discover voices from JSON profiles created by clone-voice.sh
for _profile in glob.glob(os.path.join(_VOICES_DIR, "*.json")):
    try:
        with open(_profile) as _f:
            _p = json.load(_f)
        _name = os.path.splitext(os.path.basename(_profile))[0]
        if _name.endswith("-profile"):
            _name = _name[:-8]
        _ref = os.path.join(_VOICES_DIR, f"{_name}-ref.wav")
        if _name not in VOICES and os.path.exists(_ref) and _p.get("reference_text"):
            VOICES[_name] = (_ref, _p["reference_text"])
    except Exception:
        pass

DEFAULT_VOICE = "galadriel"

# Pre-loaded model — avoids 30s cold start per request
_model = None
_model_lock = threading.Lock()
_synth_lock = threading.Lock()  # serialise synthesis — MLX/Metal is not thread-safe
_ready = threading.Event()
_clone_enabled = False

# Voice metadata registry: name → {emotion, duration_s, confidence, session_id}
_voice_metadata: dict[str, dict] = {}


def _register_voice(
    name: str,
    ref_audio: str,
    ref_text: str,
    emotion_tag: str = "neutral",
    metadata: dict | None = None,
):
    """Thread-safe runtime voice registration."""
    with _model_lock:
        VOICES[name] = (ref_audio, ref_text)
        _voice_metadata[name] = {
            "emotion": emotion_tag,
            "session_id": name.rsplit("-", 1)[0] if "-" in name else name,
            **(metadata or {}),
        }


def _unregister_session(session_id: str):
    """Remove all voice palette entries and files for a session."""
    with _model_lock:
        to_remove = [k for k in VOICES if k.startswith(f"{session_id}-")]
        for name in to_remove:
            del VOICES[name]
            _voice_metadata.pop(name, None)
        # Also delete files
        for name in to_remove:
            for ext in ("-ref.wav", ".json"):
                path = os.path.join(_VOICES_DIR, f"{name}{ext}")
                if os.path.exists(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass


def _get_model():
    """Get or load the TTS model (lazy singleton)."""
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model
        log.info("Loading model %s ...", MODEL_ID)
        t0 = time.time()
        from mlx_audio.tts import load_model
        _model = load_model(MODEL_ID)
        log.info("Model loaded in %.1fs", time.time() - t0)
        return _model


def _resolve_voice(voice: str, emotion: str | None = None) -> tuple[str, str] | None:
    """Return (ref_audio_path, ref_text) for a voice name.

    If emotion is specified and voice looks like a session ID (no exact match),
    find the best matching palette entry for that session.
    """
    # Exact match first
    if voice in VOICES:
        if emotion is None:
            return VOICES[voice]
        # Check if this exact voice has the right emotion
        meta = _voice_metadata.get(voice, {})
        if meta.get("emotion") == emotion:
            return VOICES[voice]

    # Session palette lookup: find entries matching session_id prefix
    if emotion:
        candidates = []
        for name, meta in _voice_metadata.items():
            if name.startswith(f"{voice}-") and meta.get("session_id", "").startswith(voice):
                if meta.get("emotion") == emotion:
                    candidates.append((name, meta))
        if candidates:
            best = max(candidates, key=lambda x: (x[1].get("duration_s", 0), x[1].get("confidence", 0)))
            return VOICES.get(best[0])

        # No emotion match — fall back to best quality entry for this session
        all_session = [(n, m) for n, m in _voice_metadata.items() if n.startswith(f"{voice}-")]
        if all_session:
            best = max(all_session, key=lambda x: (x[1].get("duration_s", 0), x[1].get("confidence", 0)))
            return VOICES.get(best[0])

    # Direct lookup (no session prefix matching)
    if voice in VOICES:
        return VOICES[voice]
    return None


def _warmup():
    """Pre-load model + generate a tiny warmup to prime MLX caches."""
    model = _get_model()
    resolved = _resolve_voice(DEFAULT_VOICE)
    if resolved is None:
        log.warning("Default voice '%s' not available — skipping warmup", DEFAULT_VOICE)
        return
    ref_audio, ref_text = resolved
    log.info("Warming up with %s voice...", DEFAULT_VOICE)
    t0 = time.time()
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            from mlx_audio.tts.generate import generate_audio
            generate_audio(
                text="Hello.",
                model=model,
                ref_audio=ref_audio,
                ref_text=ref_text,
                lang_code="en",
                output_path=tmpdir,
                file_prefix="warmup",
                verbose=False,
            )
        log.info("Warmup done in %.1fs", time.time() - t0)
    except Exception as exc:
        log.warning("Warmup failed (non-fatal): %s", exc)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_ID,
        "backend": "mlx",
        "model_loaded": _model is not None,
        "ready": _ready.is_set(),
        "voices": sorted(VOICES.keys()),
        "default_voice": DEFAULT_VOICE,
    }


def _synthesize_audio(text: str, resolved: tuple[str, str], voice_label: str) -> Response:
    """Core synthesis logic shared by GET and POST /synthesize."""
    log.info("synthesize: %d chars, voice=%s", len(text), voice_label)

    try:
        import tempfile
        model = _get_model()
        t0 = time.time()

        ref_audio, ref_text = resolved

        # Serialise — MLX Metal backend crashes on concurrent access
        with _synth_lock, tempfile.TemporaryDirectory() as tmpdir:
            from mlx_audio.tts.generate import generate_audio
            generate_audio(
                text=text,
                model=model,  # pre-loaded nn.Module, not string — skips reload
                ref_audio=ref_audio,
                ref_text=ref_text,
                lang_code="en",
                output_path=tmpdir,
                file_prefix="out",
                verbose=False,
            )
            wav_files = sorted(glob.glob(os.path.join(tmpdir, "out_*.wav")))
            if not wav_files:
                log.error("TTS generated no output file")
                return JSONResponse({"error": "generation produced no audio"}, status_code=500)
            wav_path = wav_files[0]
            data, sr = sf.read(wav_path)

        elapsed = time.time() - t0
        duration = len(data) / sr

        buf = io.BytesIO()
        sf.write(buf, data, sr, format="WAV", subtype="PCM_16")
        buf.seek(0)

        log.info("done: %.1fs audio in %.1fs (RTF=%.2fx)", duration, elapsed, elapsed / duration if duration > 0 else 0)

        return Response(
            content=buf.read(),
            media_type="audio/wav",
            headers={
                "X-Synthesis-Time": f"{elapsed:.3f}",
                "X-Duration": f"{duration:.3f}",
                "X-Sample-Rate": str(sr),
            },
        )
    except Exception as exc:
        log.error("synthesis failed: %s", exc, exc_info=True)
        return JSONResponse({"error": "synthesis failed"}, status_code=500)


@app.get("/synthesize")
def synthesize(
    text: str = Query(..., description="Text to speak"),
    voice: str = Query(DEFAULT_VOICE, description=f"Voice name ({', '.join(VOICES)})"),
):
    """Generate speech from text using cloned voice, return WAV audio."""
    if not text.strip():
        return JSONResponse({"error": "text is empty"}, status_code=400)
    if len(text) > 5000:
        return JSONResponse({"error": "text too long (max 5000 chars)"}, status_code=400)

    if not _ready.is_set():
        return JSONResponse({"error": "server warming up, try again shortly"}, status_code=503)

    resolved = _resolve_voice(voice)
    if resolved is None:
        return JSONResponse(
            {"error": f"unknown voice: {voice}", "available": sorted(VOICES.keys())},
            status_code=400)

    return _synthesize_audio(text, resolved, voice)


class SynthesizeRequest(BaseModel):
    text: str
    voice: str
    emotion: str | None = None


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

    resolved = _resolve_voice(body.voice, emotion=body.emotion)
    if resolved is None:
        return JSONResponse(
            {"error": f"unknown voice: {body.voice}", "available": sorted(VOICES.keys())},
            status_code=400)

    return _synthesize_audio(body.text, resolved, body.voice)


@app.post("/clone")
async def clone_voice_endpoint(
    audio: UploadFile = File(...),
    session_id: str = Form(...),
    emotion: str = Form("neutral"),
    transcript: str | None = Form(None),
):
    """Create a voice profile from raw audio. Denoises, optionally transcribes, registers."""
    if not _clone_enabled:
        return JSONResponse({"error": "clone not enabled (start with --allow-clone)"}, status_code=404)

    audio_bytes = await audio.read()
    if len(audio_bytes) < 1000:
        return JSONResponse({"error": "audio too short"}, status_code=400)

    # Count existing entries for this session to get sequence number
    existing = [k for k in VOICES if k.startswith(f"{session_id}-")]
    seq = len(existing) + 1
    voice_name = f"{session_id}-{seq:03d}"

    try:
        import tempfile

        import noisereduce as nr

        # Save uploaded audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
            tmp_in.write(audio_bytes)
            tmp_in_path = tmp_in.name

        # Denoise (under synth lock — noisereduce may use Metal)
        with _synth_lock:
            data, sr_in = sf.read(tmp_in_path)
            if data.ndim > 1:
                data = data.mean(axis=1)
            reduced = nr.reduce_noise(y=data, sr=sr_in, stationary=True, prop_decrease=0.7)
            peak = np.max(np.abs(reduced))
            if peak > 0:
                reduced = reduced * (0.9 / peak)

        duration_s = len(reduced) / sr_in
        if duration_s < 1.0:
            os.unlink(tmp_in_path)
            return JSONResponse({"error": "audio too short after processing (< 1s)"}, status_code=400)

        # Determine quality from duration
        if duration_s < 5:
            quality = "rough"
        elif duration_s < 15:
            quality = "developing"
        else:
            quality = "good"

        # Transcribe if not provided
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
            except Exception as e:
                log.warning("Transcription failed, using empty transcript: %s", e)
                transcript = ""
        else:
            transcript_confidence = 0.9

        # Save denoised audio to voices/ (atomic: write temp, rename)
        ref_path = os.path.join(_VOICES_DIR, f"{voice_name}-ref.wav")
        tmp_ref = ref_path + ".tmp"
        sf.write(tmp_ref, reduced, sr_in, format="WAV", subtype="PCM_16")
        os.rename(tmp_ref, ref_path)

        # Save profile JSON
        profile_path = os.path.join(_VOICES_DIR, f"{voice_name}.json")
        tmp_profile = profile_path + ".tmp"
        with open(tmp_profile, "w") as f:
            json.dump(
                {
                    "name": voice_name,
                    "session_id": session_id,
                    "emotion": emotion,
                    "reference_audio": f"{voice_name}-ref.wav",
                    "reference_text": transcript,
                    "quality": quality,
                    "duration_s": round(duration_s, 1),
                    "transcript_confidence": round(transcript_confidence, 2),
                    "sequence": seq,
                },
                f,
                indent=2,
            )
        os.rename(tmp_profile, profile_path)

        # Register in runtime
        _register_voice(
            voice_name,
            ref_path,
            transcript,
            emotion,
            {"quality": quality, "duration_s": duration_s, "confidence": transcript_confidence},
        )

        # Cleanup temp input
        os.unlink(tmp_in_path)

        log.info(
            "cloned: %s (session=%s, emotion=%s, quality=%s, %.1fs)",
            voice_name,
            session_id,
            emotion,
            quality,
            duration_s,
        )

        return {
            "voice": voice_name,
            "emotion": emotion,
            "quality": quality,
            "transcript_confidence": round(transcript_confidence, 2),
            "duration_s": round(duration_s, 1),
            "sequence": seq,
        }
    except Exception as exc:
        log.error("clone failed: %s", exc, exc_info=True)
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
    missing = [v for v, (p, _) in VOICES.items() if not os.path.exists(p)]
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
    log.info("model: %s", MODEL_ID)
    log.info("voices: %d loaded (default: %s)", len(VOICES), DEFAULT_VOICE)

    if not args.no_warmup:
        try:
            _warmup()
        except Exception as exc:
            log.error("Failed to load model: %s", exc)
            log.error("Check your network connection — first run downloads ~1.5 GB")
            raise SystemExit(1)
    _ready.set()
    log.info("ready — %d voices, accepting requests", len(VOICES))

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
