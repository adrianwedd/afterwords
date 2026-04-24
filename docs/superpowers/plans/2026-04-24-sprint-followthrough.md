# Multi-Backend Follow-through Sprint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the four items from revision 5 of `docs/superpowers/specs/2026-04-24-sprint-followthrough-design.md`: re-clone flagship voices across 4 backends, demo site backend comparison section, hot-reload `/reload` endpoint, multilingual groundwork.

**Architecture:** Phase A modifies backend protocol (`Backend.synthesize(..., lang)`) and adds a `POST /reload` endpoint; Phase B generates per-backend voice profiles for picard/galadriel/attenborough and updates the demo site. Locking discipline inherits from the existing multi-backend infrastructure (`_synth_lock` for Metal ops, `_model_lock` for VOICES mutation).

**Tech Stack:** Python 3.11+ with FastAPI + uvicorn, MLX + mlx-audio for TTS, pytest with FakeBackend fixture for tests, vanilla HTML/CSS/JS for the demo site.

**Spec:** `docs/superpowers/specs/2026-04-24-sprint-followthrough-design.md` (revision 5) — source of truth for design decisions.

---

## File Structure

**New files:**
- `scripts/reclone-flagship.py` — generates per-backend voice JSONs for flagship voices
- `scripts/gen-comparison-audio.sh` — synthesizes demo MP3s for comparison player
- `voices/picard-qwen3-17b.json`, `voices/picard-chatterbox.json`, `voices/picard-voxcpm-15.json` (+ galadriel, attenborough variants) — 9 new profile files
- `docs/audio/comparison/{voice}-{backend-slug}.mp3` × 12 — new demo audio files

**Modified files:**
- `backends/base.py` — add `lang: str` as required param on `Backend.synthesize` Protocol
- `backends/qwen3.py`, `backends/chatterbox.py`, `backends/voxcpm.py` — accept `lang`, validate against `supported_langs`, raise `ValueError` for unsupported
- `server.py` — lifespan context manager, `_sweep_orphaned_temp_files`, `_cleanup_current_voices`, `POST /reload` endpoint, `lang` plumbed through `_synthesize_audio` + `_warmup` + HTTP handlers + `SynthesizeRequest`, `/health` adds `supported_langs` per backend
- `afterwords.sh` — add `reload` command
- `tests/conftest.py` — `FakeBackend.synthesize` gains `lang` param + `_supported_langs` override
- `tests/test_backends.py` — protocol-signature test + conformance test
- `tests/test_server.py` — `/reload` tests, `lang` error path, `/health.supported_langs`
- `tests/test_backends_integration.py` — pass `lang="en"` explicitly
- `docs/index.html` — 11 copy updates + new Backend Comparison section
- `CLAUDE.md`, `AGENTS.md` (if exists), `README.md` — doc-sync audit

---

## Phase A — Backend work (Items 4, then 3)

### Task 1: Add `lang` to Backend Protocol

**Files:**
- Modify: `backends/base.py:38-58` (Backend Protocol class)
- Test: `tests/test_backends.py` (add protocol-signature test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_backends.py`:

```python
def test_backend_synthesize_requires_lang():
    """Backend.synthesize must take `lang` as a required parameter (no default on Protocol)."""
    import inspect
    sig = inspect.signature(Backend.synthesize)
    params = sig.parameters
    assert "lang" in params, "Backend.synthesize missing `lang` parameter"
    assert params["lang"].default is inspect.Parameter.empty, \
        "Backend.synthesize.lang must be required (no default on Protocol)"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_backends.py::test_backend_synthesize_requires_lang -v
```

Expected: FAIL with `AssertionError: Backend.synthesize missing 'lang' parameter`.

- [ ] **Step 3: Update Protocol signature**

Modify `backends/base.py`, replacing the existing `synthesize` method in the `Backend` Protocol:

```python
    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]: ...
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_backends.py::test_backend_synthesize_requires_lang -v
```

Expected: PASS.

- [ ] **Step 5: Run the full test suite — other tests will now fail because backends don't match Protocol**

```
pytest
```

Expected: FAILURES in `test_each_registered_backend_satisfies_protocol` and any `isinstance(x, Backend)` check — these will be fixed as subsequent tasks update each backend. Note the count of failures for reference.

- [ ] **Step 6: Commit**

```bash
git add backends/base.py tests/test_backends.py
git commit -m "feat(backends): add required lang param to Backend.synthesize Protocol"
```

---

### Task 2: Update Qwen3Backend to accept `lang`

**Files:**
- Modify: `backends/qwen3.py:68-91` (synthesize method)
- Test: Reuse `tests/test_backends.py::test_each_registered_backend_satisfies_protocol` (already fails from Task 1)

- [ ] **Step 1: Confirm the test is currently failing**

```
pytest tests/test_backends.py::test_each_registered_backend_satisfies_protocol -v
```

Expected: FAIL (protocol mismatch).

- [ ] **Step 2: Update Qwen3Backend.synthesize**

In `backends/qwen3.py`, replace the `synthesize` method (currently at lines 68-91) with:

```python
    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            raise RuntimeError("Qwen3Backend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"qwen3 does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        from mlx_audio.tts.generate import generate_audio
        with tempfile.TemporaryDirectory() as tmpdir:
            generate_audio(
                text=text,
                model=self._model,
                ref_audio=prepared.ref_audio_path,
                ref_text=prepared.ref_text,
                lang_code=lang,
                output_path=tmpdir,
                file_prefix="out",
                verbose=False,
            )
            wavs = sorted(glob.glob(os.path.join(tmpdir, "out_*.wav")))
            if not wavs:
                raise RuntimeError("Qwen3 produced no output")
            data, sr = sf.read(wavs[0])
            return np.asarray(data, dtype=np.float32), sr
```

- [ ] **Step 3: Commit**

```bash
git add backends/qwen3.py
git commit -m "feat(backends/qwen3): accept lang param, forward to generate_audio, raise on unsupported"
```

---

### Task 3: Update ChatterboxBackend to accept `lang`

**Files:**
- Modify: `backends/chatterbox.py:56-81` (synthesize method)

**Investigation note (from spec):** `mlx_audio`'s chatterbox-fp16 generator may or may not accept a language kwarg. This task takes the conservative path: accept only the languages declared in `supported_langs`, don't forward a `lang_code` kwarg (unchanged behavior). A separate commit can add forwarding if mlx-audio supports it.

- [ ] **Step 1: Update ChatterboxBackend.synthesize**

In `backends/chatterbox.py`, replace the `synthesize` method with:

```python
    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            raise RuntimeError("ChatterboxBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"chatterbox does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        from mlx_audio.tts.generate import generate_audio
        with tempfile.TemporaryDirectory() as tmpdir:
            kwargs = dict(
                text=text,
                model=self._model,
                ref_audio=prepared.ref_audio_path,
                output_path=tmpdir,
                file_prefix="out",
                verbose=False,
            )
            if prepared.ref_text:
                kwargs["ref_text"] = prepared.ref_text
            generate_audio(**kwargs)
            wavs = sorted(glob.glob(os.path.join(tmpdir, "out_*.wav")))
            if not wavs:
                raise RuntimeError("Chatterbox produced no output")
            data, sr = sf.read(wavs[0])
            return np.asarray(data, dtype=np.float32), sr
```

- [ ] **Step 2: Commit**

```bash
git add backends/chatterbox.py
git commit -m "feat(backends/chatterbox): accept lang param, validate against supported_langs"
```

---

### Task 4: Update VoxCPMBackend to accept `lang`

**Files:**
- Modify: `backends/voxcpm.py:92-114` (synthesize method)

- [ ] **Step 1: Update VoxCPMBackend.synthesize**

In `backends/voxcpm.py`, replace the `synthesize` method with:

```python
    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if self._model is None:
            raise RuntimeError("VoxCPMBackend.synthesize called before load()")
        if lang not in self.supported_langs:
            raise ValueError(
                f"voxcpm-1.5 does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        kwargs = dict(
            text=text,
            reference_wav_path=prepared.ref_audio_path,
        )
        if prepared.ref_text:
            kwargs["prompt_text"] = prepared.ref_text
        for k in ("cfg_value", "inference_timesteps"):
            if k in prepared.extras:
                kwargs[k] = prepared.extras[k]
        audio = self._model.generate(**kwargs)
        if hasattr(audio, "tolist"):
            audio = np.asarray(audio.tolist(), dtype=np.float32)
        else:
            audio = np.asarray(audio, dtype=np.float32)
        return audio.reshape(-1), NATIVE_SR
```

- [ ] **Step 2: Commit**

```bash
git add backends/voxcpm.py
git commit -m "feat(backends/voxcpm): accept lang param, validate against supported_langs"
```

---

### Task 5: Update FakeBackend, server dispatch, warmup, and HTTP handlers

**Files:**
- Modify: `tests/conftest.py:51-85` (FakeBackend class)
- Modify: `server.py:243` (`_warmup` call site)
- Modify: `server.py:299-340` (`_synthesize_audio` function)
- Modify: `server.py:343-363` (`GET /synthesize` handler)
- Modify: `server.py:366-390` (`SynthesizeRequest` + POST handler)

- [ ] **Step 1: Update FakeBackend.synthesize signature**

In `tests/conftest.py`, replace the existing FakeBackend class with:

```python
class FakeBackend:
    """Standin backend for tests. Returns 0.1s of silent float32 audio at 24 kHz."""
    name = "fake"
    display_name = "Fake Backend (tests)"
    sample_rate = 24000
    ref_text_policy = RefTextPolicy.OPTIONAL
    supported_langs = ("en",)

    def load(self) -> None:
        pass

    def validate_extras(self, extras: Mapping[str, object]) -> None:
        pass

    def prepare_voice(
        self,
        ref_audio_path: str,
        ref_text: str | None,
        extras: Mapping[str, object],
    ) -> PreparedVoice:
        return PreparedVoice(
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            extras=_read_only(dict(extras)),
        )

    def synthesize(
        self,
        text: str,
        prepared: PreparedVoice,
        lang: str,
    ) -> tuple[np.ndarray, int]:
        if lang not in self.supported_langs:
            raise ValueError(
                f"fake does not support lang={lang!r}; supported: {self.supported_langs}"
            )
        audio = np.zeros(self.sample_rate // 10, dtype=np.float32)
        return audio, self.sample_rate
```

- [ ] **Step 2: Update `_synthesize_audio` signature + call**

In `server.py`, modify `_synthesize_audio` (lines 299-340):

Change the signature line from:
```python
def _synthesize_audio(text: str, profile: VoiceProfile) -> Response:
```
to:
```python
def _synthesize_audio(text: str, profile: VoiceProfile, lang: str) -> Response:
```

Replace the `with _synth_lock:` block (around lines 314-319) with:
```python
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
```

- [ ] **Step 3: Update `_warmup` to pass `lang="en"`**

In `server.py`, modify `_warmup` (around line 253), changing:
```python
    with _synth_lock:
        backend.synthesize("Hello.", profile.prepared)
```
to:
```python
    with _synth_lock:
        backend.synthesize("Hello.", profile.prepared, lang="en")
```

- [ ] **Step 4: Update GET /synthesize handler**

In `server.py`, replace the GET handler (around lines 343-363) with:

```python
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
```

- [ ] **Step 5: Update POST /synthesize and its model**

In `server.py`, replace the `SynthesizeRequest` model and POST handler with:

```python
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
```

- [ ] **Step 6: Run existing tests to verify backward compat**

```
pytest tests/test_server.py -v
```

Expected: PASS for all existing tests (GET /synthesize without `lang` now defaults to `lang="en"`, same behavior).

- [ ] **Step 7: Commit**

```bash
git add tests/conftest.py server.py
git commit -m "feat(server): plumb lang through dispatch, warmup, GET/POST synthesize, FakeBackend"
```

---

### Task 6: Expose `supported_langs` in /health

**Files:**
- Modify: `server.py:260-296` (`health` endpoint)
- Test: `tests/test_server.py` (add test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_server.py`:

```python
def test_health_exposes_supported_langs(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    for name, info in body["loaded_backends"].items():
        assert "supported_langs" in info, f"backend {name!r} missing supported_langs"
        assert isinstance(info["supported_langs"], list)
        assert all(isinstance(x, str) for x in info["supported_langs"])
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/test_server.py::test_health_exposes_supported_langs -v
```

Expected: FAIL with KeyError or AssertionError about `supported_langs`.

- [ ] **Step 3: Add supported_langs to /health output**

In `server.py`, inside the `health()` function, modify the `loaded_backends` construction loop (around lines 268-275) to include `supported_langs`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/test_server.py::test_health_exposes_supported_langs -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(health): expose supported_langs per backend"
```

---

### Task 7: Add lang-rejection test + conformance test

**Files:**
- Test: `tests/test_server.py` (add test)
- Test: `tests/test_backends.py` (add conformance test)

- [ ] **Step 1: Write the unsupported-lang rejection test**

Append to `tests/test_server.py`:

```python
def test_synthesize_unsupported_lang_returns_400(client, sample_voice):
    """GET /synthesize?lang=fr against an en-only voice must return 400."""
    r = client.get("/synthesize", params={"text": "Bonjour", "voice": sample_voice, "lang": "fr"})
    assert r.status_code == 400
    body = r.json()
    assert "supported_langs" in body
    assert "en" in body["supported_langs"]
    assert "fr" not in body["supported_langs"]


def test_post_synthesize_accepts_lang(client, sample_voice):
    """POST /synthesize with lang=en against an en voice should succeed."""
    server._clone_enabled = True
    try:
        r = client.post("/synthesize", json={"text": "Hello", "voice": sample_voice, "lang": "en"})
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
    finally:
        server._clone_enabled = False
```

- [ ] **Step 2: Write the all-backends-accept-lang conformance test**

Append to `tests/test_backends.py`:

```python
def test_all_registered_backends_accept_lang_keyword():
    """Every registered backend's synthesize must accept `lang`. Catches implementations that forgot the kwarg."""
    backends.register_all()
    for name in backends.names():
        b = backends.get(name)
        import inspect
        sig = inspect.signature(b.synthesize)
        assert "lang" in sig.parameters, f"backend {name!r} missing lang kwarg"
        # We don't actually call synthesize (needs real model); the signature check is the conformance guarantee.
```

- [ ] **Step 3: Run both tests**

```
pytest tests/test_server.py::test_synthesize_unsupported_lang_returns_400 tests/test_server.py::test_post_synthesize_accepts_lang tests/test_backends.py::test_all_registered_backends_accept_lang_keyword -v
```

Expected: all three PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_server.py tests/test_backends.py
git commit -m "test: add lang-rejection, POST lang, and Backend conformance tests"
```

---

### Task 8: Update integration tests to pass `lang="en"`

**Files:**
- Modify: `tests/test_backends_integration.py:41-50`

- [ ] **Step 1: Update integration-test synth call**

In `tests/test_backends_integration.py`, change line 46 from:
```python
    audio, sr = b.synthesize("Hello.", prepared)
```
to:
```python
    audio, sr = b.synthesize("Hello.", prepared, lang="en")
```

- [ ] **Step 2: Confirm the file parses and the test is collected (not run — integration tests are opt-in)**

```
pytest tests/test_backends_integration.py --collect-only
```

Expected: 4 tests collected, all marked integration.

- [ ] **Step 3: Run the non-integration suite to confirm no regression**

```
pytest
```

Expected: all passing. Count should be >= baseline 61.

- [ ] **Step 4: Commit**

```bash
git add tests/test_backends_integration.py
git commit -m "test(integration): pass lang=en to backend.synthesize"
```

---

### Task 9: Extract `_build_voice_profile` helper + lifecycle hooks

**Files:**
- Modify: `server.py:78-143` (`_load_voice_profiles`)
- Modify: `server.py:603-666` (`main`)
- Modify: `server.py:66-68` (`app = FastAPI(...)`)

This task extracts the per-profile build logic from `_load_voice_profiles` so both startup and `/reload` can reuse it, then introduces the lifespan/cleanup/sweep functions per the spec's Lifecycle section.

- [ ] **Step 1: Extract `_build_voice_profile(profile_path) -> VoiceProfile | None`**

In `server.py`, insert this new function just before `_load_voice_profiles` (around line 78):

```python
def _build_voice_profile(profile_path: str) -> VoiceProfile | None:
    """Build a single VoiceProfile from a JSON path. Returns None if the profile
    should be skipped (missing ref, invalid extras, etc.) — logs the reason."""
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
```

Note: `prepare_voice` is NOT wrapped in try/except here — callers decide how to handle failures (`/reload` aborts atomically; startup uses `log.warning+skip` — addressed in next step).

- [ ] **Step 2: Simplify `_load_voice_profiles` to use the helper**

In `server.py`, replace the body of `_load_voice_profiles()` (around lines 78-143) with:

```python
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
```

- [ ] **Step 3: Add lifecycle helpers and lifespan**

In `server.py`, just above `app = FastAPI(title="Afterwords TTS")` (around line 68), insert:

```python
import tempfile
from contextlib import asynccontextmanager


def _cleanup_current_voices():
    """Delete cleanup_paths + owned temp audio for all currently-loaded voices.
    Called during shutdown only — never inline during reload."""
    for profile in VOICES.values():
        for path in profile.prepared.cleanup_paths:
            try: os.remove(path)
            except OSError: pass
        if (profile.prepared.owns_temp_audio
                and profile.prepared.ref_audio_path.startswith(tempfile.gettempdir())):
            try: os.remove(profile.prepared.ref_audio_path)
            except OSError: pass


def _sweep_orphaned_temp_files():
    """Delete VoxCPM-resample temp files from any prior crashed run. Best-effort.
    MUST run before _load_voice_profiles to avoid deleting fresh temps."""
    for path in glob.glob(os.path.join(tempfile.gettempdir(), "voxcpm-ref-*.wav")):
        try: os.remove(path)
        except OSError: pass


@asynccontextmanager
async def lifespan(app):
    # startup body runs after main()'s sync setup — no-op here
    yield
    # shutdown body
    _cleanup_current_voices()
```

Then change the FastAPI instantiation line from:
```python
app = FastAPI(title="Afterwords TTS")
```
to:
```python
app = FastAPI(title="Afterwords TTS", lifespan=lifespan)
```

- [ ] **Step 4: Plumb sweep into main() before voice loading**

In `server.py`, locate the `main()` function (around line 603). After the backend-load loop (after the `backend %s loaded in %.1fs` log, around line 636) and BEFORE `_load_voice_profiles()` (around line 639), add:

```python
    # Clean up any VoxCPM temp files orphaned by a previous crashed run.
    _sweep_orphaned_temp_files()
```

- [ ] **Step 5: Write a unit test for `_cleanup_current_voices`**

Append to `tests/test_server.py`:

```python
def test_cleanup_current_voices_deletes_tracked_paths(tmp_path, monkeypatch):
    """_cleanup_current_voices must delete cleanup_paths + owned_temp_audio for all VOICES."""
    import tempfile as _tempfile
    # Create two files in tempdir and one in voices/ (should NOT be deleted)
    tmp_cleanup = str(_tempfile.gettempdir() + "/test-cleanup-xyz.bin")
    tmp_owned = str(_tempfile.gettempdir() + "/test-owned-xyz.wav")
    safe_file = str(tmp_path / "safe.wav")
    for p in (tmp_cleanup, tmp_owned, safe_file):
        with open(p, "wb") as f: f.write(b"x")

    backend = backends.get("fake")
    prep = server.PreparedVoice(
        ref_audio_path=tmp_owned,
        ref_text=None,
        extras={},
        owns_temp_audio=True,
        cleanup_paths=(tmp_cleanup,),
    )
    profile = server.VoiceProfile(
        name="cleaner", backend="fake", ref_audio=tmp_owned, ref_text=None,
        session_id=None, emotion="neutral", quality=None, duration_s=None,
        confidence=None, sequence=None, extras={}, prepared=prep,
    )
    server.VOICES["cleaner"] = profile
    try:
        server._cleanup_current_voices()
        assert not os.path.exists(tmp_cleanup), "cleanup_paths entry not deleted"
        assert not os.path.exists(tmp_owned), "owns_temp_audio ref not deleted"
        assert os.path.exists(safe_file), "file outside tempdir must NOT be touched"
    finally:
        server.VOICES.pop("cleaner", None)
        for p in (tmp_cleanup, tmp_owned, safe_file):
            try: os.remove(p)
            except OSError: pass
```

Also append the sweep test:

```python
def test_sweep_orphaned_temp_files_deletes_voxcpm_refs():
    """_sweep_orphaned_temp_files must delete files matching voxcpm-ref-*.wav."""
    import tempfile as _tempfile
    stale = os.path.join(_tempfile.gettempdir(), "voxcpm-ref-deadbeef.wav")
    unrelated = os.path.join(_tempfile.gettempdir(), "not-voxcpm-xyz.wav")
    for p in (stale, unrelated):
        with open(p, "wb") as f: f.write(b"x")
    try:
        server._sweep_orphaned_temp_files()
        assert not os.path.exists(stale), "stale voxcpm-ref-*.wav not swept"
        assert os.path.exists(unrelated), "unrelated file must NOT be swept"
    finally:
        for p in (stale, unrelated):
            try: os.remove(p)
            except OSError: pass
```

- [ ] **Step 6: Run the lifecycle tests**

```
pytest tests/test_server.py::test_cleanup_current_voices_deletes_tracked_paths tests/test_server.py::test_sweep_orphaned_temp_files_deletes_voxcpm_refs -v
```

Expected: both PASS.

- [ ] **Step 7: Run full suite**

```
pytest
```

Expected: all passing.

- [ ] **Step 8: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "refactor(server): extract _build_voice_profile; add lifespan + sweep + cleanup helpers"
```

---

### Task 10: Implement `POST /reload` endpoint

**Files:**
- Modify: `server.py` (add endpoint around current line 600, before `main()`)
- Test: `tests/test_server.py` (add reload tests)

- [ ] **Step 1: Write failing tests for the happy path + add-only + atomic**

Append to `tests/test_server.py`:

```python
def _write_profile_json(dir_path, name, backend="fake", ref_text="hello"):
    """Write a profile JSON + ref WAV to dir_path. Returns (json_path, wav_path)."""
    import soundfile as sf
    import numpy as np
    wav = os.path.join(dir_path, f"{name}-ref.wav")
    sf.write(wav, np.zeros(24000, dtype=np.float32), 24000)
    j = os.path.join(dir_path, f"{name}.json")
    with open(j, "w") as f:
        json.dump({
            "name": name,
            "backend": backend,
            "reference_audio": f"{name}-ref.wav",
            "reference_text": ref_text,
        }, f)
    return j, wav


def test_reload_disabled_without_allow_clone(client):
    server._clone_enabled = False
    r = client.post("/reload")
    assert r.status_code == 404


def test_reload_adds_new_voice_from_disk(client, tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True
    try:
        _write_profile_json(str(tmp_path), "alpha", backend="fake")
        r = client.post("/reload")
        assert r.status_code == 200
        body = r.json()
        assert "alpha" in body["reloaded"]
        assert body["errors"] == []
        assert "alpha" in server.VOICES
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_is_add_only_keeps_deleted_voices(client, tmp_path, monkeypatch):
    """If a JSON is deleted from disk, the voice stays in VOICES (add-only)."""
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True
    try:
        j1, _ = _write_profile_json(str(tmp_path), "keeper", backend="fake")
        # First reload: register the voice
        r = client.post("/reload")
        assert "keeper" in server.VOICES
        # Now delete the JSON, reload again — voice must remain
        os.remove(j1)
        r = client.post("/reload")
        assert r.status_code == 200
        assert "keeper" in server.VOICES, "add-only reload must not drop deleted-from-disk voices"
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_atomic_on_error(client, tmp_path, monkeypatch):
    """If any profile fails to build, VOICES must NOT be mutated."""
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True
    try:
        _write_profile_json(str(tmp_path), "good", backend="fake")
        # Write a malformed JSON
        with open(os.path.join(str(tmp_path), "bad.json"), "w") as f:
            f.write("{not valid json")
        r = client.post("/reload")
        # Spec: malformed JSON is logged-and-skipped via _build_voice_profile returning None,
        # NOT surfaced as an error. The reload succeeds with "good" and the bad file just produces
        # a log warning. Assert good voice is loaded.
        assert r.status_code == 200
        assert "good" in server.VOICES
    finally:
        server._clone_enabled = False
        server.VOICES.clear()


def test_reload_abort_when_prepare_voice_raises(client, tmp_path, monkeypatch):
    """If prepare_voice raises (not just malformed JSON), reload aborts atomically."""
    import backends as _backends
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True

    # Pre-populate VOICES with an existing voice
    pre_wav = str(tmp_path / "pre-ref.wav")
    import soundfile as sf, numpy as np
    sf.write(pre_wav, np.zeros(24000, dtype=np.float32), 24000)
    backend = _backends.get("fake")
    prep = backend.prepare_voice(pre_wav, "pre text", {})
    server.VOICES["pre"] = server.VoiceProfile(
        name="pre", backend="fake", ref_audio=pre_wav, ref_text="pre text",
        session_id=None, emotion="neutral", quality=None, duration_s=None,
        confidence=None, sequence=None, extras={}, prepared=prep,
    )

    # Monkeypatch fake backend's prepare_voice to raise on one specific name
    original = backend.prepare_voice

    def failing_prepare(ref, txt, extras):
        if ref.endswith("boom-ref.wav"):
            raise RuntimeError("simulated prepare failure")
        return original(ref, txt, extras)

    monkeypatch.setattr(backend, "prepare_voice", failing_prepare)

    try:
        _write_profile_json(str(tmp_path), "ok_one", backend="fake")
        _write_profile_json(str(tmp_path), "boom", backend="fake")
        # Also put a ref wav for 'pre' in the voices dir so the walker finds its JSON too
        # (Not strictly required — pre already in VOICES; test verifies add-only-preservation.)

        r = client.post("/reload")
        assert r.status_code == 500
        body = r.json()
        assert body["status"] == "failed"
        assert len(body["errors"]) >= 1
        # VOICES must still contain pre (not mutated during failed reload)
        assert "pre" in server.VOICES
        # ok_one must NOT have been added — atomic abort
        assert "ok_one" not in server.VOICES
    finally:
        server._clone_enabled = False
        server.VOICES.clear()
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_server.py -k reload -v
```

Expected: all fail with 404 or AttributeError (endpoint doesn't exist).

- [ ] **Step 3: Implement `POST /reload`**

In `server.py`, insert the reload endpoint after the `DELETE /session/{session_id}` endpoint (around line 600, before `main()`):

```python
@app.post("/reload")
def reload_voices():
    """Re-walk voices/*.json and merge additions/updates into VOICES.
    Add-only: voices whose JSON is absent from disk are NOT removed.
    Atomic on error: if any profile's prepare_voice() raises, abort and rollback."""
    if not _clone_enabled:
        return JSONResponse({"error": "clone not enabled (start with --allow-clone)"}, status_code=404)

    t0 = time.time()
    new_profiles: list[VoiceProfile] = []
    tracked_cleanup_paths: list[str] = []    # for rollback on abort
    tracked_owned_refs: list[str] = []       # for rollback on abort
    errors: list[dict] = []

    # Phase 1: walk + build under _synth_lock (prepare_voice may touch Metal)
    with _synth_lock:
        for profile_path in sorted(glob.glob(os.path.join(_VOICES_DIR, "*.json"))):
            try:
                profile = _build_voice_profile(profile_path)
            except Exception as exc:
                errors.append({"file": profile_path, "error": str(exc)})
                continue
            if profile is None:
                # _build_voice_profile logged + skipped (unreadable, missing ref, etc.)
                continue
            new_profiles.append(profile)
            tracked_cleanup_paths.extend(profile.prepared.cleanup_paths)
            if profile.prepared.owns_temp_audio:
                tracked_owned_refs.append(profile.prepared.ref_audio_path)

    # Phase 2: abort-on-error — rollback temp files built during this walk
    if errors:
        for p in tracked_cleanup_paths:
            try: os.remove(p)
            except OSError: pass
        for p in tracked_owned_refs:
            if p.startswith(tempfile.gettempdir()):
                try: os.remove(p)
                except OSError: pass
        log.warning("/reload aborted: %d errors, %.1fs", len(errors), time.time() - t0)
        return JSONResponse({"status": "failed", "errors": errors}, status_code=500)

    # Phase 3: commit — merge under _model_lock (never removes absent voices)
    with _model_lock:
        for profile in new_profiles:
            VOICES[profile.name] = profile
        reloaded = sorted(VOICES.keys())

    log.info("/reload: %d voices loaded, 0 errors, %.1fs", len(reloaded), time.time() - t0)
    return {"status": "ok", "reloaded": reloaded, "errors": []}
```

- [ ] **Step 4: Run reload tests**

```
pytest tests/test_server.py -k reload -v
```

Expected: all PASS. Note — `test_reload_abort_when_prepare_voice_raises` exercises the rollback path; confirm its `len(errors) >= 1` assertion is met and VOICES is unmutated.

- [ ] **Step 5: Add the rollback-cleanup-verification test**

Append to `tests/test_server.py`:

```python
def test_reload_abort_cleans_tracked_temps(client, tmp_path, monkeypatch):
    """When reload aborts, temp files from profiles built before the failure must be deleted."""
    import backends as _backends
    import tempfile as _tempfile
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True

    # Create a sentinel tempfile to be tracked in cleanup_paths
    sentinel = str(_tempfile.gettempdir() + "/reload-abort-sentinel.tmp")
    with open(sentinel, "wb") as f: f.write(b"x")

    backend = _backends.get("fake")
    # Monkeypatch prepare_voice to return a PreparedVoice with sentinel in cleanup_paths
    # for one voice, then raise for another.
    from backends.base import PreparedVoice, _read_only

    def prepare_with_sentinel(ref, txt, extras):
        if "succeed" in ref:
            return PreparedVoice(
                ref_audio_path=ref, ref_text=txt, extras=_read_only(dict(extras)),
                cleanup_paths=(sentinel,),
            )
        raise RuntimeError("boom")

    monkeypatch.setattr(backend, "prepare_voice", prepare_with_sentinel)

    try:
        _write_profile_json(str(tmp_path), "succeed", backend="fake")
        _write_profile_json(str(tmp_path), "fail", backend="fake")
        r = client.post("/reload")
        assert r.status_code == 500
        # Sentinel must have been deleted as part of rollback
        assert not os.path.exists(sentinel), "rollback did not clean tracked cleanup_paths"
    finally:
        server._clone_enabled = False
        server.VOICES.clear()
        try: os.remove(sentinel)
        except OSError: pass
```

- [ ] **Step 6: Run the new test**

```
pytest tests/test_server.py::test_reload_abort_cleans_tracked_temps -v
```

Expected: PASS.

- [ ] **Step 7: Run full suite**

```
pytest
```

Expected: all passing, count has increased from baseline.

- [ ] **Step 8: Commit**

```bash
git add server.py tests/test_server.py
git commit -m "feat(server): POST /reload with atomic abort + tracked temp rollback"
```

---

### Task 11: Add `reload` command to afterwords.sh

**Files:**
- Modify: `afterwords.sh` (help text ~line 506-520, dispatcher ~line 535-549, add `cmd_reload` function)

- [ ] **Step 1: Add `cmd_reload` function**

In `afterwords.sh`, after the `cmd_voices` function (find it with `grep -n cmd_voices`), add this new function. Place it alongside the other command functions:

```bash
cmd_reload() {
    local response
    if ! response=$(curl -s -X POST http://localhost:7860/reload); then
        fail "Server not responding on localhost:7860"
    fi
    if command -v jq >/dev/null 2>&1; then
        echo "$response" | jq .
    else
        echo "$response"
    fi
}
```

- [ ] **Step 2: Register the command in the help block**

In the help text (around line 506-520), add a line for `reload` between `voices` and `clone`:

```
    echo -e "    ${CYAN}reload${NC}      Reload voices from disk without restarting"
```

- [ ] **Step 3: Wire the command dispatcher**

In the case statement (around line 535-549), add the `reload)` case between `voices)` and `clone)`:

```bash
    reload)    cmd_reload "$@" ;;
```

- [ ] **Step 4: Manually verify help text**

```
bash afterwords.sh help
```

Expected: output includes `reload` with description.

- [ ] **Step 5: Commit**

```bash
git add afterwords.sh
git commit -m "feat(cli): add afterwords reload command"
```

---

## Phase B — Showcase work (Items 1, then 2)

### Task 12: Write `scripts/reclone-flagship.py`

**Files:**
- Create: `scripts/reclone-flagship.py`

- [ ] **Step 1: Create the script**

Create `scripts/reclone-flagship.py`:

```python
#!/usr/bin/env python3
"""Generate per-backend voice profiles for flagship voices.

Reads voices/{name}.json for each flagship name, writes per-backend slugged
profiles that share the existing ref WAV and reference_text.

Usage:
    python scripts/reclone-flagship.py           # skip-if-exists
    python scripts/reclone-flagship.py --force   # overwrite existing
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Make `backends` importable when run from repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backends

FLAGSHIPS = ["picard", "galadriel", "attenborough"]
# Non-default backends to generate profiles for (default is qwen3-0.6b, already present).
NON_DEFAULT_BACKENDS = ["qwen3-1.7b", "chatterbox", "voxcpm-1.5"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Overwrite existing profiles")
    parser.add_argument(
        "--voices-dir",
        default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "voices"),
        help="Path to voices/ directory",
    )
    args = parser.parse_args()

    backends.register_all()

    written = 0
    skipped = 0
    for name in FLAGSHIPS:
        src_path = os.path.join(args.voices_dir, f"{name}.json")
        if not os.path.exists(src_path):
            print(f"[error] source profile missing: {src_path}", file=sys.stderr)
            return 1
        with open(src_path) as f:
            src = json.load(f)

        ref_text = src.get("reference_text")
        if not ref_text:
            print(f"[error] {name}.json missing reference_text (required for Qwen3)", file=sys.stderr)
            return 1

        ref_audio = src.get("reference_audio", f"{name}-ref.wav")

        for backend_name in NON_DEFAULT_BACKENDS:
            slug = backends.slug(backend_name)
            out_name = f"{name}-{slug}"
            out_path = os.path.join(args.voices_dir, f"{out_name}.json")

            if os.path.exists(out_path) and not args.force:
                print(f"[skip] {out_path} already exists")
                skipped += 1
                continue

            payload = {
                "name": out_name,
                "backend": backend_name,
                "reference_audio": ref_audio,
                "reference_text": ref_text,
                "session_id": None,
                "notes": f"Generated by reclone-flagship.py — shares ref WAV with {name}.json",
            }
            with open(out_path, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"[write] {out_path}")
            written += 1

    print(f"\nDone: {written} written, {skipped} skipped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Then make it executable:

```bash
chmod +x scripts/reclone-flagship.py
```

- [ ] **Step 2: Run the script (writes 9 new JSONs)**

```
python scripts/reclone-flagship.py
```

Expected output: 9 `[write]` lines (3 voices × 3 non-default backends), "Done: 9 written, 0 skipped."

- [ ] **Step 3: Verify idempotency — re-run skips all**

```
python scripts/reclone-flagship.py
```

Expected output: 9 `[skip]` lines, "Done: 0 written, 9 skipped." Exit code 0.

- [ ] **Step 4: Spot-check one generated file**

```
cat voices/picard-qwen3-17b.json
```

Expected: valid JSON with `backend: "qwen3-1.7b"`, `reference_audio: "picard-ref.wav"`, same `reference_text` as `voices/picard.json`.

- [ ] **Step 5: Commit the script and the generated profiles**

```bash
git add scripts/reclone-flagship.py voices/picard-qwen3-17b.json voices/picard-chatterbox.json voices/picard-voxcpm-15.json voices/galadriel-qwen3-17b.json voices/galadriel-chatterbox.json voices/galadriel-voxcpm-15.json voices/attenborough-qwen3-17b.json voices/attenborough-chatterbox.json voices/attenborough-voxcpm-15.json
git commit -m "feat(voices): 9 per-backend profiles for picard, galadriel, attenborough"
```

---

### Task 13: Write `scripts/gen-comparison-audio.sh` and generate MP3s

**Files:**
- Create: `scripts/gen-comparison-audio.sh`
- Create: `docs/audio/comparison/*.mp3` × 12 (output of running the script)

**Prerequisite:** server must be running with all backends loaded AND the 9 new profiles from Task 12. Operator must run `afterwords start` beforehand.

- [ ] **Step 1: Create the generator script**

Create `scripts/gen-comparison-audio.sh`:

```bash
#!/usr/bin/env bash
#
# Generate backend-comparison MP3s for the demo site.
# Calls GET /synthesize for each (voice, backend) pair and encodes to MP3.
#
# Prerequisites:
#   - Server running on localhost:7860 with all 4 backends loaded
#   - scripts/reclone-flagship.py has been run (per-backend profiles exist)
#   - `lame` installed: brew install lame
#
# Usage:
#   bash scripts/gen-comparison-audio.sh           # skip-if-exists
#   bash scripts/gen-comparison-audio.sh --force   # overwrite existing
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_DIR="$REPO_ROOT/docs/audio/comparison"
mkdir -p "$OUT_DIR"

FORCE=false
[[ "${1:-}" == "--force" ]] && FORCE=true

SENTENCE="You are absolutely right. Your Claude Code session could sound like me."

VOICES=("picard" "galadriel" "attenborough")
# Each slug maps to the voice-name suffix used by Task 12's reclone output.
declare -A BACKEND_SLUG=(
    ["qwen3-0.6b"]="qwen3-06b"
    ["qwen3-1.7b"]="qwen3-17b"
    ["chatterbox"]="chatterbox"
    ["voxcpm-1.5"]="voxcpm-15"
)

for voice in "${VOICES[@]}"; do
    for backend in "${!BACKEND_SLUG[@]}"; do
        slug="${BACKEND_SLUG[$backend]}"
        # Default-backend profile uses the raw voice name; others use voice-slug
        if [[ "$backend" == "qwen3-0.6b" ]]; then
            voice_name="$voice"
        else
            voice_name="${voice}-${slug}"
        fi

        out_mp3="$OUT_DIR/${voice}-${slug}.mp3"
        if [[ -f "$out_mp3" ]] && [[ "$FORCE" != true ]]; then
            echo "[skip] $out_mp3"
            continue
        fi

        echo "[gen]  $voice_name -> $out_mp3"
        tmp_wav=$(mktemp -t afterwords-comparison.XXXXXX.wav)
        trap 'rm -f "$tmp_wav"' EXIT

        # URL-encode the sentence for a GET query (sentence has no reserved chars beyond space)
        encoded=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$SENTENCE'))")

        if ! curl -sf "localhost:7860/synthesize?text=${encoded}&voice=${voice_name}" -o "$tmp_wav"; then
            echo "[error] failed to synth $voice_name" >&2
            rm -f "$tmp_wav"
            exit 1
        fi

        lame -V2 --quiet "$tmp_wav" "$out_mp3"
        rm -f "$tmp_wav"
    done
done

echo ""
echo "Done. MP3s in $OUT_DIR"
ls -lh "$OUT_DIR"
```

Make it executable:

```bash
chmod +x scripts/gen-comparison-audio.sh
```

- [ ] **Step 2: Start the server (operator)**

```
afterwords start
```

Wait for "afterwords ready" in logs (may take 60-180s on cold start as backends download/load).

- [ ] **Step 3: Confirm all 12 flagship profiles load**

```
curl -s localhost:7860/health | python3 -m json.tool | grep -E 'picard|galadriel|attenborough'
```

Expected: see 4 entries per flagship (default + 3 slugged), 12 total.

- [ ] **Step 4: Run the generator**

```
bash scripts/gen-comparison-audio.sh
```

Expected: 12 `[gen]` lines, 12 MP3s written to `docs/audio/comparison/`. Each MP3 is 100-300 KB.

- [ ] **Step 5: Re-run to verify idempotency**

```
bash scripts/gen-comparison-audio.sh
```

Expected: 12 `[skip]` lines.

- [ ] **Step 6: Commit script and audio**

```bash
git add scripts/gen-comparison-audio.sh docs/audio/comparison/
git commit -m "feat(docs): generator script + 12 backend-comparison MP3s"
```

---

### Task 14: Qwen3 lang-equivalence verification

**Prerequisite:** Task 2 has changed `lang_code="en"` → `lang_code=lang`. This task verifies the change is behavior-preserving.

- [ ] **Step 1: Capture post-change output**

With the server running and patches applied (already true after Task 2 + Task 5):

```bash
curl -s "localhost:7860/synthesize?text=Equivalence%20check&voice=galadriel&lang=en" -o /tmp/after.wav
shasum -a 256 /tmp/after.wav > /tmp/after.sha
cat /tmp/after.sha
```

Record the shasum.

- [ ] **Step 2: Write artifact note**

Because we can't easily revert just Task 2 at this point in the sprint, the equivalence check relies on audible/spectral similarity. Listen to `/tmp/after.wav`; confirm it sounds like Galadriel saying "Equivalence check." If it sounds broken (silent, garbled, or obviously different from other galadriel synths), investigate the `lang_code=lang` change before proceeding — MLX may have a code-path divergence.

Document the result in a note you attach to the commit or in the repo under `scripts/`:

```bash
echo "Qwen3 equivalence check on $(date): shasum $(shasum -a 256 /tmp/after.wav | cut -d' ' -f1) — audibly correct (Galadriel reading 'Equivalence check')." > /tmp/equivalence-note.txt
cat /tmp/equivalence-note.txt
```

- [ ] **Step 3: If the check passes, no code change is needed — proceed. If it fails, halt and investigate.**

No commit for this task unless the check reveals a problem.

---

### Task 15: Demo site — copy updates (locations 1-11)

**Files:**
- Modify: `docs/index.html` (11 specific locations per spec Item 2)

- [ ] **Step 1: Update OG description (location 1, ~L9)**

In `docs/index.html`, find the line with `<meta name="description"` or `<meta property="og:description"`:

```html
  <meta property="og:description" content="Zero-shot voice cloning on Apple Silicon. 20 voices included. No cloud dependency.">
```

Replace `20 voices included` with `20 voices, 4 backends`:

```html
  <meta property="og:description" content="Zero-shot voice cloning on Apple Silicon. 20 voices, 4 backends. No cloud dependency.">
```

- [ ] **Step 2: Update hero stats (location 2, ~L540-543)**

Find the `.hero-stats` block:

```html
        <div><div class="stat-value">20</div><div class="stat-label">Voices included</div></div>
        <div><div class="stat-value">~6 GB</div><div class="stat-label">Peak memory</div></div>
        <div><div class="stat-value">~20s</div><div class="stat-label">Per sentence</div></div>
        <div><div class="stat-value">0</div><div class="stat-label">Cloud calls</div></div>
```

Replace `~6 GB` / `Peak memory` cell with `~10 GB` / `Peak memory`:

```html
        <div><div class="stat-value">20</div><div class="stat-label">Voices included</div></div>
        <div><div class="stat-value">4</div><div class="stat-label">Backends</div></div>
        <div><div class="stat-value">~10 GB</div><div class="stat-label">Peak memory</div></div>
        <div><div class="stat-value">0</div><div class="stat-label">Cloud calls</div></div>
```

(Drops "Per sentence" stat since per-backend varies now — Performance section will cover it.)

- [ ] **Step 3: Update voice-gallery section title + narration (locations 3-4, ~L567-568)**

Find the `.section-title` for the voice gallery:

```html
      <div class="section-title">20 voices, each cloned from a 15-second clip</div>
      <p class="section-desc">Each says <em>&ldquo;You are absolutely right. Your Claude Code session could sound like me.&rdquo;</em> &mdash; generated locally on an 8 GB M1.</p>
```

Replace with:

```html
      <div class="section-title">20 voices on Qwen3 0.6B — see backend comparison below for flagship voices on all 4 models</div>
      <p class="section-desc">Each says <em>&ldquo;You are absolutely right. Your Claude Code session could sound like me.&rdquo;</em> &mdash; generated locally on a 32 GB M1.</p>
```

- [ ] **Step 4: Update "How It Works" paragraph (location 5, ~L743)**

Find:

```html
      <p>The server uses <a href="https://github.com/QwenLM/Qwen3-TTS">Qwen3-TTS</a> (0.6B, 8-bit) on <a href="https://github.com/ml-explore/mlx">MLX</a>. Zero-shot voice cloning &mdash; no training. A 15-second reference + transcript = cloned voice.</p>
```

Replace with:

```html
      <p>The server ships four MLX backends: <a href="https://github.com/QwenLM/Qwen3-TTS">Qwen3-TTS</a> (0.6B and 1.7B, 8-bit), <a href="https://huggingface.co/mlx-community/chatterbox-fp16">Chatterbox</a> (fp16, multilingual), and <a href="https://huggingface.co/mlx-community/VoxCPM1.5">VoxCPM 1.5</a> (44.1 kHz). Zero-shot voice cloning &mdash; no training. A 15-second reference + transcript = cloned voice on every backend.</p>
```

- [ ] **Step 5: Update /health example body (location 6, ~L764-772)**

Find the code block showing the /health JSON (starts with `{` after `curl localhost:7860/health | jq .`). Replace its contents with:

```html
<pre><code>{
  "status": "ok",
  "model": "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit",
  "backend": "mlx",
  "model_loaded": true,
  "ready": true,
  "voices": ["attenborough", "attenborough-chatterbox", "attenborough-qwen3-17b", "attenborough-voxcpm-15", "audrey", "..."],
  "default_voice": "galadriel",
  "loaded_backends": {
    "qwen3-0.6b":  {"loaded": true, "voice_count": 20, "sample_rate": 24000, "display_name": "Qwen3-TTS 0.6B", "supported_langs": ["en","zh","ja","ko","es","fr","de","it","pt","ru"]},
    "qwen3-1.7b":  {"loaded": true, "voice_count": 3,  "sample_rate": 24000, "display_name": "Qwen3-TTS 1.7B", "supported_langs": ["en","zh","ja","ko","es","fr","de","it","pt","ru"]},
    "chatterbox":  {"loaded": true, "voice_count": 3,  "sample_rate": 24000, "display_name": "Chatterbox (fp16, multilingual)", "supported_langs": ["en","es","fr","de","it","pt","zh","ja","ko"]},
    "voxcpm-1.5":  {"loaded": true, "voice_count": 3,  "sample_rate": 44100, "display_name": "VoxCPM 1.5", "supported_langs": ["en","zh"]}
  }
}</code><span class="copy-hint">click to copy</span></pre>
```

- [ ] **Step 6: Update clone-CLI restart note (location 7, ~L815)**

Find the `<p>` inside the `afterwords clone` endpoint card:

```html
        <p class="endpoint-desc">Clone a new voice from a YouTube clip. Restart the server to load it.</p>
```

Replace with:

```html
        <p class="endpoint-desc">Clone a new voice from a YouTube clip. Run <code>afterwords reload</code> to load it (no restart needed).</p>
```

- [ ] **Step 7: Update CLI command list (location 8, ~L967-978)**

Find the CLI command block. Add a `reload` line:

```html
<pre><code>afterwords start       # start the server (auto-starts on login)
afterwords stop        # stop the server
afterwords restart     # restart after adding voices
afterwords status      # show health, model, loaded voices
afterwords logs        # tail the server log
afterwords voices      # list available voices
afterwords reload      # pick up new voices without restart
afterwords clone       # clone a new voice from YouTube
afterwords uninstall   # remove service and optionally hooks</code><span class="copy-hint">click to copy</span></pre>
```

- [ ] **Step 8: Update Performance section title (location 9, ~L988)**

Find:

```html
      <div class="section-title">On an 8 GB M1</div>
```

Replace with:

```html
      <div class="section-title">On a 32 GB Apple Silicon Mac</div>
```

- [ ] **Step 9: Update Performance info-grid (location 10, ~L990-993)**

Find the existing info-grid block:

```html
      <div class="info-grid">
        <div class="info-cell"><div class="info-cell-label">Model load</div><div class="info-cell-value">~5s cached</div></div>
        <div class="info-cell"><div class="info-cell-label">Per sentence</div><div class="info-cell-value">~20s</div></div>
        <div class="info-cell"><div class="info-cell-label">Peak memory</div><div class="info-cell-value">~6 GB</div></div>
        <div class="info-cell"><div class="info-cell-label">Adding a voice</div><div class="info-cell-value">0 extra RAM</div></div>
      </div>
```

Replace with:

```html
      <div class="info-grid">
        <div class="info-cell"><div class="info-cell-label">Qwen3 0.6B</div><div class="info-cell-value">~20s / sentence</div></div>
        <div class="info-cell"><div class="info-cell-label">Qwen3 1.7B</div><div class="info-cell-value">~35s / sentence</div></div>
        <div class="info-cell"><div class="info-cell-label">Chatterbox</div><div class="info-cell-value">~25s / sentence</div></div>
        <div class="info-cell"><div class="info-cell-label">VoxCPM 1.5</div><div class="info-cell-value">~30s / sentence</div></div>
        <div class="info-cell"><div class="info-cell-label">Peak memory</div><div class="info-cell-value">~10 GB (all 4 loaded)</div></div>
        <div class="info-cell"><div class="info-cell-label">Adding a voice</div><div class="info-cell-value">0 extra RAM</div></div>
      </div>
```

- [ ] **Step 10: Update Requirements info-grid (location 11, ~L1004)**

Find:

```html
        <div class="info-cell"><div class="info-cell-label">Memory</div><div class="info-cell-value">8 GB+ RAM</div></div>
```

Replace with:

```html
        <div class="info-cell"><div class="info-cell-label">Memory</div><div class="info-cell-value">32 GB+ RAM</div></div>
```

- [ ] **Step 11: Update Credits (add Chatterbox + VoxCPM)**

Find the Credits section (~L1015):

```html
      <p><a href="https://github.com/QwenLM/Qwen3-TTS">Qwen3-TTS</a> (Alibaba, Apache 2.0) &middot; <a href="https://github.com/Blaizzy/mlx-audio">mlx-audio</a> &middot; <a href="https://github.com/ml-explore/mlx">MLX</a> (Apple) &middot; <a href="https://docs.anthropic.com/en/docs/claude-code/">Claude Code</a> (Anthropic)</p>
```

Replace with:

```html
      <p><a href="https://github.com/QwenLM/Qwen3-TTS">Qwen3-TTS</a> (Alibaba) &middot; <a href="https://huggingface.co/mlx-community/chatterbox-fp16">Chatterbox</a> (mlx-community) &middot; <a href="https://huggingface.co/mlx-community/VoxCPM1.5">VoxCPM</a> (mlx-community) &middot; <a href="https://github.com/Blaizzy/mlx-audio">mlx-audio</a> &middot; <a href="https://github.com/ml-explore/mlx">MLX</a> (Apple) &middot; <a href="https://docs.anthropic.com/en/docs/claude-code/">Claude Code</a> (Anthropic)</p>
```

- [ ] **Step 12: Verify no residual "8 GB" outside of historic/contextual uses**

```
grep -n "8 GB\|8 gb" docs/index.html
```

Expected: no hits (or only inside unrelated historical phrasing, e.g. within an endpoint description where the number is illustrative). Fix any true-positives inline.

- [ ] **Step 13: Commit**

```bash
git add docs/index.html
git commit -m "docs(site): update copy across 11 locations for multi-backend reality"
```

---

### Task 16: Demo site — Backend Comparison section (HTML + CSS + JS)

**Files:**
- Modify: `docs/index.html` (insert new section between Voice Gallery and How It Works; add CSS + JS)

- [ ] **Step 1: Insert the Backend Comparison section HTML**

In `docs/index.html`, find the `</section>` that closes the voice-gallery section (right before the divider leading to "How It Works"). After that `</section>` and its following `<div class="divider"></div>`, insert:

```html
    <section class="reveal">
      <div class="section-label">Backend Comparison</div>
      <div class="section-title">Same voice, four backends</div>
      <p class="section-desc">Three flagship voices, each synthesized by all four backends. Click a tab to hear how the same 15-second reference sounds across Qwen3 0.6B, Qwen3 1.7B, Chatterbox, and VoxCPM 1.5.</p>

      <div class="compare-grid">
        <div class="compare-card" data-voice="picard" data-urls='{"qwen3-0.6b":"audio/comparison/picard-qwen3-06b.mp3","qwen3-1.7b":"audio/comparison/picard-qwen3-17b.mp3","chatterbox":"audio/comparison/picard-chatterbox.mp3","voxcpm-1.5":"audio/comparison/picard-voxcpm-15.mp3"}'>
          <div class="voice-name">Picard</div>
          <div class="voice-source">Patrick Stewart, Star Trek</div>
          <div role="tablist" class="backend-tabs" aria-label="Backends for Picard">
            <button role="tab" id="picard-tab-0" aria-selected="true"  aria-controls="picard-panel" tabindex="0"  data-backend="qwen3-0.6b">Qwen3 0.6B</button>
            <button role="tab" id="picard-tab-1" aria-selected="false" aria-controls="picard-panel" tabindex="-1" data-backend="qwen3-1.7b">Qwen3 1.7B</button>
            <button role="tab" id="picard-tab-2" aria-selected="false" aria-controls="picard-panel" tabindex="-1" data-backend="chatterbox">Chatterbox</button>
            <button role="tab" id="picard-tab-3" aria-selected="false" aria-controls="picard-panel" tabindex="-1" data-backend="voxcpm-1.5">VoxCPM</button>
          </div>
          <div role="tabpanel" id="picard-panel" aria-labelledby="picard-tab-0" tabindex="0">
            <audio controls preload="none" src="audio/comparison/picard-qwen3-06b.mp3" aria-label="Picard synthesized"></audio>
          </div>
        </div>

        <div class="compare-card" data-voice="galadriel" data-urls='{"qwen3-0.6b":"audio/comparison/galadriel-qwen3-06b.mp3","qwen3-1.7b":"audio/comparison/galadriel-qwen3-17b.mp3","chatterbox":"audio/comparison/galadriel-chatterbox.mp3","voxcpm-1.5":"audio/comparison/galadriel-voxcpm-15.mp3"}'>
          <div class="voice-name">Galadriel</div>
          <div class="voice-source">Cate Blanchett, LOTR</div>
          <div role="tablist" class="backend-tabs" aria-label="Backends for Galadriel">
            <button role="tab" id="galadriel-tab-0" aria-selected="true"  aria-controls="galadriel-panel" tabindex="0"  data-backend="qwen3-0.6b">Qwen3 0.6B</button>
            <button role="tab" id="galadriel-tab-1" aria-selected="false" aria-controls="galadriel-panel" tabindex="-1" data-backend="qwen3-1.7b">Qwen3 1.7B</button>
            <button role="tab" id="galadriel-tab-2" aria-selected="false" aria-controls="galadriel-panel" tabindex="-1" data-backend="chatterbox">Chatterbox</button>
            <button role="tab" id="galadriel-tab-3" aria-selected="false" aria-controls="galadriel-panel" tabindex="-1" data-backend="voxcpm-1.5">VoxCPM</button>
          </div>
          <div role="tabpanel" id="galadriel-panel" aria-labelledby="galadriel-tab-0" tabindex="0">
            <audio controls preload="none" src="audio/comparison/galadriel-qwen3-06b.mp3" aria-label="Galadriel synthesized"></audio>
          </div>
        </div>

        <div class="compare-card" data-voice="attenborough" data-urls='{"qwen3-0.6b":"audio/comparison/attenborough-qwen3-06b.mp3","qwen3-1.7b":"audio/comparison/attenborough-qwen3-17b.mp3","chatterbox":"audio/comparison/attenborough-chatterbox.mp3","voxcpm-1.5":"audio/comparison/attenborough-voxcpm-15.mp3"}'>
          <div class="voice-name">Attenborough</div>
          <div class="voice-source">David Attenborough, BBC Earth</div>
          <div role="tablist" class="backend-tabs" aria-label="Backends for Attenborough">
            <button role="tab" id="attenborough-tab-0" aria-selected="true"  aria-controls="attenborough-panel" tabindex="0"  data-backend="qwen3-0.6b">Qwen3 0.6B</button>
            <button role="tab" id="attenborough-tab-1" aria-selected="false" aria-controls="attenborough-panel" tabindex="-1" data-backend="qwen3-1.7b">Qwen3 1.7B</button>
            <button role="tab" id="attenborough-tab-2" aria-selected="false" aria-controls="attenborough-panel" tabindex="-1" data-backend="chatterbox">Chatterbox</button>
            <button role="tab" id="attenborough-tab-3" aria-selected="false" aria-controls="attenborough-panel" tabindex="-1" data-backend="voxcpm-1.5">VoxCPM</button>
          </div>
          <div role="tabpanel" id="attenborough-panel" aria-labelledby="attenborough-tab-0" tabindex="0">
            <audio controls preload="none" src="audio/comparison/attenborough-qwen3-06b.mp3" aria-label="Attenborough synthesized"></audio>
          </div>
        </div>
      </div>
    </section>

    <div class="divider"></div>
```

- [ ] **Step 2: Add CSS for the compare section**

In the `<style>` block (inside `<head>`), just before the Responsive media queries (around line 505), add:

```css
    /* ── Backend Comparison ──────────────────────── */
    .compare-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 1.1rem;
      margin-top: 1rem;
    }
    .compare-card {
      background: var(--bg-card);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 1.25rem 1.3rem 1.15rem;
      transition: border-color 0.3s, background 0.3s;
    }
    .compare-card:hover { border-color: var(--border-hover); }
    .backend-tabs {
      display: flex;
      gap: 0;
      margin: 0.75rem 0;
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }
    .backend-tabs button {
      flex: 1;
      font-family: var(--mono);
      font-size: 0.65rem;
      font-weight: 500;
      background: transparent;
      color: var(--text-secondary);
      border: none;
      padding: 0.5rem 0.4rem;
      cursor: pointer;
      transition: background 0.2s, color 0.2s;
      border-right: 1px solid var(--border);
    }
    .backend-tabs button:last-child { border-right: none; }
    .backend-tabs button:hover { color: var(--text); background: rgba(255,255,255,0.03); }
    .backend-tabs button[aria-selected="true"] {
      color: var(--accent);
      background: var(--accent-glow);
    }
    .backend-tabs button:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: -2px;
    }
    .compare-card [role="tabpanel"] { outline: none; }
    .compare-card audio { width: 100%; height: 32px; border-radius: 4px; }
```

- [ ] **Step 3: Add JS wiring**

Find the `</script>` tag at the end of the `<script>` block (around line 1180). Just before it, add:

```javascript
// ── Backend Comparison tabs ──────────────────────────────────────
document.querySelectorAll('.compare-card').forEach(card => {
  const tablist = card.querySelector('[role="tablist"]');
  const tabs = Array.from(card.querySelectorAll('[role="tab"]'));
  const panel = card.querySelector('[role="tabpanel"]');
  const audio = card.querySelector('audio');
  if (!tablist || !panel || !audio) return;

  let urls = {};
  try { urls = JSON.parse(card.getAttribute('data-urls') || '{}'); } catch (e) { return; }

  function activate(idx) {
    tabs.forEach((t, i) => {
      const on = i === idx;
      t.setAttribute('aria-selected', on ? 'true' : 'false');
      t.setAttribute('tabindex', on ? '0' : '-1');
      if (on) {
        panel.setAttribute('aria-labelledby', t.id);
        const backend = t.getAttribute('data-backend');
        const url = urls[backend];
        if (url && audio.src !== new URL(url, location.href).href) {
          audio.pause();
          audio.src = url;
          audio.load();
        }
      }
    });
  }

  tabs.forEach((tab, idx) => {
    tab.addEventListener('click', () => { activate(idx); tab.focus(); });
    tab.addEventListener('keydown', (e) => {
      let next = idx;
      if (e.key === 'ArrowRight') next = (idx + 1) % tabs.length;
      else if (e.key === 'ArrowLeft') next = (idx - 1 + tabs.length) % tabs.length;
      else if (e.key === 'Home') next = 0;
      else if (e.key === 'End') next = tabs.length - 1;
      else return;
      e.preventDefault();
      activate(next);
      tabs[next].focus();
    });
  });
});
```

- [ ] **Step 4: Manually verify in a browser**

Start any simple HTTP server from the repo:

```
cd docs && python3 -m http.server 8000
```

Open `http://localhost:8000/` in a browser. Scroll to Backend Comparison. Click each tab — audio source must swap. Use keyboard: Tab to focus a tablist, then Left/Right arrows should move selection and focus. Home/End jump to first/last. Active tab has accent styling.

- [ ] **Step 5: Stop the HTTP server and commit**

```
# Ctrl-C the python server
git add docs/index.html
git commit -m "docs(site): add Backend Comparison section with accessible tabs"
```

---

### Task 17: Cross-project doc audit (CLAUDE.md, AGENTS.md, README.md)

**Files:**
- Modify (if residual "8 GB" content found): `CLAUDE.md`, `AGENTS.md` (if exists), `README.md`

- [ ] **Step 1: Grep for residuals**

```
grep -rni '8 gb\|8 ghz\|Qwen3-TTS (0.6B, 8-bit) on MLX' CLAUDE.md AGENTS.md README.md 2>/dev/null || true
```

Expected: no relevant hits. If there are, update each to match the multi-backend reality (see revision-5 spec's cross-project doc section).

- [ ] **Step 2: Commit any updates**

If any files were modified:

```bash
git add -u
git commit -m "docs: cross-project audit — remove residual 8 GB / single-backend copy"
```

If nothing needs updating, skip the commit and proceed.

---

### Task 18: Final verification

**Files:** none (all verification commands).

- [ ] **Step 1: Run the full test suite**

```
pytest
```

Expected: all tests pass, count at least: baseline 61 + 11 new (from Tasks 1, 6, 7, 9, 10) = 72. Integration tests remain 4 deselected.

- [ ] **Step 2: Grep acceptance criteria**

```
grep -n "8 GB\|8 gb\|20 voices included" docs/index.html CLAUDE.md AGENTS.md README.md 2>/dev/null
```

Expected: no true hits (no 8-GB RAM callouts outside history/examples).

- [ ] **Step 3: Confirm voice-profile load count**

```
curl -s localhost:7860/health | python3 -c "import sys,json; b=json.load(sys.stdin); print(len(b['voices']), 'voices'); print({k:v['voice_count'] for k,v in b['loaded_backends'].items()})"
```

Expected: total voices includes the 9 new flagship profiles; per-backend counts reflect them.

- [ ] **Step 4: Manually test /reload end-to-end**

Create a throwaway profile:

```
cat > voices/_reload-smoke.json <<EOF
{"name":"_reload-smoke","backend":"qwen3-0.6b","reference_audio":"galadriel-ref.wav","reference_text":"Smoke test."}
EOF
curl -sX POST localhost:7860/reload | python3 -m json.tool
```

Expected: `_reload-smoke` in `reloaded[]`. Clean up:

```
rm voices/_reload-smoke.json
```

Run `/reload` again — the add-only semantics mean `_reload-smoke` stays in VOICES (expected behavior per decision 3A). A server restart would drop it.

- [ ] **Step 5: Spot-check the demo site**

```
cd docs && python3 -m http.server 8000
```

Open `http://localhost:8000/`, verify:
- Hero says "20 voices / 4 backends / ~10 GB / 0"
- Backend Comparison section visible between Gallery and How It Works
- Tab keyboard nav works
- Audio switches on tab click

Stop the server (Ctrl-C).

- [ ] **Step 6: Confirm no TODO/FIXME added in this sprint**

```
git diff --unified=0 main -- '*.py' '*.sh' '*.html' | grep -iE '^\+.*(TODO|FIXME|HACK|XXX)' | grep -v 'No TODO'
```

Expected: empty output (the only hit should be the spec's acceptance criterion referencing the anti-pattern, which isn't in diff scope).

- [ ] **Step 7: Final commit if anything uncommitted**

```
git status
# If clean, nothing to do. Otherwise git add + commit the last fixes.
```

---

## Done

All 4 sprint items delivered. Ready for `superpowers:finishing-a-development-branch`.
