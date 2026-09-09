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

# Agent name used for .afterwords mapping lookup
HERMES_AGENT = "hermes"

# Global fallback config (read from home dir)
GLOBAL_AFTERWORDS = Path.home() / ".afterwords"


def strip_markdown(text: str) -> str:
    """Strip markdown for TTS, with Hermes footer cleanup.

    Prefers the shared strip_markdown.py (list/heading pause cues) from the
    repo or ~/.claude/hooks; falls back to a minimal local pass.
    """
    cleaned = _shared_strip_markdown(text)
    # Strip model/tokens/cost footers like "glm-5.1 · 9% · ~" or "claude-3.5-sonnet · 42% · $0.02"
    cleaned = re.sub(r'[a-z0-9._-]+\s*·.*$', '', cleaned, flags=re.I)
    return cleaned.strip()


def _shared_strip_markdown(text: str) -> str:
    import importlib.util

    candidates = [
        Path(__file__).resolve().parents[3] / "strip_markdown.py",
        Path.home() / ".claude" / "hooks" / "strip-markdown.py",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("aw_strip_markdown", path)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.strip_markdown(text, max_chars=None)
        except Exception:
            continue
    # Minimal fallback if shared module is unavailable.
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^\s*([-*•]|\d+[.)])\s+', '', text, flags=re.M)
    text = re.sub(r'\n{2,}', '. ', text)
    return re.sub(r'\s+', ' ', text).strip()


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Split text into sentence-boundary chunks for TTS synthesis.

    Each chunk is capped at max_chars characters. Splits on sentence
    boundaries (.!?) then on word boundaries for overlong sentences.
    """
    if not text:
        return []

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?…])\s+', text)
    sentences = [s.strip().replace('\n', ' ') for s in sentences if s.strip()]

    # Word-split overlong sentences
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

    # Merge short consecutive parts into chunks up to max_chars
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

                        asyncio.create_task(
                            asyncio.to_thread(
                                _archive_wav_and_cleanup,
                                wav_path,
                                f"{stamp}-c{i-1}.mp3",
                                archive_dir,
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