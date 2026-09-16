"""Afterwords TTS hook for Hermes — auto-speaks agent responses.

Chunked pipelining: split text into ~400-char sentence chunks, then
synthesize chunk N+1 while playing chunk N for ~2s latency-to-first-audio.

Voice resolution priority (first match wins):
  1. Project .afterwords — agent key (hermes: voice) → default: fallback
  2. Global ~/.afterwords  — agent key → default: fallback → single voice
  3. Server default voice (from /health endpoint)

The .afterwords file supports two formats:
  Simple:   galadriel
  Mapping:  default: galadriel
            hermes: seven-of-nine

Requires Afterwords server running at http://127.0.0.1:7860
"""

import asyncio
import importlib.util
import inspect
import json
import logging
import os
import re
import subprocess
import urllib.parse
import uuid
from pathlib import Path

try:
    import aiohttp
except ModuleNotFoundError:  # only needed for the CLI/local synth+playback path
    aiohttp = None  # type: ignore[assignment]  # messaging-only installs return early

log = logging.getLogger("afterwords-tts")

# Afterwords server endpoint
AFTERWORDS_URL = "http://127.0.0.1:7860"
AFTERWORDS_HEALTH = f"{AFTERWORDS_URL}/health"
TTS_ENDPOINT = f"{AFTERWORDS_URL}/synthesize"

# Chunk size for TTS (characters per synthesis request).
# 400 keeps first-audio latency low while cutting seams vs 200.
CHUNK_CHARS = 400

# Canonical helper module filenames in the repo root. The gateway hook, the CLI
# shell hook and the Claude/Codex workers all load these — one implementation.
_STRIP_MODULE = "strip_markdown.py"
_CHUNK_MODULE = "chunks.py"

# Repo root for this deployment, stamped by scripts/install-hermes-hook.sh when
# handler.py is installed outside the repo (the gateway loads it from
# ~/.hermes/hooks/afterwords-tts/, where a walk-up cannot reach the checkout).
# Also settable via $AFTERWORDS_REPO.
_REPO_HINT = ""

# Agent name used for .afterwords mapping lookup
HERMES_AGENT = "hermes"

# Global fallback config (read from home dir)
GLOBAL_AFTERWORDS = Path.home() / ".afterwords"


def strip_markdown(text: str) -> str:
    """Strip markdown for TTS via the canonical repo implementation.

    The rules (including Hermes' model/tokens/cost footer) live in the repo-root
    `strip_markdown.py`. This function does not re-implement them; if the
    canonical module cannot be resolved it logs a warning and uses a minimal
    fallback, so the degradation is visible in the gateway log rather than
    silently changing what gets spoken.
    """
    fn, _ = _canonical("strip_markdown.py", "strip_markdown")
    if fn is not None:
        return fn(text, max_chars=None).strip()
    log.warning(
        "canonical strip_markdown.py unresolved (%s) — using minimal fallback; "
        "TTS will lack list/heading pause cues",
        _resolution_report(),
    )
    return _minimal_strip(text)


def _minimal_strip(text: str) -> str:
    """Last-resort strip for when the canonical module is unreachable."""
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^\s*([-*•]|\d+[.)])\s+', '', text, flags=re.M)
    text = re.sub(r'[a-z0-9._-]+\s*·.*$', '', text, flags=re.I)
    text = re.sub(r'\n{2,}', '. ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _repo_root() -> Path | None:
    """Locate the afterwords repo root, or None if it isn't reachable.

    Resolution order:
      1. `$AFTERWORDS_REPO` — explicit override.
      2. `_REPO_HINT` — stamped into the installed copy by
         scripts/install-hermes-hook.sh, because the gateway loads this file from
         ~/.hermes/hooks/afterwords-tts/ where a walk-up cannot reach the repo.
      3. Walk up from this file for a directory holding BOTH canonical modules.
         When handler.py is symlinked into ~/.hermes/hooks/, `resolve()` lands in
         the repo and this finds it; it also finds it for any in-repo run.
         No hardcoded parents[n] index.
    """
    for override in (os.environ.get("AFTERWORDS_REPO", "").strip(), _REPO_HINT):
        if not override:
            continue
        candidate = Path(override).expanduser()
        if (candidate / _STRIP_MODULE).is_file() and (candidate / _CHUNK_MODULE).is_file():
            return candidate
        log.warning("repo hint %s has no %s/%s", override, _STRIP_MODULE, _CHUNK_MODULE)
    for directory in Path(__file__).resolve().parents:
        if (directory / _STRIP_MODULE).is_file() and (directory / _CHUNK_MODULE).is_file():
            return directory
    return None


def _candidates(filename: str) -> list[Path]:
    """Places to look for a canonical module, in priority order."""
    paths: list[Path] = []
    root = _repo_root()
    if root is not None:
        paths.append(root / filename)
    # setup.sh-installed helper locations (shim-backed after the 2026-09 fix, so
    # they resolve back to the repo rather than carrying their own rules).
    hooks = Path.home() / ".claude" / "hooks"
    paths.append(hooks / filename.replace("_", "-"))
    paths.append(hooks / filename)
    seen: set[Path] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def _canonical(filename: str, attr: str):
    """Load a canonical helper. Returns (callable, source) or (None, reason)."""
    for path in _candidates(filename):
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"aw_{attr}", path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as exc:
            # Never swallow this: a silent fallback is how the gateway hook and
            # the shell hook drifted into different TTS semantics.
            log.warning("cannot load canonical %s at %s: %r", filename, path, exc)
            continue
        fn = getattr(mod, attr, None)
        if not callable(fn):
            log.warning("%s defines no callable %s", path, attr)
            continue
        # A file in the hooks dir that lacks max_chars is the pre-2026-09 legacy
        # copy: calling it would raise TypeError and demote every caller to the
        # fallback, which is the exact silent degradation this guards against.
        if path.parent == Path.home() / ".claude" / "hooks":
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):
                params = {}
            accepts_max = "max_chars" in params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
            if not accepts_max:
                log.warning(
                    "ignoring legacy %s at %s (no max_chars; run setup.sh to install the shim)",
                    filename, path,
                )
                continue
        return fn, str(path)
    return None, f"{filename} not found in {[str(p) for p in _candidates(filename)]}"


def _resolution_report() -> str:
    """Human-readable summary of which canonical helpers resolved, for logs/tests."""
    parts: list[str] = []
    for filename, attr in ((_STRIP_MODULE, "strip_markdown"), (_CHUNK_MODULE, "chunk_text")):
        fn, source = _canonical(filename, attr)
        parts.append(f"{filename}={'OK:' + source if fn is not None else 'MISSING (' + source + ')'}")
    return "; ".join(parts)


def chunk_text(text: str, max_chars: int | None = None) -> list[str]:
    """Split text into TTS chunks via the canonical repo implementation.

    Falls back to the local splitter only if the canonical module is
    unreachable, and logs that it did.
    """
    fn, _ = _canonical(_CHUNK_MODULE, "chunk_text")
    if fn is not None:
        return fn(text, max_chars=max_chars)
    log.warning(
        "canonical chunks.py unresolved (%s) — using local splitter",
        _resolution_report(),
    )
    return _local_chunk_text(text, max_chars or CHUNK_CHARS)


def _local_chunk_text(text: str, max_chars: int) -> list[str]:
    """Last-resort splitter for when the canonical module is unreachable."""
    if not text:
        return []

    sentences = re.split(r'(?<=[.!?…])\s+', text)
    sentences = [s.strip().replace('\n', ' ') for s in sentences if s.strip()]

    parts: list[str] = []
    for s in sentences:
        if len(s) > max_chars:
            while len(s) > max_chars:
                split_at = s.rfind(' ', 0, max_chars)
                if split_at == -1:
                    split_at = max_chars
                part = s[:split_at].strip()
                if part:
                    parts.append(part)
                s = s[split_at:].strip()
            if s:
                parts.append(s)
        else:
            parts.append(s)

    chunks: list[str] = []
    chunk = ''
    for part in parts:
        if chunk and len(chunk) + 1 + len(part) > max_chars:
            chunks.append(chunk)
            chunk = part
        elif chunk:
            chunk = chunk + ' ' + part
        else:
            chunk = part
    if chunk:
        chunks.append(chunk)

    return chunks


def _get_cwd(context: dict) -> str:
    """Resolve the working directory for .afterwords lookup."""
    return (
        context.get("cwd", "")
        or context.get("working_directory", "")
        or os.environ.get("TERMINAL_CWD", "")
        or str(Path.home())
    )


def resolve_voice(context: dict) -> str | None:
    """Resolve voice from .afterwords files."""
    cwd = _get_cwd(context)
    if cwd:
        project_aw = Path(cwd) / ".afterwords"
        voice = _read_afterwords(project_aw, HERMES_AGENT)
        if voice:
            log.info("Voice resolved from project .afterwords: %s (agent=%s, cwd=%s)", voice, HERMES_AGENT, cwd)
            return voice

    voice = _read_afterwords(GLOBAL_AFTERWORDS, HERMES_AGENT)
    if voice:
        log.info("Voice resolved from global ~/.afterwords: %s (agent=%s)", voice, HERMES_AGENT)
        return voice

    log.info("No .afterwords match, using server default voice")
    return None


def _read_afterwords(path: Path, agent: str) -> str | None:
    """Read an .afterwords file and resolve voice for the given agent."""
    if not path.is_file():
        return None
    try:
        content = path.read_text().strip()
    except OSError:
        return None
    if not content:
        return None

    lines = content.splitlines()
    # Mapping mode. Split on the final colon so keys may contain colons and
    # both `key: value` and `key:value` are accepted.
    has_mapping = any(":" in line and not line.strip().startswith("#") for line in lines)

    if has_mapping:
        fallback = None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.rpartition(":")
            if not sep:
                continue
            key = key.strip()
            value = value.strip()
            if key == agent:
                return value
            if key == "default" and fallback is None:
                fallback = value
        return fallback

    # Simple mode: first non-empty, non-comment line
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            return line

    return None


async def handle(event_type: str, context: dict) -> None:
    """Handle agent:end event — speak the response with chunked pipelining.

    Only plays audio locally via afplay (CLI sessions).
    Messaging platforms (Telegram/Discord) are NOT sent audio — use the
    tts-audio-feed cron job or the command provider for that.
    """
    if event_type != "agent:end":
        return

    response = context.get("response", "")
    platform = context.get("platform", "")

    if not response:
        return

    log.info("Hook fired: platform=%s, cwd=%s, response_len=%d", platform, _get_cwd(context), len(response))

    # Messaging platforms: skip — audio delivery is handled by the cron feed watcher
    if platform in ("telegram", "discord"):
        log.info("Skipping TTS for messaging platform %s (use tts-audio-feed cron)", platform)
        return

    # Native synth+playback needs aiohttp; messaging-only installs omit it. Bail
    # explicitly here rather than dereferencing None below and being rescued by
    # the broad health-check `except` (which would log a misleading "server not
    # reachable"). Everything past this point may use aiohttp.
    if aiohttp is None:
        log.info("aiohttp not installed — skipping local TTS (messaging-only install)")
        return

    # Check server health
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(AFTERWORDS_HEALTH, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status != 200:
                    log.warning("Afterwords health check failed: HTTP %d", resp.status)
                    return
    except Exception as e:
        log.info("Afterwords server not reachable: %s", e)
        return

    # Resolve voice from .afterwords files
    voice = resolve_voice(context)

    # Prepare text
    clean_text = strip_markdown(response)
    if not clean_text:
        return

    # CLI/local sessions: chunked pipelined playback via afplay
    chunks = chunk_text(clean_text)
    if not chunks:
        return

    log.info("Speaking: voice=%s, chunks=%d, total_chars=%d", voice, len(chunks), len(clean_text))
    asyncio.create_task(_speak_chunked(chunks, voice))


def _read_pid(pid_file: Path) -> int | None:
    """Read PID from pid_file. Returns None if missing, empty, or non-integer."""
    try:
        return int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    """Return True if process pid exists and is alive.

    os.kill(pid, 0) returns None on success — do NOT test its return value.
    Use try/except: no exception means alive; ProcessLookupError means dead.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # Process exists under a different user — treat as alive
    except OSError:
        return False


async def _speak_chunked(chunks: list[str], voice: str | None = None) -> None:
    """Async chunked TTS: synthesize chunk N+1 while playing chunk N.

    Acquires the same /tmp/afterwords-play.lock as Claude/Codex/AGy workers
    so we don't overlap with other agents' audio playback.
    """
    lock_dir = Path("/tmp/afterwords-play.lock")
    pid_file = Path("/tmp/afterwords-play.pid")
    waited = 0
    while True:
        try:
            lock_dir.mkdir()
        except FileExistsError:
            # Read holder PID; if empty/missing, do 50ms TOCTOU recheck.
            holder_pid = _read_pid(pid_file)
            if holder_pid is None:
                await asyncio.sleep(0.05)
                holder_pid = _read_pid(pid_file)

            if holder_pid is not None and _pid_alive(holder_pid):
                # Lock holder is alive — wait for it.
                waited += 1
                if waited > 200:  # ~60s at 0.3s intervals
                    log.info("Gave up waiting for play lock after %d checks", waited)
                    return
                await asyncio.sleep(0.3)
                continue

            # Stale lock (dead or no PID) — clear and retry.
            try:
                pid_file.unlink(missing_ok=True)
                lock_dir.rmdir()
            except OSError:
                pass
            continue
        break  # Lock acquired

    pid_file.write_text(str(os.getpid()))
    try:
        await _speak_chunked_inner(chunks, voice, session_pool=None)
    finally:
        try:
            pid_file.unlink(missing_ok=True)
            lock_dir.rmdir()
        except OSError:
            pass


async def _speak_chunked_inner(chunks: list[str], voice: str | None = None, session_pool=None) -> None:
    """Inner implementation: synthesize chunk N+1 while playing chunk N."""
    tag = uuid.uuid4().hex[:8]
    archive_dir = Path.home() / ".hermes" / "tts-archive"
    stamp = f"{voice or 'default'}-{_ts()}"
    archive_base = archive_dir / stamp
    # Write text sidecar (once)
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_base.with_suffix(".txt").write_text("\n".join(chunks))
    except OSError:
        pass  # archiving is best-effort

    archive_tasks: list[asyncio.Task] = []
    try:
        async with aiohttp.ClientSession() as session:
            prev_wav: Path | None = None
            prev_task: asyncio.Task | None = None

            for i, chunk in enumerate(chunks):
                # Build URL
                encoded = urllib.parse.quote(chunk)
                url = f"{TTS_ENDPOINT}?text={encoded}"
                if voice:
                    url += f"&voice={urllib.parse.quote(voice)}"

                # Start synthesizing current chunk
                curr_task = asyncio.create_task(_fetch_audio(session, url))

                # Wait for previous synthesis + play it
                if prev_task is not None:
                    wav_bytes = await prev_task
                    prev_task = None

                    if wav_bytes and len(wav_bytes) > 1000:
                        # Write to temp file
                        wav_path = Path(f"/tmp/hermes-hook-tts-{tag}-{i-1}.wav")
                        wav_path.write_bytes(wav_bytes)

                        # Play first; archive in a thread so lame never delays
                        # the next synth kickoff.
                        if not Path("/tmp/afterwords-muted").exists():
                            subprocess.call(
                                ["afplay", str(wav_path)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL
                            )

                        # Keep a reference: an un-referenced task can be garbage
                        # collected mid-flight, dropping the archived MP3. Gathered
                        # before the lock is released (see `finally` below).
                        archive_tasks.append(
                            asyncio.create_task(
                                asyncio.to_thread(
                                    _archive_wav_and_cleanup,
                                    wav_path,
                                    f"{stamp}-c{i-1}.mp3",
                                    archive_dir,
                                )
                            )
                        )

                prev_task = curr_task

            # Play the last chunk
            if prev_task is not None:
                wav_bytes = await prev_task
                if wav_bytes and len(wav_bytes) > 1000:
                    wav_path = Path(f"/tmp/hermes-hook-tts-{tag}-last.wav")
                    wav_path.write_bytes(wav_bytes)

                    if not Path("/tmp/afterwords-muted").exists():
                        subprocess.call(
                            ["afplay", str(wav_path)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL
                        )

                    await asyncio.to_thread(
                        _archive_wav_and_cleanup,
                        wav_path,
                        f"{stamp}-c{len(chunks)-1}.mp3",
                        archive_dir,
                    )

    except Exception as e:
        # Fail silently — TTS is a nice-to-have
        log.warning("TTS playback error: %s", e)
    finally:
        # Let in-flight archive jobs finish before the loop can tear down.
        if archive_tasks:
            await asyncio.gather(*archive_tasks, return_exceptions=True)


def _ts() -> str:
    """ISO-like timestamp for archive filenames: YYYYMMDD-HHMMSS."""
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _archive_wav_and_cleanup(wav_path: Path, mp3_name: str, archive_dir: Path) -> None:
    _archive_wav(wav_path, mp3_name, archive_dir)
    wav_path.unlink(missing_ok=True)


def _archive_wav(wav_path: Path, mp3_name: str, archive_dir: Path) -> None:
    """Convert WAV to MP3 in archive dir. Best-effort — never raises."""
    try:
        mp3_path = archive_dir / mp3_name
        subprocess.call(
            ["lame", "--quiet", "-V", "2", str(wav_path), str(mp3_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


async def _fetch_audio(session, url: str) -> bytes | None:
    """Fetch audio bytes from the TTS endpoint; one retry on empty/short/fail."""
    for attempt in range(2):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    log.warning("TTS synthesis failed: HTTP %d", resp.status)
                else:
                    data = await resp.read()
                    if data and len(data) > 1000:
                        return data
                    log.warning(
                        "TTS synthesis returned short audio (%s bytes)",
                        0 if not data else len(data),
                    )
        except Exception as e:
            log.warning("TTS fetch error: %s", e)
        if attempt == 0:
            await asyncio.sleep(0.2)
    return None