#!/usr/bin/env python3
"""Fidelity probe for issue #122 — bounded, inspectable controlled matrix.

WHAT THIS IS
    A diagnostic harness, not a fix. It builds an explicit, deterministic
    request matrix for the two reported single-chunk Qwen3-TTS symptoms:

      (a) first words lost when the chunk opens with a heading cue
      (b) a long (~16s) near-silent stretch after a heading / pause cue

    Two condition families, each internally controlled:

      opening_pair   Markdown heading / same spoken cue without Markdown /
                     body-only, with IDENTICAL following words
      pause_form     heading / punctuation-only / paragraph-break / no cue,
                     IDENTICAL body text

    Every request is exactly ONE chunk. The probe never splits text (that is
    chunks.py's job) so what reaches the server is byte-for-byte what the
    manifest records.

WHAT THIS IS NOT
    - It does not change backends, strip_markdown.py, chunks.py, the server, or
      the command provider. It is read-only against the repo and the API.
    - It never claims perceptual fidelity. Waveform metrics (duration, peak
      dBFS, internal-silence spans) are OBJECTIVE and are NOT evidence that a
      listener heard the right words. The heard-opening-words judgement lives in
      the annotations template and stays UNKNOWN until a human or an ASR pass
      fills it in. See the `perceptual_fidelity_claim` field.

SAFETY INVARIANTS (enforced, not documented-only)
    - Dry run is the default: zero network calls, zero GPU work, zero synthesis.
    - Live use requires BOTH `--execute` and `--out DIR`.
    - `--max-requests N` (positive int) caps ALL HTTP calls, including the
      default health preflight; an over-budget plan is refused BEFORE any call.
    - The endpoint must be loopback. A non-loopback host is refused unless the
      caller passes `--allow-non-loopback` (recorded in the manifest).
    - Requests are strictly serial, one at a time, in manifest order.
    - A multi-backend live plan requires /health and refuses missing loaded
      backends before spending even one synthesis request.
    - Only GET /synthesize and GET /health are ever issued. No /reload, no
      /clone, no DELETE, no server start/stop/restart, no voice cloning.
    - No file under voices/ is ever opened. Voice names are passed as opaque
      strings to the server, and names containing path separators are rejected
      so the probe cannot be aimed at an untracked private reference.
    - A partial / malformed / non-WAV response fails the run closed (exit 1)
      while keeping every receipt already collected, and stops before issuing
      any further request. Only accepted audio receives a .wav filename.
    - A live output directory must be empty; prior receipts are never forced
      over by this probe.
    - Generated artifacts are written with a `*` .gitignore inside the output
      directory so audio and manifests stay out of git unless staged.

USAGE
    # 1. Inspect the matrix. No network, no audio, no GPU.
    python3 scripts/fidelity-probe.py --voice picard-qwen3-06b --repeats 2
    python3 scripts/fidelity-probe.py --voice picard-qwen3-06b --out /tmp/fp-plan

    # 2. Fill the annotation template (all fields UNKNOWN until someone listens).
    python3 scripts/fidelity-probe.py --voice picard-qwen3-06b --annotation-template

    # 3. Live run — the remaining two-model gate. Requires a human decision.
    python3 scripts/fidelity-probe.py \
        --execute --out /tmp/fp-122-run1 --repeats 2 --max-requests 32 \
        --voice picard-qwen3-06b=qwen3-0.6b \
        --voice picard=qwen3-1.7b

EXIT CODES
    0  every attempt completed with a valid WAV (metrics may still show gaps —
       that is a finding, not a failure)
    1  a response was partial / bad / mismatched backend: failed closed, with
       receipts and manifest written for everything completed before the stop
    2  usage or configuration error (bad cap, missing voice, non-loopback
       endpoint, refused/missing output directory, backend mismatch on plan)
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import http.client
import ipaddress
import json
import math
import struct
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import numpy as np
import soundfile as sf

REPO = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = 1
ISSUE = 122
DEFAULT_ENDPOINT = "http://127.0.0.1:7860"
# The only two URLs this script is allowed to touch.
ALLOWED_PATHS = {"/synthesize", "/health"}

DEFAULT_REPEATS = 2
DEFAULT_MAX_REQUESTS = 32
DEFAULT_SILENCE_DBFS = -50.0
DEFAULT_MIN_SILENCE_S = 0.25
DEFAULT_TIMEOUT_S = 120.0
FRAME_MS = 20.0
HOP_MS = 10.0
OPENING_TOKEN_COUNT = 5

# Synthetic, non-private probe bodies. Overridable with --opening-body /
# --pause-body so an operator can swap in a different non-private body without
# editing this file. Every condition in a family carries the SAME body — that
# is what makes the family controlled.
DEFAULT_OPENING_BODY = (
    "The quick brown fox jumps over the lazy dog. "
    "The kettle boils at noon and the window is closed."
)
DEFAULT_PAUSE_BODY = (
    "The kettle boils at noon. The window stays closed and the lamp is still on."
)

# ── The matrix ───────────────────────────────────────────────────────────────
# cue_text is a literal prefix (including its trailing blank line) prepended to
# the family body. Nothing here is derived at runtime — the plan records the
# exact bytes, so a change to this table is visible in the plan diff.
CONDITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "opening_heading",
        "family": "opening_pair",
        "cue_text": "## Setup cue\n\n",
        "note": "Markdown heading cue directly before the body. Pair with "
                "opening_plain_label (same cue words, no Markdown marker) and "
                "opening_no_heading (body only); following body bytes match.",
    },
    {
        "id": "opening_plain_label",
        "family": "opening_pair",
        "cue_text": "Setup cue.\n\n",
        "note": "Same spoken cue words as opening_heading without the Markdown marker. "
                "Separates syntax from a lexical preface.",
    },
    {
        "id": "opening_no_heading",
        "family": "opening_pair",
        "cue_text": "",
        "note": "No cue; body only. Baseline for the opening pair.",
    },
    {
        "id": "pause_heading",
        "family": "pause_form",
        "cue_text": "## Pause cue\n\n",
        "note": "Heading cue before the shared pause body.",
    },
    {
        "id": "pause_punct_only",
        "family": "pause_form",
        "cue_text": "\u2026\n\n",
        "note": "Punctuation-only line (ellipsis) before the shared pause body.",
    },
    {
        "id": "pause_paragraph_break",
        "family": "pause_form",
        "cue_text": "Pause cue.\n\n",
        "note": "Short spoken cue sentence plus a paragraph break. This is the "
                "only pause form whose cue adds spoken words by construction.",
    },
    {
        "id": "pause_none",
        "family": "pause_form",
        "cue_text": "",
        "note": "No cue; shared pause body only. Baseline for the pause forms.",
    },
)


class FetchResult(NamedTuple):
    status: int | None
    headers: dict[str, str]
    body: bytes
    partial: bool
    error: str | None


# ── Text helpers ─────────────────────────────────────────────────────────────

def canonical_spoken_text(text: str) -> tuple[str | None, str | None]:
    """Return (spoken_text, error) from the repo's canonical strip_markdown.

    The probe sends cue-bearing RAW text on purpose (so the cue survives into
    the request). This function records what the hook pipeline would have
    spoken, giving the annotator a defined reference for "heard opening words".
    """
    try:
        repo = str(REPO)
        if repo not in sys.path:
            sys.path.insert(0, repo)
        import strip_markdown  # noqa: PLC0415 — deliberate lazy, repo-relative

        return strip_markdown.strip_markdown(text, max_chars=None), None
    except Exception as exc:  # pragma: no cover - only on a broken checkout
        return None, f"{type(exc).__name__}: {exc}"


def _norm_token(token: str) -> str:
    return token.strip(".,!?;:\u2026\u2014\u2013\"'`()[]{}*#").lower()


def opening_tokens(text: str | None, n: int = OPENING_TOKEN_COUNT) -> list[str]:
    if not text:
        return []
    return [_norm_token(t) for t in text.split()[:n] if _norm_token(t)]


def opening_token_diff(expected: str | None, heard: str | None) -> dict[str, Any]:
    """Deterministic opening-word diff for an annotator to consult.

    This never sets a judgement. `opening_token_diff` is a convenience for the
    person filling the annotations template: it answers "which of the expected
    opening words are absent from what was heard", nothing more.
    """
    exp = opening_tokens(expected)
    hea = opening_tokens(heard)
    if not exp or not hea:
        return {
            "expected_opening": exp,
            "heard_opening": hea,
            "missing": None,
            "extra": None,
            "judgement": "UNKNOWN",
            "reason": "needs both an expected text and heard words",
        }
    # Align a little beyond the displayed opening so a dropped first word can
    # still match the words that shift into its place. Set membership loses
    # order and repeated words ("the the ..."), exactly the shape at issue.
    context_n = 2 * OPENING_TOKEN_COUNT
    exp_context = opening_tokens(expected, context_n)
    hea_context = opening_tokens(heard, context_n)
    matcher = difflib.SequenceMatcher(a=exp_context, b=hea_context, autojunk=False)
    missing: list[str] = []
    extra: list[str] = []
    for tag, i0, i1, j0, j1 in matcher.get_opcodes():
        if tag in {"delete", "replace"}:
            missing.extend(exp_context[i] for i in range(i0, min(i1, OPENING_TOKEN_COUNT)))
        if tag in {"insert", "replace"}:
            extra.extend(hea_context[j] for j in range(j0, min(j1, OPENING_TOKEN_COUNT)))
    return {
        "expected_opening": exp,
        "heard_opening": hea,
        "missing": missing,
        "extra": extra,
        "judgement": "UNKNOWN",
        "reason": "order-aware alignment hint only — a human/ASR judgement sets the verdict",
    }


# ── WAV metrics (objective; never trim or repair) ────────────────────────────

def analyse_audio(
    mono: np.ndarray,
    sr: int,
    *,
    silence_dbfs: float = DEFAULT_SILENCE_DBFS,
    min_silence_s: float = DEFAULT_MIN_SILENCE_S,
    frame_ms: float = FRAME_MS,
    hop_ms: float = HOP_MS,
) -> dict[str, Any]:
    """Measure duration, peak level and silence spans of the returned audio.

    Purely descriptive: the array is not trimmed, gated, normalised or repaired,
    and no file is written. Silence spans strictly inside the file are reported
    separately from leading/trailing silence so a "lost first words" symptom and
    a "long dead stretch after the cue" symptom stay distinguishable.
    """
    x = np.asarray(mono, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    x = np.ravel(x)
    n = int(x.size)
    duration = n / float(sr) if sr else 0.0

    peak = float(np.max(np.abs(x))) if n else 0.0
    peak_dbfs = 20.0 * math.log10(peak) if peak > 0 else None

    frame_n = max(1, int(round(sr * frame_ms / 1000.0)))
    hop_n = max(1, int(round(sr * hop_ms / 1000.0)))

    if n == 0:
        return {
            "duration_s": 0.0,
            "peak_dbfs": None,
            "leading_silence_s": 0.0,
            "trailing_silence_s": 0.0,
            "internal_silences": [],
            "longest_internal_silence_s": 0.0,
            "silence_threshold_dbfs": silence_dbfs,
            "min_silence_s": min_silence_s,
            "frame_ms": frame_ms,
            "hop_ms": hop_ms,
            "samples": 0,
            "sample_rate": sr,
            "note": "no samples",
        }

    if n < frame_n:
        frames = x.reshape(1, -1)
    else:
        frames = np.lib.stride_tricks.sliding_window_view(x, frame_n)[::hop_n]

    rms = np.sqrt(np.mean(np.square(frames), axis=1))
    with np.errstate(divide="ignore"):
        levels = 20.0 * np.log10(np.maximum(rms, 1e-12))

    silent = levels <= silence_dbfs
    total_frames = int(silent.size)

    def span_bounds(i0: int, i1: int) -> tuple[float, float]:
        start = (i0 * hop_n) / float(sr)
        end = min(duration, ((i1 - 1) * hop_n + frame_n) / float(sr))
        return start, end

    spans: list[tuple[int, int, dict[str, float]]] = []
    idx = 0
    while idx < total_frames:
        if not silent[idx]:
            idx += 1
            continue
        i0 = idx
        while idx < total_frames and silent[idx]:
            idx += 1
        i1 = idx
        start, end = span_bounds(i0, i1)
        if end - start > 0:
            spans.append((i0, i1, {"start_s": start, "end_s": end, "duration_s": end - start}))

    # Leading / trailing silence are reported but are NOT internal spans: audio
    # that is silent end-to-end must not masquerade as an internal gap.
    non_silent = np.flatnonzero(~silent)
    if non_silent.size == 0:
        first = last = -1
        leading = duration
        trailing = duration
    else:
        first, last = int(non_silent[0]), int(non_silent[-1])
        leading = (first * hop_n) / float(sr)
        trailing = max(0.0, duration - ((last * hop_n + frame_n) / float(sr)))

    # A long gap after a tiny initial click is still INTERNAL. Classify by
    # actual non-silent frames on both sides, not a 20 ms edge tolerance that
    # could discard a 16-second cue gap beginning at 10 ms.
    internal = [
        span for i0, i1, span in spans
        if span["duration_s"] >= min_silence_s and i0 > first and i1 <= last
    ] if non_silent.size else []

    return {
        "duration_s": duration,
        "peak_dbfs": peak_dbfs,
        "leading_silence_s": leading,
        "trailing_silence_s": trailing,
        "internal_silences": internal,
        "longest_internal_silence_s": max(
            (s["duration_s"] for s in internal), default=0.0
        ),
        "silence_threshold_dbfs": silence_dbfs,
        "min_silence_s": min_silence_s,
        "frame_ms": frame_ms,
        "hop_ms": hop_ms,
        "samples": n,
        "sample_rate": sr,
    }


def riff_info(data: bytes) -> dict[str, Any]:
    """Parse just enough RIFF to detect truncation / a partial body.

    Deliberately independent of soundfile: a decoder may be lenient about a
    short data chunk, and a partial response must still be flagged.
    """
    info: dict[str, Any] = {
        "is_riff_wave": False,
        "declared_riff_bytes": None,
        "expected_total_bytes": None,
        "data_declared_bytes": None,
        "data_actual_bytes": None,
        "truncated": None,
        "error": None,
    }
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        info["error"] = "not a RIFF/WAVE container"
        return info

    info["is_riff_wave"] = True
    declared = struct.unpack_from("<I", data, 4)[0]
    info["declared_riff_bytes"] = declared
    info["expected_total_bytes"] = declared + 8
    pos = 12
    truncated = False
    while pos + 8 <= len(data):
        cid = data[pos : pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        body = pos + 8
        if body + size > len(data):
            truncated = True
            if cid == b"data":
                info["data_declared_bytes"] = size
                info["data_actual_bytes"] = len(data) - body
            break
        if cid == b"data":
            info["data_declared_bytes"] = size
            info["data_actual_bytes"] = size
        pos = body + size + (size & 1)  # chunks are word-aligned
    if info["data_declared_bytes"] is None:
        truncated = True
        info["error"] = "no data chunk found"
    info["truncated"] = truncated
    if not truncated and len(data) != info["expected_total_bytes"]:
        if len(data) < info["expected_total_bytes"]:
            info["truncated"] = True
        else:
            info["error"] = "RIFF byte count disagrees with the received body"
    return info


def read_and_analyse(
    path: Path, *, silence_dbfs: float, min_silence_s: float
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    """Return (wav_info, metrics, error) for the receipt on disk."""
    raw = path.read_bytes()
    wav: dict[str, Any] = {"valid": False, "error": None, "partial": None}
    wav.update(riff_info(raw))
    if not wav.pop("is_riff_wave", False):
        wav["valid"] = False
        wav["error"] = wav.get("error") or "not a RIFF/WAVE container"
        return wav, None, wav["error"]
    if wav.get("error") and not wav.get("truncated"):
        wav["valid"] = False
        return wav, None, wav["error"]

    try:
        data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    except Exception as exc:
        wav["error"] = f"{type(exc).__name__}: {exc}"
        return wav, None, wav["error"]

    frames = int(np.asarray(data).shape[0])
    wav.update(
        {
            "valid": True,
            "sample_rate": int(sr),
            "channels": 1 if np.asarray(data).ndim == 1 else int(np.asarray(data).shape[1]),
            "frames": frames,
        }
    )
    if frames == 0:
        wav["valid"] = False
        wav["error"] = "zero frames"
        return wav, None, wav["error"]

    metrics = analyse_audio(
        np.asarray(data), int(sr), silence_dbfs=silence_dbfs, min_silence_s=min_silence_s
    )
    if wav.get("truncated"):
        wav["valid"] = False
        wav["error"] = "truncated data chunk (partial response)"
        return wav, metrics, wav["error"]
    return wav, metrics, None


# ── HTTP (serial; loopback-only by policy) ───────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        # A loopback endpoint must not redirect text/voice parameters to a
        # different host. Treat even a same-host redirect as a failed probe.
        return None


def _fetch(url: str, timeout: float) -> FetchResult:
    """One synchronous GET. Never retries, never follows a non-synth path."""
    parsed = urllib.parse.urlparse(url)
    if parsed.path not in ALLOWED_PATHS:
        raise ValueError(f"refusing non-probe path: {parsed.path!r}")
    req = urllib.request.Request(url, headers={"Accept": "audio/wav"})
    # Do not let ambient HTTP_PROXY settings route a loopback-only probe via a
    # third party. The endpoint override remains explicit, never implicit.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    try:
        with opener.open(req, timeout=timeout) as resp:
            status = int(getattr(resp, "status", None) or resp.getcode())
            headers = {str(k).lower(): str(v) for k, v in resp.headers.items()}
            chunks: list[bytes] = []
            partial = False
            err: str | None = None
            try:
                while True:
                    block = resp.read(65536)
                    if not block:
                        break
                    chunks.append(block)
            except http.client.IncompleteRead as exc:
                partial = True
                err = f"IncompleteRead: {exc}"
                if exc.partial:
                    chunks.append(exc.partial)
            except Exception as exc:  # mid-stream transport failure
                partial = True
                err = f"{type(exc).__name__}: {exc}"
            return FetchResult(status, headers, b"".join(chunks), partial, err)
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read() or b""
        except Exception:
            pass
        headers = {}
        try:
            headers = {str(k).lower(): str(v) for k, v in (exc.headers or {}).items()}
        except Exception:
            pass
        return FetchResult(int(exc.code), headers, body, False, f"HTTPError {exc.code}")
    except Exception as exc:
        return FetchResult(None, {}, b"", False, f"{type(exc).__name__}: {exc}")


def endpoint_guard(endpoint: str, allow_non_loopback: bool) -> tuple[dict[str, Any], str | None]:
    """Validate the endpoint. Returns (info, error)."""
    info: dict[str, Any] = {
        "endpoint": endpoint,
        "allow_non_loopback": allow_non_loopback,
        "is_loopback": None,
    }
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme not in {"http", "https"}:
        return info, f"endpoint scheme must be http/https, got {parsed.scheme!r}"
    if not parsed.hostname:
        return info, f"endpoint has no host: {endpoint!r}"
    if parsed.username is not None or parsed.password is not None:
        return info, "endpoint must not contain credentials"
    if parsed.query or parsed.fragment:
        return info, "endpoint must not contain a query or fragment"
    try:
        parsed.port  # reject malformed ports before any request is planned
    except ValueError:
        return info, "endpoint has an invalid port"
    host = parsed.hostname.lower()
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host == "localhost"
    info["is_loopback"] = is_loopback
    if not is_loopback and not allow_non_loopback:
        return info, (
            f"endpoint host {host!r} is not loopback; pass --allow-non-loopback "
            "if that is genuinely intended (recorded in the manifest)"
        )
    if parsed.path not in {"", "/"}:
        return info, f"endpoint must not carry a path: {endpoint!r}"
    return info, None


# ── Plan construction (deterministic, printed before any synthesis) ──────────

def family_body(family: str, opening_body: str, pause_body: str) -> str:
    return opening_body if family == "opening_pair" else pause_body


def build_plan(
    voices: list[tuple[str, str | None]],
    *,
    repeats: int,
    lang: str,
    endpoint: str,
    allow_non_loopback: bool,
    send_stripped: bool,
    opening_body: str,
    pause_body: str,
) -> dict[str, Any]:
    """Enumerate every request in manifest order: voice → condition → repeat."""
    for name, _ in voices:
        if (not isinstance(name, str) or not name or name.startswith(".")
                or any(ch in name for ch in ("/", "\\", "\x00"))):
            raise ValueError(f"voice name must be a plain profile name, got {name!r}")
    names = [unicodedata.normalize("NFC", name).casefold() for name, _ in voices]
    if len(names) != len(set(names)):
        raise ValueError("duplicate voice names would reuse attempt IDs and receipts")
    requests: list[dict[str, Any]] = []
    order = 0
    for v_idx, (voice, backend) in enumerate(voices):
        for c_idx, cond in enumerate(CONDITIONS):
            body = family_body(cond["family"], opening_body, pause_body)
            raw_text = cond["cue_text"] + body
            if send_stripped:
                sent, strip_err = canonical_spoken_text(raw_text)
                if strip_err or sent is None:
                    sent = raw_text
            else:
                sent = raw_text
            expected, expected_err = canonical_spoken_text(raw_text)
            for repeat in range(1, repeats + 1):
                requests.append(
                    {
                        "order_index": order,
                        "attempt_id": f"{voice}__{cond['id']}__r{repeat}",
                        "voice": voice,
                        "voice_index": v_idx,
                        "requested_backend": backend,
                        "condition_id": cond["id"],
                        "condition_index": c_idx,
                        "family": cond["family"],
                        "repeat": repeat,
                        "text": sent,
                        "raw_text": raw_text,
                        "cue_text": cond["cue_text"],
                        "expected_spoken_text": expected,
                        "expected_spoken_text_error": expected_err,
                        "expected_opening_tokens": opening_tokens(expected),
                    }
                )
                order += 1

    plan = {
        "schema_version": SCHEMA_VERSION,
        "probe": "afterwords fidelity probe",
        "issue": ISSUE,
        "endpoint": endpoint,
        "allow_non_loopback": allow_non_loopback,
        "lang": lang,
        "repeats": repeats,
        "send_stripped": send_stripped,
        "bodies": {
            "opening_pair": opening_body,
            "pause_form": pause_body,
        },
        "voices": [
            {"index": i, "name": v, "requested_backend": b}
            for i, (v, b) in enumerate(voices)
        ],
        "conditions": [
            {
                "index": i,
                "id": c["id"],
                "family": c["family"],
                "cue_text": c["cue_text"],
                "note": c["note"],
            }
            for i, c in enumerate(CONDITIONS)
        ],
        "requests": requests,
    }
    plan["request_count"] = len(requests)
    plan["plan_id"] = plan_id(plan)
    return plan


def plan_id(plan: dict[str, Any]) -> str:
    """Stable id derived from the plan alone — no timestamps, no host state."""
    blob = {k: v for k, v in plan.items() if k != "plan_id"}
    canonical = json.dumps(blob, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "fp-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


# ── Annotation template ──────────────────────────────────────────────────────

ANNOTATION_LEGEND = {
    "missing_token_judgement": [
        "UNKNOWN",
        "NONE_MISSING",
        "MISSING_TOKENS",
        "UNCLEAR_AUDIO",
    ],
    "human_verdict": ["UNKNOWN", "PASS", "FAIL"],
    "attempt_status": ["ok", "bad", "not_attempted"],
    "rule": (
        "Waveform metrics are objective but are NOT evidence of perceptual "
        "fidelity. `missing_token_judgement` and `human_verdict` must be set by "
        "someone who heard the audio (or by an ASR pass whose engine and model "
        "are recorded). Leave them UNKNOWN otherwise."
    ),
    "fields": {
        "heard_opening_words": "The first words actually heard, verbatim, or null.",
        "missing_tokens": "Expected opening words absent from what was heard.",
        "asr.transcript": "Full ASR transcript for this attempt, or null.",
    },
}


def build_annotations(
    plan: dict[str, Any], attempt_status: dict[str, str] | None = None
) -> dict[str, Any]:
    """One entry per planned request, every judgement field UNKNOWN."""
    status = attempt_status or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "probe": "afterwords fidelity probe",
        "issue": ISSUE,
        "plan_id": plan["plan_id"],
        "perceptual_fidelity_claim": "NONE",
        "note": (
            "Structured ASR/human annotation template. Every judgement field is "
            "UNKNOWN until filled in. Mechanical opening-word diffs can be "
            "produced with opening_token_diff() from scripts/fidelity-probe.py, "
            "but they do not set a verdict."
        ),
        "legend": ANNOTATION_LEGEND,
        "entries": [
            {
                "attempt_id": r["attempt_id"],
                "order_index": r["order_index"],
                "voice": r["voice"],
                "condition_id": r["condition_id"],
                "family": r["family"],
                "repeat": r["repeat"],
                "attempt_status": status.get(r["attempt_id"], "not_attempted"),
                "expected_spoken_text": r["expected_spoken_text"],
                "expected_opening_tokens": r["expected_opening_tokens"],
                "heard_opening_words": None,
                "missing_tokens": None,
                "missing_token_judgement": "UNKNOWN",
                "asr": {"engine": None, "model": None, "transcript": None, "run_at": None},
                "human": {
                    "verdict": "UNKNOWN",
                    "notes": None,
                    "annotator": None,
                    "listened_at": None,
                },
            }
            for r in plan["requests"]
        ],
    }


# ── Execution ────────────────────────────────────────────────────────────────

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def _health(endpoint: str, timeout: float) -> dict[str, Any]:
    url = endpoint.rstrip("/") + "/health"
    res = _fetch(url, timeout)
    payload: Any = None
    if res.body:
        try:
            payload = json.loads(res.body.decode("utf-8", "replace"))
        except Exception:
            payload = None
    registered = payload.get("loaded_backends") if isinstance(payload, dict) else None
    loaded_names = (
        sorted(name for name, info in registered.items()
               if isinstance(info, dict) and info.get("loaded") is True)
        if isinstance(registered, dict) else None
    )
    return {
        "url": url,
        "status": res.status,
        "error": res.error,
        "ready": (payload or {}).get("ready") if isinstance(payload, dict) else None,
        "default_voice": (payload or {}).get("default_voice") if isinstance(payload, dict) else None,
        "voice_count": len((payload or {}).get("voices") or []) if isinstance(payload, dict) else None,
        "loaded_backend_names": loaded_names,
        "partial": res.partial,
    }


def execute(
    plan: dict[str, Any],
    *,
    out_dir: Path,
    max_requests: int,
    timeout: float,
    silence_dbfs: float,
    min_silence_s: float,
    health_check: bool,
) -> tuple[dict[str, Any], int]:
    _, endpoint_error = endpoint_guard(plan["endpoint"], bool(plan.get("allow_non_loopback")))
    if endpoint_error:
        raise ValueError(endpoint_error)
    if len(plan["voices"]) > 1 and (
        not health_check or any(v["requested_backend"] is None for v in plan["voices"])
    ):
        raise ValueError("multi-voice live plan requires pinned backends and /health preflight")
    if any(not isinstance(req["attempt_id"], str) or not req["attempt_id"]
           or req["attempt_id"].startswith(".")
           or any(ch in req["attempt_id"] for ch in ("/", "\\", "\x00"))
           for req in plan["requests"]):
        raise ValueError("attempt ID is not a safe receipt filename")
    attempt_ids = [unicodedata.normalize("NFC", req["attempt_id"]).casefold()
                   for req in plan["requests"]]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise ValueError("duplicate attempt IDs would overwrite receipts")
    required_calls = plan["request_count"] + int(health_check)
    if required_calls > max_requests:
        raise ValueError(
            f"plan needs {required_calls} HTTP request(s), including health when enabled; "
            f"hard cap is {max_requests}. Nothing was called."
        )
    # A run never overwrites a prior receipt or a user's .gitignore. Refuse a
    # nonempty output directory before creating even one file or making a call.
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise ValueError(f"output directory {out_dir} is not empty; choose a fresh --out")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / ".gitignore").write_text("*\n", encoding="utf-8")
    audio_dir = out_dir / "audio"
    receipt_dir = out_dir / "receipts"
    audio_dir.mkdir(exist_ok=True)
    receipt_dir.mkdir(exist_ok=True)

    manifest_path = out_dir / "manifest.json"

    endpoint = plan["endpoint"]
    lang = plan["lang"]
    attempts: list[dict[str, Any]] = []
    status_by_attempt: dict[str, str] = {}
    aborted = False
    abort_reason: str | None = None
    made = 0

    health = _health(endpoint, timeout) if health_check else None
    if health_check:
        expected_backends = {
            req["requested_backend"] for req in plan["requests"]
            if req["requested_backend"] is not None
        }
        loaded = set(health.get("loaded_backend_names") or [])
        if health["status"] != 200 or health["partial"] or health["error"] or health["ready"] is not True:
            aborted = True
            abort_reason = f"health preflight unavailable or not ready: {health['error'] or health['status']}"
        elif expected_backends and not expected_backends <= loaded:
            aborted = True
            abort_reason = (
                "health preflight missing loaded backend(s): "
                + ", ".join(sorted(expected_backends - loaded))
            )

    for req in ([] if aborted else plan["requests"]):
        if made + int(health_check) >= max_requests:  # guard unexpected plan mutation
            aborted = True
            abort_reason = f"hard cap reached ({made + int(health_check)}/{max_requests})"
            break
        made += 1

        params = urllib.parse.urlencode(
            {"text": req["text"], "voice": req["voice"], "lang": lang}
        )
        url = f"{endpoint}/synthesize?{params}"
        t0 = time.time()
        res = _fetch(url, timeout)
        elapsed = time.time() - t0

        content_type = res.headers.get("content-type", "")
        looks_audio = res.body[:4] == b"RIFF" or content_type.startswith("audio/")
        # Every response starts as an atomic raw receipt. Only a fully valid,
        # accepted audio response earns the .wav suffix; a partial transfer
        # can never look like a completed recording after an interruption.
        receipt = receipt_dir / f"{req['attempt_id']}.body"
        _atomic_bytes(receipt, res.body)

        declared_len = res.headers.get("content-length")
        length_mismatch = bool(
            declared_len and declared_len.isdigit() and int(declared_len) != len(res.body)
        )

        wav: dict[str, Any] = {"valid": False, "error": None}
        metrics: dict[str, Any] | None = None
        error: str | None = None
        if looks_audio:
            wav, metrics, wav_err = read_and_analyse(
                receipt, silence_dbfs=silence_dbfs, min_silence_s=min_silence_s
            )
            if wav_err:
                error = f"bad WAV: {wav_err}"
        elif res.status is None:
            error = f"transport error: {res.error or 'no response'}"
        else:
            error = f"non-audio response ({content_type or 'no content-type'})"

        if error is None and res.status != 200:
            error = f"HTTP {res.status}"
        if error is None and res.partial:
            error = f"partial response: {res.error or 'truncated transfer'}"
        if error is None and res.error and res.status == 200:
            error = f"transport error: {res.error}"
        if error is None and length_mismatch:
            error = (
                f"content-length mismatch (declared {declared_len}, "
                f"received {len(res.body)})"
            )

        observed_backend = res.headers.get("x-backend")
        expected_backend = req["requested_backend"]
        backend_match = (
            None if expected_backend is None else observed_backend == expected_backend
        )
        if error is None and backend_match is False:
            error = (
                f"backend mismatch: requested {expected_backend}, "
                f"server reported {observed_backend}"
            )

        ok = error is None
        if ok and looks_audio:
            wav_receipt = audio_dir / f"{req['attempt_id']}.wav"
            receipt.replace(wav_receipt)
            receipt = wav_receipt
        attempts.append(
            {
                "attempt_id": req["attempt_id"],
                "order_index": req["order_index"],
                "voice": req["voice"],
                "voice_index": req["voice_index"],
                "condition_id": req["condition_id"],
                "condition_index": req["condition_index"],
                "family": req["family"],
                "repeat": req["repeat"],
                "attempt": 1,
                "request": {
                    "method": "GET",
                    "url": url,
                    "text": req["text"],
                    "raw_text": req["raw_text"],
                    "cue_text": req["cue_text"],
                    "voice": req["voice"],
                    "lang": lang,
                    "expected_backend": expected_backend,
                },
                "expected_spoken_text": req["expected_spoken_text"],
                "expected_opening_tokens": req["expected_opening_tokens"],
                "response": {
                    "status": res.status,
                    "headers": res.headers,
                    "content_type": content_type,
                    "bytes": len(res.body),
                    "sha256": _sha256(res.body) if res.body else None,
                    "receipt_path": str(receipt.relative_to(out_dir)),
                    "receipt_is_audio": ok and looks_audio,
                    "partial": res.partial,
                    "content_length_mismatch": length_mismatch,
                    "transport_error": res.error,
                    "elapsed_s": elapsed,
                },
                "wav": wav,
                "backend": {
                    "expected": expected_backend,
                    "observed": observed_backend,
                    "match": backend_match,
                },
                "metrics": metrics,
                "ok": ok,
                "error": error,
            }
        )
        status_by_attempt[req["attempt_id"]] = "ok" if ok else "bad"

        flag = "ok" if ok else "BAD"
        print(
            f"  [{made}/{plan['request_count']}] {req['condition_id']:<24} "
            f"r{req['repeat']} voice={req['voice']:<22} {flag}"
            + ("" if ok else f" — {error}"),
            file=sys.stderr,
        )

        if not ok:
            aborted = True
            abort_reason = f"{req['attempt_id']}: {error}"
            break

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "probe": "afterwords fidelity probe",
        "issue": ISSUE,
        "plan_id": plan["plan_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "perceptual_fidelity_claim": "NONE",
        "claim_scope": (
            "Waveform metrics only. No perceptual-fidelity claim is made by this "
            "file; the heard-opening-words judgement lives in annotations.template.json "
            "and is UNKNOWN until a human or ASR pass fills it."
        ),
        "config": {
            "endpoint": plan["endpoint"],
            "allow_non_loopback": plan["allow_non_loopback"],
            "lang": lang,
            "repeats": plan["repeats"],
            "send_stripped": plan["send_stripped"],
            "max_requests": max_requests,
            "planned_requests": plan["request_count"],
            "requests_made": made,
            "http_requests_made": made + int(health_check),
            "silence_threshold_dbfs": silence_dbfs,
            "min_silence_s": min_silence_s,
            "frame_ms": FRAME_MS,
            "hop_ms": HOP_MS,
            "timeout_s": timeout,
            "health_check": health_check,
            "dry_run": False,
            "python": sys.version.split()[0],
            "platform": sys.platform,
        },
        "health": health,
        "voices": plan["voices"],
        "conditions": plan["conditions"],
        "bodies": plan["bodies"],
        "attempts": attempts,
        "summary": {
            "planned": plan["request_count"],
            "made": made,
            "ok": sum(1 for a in attempts if a["ok"]),
            "bad": sum(1 for a in attempts if not a["ok"]),
            "aborted": aborted,
            "abort_reason": abort_reason,
            "attempts_with_internal_silence": [
                {
                    "attempt_id": a["attempt_id"],
                    "longest_internal_silence_s": a["metrics"]["longest_internal_silence_s"],
                }
                for a in attempts
                if a["metrics"] and a["metrics"]["internal_silences"]
            ],
            "max_internal_silence_s": max(
                (
                    a["metrics"]["longest_internal_silence_s"]
                    for a in attempts
                    if a["metrics"]
                ),
                default=None,
            ),
        },
        "annotations_file": "annotations.template.json",
    }

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    annotations = build_annotations(plan, status_by_attempt)
    (out_dir / "annotations.template.json").write_text(
        json.dumps(annotations, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest, (1 if (aborted or manifest["summary"]["bad"]) else 0)


# ── CLI ──────────────────────────────────────────────────────────────────────

def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {raw!r}")
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return value


def _voice_spec(raw: str) -> tuple[str, str | None]:
    name, sep, backend = raw.partition("=")
    name = name.strip()
    backend = backend.strip() if sep else None
    if not name:
        raise argparse.ArgumentTypeError(f"empty voice name in {raw!r}")
    if any(ch in name for ch in ("/", "\\")) or name.startswith("."):
        # The probe never opens a voice file, and it must not be aimable at one.
        raise argparse.ArgumentTypeError(
            f"voice name must be a plain profile name, got {name!r}"
        )
    if sep and not backend:
        raise argparse.ArgumentTypeError(f"empty backend in {raw!r}")
    return name, backend


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--voice",
        action="append",
        type=_voice_spec,
        default=None,
        metavar="NAME[=BACKEND]",
        help="Voice profile to probe, optionally pinned to an expected backend "
             "(e.g. picard-qwen3-06b=qwen3-0.6b). Repeatable; order is the "
             "request order. Required.",
    )
    ap.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    ap.add_argument(
        "--allow-non-loopback",
        action="store_true",
        help="Permit a non-loopback endpoint. Recorded in the manifest.",
    )
    ap.add_argument("--lang", default="en")
    ap.add_argument(
        "--repeats", type=_positive_int, default=DEFAULT_REPEATS,
        help=f"Repeats per condition (minimum 2). Default {DEFAULT_REPEATS}.",
    )
    ap.add_argument(
        "--max-requests", type=_positive_int, default=DEFAULT_MAX_REQUESTS,
        help=f"Hard cap on all HTTP requests, including /health when enabled; checked before any call. "
             f"Default {DEFAULT_MAX_REQUESTS}.",
    )
    ap.add_argument("--execute", action="store_true",
                    help="Actually issue requests. Without this the probe is a dry run.")
    ap.add_argument("--out", default=None, metavar="DIR",
                    help="Output directory. Required with --execute; optional in a "
                         "dry run (writes plan.json + annotations.template.json only).")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--silence-dbfs", type=float, default=DEFAULT_SILENCE_DBFS,
                    help=f"Frame level at or below which audio counts as silent "
                         f"(default {DEFAULT_SILENCE_DBFS}).")
    ap.add_argument("--min-silence-s", type=float, default=DEFAULT_MIN_SILENCE_S,
                    help=f"Minimum duration for a silence span to be reported "
                         f"(default {DEFAULT_MIN_SILENCE_S}).")
    ap.add_argument("--no-health-check", action="store_true",
                    help="Skip GET /health (refused for a multi-backend live plan).")
    ap.add_argument("--opening-body", default=DEFAULT_OPENING_BODY)
    ap.add_argument("--pause-body", default=DEFAULT_PAUSE_BODY)
    ap.add_argument(
        "--send-stripped",
        action="store_true",
        help="Send the canonical strip_markdown output instead of the raw "
             "cue-bearing text (default: raw, so the cue survives into the request).",
    )
    ap.add_argument(
        "--annotation-template",
        action="store_true",
        help="Emit the annotations template (all judgement fields UNKNOWN) instead "
             "of the plan. Never touches the network.",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.voice:
        print(
            "error: no voice selected. Pass --voice NAME (optionally =BACKEND) at "
            "least once — the probe never guesses a voice, and never opens a voice "
            "profile or reference file.",
            file=sys.stderr,
        )
        return 2
    names = [unicodedata.normalize("NFC", name).casefold() for name, _ in args.voice]
    if len(names) != len(set(names)):
        print("error: duplicate --voice names would overwrite receipts", file=sys.stderr)
        return 2
    if args.repeats < 2:
        print(
            f"error: --repeats must be >= 2 (got {args.repeats}); a single repeat "
            "cannot separate a cue effect from run-to-run variance.",
            file=sys.stderr,
        )
        return 2

    guard, guard_err = endpoint_guard(args.endpoint, args.allow_non_loopback)
    if guard_err:
        print(f"error: {guard_err}", file=sys.stderr)
        return 2

    plan = build_plan(
        list(args.voice),
        repeats=args.repeats,
        lang=args.lang,
        endpoint=args.endpoint.rstrip("/"),
        allow_non_loopback=bool(args.allow_non_loopback),
        send_stripped=bool(args.send_stripped),
        opening_body=args.opening_body,
        pause_body=args.pause_body,
    )
    planned = len(plan["requests"])
    required_calls = planned + int(not args.no_health_check)

    if required_calls > args.max_requests:
        print(
            f"error: plan needs {required_calls} HTTP requests including health when enabled, but --max-requests is "
            f"{args.max_requests}. Nothing was called. Raise the cap or reduce "
            "--voice/--repeats.",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out).expanduser().resolve() if args.out else None

    # ── Dry run (default): no network, no GPU, no synthesis ──────────────
    if not args.execute:
        if args.annotation_template:
            payload = build_annotations(plan)
            label = "annotations template"
        else:
            payload = plan
            label = "plan"
        if out_dir is not None:
            if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
                print(f"error: output directory {out_dir} is not empty; choose a fresh --out", file=sys.stderr)
                return 2
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / ".gitignore").write_text("*\n", encoding="utf-8")
            name = "annotations.template.json" if args.annotation_template else "plan.json"
            (out_dir / name).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(f"wrote {out_dir / name}", file=sys.stderr)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(
            f"\nDRY RUN — {label} for {planned} request(s) across "
            f"{len(plan['voices'])} voice(s) x {len(plan['conditions'])} condition(s) "
            f"x {args.repeats} repeat(s). No network call, no GPU, no audio.\n"
            "Live run requires --execute and --out DIR. Waveform metrics from such a "
            "run are not a perceptual-fidelity verdict.",
            file=sys.stderr,
        )
        return 0

    # ── Live run ─────────────────────────────────────────────────────────
    if out_dir is None:
        print("error: --execute requires --out DIR for receipts and manifest.",
              file=sys.stderr)
        return 2
    if any(backend is None for _, backend in args.voice):
        print("error: live probes require --voice NAME=BACKEND for every voice", file=sys.stderr)
        return 2
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        print(
            f"error: output directory {out_dir} is not empty; choose a fresh --out.",
            file=sys.stderr,
        )
        return 2
    if args.no_health_check and len(args.voice) > 1:
        print("error: a multi-voice live plan requires /health preflight; remove --no-health-check", file=sys.stderr)
        return 2
    manifest_path = out_dir / "manifest.json"

    print(
        f"LIVE RUN: {planned} serial synthesis request(s) to {plan['endpoint']} "
        f"(cap {args.max_requests}), receipts under {out_dir}\n"
        "This is the synthesis gate: it will exercise the live server's voice(s) "
        "and will NOT be restarted, reloaded or re-cloned by this script.",
        file=sys.stderr,
    )
    manifest, rc = execute(
        plan,
        out_dir=out_dir,
        max_requests=args.max_requests,
        timeout=args.timeout,
        silence_dbfs=args.silence_dbfs,
        min_silence_s=args.min_silence_s,
        health_check=not args.no_health_check,
    )
    summary = manifest["summary"]
    print(
        json.dumps(
            {
                "plan_id": plan["plan_id"],
                "out_dir": str(out_dir),
                "manifest": str(manifest_path),
                "annotations_template": str(out_dir / "annotations.template.json"),
                "summary": {
                    "planned": summary["planned"],
                    "made": summary["made"],
                    "ok": summary["ok"],
                    "bad": summary["bad"],
                    "aborted": summary["aborted"],
                    "abort_reason": summary["abort_reason"],
                    "max_internal_silence_s": summary["max_internal_silence_s"],
                },
                "perceptual_fidelity_claim": "NONE",
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    if rc != 0:
        print(
            "run failed closed — receipts and manifest kept for every attempt made. "
            "Do not read a fidelity verdict out of this: fill annotations.template.json.",
            file=sys.stderr,
        )
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
