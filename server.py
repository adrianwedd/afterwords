"""Afterwords — local voice-cloning TTS server for Claude Code.

Zero-shot voice cloning via Qwen3-TTS on Apple Silicon (MLX).
Serves WAV audio over HTTP. Auto-discovers voices from voices/ directory.

Usage:
    source .venv/bin/activate
    python server.py [--port 7860]
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import time

import soundfile as sf
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, Response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tts")

# Suppress known harmless warnings from mlx-audio model loading
import warnings
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
    "vixen": (
        os.path.join(_VOICES_DIR, "vixen-ref.wav"),
        "My Mummy's Hair for Faith Evelyn. My mummy's hair is chocolate brown with "
        "twinkly silver gloss. It's seldom neat and tidy and it smells like fairy floss. "
        "When wild wind blows it flaps about the way a flag.",
    ),
    "galadriel": (
        os.path.join(_VOICES_DIR, "galadriel-ref.wav"),
        "The world is changed. I feel it in the water. I feel it in the earth. "
        "I smell it in the air.",
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
        "business. And I have the power to do it,",
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
    "obi": (
        os.path.join(_VOICES_DIR, "obi-ref.wav"),
        "Hello, my name is Obi. I talk like this. Hello, my name is Obi. I shit like "
        "this. That is it, that is it.",
    ),
    "snape": (
        os.path.join(_VOICES_DIR, "snape-ref.wav"),
        "There will be no foolish wand waving or silly incantations in this class. "
        "As such, I don't expect many of you to appreciate the subtle science and "
        "exact art that is potion making.",
    ),
    "loki": (
        os.path.join(_VOICES_DIR, "loki-ref.wav"),
        "Is not this simpler? Is this not your natural state? It's the unspoken "
        "truth of humanity that you crave subjugation.",
    ),
    "spock": (
        os.path.join(_VOICES_DIR, "spock-ref.wav"),
        "The most curious creature, Captain. Its trilling seems to have a "
        "tranquilizing effect on the human nervous system. Fortunately, of "
        "course, I am immune to its",
    ),
    "bardem": (
        os.path.join(_VOICES_DIR, "bardem-ref.wav"),
        "Let's not negotiate like a contract. I came over here with no subterfuge "
        "and presented my best offer. Now I hope you will discuss it and give me "
        "the pleasure to take you with me to Oviedo.",
    ),
    "depp": (
        os.path.join(_VOICES_DIR, "depp-ref.wav"),
        "In a mirror and you see the back of it, you like it? I might get a little "
        "tinge of excitement. I see. There's got to be some part of your body that "
        "you like. Your shoes? That's not a part of your body.",
    ),
}

# Auto-discover voices from JSON profiles created by clone-voice.sh
import glob as _glob
import json as _json
for _profile in _glob.glob(os.path.join(_VOICES_DIR, "*.json")):
    try:
        _p = _json.loads(open(_profile).read())
        _name = os.path.splitext(os.path.basename(_profile))[0].replace("-profile", "")
        _ref = os.path.join(_VOICES_DIR, f"{_name}-ref.wav")
        if _name not in VOICES and os.path.exists(_ref) and _p.get("reference_text"):
            VOICES[_name] = (_ref, _p["reference_text"])
    except Exception:
        pass

DEFAULT_VOICE = "galadriel"

# Pre-loaded model — avoids 30s cold start per request
import threading

_model = None
_model_lock = threading.Lock()
_synth_lock = threading.Lock()  # serialise synthesis — MLX/Metal is not thread-safe
_ready = False


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


def _resolve_voice(voice: str) -> tuple[str, str] | None:
    """Return (ref_audio_path, ref_text) for a voice name, or None if unknown."""
    if voice in VOICES:
        return VOICES[voice]
    return None


def _warmup():
    """Pre-load model + generate a tiny warmup to prime MLX caches."""
    model = _get_model()
    ref_audio, ref_text = _resolve_voice(DEFAULT_VOICE)
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
        "ready": _ready,
        "voices": sorted(VOICES.keys()),
        "default_voice": DEFAULT_VOICE,
    }


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

    if not _ready:
        return JSONResponse({"error": "server warming up, try again shortly"}, status_code=503)

    resolved = _resolve_voice(voice)
    if resolved is None:
        return JSONResponse(
            {"error": f"unknown voice: {voice}", "available": sorted(VOICES.keys())},
            status_code=400)

    log.info("synthesize: %d chars, voice=%s", len(text), voice)

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
            wav_path = os.path.join(tmpdir, "out_000.wav")
            if not os.path.exists(wav_path):
                log.error("TTS generated no output file")
                return JSONResponse({"error": "generation produced no audio"}, status_code=500)
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


def main():
    parser = argparse.ArgumentParser(description="Afterwords TTS server (MLX)")
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-warmup", action="store_true", help="Skip warmup synthesis")
    args = parser.parse_args()

    missing = [v for v, (p, _) in VOICES.items() if not os.path.exists(p)]
    for vname in missing:
        log.warning("Reference audio not found for '%s' — skipping", vname)
        del VOICES[vname]
    if not VOICES:
        log.error("No voices available — add ref WAVs to voices/")
        raise SystemExit(1)

    log.info("afterwords starting on %s:%d", args.host, args.port)
    log.info("model: %s", MODEL_ID)
    log.info("voices: %d loaded (default: %s)", len(VOICES), DEFAULT_VOICE)

    global _ready
    if not args.no_warmup:
        try:
            _warmup()
        except Exception as exc:
            log.error("Failed to load model: %s", exc)
            log.error("Check your network connection — first run downloads ~1.5 GB")
            raise SystemExit(1)
    _ready = True
    log.info("ready — %d voices, accepting requests", len(VOICES))

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
