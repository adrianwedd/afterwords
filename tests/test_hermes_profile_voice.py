"""Two Hermes bot profiles sharing one Afterwords server keep their own voices.

Failure this pins (2026-10-15): two Telegram bots — the default profile
(`~/.hermes`, voice seven-of-nine) and the `vixen` profile
(`~/.hermes/profiles/vixen`, voice seydoux) — share `afterwords-tts-command.sh`.
Every in-Hermes speech path (the `text_to_speech` tool, `/voice` auto replies to
text input, auto-TTS on voice-message input) ends in that one command, and it
discarded the only identity Hermes hands it (`HERMES_HOME`):

  * an empty `{voice}` was silently re-resolved from `.afterwords` under the
    hardcoded `hermes` key, so Vixen spoke as seven-of-nine;
  * every artifact was archived into `~/.hermes/tts-archive`, which
    `tts-feed-send.py` relays with the DEFAULT profile's bot, so Vixen's voice
    notes were delivered a second time by the Hermes bot.

The contract now: the voice is the serving profile's explicit `{voice}` or the
request fails visibly; the artifact stays in the serving profile's scope; each
request leaves an evidence line in that profile's own log.
"""
from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
COMMAND_SCRIPT = Path(os.environ.get("AFTERWORDS_COMMAND_SCRIPT") or (REPO / "scripts" / "afterwords-tts-command.sh"))
FEED_SCRIPT = REPO / "scripts" / "tts-feed-send.py"

VOICES = {"default": "seven-of-nine", "vixen": "seydoux"}


def _write_exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def world(tmp_path):
    """Real HOME layout with two profile homes and a request-logging fake server."""
    home = tmp_path / "home"
    hermes = home / ".hermes"
    homes = {"default": hermes, "vixen": hermes / "profiles" / "vixen",
             "novoice": hermes / "profiles" / "novoice"}
    for h in homes.values():
        h.mkdir(parents=True, exist_ok=True)
    # Both fallback sources the old script consulted, populated with the
    # Hermes bot's voice — a borrowing implementation would find them.
    (home / ".afterwords").write_text("default: galadriel\nhermes: seven-of-nine\n")
    workdir = tmp_path / "work"
    workdir.mkdir()
    (workdir / ".afterwords").write_text("default: holly\nhermes: seven-of-nine\n")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    requests = tmp_path / "requests.jsonl"
    # Fake Afterwords: records voice + text + the calling profile per request,
    # rejects unknown voices like server.py does (HTTP 400), and serves a
    # genuine WAV otherwise. Handles both the CLI (-G --data-urlencode) and the
    # messaging (query-string URL, -w %{http_code}) request shapes.
    _write_exe(bindir / "curl", textwrap.dedent(f"""\
        #!/usr/bin/env bash
        exec python3 - "$@" <<'PY'
        import json, os, sys, urllib.parse, wave
        args = sys.argv[1:]
        out = None; fields = {{}}; write_code = False
        i = 0
        while i < len(args):
            a = args[i]
            if a == "-o": out = args[i + 1]; i += 1
            elif a == "-w": write_code = True; i += 1
            elif a == "--data-urlencode":
                k, _, v = args[i + 1].partition("="); fields[k] = v; i += 1
            elif a.startswith("http"):
                q = urllib.parse.urlparse(a).query
                for k, v in urllib.parse.parse_qsl(q): fields[k] = v
            i += 1
        if "synthesize" not in " ".join(args):
            sys.exit(0)
        voice = fields.get("voice")
        known = {json.dumps(sorted(set(VOICES.values())))}
        status = 200 if voice in known else 400
        with open({str(requests)!r}, "a") as fh:
            fh.write(json.dumps({{"voice": voice, "text": fields.get("text", ""),
                                 "hermes_home": os.environ.get("HERMES_HOME"),
                                 "status": status}}) + "\\n")
        if out:
            if status == 200:
                with wave.open(out, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
                    w.writeframes(((voice or "") + "|" + fields.get("text", "")).encode().ljust(48000, b"\\0"))
            else:
                open(out, "w").write(json.dumps({{"error": f"unknown voice: {{voice}}"}}))
        if write_code:
            sys.stdout.write(str(status))
        PY
        """))
    for tool in ("afplay", "lame", "ffmpeg", "hermes"):
        _write_exe(bindir / tool, "#!/usr/bin/env bash\nexit 0\n")

    provider = tmp_path / "provider.sh"
    source = COMMAND_SCRIPT.read_text()
    for filename in ("afterwords-play.lock", "afterwords-play.pid"):
        source = source.replace(f'"/tmp/{filename}"', shlex.quote(str(tmp_path / filename)))
    provider.write_text(source)

    return {"tmp": tmp_path, "home": home, "homes": homes, "bindir": bindir,
            "requests": requests, "provider": provider, "workdir": workdir}


def _run(world, profile: str, text: str, voice: str | None = None,
         platform: str | None = "telegram", tag: str = "x"):
    voice = VOICES.get(profile, "") if voice is None else voice
    env = dict(os.environ)
    env.update(PATH=f"{world['bindir']}:{env['PATH']}", HOME=str(world["home"]),
               HERMES_HOME=str(world["homes"][profile]), AFTERWORDS_REPO=str(REPO))
    env.pop("HERMES_SESSION_PLATFORM", None)
    if platform:
        env["HERMES_SESSION_PLATFORM"] = platform
    text_path = world["tmp"] / f"in-{tag}.txt"
    text_path.write_text(text)
    out = world["tmp"] / f"out-{tag}.wav"
    result = subprocess.run(["bash", str(world["provider"]), str(text_path), str(out), voice],
                            capture_output=True, text=True, env=env, cwd=world["workdir"],
                            timeout=120)
    return result, out


def _requests(world) -> list[dict]:
    if not world["requests"].exists():
        return []
    return [json.loads(line) for line in world["requests"].read_text().splitlines() if line]


def _evidence(world, profile: str) -> list[str]:
    log = world["homes"][profile] / "logs" / "afterwords-command.log"
    return log.read_text().splitlines() if log.exists() else []


# --------------------------------------------------------------------------

@pytest.mark.parametrize("platform", ["telegram", None], ids=["messaging", "cli"])
def test_interleaved_requests_from_two_bots_never_cross_voices(world, platform):
    """Concurrent, interleaved turns: every server request carries its own profile's voice."""
    jobs = [(p, f"{p} turn {i}: the quick brown fox.", f"{p}-{i}")
            for i in range(6) for p in ("default", "vixen")]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda j: _run(world, j[0], j[1], platform=platform, tag=j[2]), jobs))
    for (profile, _, tag), (result, out) in zip(jobs, results):
        assert result.returncode == 0, (tag, result.stderr)
        # The delivered artifact is the speech of THIS profile's voice.
        assert out.read_bytes().find(VOICES[profile].encode() + b"|" + profile.encode()) > 0, tag

    reqs = _requests(world)
    assert len(reqs) == len(jobs)
    for r in reqs:
        profile = "vixen" if r["hermes_home"].endswith("/profiles/vixen") else "default"
        assert r["text"].startswith(profile), r
        assert r["voice"] == VOICES[profile], f"{profile} request spoke as {r['voice']}: {r}"

    for profile in ("default", "vixen"):
        lines = _evidence(world, profile)
        assert len(lines) == 6, lines
        for line in lines:
            assert f"profile={profile} " in line and f"voice={VOICES[profile]} " in line, line
            assert "outcome=ok" in line, line


@pytest.mark.parametrize("platform", ["telegram", None], ids=["messaging", "cli"])
def test_unresolved_voice_fails_visibly_and_never_borrows(world, platform):
    """No `{voice}` → exit 2, nothing synthesized — even with `hermes:` keys on disk."""
    result, out = _run(world, "novoice", "Who am I speaking as?", voice="", platform=platform)
    assert result.returncode == 2
    assert 'profile "novoice"' in result.stderr
    assert "tts.providers.afterwords.voice" in result.stderr
    assert _requests(world) == [], "an unconfigured profile reached the server anyway"
    assert not out.exists()
    assert any("outcome=failed:no-voice-configured" in line for line in _evidence(world, "novoice"))


def test_unknown_voice_is_rejected_not_substituted(world):
    """A configured-but-missing voice surfaces the server's 400; no second request."""
    result, out = _run(world, "vixen", "Speak.", voice="seydoux-typo")
    assert result.returncode == 1
    assert "voice=seydoux-typo" in result.stderr and "unknown voice" in result.stderr
    assert [r["voice"] for r in _requests(world)] == ["seydoux-typo"]
    assert not out.exists()
    assert any("outcome=failed:http-400" in line for line in _evidence(world, "vixen"))


def _relayed(world) -> list[str]:
    """What tts-feed-send.py would deliver with the DEFAULT profile's bot."""
    env = dict(os.environ, HOME=str(world["home"]), AFTERWORDS_SEND_TO="telegram")
    result = subprocess.run(["python3", str(FEED_SCRIPT), "--once", "--dry-run"],
                            capture_output=True, text=True, env=env, cwd=world["workdir"],
                            timeout=60)
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if "[dry-run]" in line or "would" in line.lower()]


def test_gateway_delivered_audio_is_never_relayed_by_the_default_bot(world):
    """Messaging artifacts (already sent by their own bot) stay out of the relay archive."""
    for profile in ("default", "vixen"):
        result, _ = _run(world, profile, f"{profile} telegram reply.", tag=f"{profile}-tg")
        assert result.returncode == 0, result.stderr
    relay = world["homes"]["default"] / "tts-archive"
    assert not list(relay.glob("*.mp3")) and not list(relay.glob("*.txt"))
    assert _relayed(world) == []
    for profile in ("default", "vixen"):
        kept = world["homes"][profile] / "tts-archive" / "gateway-delivered"
        assert list(kept.glob("*.txt")), f"{profile} lost its delivery record"


def test_cli_archives_stay_in_the_speaking_profiles_scope(world):
    """Only default-profile CLI speech lands where the default bot relays from."""
    for profile in ("default", "vixen"):
        result, _ = _run(world, profile, f"{profile} local turn.", platform=None, tag=f"{profile}-cli")
        assert result.returncode == 0, result.stderr
    relay = world["homes"]["default"] / "tts-archive"
    assert [p.read_text().strip() for p in relay.glob("*.txt")] == ["default local turn."]
    vixen_archive = world["homes"]["vixen"] / "tts-archive"
    assert [p.read_text().strip() for p in vixen_archive.glob("*.txt")] == ["vixen local turn."]


# --------------------------------------------------------------------------
# Through the installed Hermes implementation, as the gateways run it
# --------------------------------------------------------------------------

HERMES_SRC = Path.home() / ".hermes" / "hermes-agent"


def _hermes_runtime() -> tuple[Path, Path] | None:
    """(interpreter, site-packages) the running gateways use, if installed."""
    py = next(iter(sorted((Path.home() / ".hermes" / "tools").glob("python-3.*/bin/python3"))), None)
    sp = next(iter(sorted((Path.home() / ".hermes" / "installs").glob(
        "*/environments/*/venv/lib/python3.*/site-packages"))), None)
    if not (py and sp and (HERMES_SRC / "tools" / "tts_tool.py").is_file()):
        return None
    return py, sp


# One fresh interpreter per call = a gateway (re)start: config is read from the
# profile's config.yaml on disk, nothing survives in memory between calls.
# Both gateway entry points are driven: the runner's `_send_voice_reply`
# (text input, /voice all) and the base adapter's `_synthesize_auto_tts`
# (voice-message input). Both end in `text_to_speech_tool`.
_HERMES_DRIVER = textwrap.dedent("""\
    import asyncio, json, sys, types
    sys.path[:0] = [sys.argv[1], sys.argv[2]]
    entry, text, out = sys.argv[3], sys.argv[4], sys.argv[5]
    from gateway.config import Platform
    if entry == "voice_input":
        from gateway.platforms.base import BasePlatformAdapter
        stub = types.SimpleNamespace(platform=Platform.TELEGRAM, name="telegram",
                                     prepare_tts_text=lambda t: t)
        paths, _ = asyncio.run(BasePlatformAdapter._synthesize_auto_tts(stub, text))
        print(json.dumps({"success": bool(paths), "file_paths": paths}))
    else:
        from tools.tts_tool import text_to_speech_tool
        print(text_to_speech_tool(text=text, output_path=out))
""")


def _profile_config(world, profile: str, voice: str | None) -> None:
    command = (f"env PATH={world['bindir']}:$PATH AFTERWORDS_REPO={REPO} "
               f"bash {world['provider']} {{input_path}} {{output_path}} {{voice}}")
    block = {"type": "command", "command": command, "output_format": "wav",
             "voice_compatible": True, "timeout": 120}
    if voice is not None:
        block["voice"] = voice
    cfg = {"tts": {"provider": "afterwords", "providers": {"afterwords": block}}}
    (world["homes"][profile] / "config.yaml").write_text(json.dumps(cfg))  # JSON ⊂ YAML


def _hermes_call(world, runtime, profile, entry, text, tag):
    py, sp = runtime
    driver = world["tmp"] / "driver.py"
    driver.write_text(_HERMES_DRIVER)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_", "PYTHON"))}
    env.update(HOME=str(world["home"]), HERMES_HOME=str(world["homes"][profile]),
               HERMES_SESSION_PLATFORM="telegram")
    out = world["tmp"] / f"h-{tag}.ogg"
    return subprocess.run([str(py), "-I", str(driver), str(HERMES_SRC), str(sp), entry, text, str(out)],
                          capture_output=True, text=True, env=env, cwd=world["workdir"], timeout=180)


def test_real_hermes_paths_keep_each_profile_voice_across_restarts(world):
    runtime = _hermes_runtime()
    if runtime is None:
        pytest.skip("installed Hermes runtime not available")
    for profile in ("default", "vixen"):
        _profile_config(world, profile, VOICES[profile])

    calls = [(rnd, p, entry) for rnd in range(2) for entry in ("text_input", "voice_input")
             for p in ("default", "vixen")]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda c: _hermes_call(world, runtime, c[1], c[2],
                                   f"{c[1]} {c[2]} round {c[0]}.", f"{c[1]}-{c[2]}-{c[0]}"),
            calls))
    for call, res in zip(calls, results):
        assert res.returncode == 0, (call, res.stderr[-2000:])
        payload = json.loads(res.stdout.strip().splitlines()[-1])
        assert payload.get("success"), (call, payload)

    reqs = _requests(world)
    assert len(reqs) == len(calls), reqs
    for r in reqs:
        profile = r["text"].split()[0]
        assert r["voice"] == VOICES[profile], f"{profile} spoke as {r['voice']}: {r}"
        assert r["hermes_home"] == str(world["homes"][profile]), r


def test_real_hermes_profile_without_voice_fails_instead_of_borrowing(world):
    runtime = _hermes_runtime()
    if runtime is None:
        pytest.skip("installed Hermes runtime not available")
    _profile_config(world, "default", VOICES["default"])
    _profile_config(world, "novoice", None)
    res = _hermes_call(world, runtime, "novoice", "text_input", "novoice turn.", "nv")
    payload = json.loads(res.stdout.strip().splitlines()[-1])
    assert payload.get("success") is False, payload
    assert "no voice configured" in payload.get("error", ""), payload
    assert _requests(world) == []
