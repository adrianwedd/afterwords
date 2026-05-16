# QA Followup — Requirements Hygiene + Test Coverage Plan

> **Status (2026-05-16): historical.** Tasks 1–6 landed in commits
> `48455ff..639de85`; task 7 (issue #14 fidelity verification) was rolled
> into Sprint 1 of the v1.0.0 roadmap. See
> `docs/superpowers/plans/2026-05-16-roadmap.md`. Checkboxes below are
> NOT maintained.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the six open findings from the 2026-05-10 QA session: three requirements hygiene issues (M4-M6) and three test coverage gaps (M1-M3), then resolve issue #14 (silence-gap + Chatterbox fidelity verification).

**Architecture:** No new production files. Tasks M4-M6 are requirements edits only. Tasks M1-M3 add test cases inside the existing `tests/test_server.py` and `tests/test_backends.py` files, using the existing `FakeBackend` fixture and `pytest` patterns already in the repo. Issue #14 is a manual verification + comment task.

**Tech Stack:** Python 3.11+, pytest, FastAPI test client (httpx), soundfile, numpy; no GPU required for any task.

---

## Context for new agents

This is the `afterwords` repo — a local voice-cloning TTS server on Apple Silicon. The test suite uses a `FakeBackend` (defined at `tests/test_server.py:51`) that only supports `lang="en"` and raises `ValueError` for anything else. All tests run with `.venv/bin/pytest` (not system pytest). No GPU is needed.

Key types:
- `PreparedVoice` — frozen dataclass in `backends/base.py`; fields: `ref_audio_path`, `ref_text`, `extras`, `owns_temp_audio=False`, `cleanup_paths=()`, `data=None`
- `VoiceProfile` — dataclass in `server.py`; fields include `name`, `backend`, `ref_audio`, `ref_text`, `session_id`, `emotion`, `quality`, `duration_s`, `confidence`, `sequence`, `extras`, `prepared`
- `server.VOICES` — `dict[str, VoiceProfile]`; must be restored after mutating in tests
- `server._clone_enabled` — must be `True` for `/reload` endpoint to respond

Run tests: `.venv/bin/pytest`
Run single test: `.venv/bin/pytest tests/test_server.py::test_name -v`

---

### Task 1: Pin unpinned packages in requirements-firered-tts-2.txt (M4)

**Files:**
- Modify: `requirements-firered-tts-2.txt`

The file currently has five unpinned packages: `einops`, `librosa`, `optuna`, `accelerate`, `tensorboard`. These should be pinned to concrete minimum versions matching the ecosystem (torch 2.8 / transformers 4.48).

- [ ] **Step 1: Check current latest compatible versions**

```bash
# Quick check — these versions are known-good for torch>=2.8 + transformers>=4.48
# einops 0.8.x is the stable series; librosa 0.10.x; optuna 4.x; accelerate 1.x; tensorboard 2.x
echo "einops>=0.8.0" "librosa>=0.10.2" "optuna>=4.0.0" "accelerate>=1.0.0" "tensorboard>=2.17.0"
```

- [ ] **Step 2: Pin the five packages**

Edit `requirements-firered-tts-2.txt`. Change lines 22-26 from:
```
einops
librosa
optuna
accelerate
tensorboard
```
to:
```
einops>=0.8.0
librosa>=0.10.2
optuna>=4.0.0
accelerate>=1.0.0
tensorboard>=2.17.0
```

- [ ] **Step 3: Verify the file looks correct**

```bash
cat requirements-firered-tts-2.txt
```

Expected: all packages have version constraints, no bare package names.

- [ ] **Step 4: Commit**

```bash
git add requirements-firered-tts-2.txt
git commit -m "chore: pin unpinned packages in requirements-firered-tts-2.txt"
```

---

### Task 2: Fix torch/torchaudio version mismatch in requirements-cosyvoice2.txt (M5)

**Files:**
- Modify: `requirements-cosyvoice2.txt`

The file pins `torch==2.8.0` but `torchaudio==2.3.1`. These are mismatched: torchaudio 2.3.1 requires torch 2.3.x. The correct pairing is `torchaudio==2.8.0`. Additionally, `numpy==1.26.4` conflicts with `transformers==5.0.0rc3` which requires numpy>=1.24 (fine) but some torch 2.8 ops need numpy>=2.0 on arm64. The safest fix is to loosen numpy to `numpy>=1.26.4,<3`.

- [ ] **Step 1: Fix torchaudio pin**

Edit `requirements-cosyvoice2.txt` line 13: change `torchaudio==2.3.1` → `torchaudio==2.8.0`

- [ ] **Step 2: Loosen numpy pin**

Edit `requirements-cosyvoice2.txt` line 25: change `numpy==1.26.4` → `numpy>=1.26.4,<3`

- [ ] **Step 3: Verify**

```bash
grep -n "torch\|numpy" requirements-cosyvoice2.txt
```

Expected output:
```
12:torch==2.8.0
13:torchaudio==2.8.0
...
25:numpy>=1.26.4,<3
```

- [ ] **Step 4: Commit**

```bash
git add requirements-cosyvoice2.txt
git commit -m "fix: align torchaudio pin to torch==2.8.0 and loosen numpy in cosyvoice2 deps"
```

---

### Task 3: Remove remote -r flag from requirements-gpt-sovits.txt (M6)

**Files:**
- Modify: `requirements-gpt-sovits.txt`

Line 17 is `-r https://raw.githubusercontent.com/...` — pip allows `-r` with a URL but this bypasses local dependency auditing, is fragile (remote file changes silently), and triggers pip security warnings. The comment block above already tells users to clone the repo manually. Remove the remote -r line entirely; add a comment noting users should install from the cloned repo's requirements.txt themselves.

- [ ] **Step 1: Remove the remote -r line**

Edit `requirements-gpt-sovits.txt`. Remove line 17:
```
-r https://raw.githubusercontent.com/RVC-Boss/GPT-SoVITS/main/requirements.txt
```

And add this comment at the bottom:
```
# Install GPT-SoVITS Python deps separately from the cloned repo:
#   pip install -r backends/extras/gpt-sovits/GPT-SoVITS/requirements.txt
```

- [ ] **Step 2: Verify the file**

```bash
cat requirements-gpt-sovits.txt
```

Expected: No `-r https://...` line. The file should contain only comments now (plus the new comment).

- [ ] **Step 3: Commit**

```bash
git add requirements-gpt-sovits.txt
git commit -m "fix: remove remote -r URL from requirements-gpt-sovits.txt"
```

---

### Task 4: Add test — real ValueError path in synthesize for unsupported lang (M1)

**Files:**
- Modify: `tests/test_server.py` — add test after `test_synthesize_unsupported_lang_returns_400` (around line 299)

The existing `test_synthesize_unsupported_lang_returns_400` at line 292 tests the HTTP 400 response. However, it relies on the routing layer catching the ValueError from `FakeBackend.synthesize`. We need a lower-level test confirming that when the routing logic calls `backend.synthesize()` with an unsupported lang, it really does raise `ValueError` (not just silently produce wrong output).

- [ ] **Step 1: Write the failing test**

Insert this test after `test_synthesize_unsupported_lang_returns_400` (after line 299 in `tests/test_server.py`):

```python
def test_fake_backend_synthesize_raises_for_unsupported_lang():
    """FakeBackend.synthesize must raise ValueError for langs outside supported_langs.

    This verifies the backend contract, independent of the HTTP routing layer.
    The server relies on ValueError to produce the 400 + supported_langs body.
    """
    import backends as _backends
    from backends.base import PreparedVoice, _read_only
    import numpy as np

    be = _backends.get("fake")
    pv = PreparedVoice(
        ref_audio_path="/dev/null",
        ref_text=None,
        extras=_read_only({}),
    )
    assert "en" in be.supported_langs
    assert "fr" not in be.supported_langs

    # Supported lang must not raise
    audio, sr = be.synthesize("hello", pv, "en")
    assert isinstance(audio, np.ndarray)

    # Unsupported lang must raise ValueError (not KeyError, not RuntimeError)
    import pytest as _pytest
    with _pytest.raises(ValueError, match="fr"):
        be.synthesize("bonjour", pv, "fr")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_server.py::test_fake_backend_synthesize_raises_for_unsupported_lang -v
```

Expected: FAIL (FakeBackend may not yet raise ValueError for unsupported langs — check its `synthesize` implementation first).

If the test *passes* immediately, inspect `FakeBackend.synthesize` — it may already have the guard. In that case, this is a documentation-level test; proceed to Step 4.

- [ ] **Step 3: If test fails — add guard to FakeBackend.synthesize**

Find `FakeBackend` near line 51 in `tests/test_server.py`. Its `synthesize` method should have:

```python
def synthesize(self, text, prepared, lang):
    if lang not in self.supported_langs:
        raise ValueError(
            f"fake does not support lang={lang!r}; supported: {self.supported_langs}"
        )
    return np.zeros(24000, dtype=np.float32), 24000
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_server.py::test_fake_backend_synthesize_raises_for_unsupported_lang -v
```

Expected: PASS

- [ ] **Step 5: Run full suite to check for regressions**

```bash
.venv/bin/pytest
```

Expected: All tests pass (or same count as before).

- [ ] **Step 6: Commit**

```bash
git add tests/test_server.py
git commit -m "test: verify FakeBackend raises ValueError for unsupported lang (backend contract)"
```

---

### Task 5: Add test — reload abort with owns_temp_audio=True (M2)

**Files:**
- Modify: `tests/test_server.py` — add test near `test_reload_abort_cleans_tracked_temps` (around line 503)

The existing reload abort test (`test_reload_abort_cleans_tracked_temps`, line 503) covers `cleanup_paths`. There is a second rollback loop in `server.reload_voices()` that deletes `ref_audio_path` when `owns_temp_audio=True`. This path is untested.

- [ ] **Step 1: Write the failing test**

Insert this test after `test_reload_abort_cleans_tracked_temps` (after line 540 in `tests/test_server.py`):

```python
def test_reload_abort_cleans_owned_temp_audio(client, tmp_path, monkeypatch):
    """When reload aborts mid-batch, a PreparedVoice with owns_temp_audio=True
    must have its ref_audio_path deleted during rollback."""
    import backends as _backends
    import tempfile as _tempfile
    monkeypatch.setattr(server, "_VOICES_DIR", str(tmp_path))
    server.VOICES.clear()
    server._clone_enabled = True

    owned_ref = os.path.join(_tempfile.gettempdir(), "reload-owned-ref.wav")
    with open(owned_ref, "wb") as f:
        f.write(b"x")

    backend = _backends.get("fake")
    from backends.base import PreparedVoice, _read_only

    def prepare_with_owned_temp(ref, txt, extras):
        if "succeed" in ref:
            return PreparedVoice(
                ref_audio_path=owned_ref,
                ref_text=txt,
                extras=_read_only(dict(extras)),
                owns_temp_audio=True,
            )
        raise RuntimeError("boom")

    monkeypatch.setattr(backend, "prepare_voice", prepare_with_owned_temp)

    try:
        _write_profile_json(str(tmp_path), "succeed", backend="fake")
        _write_profile_json(str(tmp_path), "fail", backend="fake")
        r = client.post("/reload")
        assert r.status_code == 500
        assert not os.path.exists(owned_ref), \
            "rollback did not delete ref_audio_path for owns_temp_audio=True PreparedVoice"
    finally:
        server._clone_enabled = False
        server.VOICES.clear()
        try:
            os.remove(owned_ref)
        except OSError:
            pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_server.py::test_reload_abort_cleans_owned_temp_audio -v
```

Expected: FAIL — the owned temp file should still exist after the (currently untested) rollback path.

If the test passes immediately, inspect `server.reload_voices()` for the second rollback loop (after the `cleanup_paths` loop). It may already be implemented. In that case proceed to Step 4.

- [ ] **Step 3: If test fails — check the reload rollback in server.py**

Find the rollback section in `server.reload_voices()`. It should contain two cleanup loops:

```python
# Rollback — delete tracked cleanup_paths
for pv in built_profiles:
    for path in pv.cleanup_paths:
        try:
            os.remove(path)
        except OSError:
            pass
    # Delete owned temp ref audio
    if pv.owns_temp_audio:
        try:
            os.remove(pv.ref_audio_path)
        except OSError:
            pass
```

If the second `if pv.owns_temp_audio` block is missing, add it.

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_server.py::test_reload_abort_cleans_owned_temp_audio -v
```

Expected: PASS

- [ ] **Step 5: Run full suite**

```bash
.venv/bin/pytest
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add tests/test_server.py server.py
git commit -m "test: cover owns_temp_audio rollback path in reload abort test (M2)"
```

---

### Task 6: Expand Chatterbox synthesize mock — assert text + ref_audio + ref_text args (M3)

**Files:**
- Modify: `tests/test_backends.py` — expand `test_chatterbox_synthesize_forwards_lang_and_defaults`

The existing test at `tests/test_backends.py:664` captures `kwargs` but only asserts `lang_code`, `cfg_weight`, `exaggeration`. It does not assert that `text`, `ref_audio`, and `ref_text` are forwarded correctly. A typo in those kwargs would go undetected.

- [ ] **Step 1: Write the additional assertions**

Find `test_chatterbox_synthesize_forwards_lang_and_defaults` in `tests/test_backends.py` (around line 664). After `assert captured_kwargs["exaggeration"] == _DEFAULT_EXAGGERATION` (line 697), add:

```python
    assert captured_kwargs["text"] == "test text"
    assert captured_kwargs["ref_audio"] == str(tmp_path / "ref.wav")
    assert captured_kwargs.get("ref_text") == "hello"
```

And after `assert captured_kwargs["exaggeration"] == 0.3` (near the end of the test), add:

```python
    assert captured_kwargs["text"] == "test text"
    assert captured_kwargs["ref_audio"] == str(tmp_path / "ref.wav")
    assert captured_kwargs.get("ref_text") == "hello"
    assert captured_kwargs["lang_code"] == "fr"
```

- [ ] **Step 2: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_backends.py::test_chatterbox_synthesize_forwards_lang_and_defaults -v
```

Expected: PASS (the implementation already forwards these; we're adding coverage).

If it fails, that means the production code has a bug — investigate `backends/chatterbox.py:synthesize()` and fix the kwarg name.

- [ ] **Step 3: Run full suite**

```bash
.venv/bin/pytest
```

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_backends.py
git commit -m "test: assert text/ref_audio/ref_text args in chatterbox synthesize mock (M3)"
```

---

### Task 7: Resolve GitHub issue #14 (loki silence-gap + Chatterbox fidelity)

**Files:**
- No code changes — verification + GitHub comment

Issue #14 tracks silence-gap QA across all demo voices. Status as of 2026-05-10: 3 of 4 silence-gap voices fixed (galadriel, picard, elara). Loki status unclear. Chatterbox kwargs fix landed in PR #69 but Chatterbox is still excluded from the demo (`voices/loki.json` uses chatterbox backend).

- [ ] **Step 1: Check loki voice profile**

```bash
cat voices/loki.json
```

Note the backend, whether `silence_start_s` / `silence_end_s` fields are present, and the quality score.

- [ ] **Step 2: Play loki sample to check for silence gap**

```bash
afterwords voices --demo
# Or specifically:
curl "localhost:7860/synthesize?text=Glorious+purpose&voice=loki" -o /tmp/loki-test.wav
afplay /tmp/loki-test.wav
```

If the server is not running: `afterwords start` first. Listen for leading/trailing silence.

- [ ] **Step 3: Check Chatterbox fidelity post-kwargs fix**

The kwargs fix (PR #69) forwarded `lang_code`, `cfg_weight`, `exaggeration` to `generate_audio`. Run a quick synthesis and compare perceptually to the reference clip:

```bash
curl "localhost:7860/synthesize?text=The+tesseract+has+awakened&voice=loki&lang=en" \
  -o /tmp/loki-post-fix.wav
afplay /tmp/loki-post-fix.wav
afplay voices/loki-ref.wav
```

Assess: does the synthesized voice sound like loki-ref.wav? If yes, Chatterbox is ready for demo inclusion.

- [ ] **Step 4: Post findings to GitHub issue #14**

```bash
gh issue comment 14 --body "$(cat <<'EOF'
### Loki status (2026-05-11)

**Silence gap:** [PASS/FAIL — fill in after Step 2]

**Chatterbox fidelity post-kwargs fix (PR #69):** [PASS/FAIL — fill in after Step 3]

If both pass, loki can be re-enabled in the demo voice list. Closing or keeping open based on result.
EOF
)"
```

- [ ] **Step 5: Close issue #14 if all voices pass**

If loki silence gap is gone and Chatterbox fidelity is acceptable:

```bash
gh issue close 14 --comment "All silence-gap voices verified. Chatterbox kwargs fix confirmed. Loki re-enabled in demo."
```

---

## Self-review

**Spec coverage check:**
- M4 (pin unpinned firered deps) → Task 1 ✓
- M5 (cosyvoice2 torch/torchaudio/numpy) → Task 2 ✓
- M6 (remove remote -r from gpt-sovits) → Task 3 ✓
- M1 (real ValueError path in synthesize) → Task 4 ✓
- M2 (reload abort with owns_temp_audio=True) → Task 5 ✓
- M3 (assert text/ref_audio/ref_text in Chatterbox mock) → Task 6 ✓
- Issue #14 (loki + Chatterbox fidelity) → Task 7 ✓
- Issue #70 (MFCC regression test) — **not in scope for this plan** — deserves its own plan due to new test infrastructure (MFCC computation, threshold calibration, CI fixture audio)

**Placeholder scan:** No TBDs, no "similar to above", all test code is complete.

**Type consistency:** `PreparedVoice` fields (`ref_audio_path`, `ref_text`, `extras`, `owns_temp_audio`, `cleanup_paths`, `data`) match `backends/base.py`. `_write_profile_json` helper used in Tasks 5-6 is already defined in `tests/test_server.py`. `_backends.get("fake")` matches existing fixture usage at line 515.
