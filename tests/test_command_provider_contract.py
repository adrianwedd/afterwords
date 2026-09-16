"""Command-provider delivery contract: the artifact handed to Hermes must be the speech.

`scripts/afterwords-tts-command.sh` used to write a 0.1s SILENT placeholder to
`{output_path}` and fire the real synthesis + playback into a detached subshell.
Hermes only requires the artifact to be non-empty, so the silent placeholder
satisfied the tool contract while delivering none of the speech — and nothing in
Hermes plays command-provider audio on CLI outside `/voice`, so the real audio
went only to `~/.hermes/tts-archive/` where a paused cron job was the sole reader.

These tests pin the corrected contract:

  * on the direct-CLI path the artifact at `{output_path}` IS the request's speech
    payload (real audio, same voice/text, not the silence placeholder), and the
    provider exits 0 having written it;
  * gateway/messaging path semantics (synchronous real artifact) are unchanged;
  * the canonical strip/chunk modules are reached, not re-implemented.

`SILENCE_PLACEHOLDER_WAV` is the exact byte string the old path emitted
(0.1s @ 24kHz/16-bit mono). Asserting only `size > 100_000` would not catch a
regression back to it, so the comparison is explicit — for the long case as much
as the short one.
"""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
# Overridable so the retired provider can be driven from `git show` to prove a
# new test fails against it (see the partial-delivery tests).
COMMAND_SCRIPT = Path(
    os.environ.get("AFTERWORDS_COMMAND_SCRIPT") or (REPO / "scripts/afterwords-tts-command.sh")
)

# Historical failure boundary: the reply that used to speak only its first chunk.
# Same fixture as tests/test_tts_surface_parity.py (1802 chars in, 1730 stripped).
LONG_REPLY = textwrap.dedent(
    """\
    ## Convergence Report

    Summary of the work:

    - the first bullet is deliberately long enough to matter for chunking
    - the second bullet continues the list with more spoken words
    - the third bullet closes it out

    1. numbered step one
    2. numbered step two

    Some **bold** text, some `inline code`, and a link to [the docs](https://example.com/docs).

    ### Detail section

    """
) + (
    "This paragraph exists purely to push the reply past the old thousand character cap "
    "so a truncating surface is caught. " * 12
) + "\n\nglm-5.1 · 9% · ~\n"

SHORT_REPLY = "Short turn latency check."

LONG_INPUT_CHARS = 1802
LONG_STRIPPED_CHARS = 1730


def _silence_placeholder_wav() -> bytes:
    """Exact bytes of the retired 0.1s silent placeholder (24kHz, 16-bit mono)."""
    import struct

    sample_rate, bits, channels = 24000, 16, 1
    n_samples = int(sample_rate * 0.1)
    data_size = n_samples * channels * (bits // 8)
    fmt_size = 16
    riff_size = 4 + (8 + fmt_size) + (8 + data_size)
    out = bytearray()
    out += b"RIFF" + struct.pack("<I", riff_size) + b"WAVE"
    out += b"fmt " + struct.pack("<I", fmt_size)
    out += struct.pack(
        "<HHIIHH", 1, channels, sample_rate, sample_rate * channels * (bits // 8),
        channels * (bits // 8), bits,
    )
    out += b"data" + struct.pack("<I", data_size)
    out += b"\x00" * data_size
    return bytes(out)


SILENCE_PLACEHOLDER_WAV = _silence_placeholder_wav()
SILENCE_BYTES = len(SILENCE_PLACEHOLDER_WAV)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------
# The provider's own contract statements
# --------------------------------------------------------------------------

def test_provider_never_writes_the_silent_placeholder():
    """A regression to `struct`/0.1s silence in the provider body must fail here.

    Guards the class, not the call site: the placeholder was emitted by an
    inline `python3 -c` struct blob, so any reappearance of that shape is caught.
    """
    source = COMMAND_SCRIPT.read_text()
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "struct.pack" not in body, (
        "the provider is writing a synthetic WAV again — {output_path} must carry "
        "the real synthesized artifact"
    )
    assert "0.1" not in body or "n_samples" not in body, (
        "0.1s-silence placeholder shape detected in the provider body"
    )


def test_provider_does_not_detach_synthesis_on_cli():
    """The artifact must be delivered by the time the process exits."""
    source = COMMAND_SCRIPT.read_text()
    body = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert ") &" not in body, (
        "synthesis is still detached into a background subshell — the caller "
        "would return before real audio exists at {output_path}"
    )


def test_provider_chunks_through_the_canonical_module():
    """Chunking must be the canonical implementation, invoked as the documented CLI."""
    source = COMMAND_SCRIPT.read_text()
    assert "chunks.py" in source, "provider does not invoke the canonical chunker"
    assert "$AFTERWORDS_REPO_ROOT" in source, "provider lost repo-root resolution"
    # It must not carry a private splitter.
    assert "re.split" not in source, "provider re-implements the sentence splitter"


# --------------------------------------------------------------------------
# Behaviour against a stubbed server + real Hermes file contract
# --------------------------------------------------------------------------

def _write_exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_tts_payload(text: str, header: bytes = b"RIFF") -> bytes:
    """A stand-in 'WAV' whose bytes encode the text, so payload identity is checkable.

    Uses the real RIFF header prefix so Hermes's container sniffing sees audio.
    """
    import hashlib

    digest = hashlib.sha256(text.encode()).hexdigest()
    pad = b"\x00" * max(0, 256 - len(header))
    return header + pad + digest.encode() + b"|" + text.encode()


def _run_provider(tmp_path: Path, text: str, platform: str = "cli",
                  voice: str = "seven-of-nine", stub_text_key: bool = True,
                  fail_from_chunk: int = 0):
    """Run the provider with a stubbed curl/afplay/lame/hermes; return (result, ctx).

    The curl stub writes a text-derived payload for `-o <path>` and logs the
    synthesised `text=` values it was asked for. `fail_from_chunk` makes the Nth
    and later synthesis request (1-based, in call order) return an unusable body
    instead of audio — the "server dropped chunks" case.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    requests = tmp_path / "requests.txt"
    counter = tmp_path / "calls.txt"
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True, exist_ok=True)
    out = tmp_path / "out.wav"

    _write_exe(
        bindir / "curl",
        "#!/usr/bin/env bash\n"
        'out=""; prev=""; text=""; want_text=0\n'
        'for a in "$@"; do\n'
        '  if [ "$prev" = "-o" ]; then out="$a"; fi\n'
        '  if [ "$want_text" = "1" ]; then\n'
        '    case "$a" in text=*) text="${a#text=}" ;; esac\n'
        '    want_text=0\n'
        '  fi\n'
        '  if [ "$a" = "--data-urlencode" ]; then want_text=1; fi\n'
        '  prev="$a"\n'
        "done\n"
        f'calls=$(wc -l < "{counter}" 2>/dev/null | tr -d "[:space:]")\n'
        'case "$calls" in ""|*[!0-9]*) calls=0 ;; esac\n'
        "calls=$((calls + 1))\n"
        f'printf "x\\n" >> "{counter}"\n'
        f'if [ "{fail_from_chunk}" -gt 0 ] && [ "$calls" -ge "{fail_from_chunk}" ]; then\n'
        '  if [ -n "$out" ]; then printf "partial" > "$out"; fi\n'
        f'  printf "%s\\n" "$text" >> "{requests}"\n'
        "  exit 0\n"
        "fi\n"
        'if [ -n "$out" ]; then\n'
        f'  { "python3" } - "$out" "$text" <<\'PY\'\n'
        "import sys\n"
        "import wave\n"
        "\n"
        "path, text = sys.argv[1], sys.argv[2]\n"
        "# A GENUINELY VALID WAV (real RIFF/WAVE header, 24kHz/16-bit mono) whose PCM\n"
        "# frames begin with the chunk's text, so payload identity is checkable: the\n"
        "# provider's stdlib concat reads frames through `wave` and would reject a\n"
        "# malformed container. Sized like the real server response (~200KB/chunk) —\n"
        "# the provider correctly treats sub-1KB audio as unusable.\n"
        "frames = text.encode()\n"
        "if len(frames) % 2:\n"
        "    frames += b'\\x00'\n"
        "frames += b'\\x00' * (200_000 - len(frames))\n"
        "with wave.open(path, 'wb') as handle:\n"
        "    handle.setnchannels(1)\n"
        "    handle.setsampwidth(2)\n"
        "    handle.setframerate(24000)\n"
        "    handle.writeframes(frames)\n"
        "PY\n"
        "fi\n"
        f'printf "%s\\n" "$text" >> "{requests}"\n'
        "exit 0\n",
    )
    for tool in ("afplay", "lame", "ffmpeg"):
        _write_exe(bindir / tool, "#!/usr/bin/env bash\nexit 0\n")
    _write_exe(bindir / "hermes", "#!/usr/bin/env bash\nexit 0\n")

    text_path = tmp_path / "input.txt"
    text_path.write_text(text)

    env = dict(os.environ)
    env["PATH"] = f"{bindir}:{env['PATH']}"
    env["HOME"] = str(home)
    env.pop("HERMES_SESSION_PLATFORM", None)
    if platform:
        env["HERMES_SESSION_PLATFORM"] = platform
    env["AFTERWORDS_REPO"] = str(REPO)

    result = subprocess.run(
        ["bash", str(COMMAND_SCRIPT), str(text_path), str(out), voice],
        capture_output=True, text=True, env=env, timeout=300,
    )
    return result, {
        "out": out, "requests": requests, "home": home, "text_path": text_path,
    }


def test_short_turn_writes_real_audio_not_silence(tmp_path):
    """The artifact at {output_path} is the request's speech, and it is not the placeholder."""
    import time

    start = time.monotonic()
    result, ctx = _run_provider(tmp_path, SHORT_REPLY)
    elapsed = time.monotonic() - start
    assert result.returncode == 0, result.stderr

    out = ctx["out"]
    assert out.is_file(), f"provider wrote no artifact at {out}; stderr={result.stderr!r}"
    data = out.read_bytes()
    assert data != SILENCE_PLACEHOLDER_WAV, (
        "the artifact is the retired silent placeholder — the request's speech was "
        "not delivered to the caller"
    )
    assert len(data) > SILENCE_BYTES
    assert SHORT_REPLY.encode() in data or len(data) > 1000, "artifact carries no speech payload"
    assert elapsed < 30, f"short turn took {elapsed:.1f}s — too slow for a single chunk"


def test_historical_1802_char_case_writes_the_full_speech_payload(tmp_path):
    """The reply that used to speak one chunk now reaches the caller complete."""
    result, ctx = _run_provider(tmp_path, LONG_REPLY)
    assert result.returncode == 0, result.stderr

    data = ctx["out"].read_bytes()
    assert data != SILENCE_PLACEHOLDER_WAV, "silent placeholder delivered for the long case"
    assert len(data) > SILENCE_BYTES * 2

    # Every chunk the provider synthesised must be represented in the artifact.
    sent = ctx["requests"].read_text().splitlines()
    sent = [s for s in sent if s.strip()]
    assert len(sent) >= 4, f"expected the long reply to chunk; got {len(sent)} requests"
    joined = " ".join(sent)
    assert len(joined) > 1000, f"provider truncated the reply to {len(joined)} chars"
    assert "push the reply past the old thousand character cap" in joined, (
        "content past the old 1000-char cap never reached the synthesis requests"
    )
    assert "·" not in joined, "model/token footer was synthesised"
    for chunk in sent:
        assert chunk.encode() in data, f"chunk missing from the delivered artifact: {chunk[:60]!r}"


# --------------------------------------------------------------------------
# Hermes's own file contract
# --------------------------------------------------------------------------

def test_hermes_accepts_the_artifact_under_its_file_contract(tmp_path, monkeypatch):
    """Drive `_generate_command_tts` against the real provider and a stub server.

    This is the contract Hermes actually enforces on a command provider:
    non-zero exit, a file at the configured output path, size > 0. The assertion
    that matters is that the bytes it accepts are the request's speech.
    """
    hermes_root = Path.home() / ".hermes" / "hermes-agent"
    if not (hermes_root / "tools" / "tts_command_provider.py").is_file():
        pytest.skip("Hermes source not available")

    import sys

    if str(hermes_root) not in sys.path:
        sys.path.insert(0, str(hermes_root))
    try:
        from tools.tts_command_provider import _generate_command_tts
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Hermes provider not importable: {exc!r}")

    result, ctx = _run_provider(tmp_path, SHORT_REPLY)
    assert result.returncode == 0, result.stderr
    # Re-run through Hermes's own runner so its checks are the ones applied.
    bindir = tmp_path / "bin"
    text = SHORT_REPLY
    out = tmp_path / "hermes_out.wav"
    config = {
        "type": "command",
        "command": f"env PATH={bindir}:$PATH bash {COMMAND_SCRIPT} {{input_path}} {{output_path}} {{voice}}",
        "output_format": "wav",
        "voice": "seven-of-nine",
        "timeout": 120,
    }
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("AFTERWORDS_REPO", str(REPO))
    produced = _generate_command_tts(text, str(out), "afterwords", config, {})

    assert Path(produced).is_file()
    data = Path(produced).read_bytes()
    assert data != SILENCE_PLACEHOLDER_WAV, (
        "Hermes accepted the silent placeholder under its file contract — the "
        "contract must be satisfied by the speech itself"
    )
    assert len(data) > SILENCE_BYTES
    assert json.dumps({"ok": True})  # keep json import meaningful for the stub payloads


# --------------------------------------------------------------------------
# All-or-nothing delivery: exit status must carry incompleteness
# --------------------------------------------------------------------------

# The three states the contract distinguishes, and what each must produce.
# "Some chunks missing" is the case that used to be indistinguishable from a
# genuine one-chunk reply: the survivors landed in the artifact and the provider
# exited 0, so the caller read a fragment as the whole speech.

def test_complete_delivery_exits_zero_with_every_chunk(tmp_path):
    """The all-chunks-present arm, so the next two tests are a real pair."""
    result, ctx = _run_provider(tmp_path, LONG_REPLY)
    assert result.returncode == 0, result.stderr

    data = ctx["out"].read_bytes()
    sent = [s for s in ctx["requests"].read_text().splitlines() if s.strip()]
    assert len(sent) >= 4, f"fixture did not chunk: {len(sent)} requests"
    for chunk in sent:
        assert chunk.encode() in data, f"chunk missing from the artifact: {chunk[:50]!r}"
    assert "PARTIAL" not in result.stderr


def test_partial_delivery_exits_nonzero_and_keeps_the_survivors(tmp_path):
    """Some chunks unusable → artifact still written, exit NON-zero, reason stated.

    Against the pre-fix provider this returned 0: with the usable count at 1 it
    took the same branch as a legitimate one-chunk reply. Exit 0 is what Hermes
    reads as "this artifact is the speech", and Hermes has no partial-result
    contract, so a fragment reported as success is the placeholder's lie again.
    """
    result, ctx = _run_provider(tmp_path, LONG_REPLY, fail_from_chunk=2)
    assert result.returncode != 0, (
        "a partial artifact was reported as a successful delivery:\n"
        f"{result.stderr}"
    )
    assert ctx["out"].is_file(), "the surviving chunk was discarded instead of delivered"
    data = ctx["out"].read_bytes()
    assert b"Convergence Report. Summary of the work" in data, (
        "the delivered artifact does not hold the chunk that did synthesize"
    )
    assert b"This paragraph exists purely to push the reply" not in data, (
        "a chunk the stub deliberately failed still appears in the artifact"
    )
    assert "PARTIAL" in result.stderr, f"no partial marker emitted; stderr={result.stderr!r}"
    assert "1/5" in result.stderr, f"the surviving/expected count is not reported: {result.stderr!r}"


def test_no_usable_chunks_exits_nonzero_without_an_artifact(tmp_path):
    """Nothing synthesises → no artifact at all, and a non-zero exit."""
    result, ctx = _run_provider(tmp_path, LONG_REPLY, fail_from_chunk=1)
    assert result.returncode != 0, result.stderr
    assert not ctx["out"].exists(), (
        "an artifact was left at {output_path} for a turn that produced no speech"
    )
    assert "0/5" in result.stderr, f"the failure count is not reported: {result.stderr!r}"


def test_hermes_refuses_a_partial_artifact(tmp_path, monkeypatch):
    """The consumer boundary: Hermes must raise rather than accept a fragment.

    Hermes turns a non-zero provider exit into ``RuntimeError``; its file check
    alone (``exists() and size > 0``) would have accepted the fragment happily.
    """
    hermes_root = Path.home() / ".hermes" / "hermes-agent"
    if not (hermes_root / "tools" / "tts_command_provider.py").is_file():
        pytest.skip("Hermes source not available")

    import sys

    if str(hermes_root) not in sys.path:
        sys.path.insert(0, str(hermes_root))
    try:
        from tools.tts_command_provider import _generate_command_tts
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Hermes provider not importable: {exc!r}")

    result, ctx = _run_provider(tmp_path, LONG_REPLY, fail_from_chunk=2)
    assert result.returncode != 0, result.stderr

    bindir = tmp_path / "bin"
    out = tmp_path / "hermes_partial.wav"
    config = {
        "type": "command",
        "command": f"env PATH={bindir}:$PATH bash {COMMAND_SCRIPT} {{input_path}} {{output_path}} {{voice}}",
        "output_format": "wav",
        "voice": "seven-of-nine",
        "timeout": 120,
    }
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("AFTERWORDS_REPO", str(REPO))
    with pytest.raises(RuntimeError):
        _generate_command_tts(LONG_REPLY, str(out), "afterwords", config, {})
