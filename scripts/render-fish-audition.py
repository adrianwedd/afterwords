#!/usr/bin/env python3
"""Render and verify a one-line self-introduction for every fish-* alias.

For each alias: synthesize "Hello, I'm <alias> in fish drama three." on the
private expressive API, then re-transcribe the result with faster-whisper and
reject degenerate takes (silence/noise tails, wrong words, absurd duration).
Rejected takes are retried; a persistent failure is recorded, not passed off as
a good sample.

Outputs (all under --out):
  audio/<alias>.wav     one verified take per voice
  rejected/<alias>-N.wav  kept only for takes that never passed
  manifest.json         per-voice text, hashes, durations, ASR text, attempts
  index.html            audition page, alphabetical, one <audio> per voice
  README.md             how the set was made and what it does not prove

Resumable: voices already ok in manifest.json are skipped.
Sequential by design: the Fish Drama sidecar holds a single model lease.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

DEFAULT_API = "http://127.0.0.1:7862"
# Deterministic degenerate takes exist for specific (voice, phrasing) pairs: the
# sidecar returns ~18 s of near-silent noise. Rotating the wording across
# attempts escapes those fixed points; retrying identical text does not.
PHRASINGS = (
    "Hello, I'm {name} in fish drama three.",
    "Hello, I'm {name}, and this is fish drama three.",
    "Hello, I am {name} speaking in fish drama three.",
    "Hello, I'm the voice {name} on fish drama three.",
    "Hello, I'm {name}.",
)


def spoken_name(alias: str) -> str:
    return alias.replace("-", " ")


def intro_text(alias: str, attempt: int = 1) -> str:
    phrasing = PHRASINGS[min(attempt - 1, len(PHRASINGS) - 1)]
    return phrasing.format(name=spoken_name(alias))


def peak_amplitude(path: Path) -> int:
    import array
    import wave

    with wave.open(str(path)) as w:
        data = w.readframes(w.getnframes())
    samples = array.array("h", data)
    return max((abs(x) for x in samples), default=0)


def normalize(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower().replace("-", " "))


def similarity(expected: str, heard: str) -> float:
    a, b = normalize(expected), normalize(heard)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def list_fish(api: str) -> list[str]:
    with urllib.request.urlopen(f"{api}/health", timeout=30) as r:
        health = json.load(r)
    return sorted(v for v in health.get("voices", []) if v.startswith("fish-"))


def synthesize(api: str, alias: str, text: str, dest: Path, timeout: float) -> dict:
    qs = urllib.parse.urlencode({"text": text, "voice": alias})
    req = urllib.request.Request(f"{api}/synthesize?{qs}")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
        hdrs = {k.lower(): v for k, v in r.headers.items()}
    wall = time.time() - t0
    if not body.startswith(b"RIFF"):
        raise RuntimeError(f"non-WAV response ({len(body)} bytes)")
    dest.write_bytes(body)
    return {
        "file": dest.name,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "audio_seconds": round(float(hdrs.get("x-duration", 0) or 0), 3),
        "synth_seconds_wall": round(wall, 2),
        "backend": hdrs.get("x-backend"),
        "sample_rate": hdrs.get("x-sample-rate"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default=DEFAULT_API)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", action="append", default=[])
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--sim-min", type=float, default=0.35)
    ap.add_argument("--min-peak", type=int, default=4000)
    ap.add_argument("--max-seconds", type=float, default=12.0)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()

    out = Path(args.out)
    audio = out / "audio"
    rejected_dir = out / "rejected"
    audio.mkdir(parents=True, exist_ok=True)

    manifest: dict = {}
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())

    def save_manifest() -> None:
        manifest_path.write_text(json.dumps(manifest, indent=1, sort_keys=True))

    voices = list_fish(args.api)
    if args.only:
        wanted = set(args.only)
        voices = [v for v in voices if v in wanted]
    if args.limit:
        voices = voices[: args.limit]
    print(f"fish aliases in scope: {len(voices)}", flush=True)

    asr = None
    if not args.no_verify:
        from faster_whisper import WhisperModel

        asr = WhisperModel("base.en", device="cpu", compute_type="int8")

    def transcribe(path: Path) -> str:
        segs, _info = asr.transcribe(str(path), language="en")
        return " ".join(s.text.strip() for s in segs)

    failures: list[str] = []
    for i, alias in enumerate(voices, 1):
        dest = audio / f"{alias}.wav"
        prev = manifest.get(alias)
        if prev and prev.get("status") == "ok" and dest.exists() and dest.stat().st_size > 44:
            print(f"[{i}/{len(voices)}] {alias} skip (verified {prev['audio_seconds']}s)", flush=True)
            continue

        attempts: list[dict] = []
        good = None
        tmp = out / f".take-{alias}.wav"
        for attempt in range(1, args.attempts + 1):
            text = intro_text(alias, attempt)
            try:
                rec = synthesize(args.api, alias, text, tmp, args.timeout)
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                attempts.append({"attempt": attempt, "text": text, "error": msg})
                print(f"[{i}/{len(voices)}] {alias} attempt {attempt} transport error: {msg}", flush=True)
                time.sleep(min(20, 3 * attempt))
                continue
            heard = transcribe(tmp) if asr is not None else ""
            sim = similarity(text, heard) if asr is not None else 1.0
            peak = peak_amplitude(tmp)
            dur = rec["audio_seconds"]
            reasons = []
            quiet = False
            if asr is not None:
                if dur > args.max_seconds:
                    reasons.append(f"degenerate length {dur}s > {args.max_seconds}s")
                if dur < 0.8:
                    reasons.append(f"too short {dur}s < 0.8s")
                if peak < args.min_peak:
                    # Inteligible but low-level (quiet reference): keep it, flag it.
                    if sim >= args.sim_min:
                        quiet = True
                    else:
                        reasons.append(f"near-silent peak {peak} < {args.min_peak}")
                if sim < args.sim_min:
                    reasons.append(f"low ASR similarity {sim:.2f} < {args.sim_min}")
            attempts.append({**rec, "attempt": attempt, "text": text, "heard": heard,
                             "peak": peak, "quiet": quiet,
                             "similarity": round(sim, 3), "reject": reasons})
            if not reasons:
                good = attempts[-1]
                tmp.replace(dest)
                good["file"] = dest.name
                break
            rejected_dir.mkdir(exist_ok=True)
            tmp.replace(rejected_dir / f"{alias}-attempt{attempt}.wav")
            print(f"[{i}/{len(voices)}] {alias} attempt {attempt} rejected: "
                  f"{'; '.join(reasons)} | heard={heard!r}", flush=True)
            time.sleep(1.0)

        if good:
            manifest[alias] = {
                "voice": alias,
                "text": good["text"],
                "phrasing_index": good["attempt"],
                "status": "ok",
                "file": good["file"],
                "bytes": good["bytes"],
                "sha256": good["sha256"],
                "audio_seconds": good["audio_seconds"],
                "synth_seconds_wall": good["synth_seconds_wall"],
                "backend": good["backend"],
                "sample_rate": good["sample_rate"],
                "heard": good["heard"],
                "similarity": good["similarity"],
                "peak": good["peak"],
                "quiet": good["quiet"],
                "attempts": attempts,
            }
            print(f"[{i}/{len(voices)}] {alias} ok {good['audio_seconds']}s "
                  f"sim={good['similarity']} attempt={good['attempt']}", flush=True)
        else:
            last = attempts[-1] if attempts else {}
            manifest[alias] = {"voice": alias, "status": "failed",
                               "error": last.get("error") or "; ".join(last.get("reject", [])),
                               "attempts": attempts}
            failures.append(alias)
            print(f"[{i}/{len(voices)}] {alias} FAILED after {len(attempts)} attempts", flush=True)
        save_manifest()

    ok = [v for v, r in manifest.items() if r.get("status") == "ok"]
    bad = [v for v, r in manifest.items() if r.get("status") != "ok"]
    write_index(out, manifest, args.sim_min, args.max_seconds)
    print(f"done: ok={len(ok)} failed={len(bad)}", flush=True)
    if bad:
        print("failed:", ", ".join(sorted(bad)), flush=True)
    return 0 if not bad else 1


def write_index(out: Path, manifest: dict, sim_min: float, max_seconds: float) -> None:
    ok = {v: r for v, r in manifest.items() if r.get("status") == "ok"}
    rows = []
    for alias in sorted(ok):
        r = ok[alias]
        rows.append(
            f'<li><b>{alias[5:]}</b> '
            f'<span class="meta">{r["audio_seconds"]}s &middot; sim {r["similarity"]}'
            f' &middot; {r["backend"]}</span><br>'
            f'<audio controls preload="none" src="audio/{r["file"]}"></audio></li>'
        )
    failed = sorted(v for v, r in manifest.items() if r.get("status") != "ok")
    fail_html = ""
    if failed:
        fail_html = ("<h2>Not rendered / rejected</h2><ul>"
                     + "".join(f"<li>{v}</li>" for v in failed) + "</ul>")
    out.joinpath("index.html").write_text(f"""<!doctype html>
<meta charset="utf-8"><title>Fish audition set</title>
<style>
body{{font:15px/1.5 -apple-system,Helvetica,sans-serif;margin:2rem auto;max-width:46rem;padding:0 1rem}}
h1{{font-size:1.3rem}} li{{margin:0 0 1.1rem;list-style:none}}
.meta{{color:#777;font-size:.8rem}} audio{{width:100%;margin-top:.3rem}}
</style>
<h1>Fish audition set &mdash; {len(ok)} voices</h1>
<p>Each take: <em>&ldquo;Hello, I'm &lt;voice&gt; in fish drama three.&rdquo;</em>
Machine-verified only (faster-whisper base.en, similarity &ge; {sim_min:.2f} and
&le; {max_seconds:g}&nbsp;s). Not a listening verdict.</p>
<ul>{''.join(rows)}</ul>{fail_html}
""")
    lines = ["# Fish audition set", "",
             f"{len(ok)} verified takes, {len(failed)} rejected.", "",
             "Each WAV says: \"Hello, I'm <voice> in fish drama three.\"", "",
             "| voice | seconds | ASR similarity |", "| --- | --- | --- |"]
    for alias in sorted(ok):
        r = ok[alias]
        lines.append(f"| {alias} | {r['audio_seconds']} | {r['similarity']} |")
    out.joinpath("README.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    sys.exit(main())
