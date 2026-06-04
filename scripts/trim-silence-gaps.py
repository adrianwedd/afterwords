#!/usr/bin/env python3
"""Trim mid-clip silence from voice references and refresh transcripts.

Walks every voices/*.json the audit tool flags for mid-clip silence, applies
ffmpeg silenceremove to densify the WAV, re-runs Whisper, writes the updated
reference_text, and appends a notes line summarising the change.

Usage:
    python scripts/trim-silence-gaps.py             # dry run
    python scripts/trim-silence-gaps.py --apply
    python scripts/trim-silence-gaps.py --apply --voice the-doctor
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VOICES = REPO / "voices"
SCRIPTS = REPO / "scripts"

import importlib.util
spec = importlib.util.spec_from_file_location("audit_vt", SCRIPTS / "audit-voice-transcripts.py")
audit = importlib.util.module_from_spec(spec)
sys.modules["audit_vt"] = audit  # required for dataclasses on py3.14+
spec.loader.exec_module(audit)


def trim_wav(src: Path, dst: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-af",
        "silenceremove=stop_periods=-1:stop_duration=0.6:stop_threshold=-30dB",
        str(dst),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually overwrite WAVs and JSONs (otherwise dry-run)")
    ap.add_argument("--voice", help="Only process a single voice by name")
    ap.add_argument("--model", default="base.en")
    ap.add_argument("--json", action="store_true",
                    help="Emit JSON to stdout; suppress human output")
    args = ap.parse_args()

    from faster_whisper import WhisperModel
    print("loading whisper...", file=sys.stderr)
    model = WhisperModel(args.model, compute_type="int8")

    profiles = sorted(VOICES.glob("*.json"))
    if args.voice:
        profiles = [p for p in profiles if p.stem == args.voice]

    quiet = args.json
    cache: dict[Path, str] = {}
    results: list[dict] = []                 # one entry per processed voice
    targets: list[tuple[Path, Path, dict]] = []
    for jp in profiles:
        finding = audit.audit_one(jp, VOICES, cache, model)
        gap_count = sum(1 for i in finding.issues if "mid-clip silence" in i)
        rec = {"name": jp.stem, "gap_count": gap_count, "changed": False}
        results.append(rec)
        if gap_count > 0:
            ref = jp.parent / json.loads(jp.read_text())["reference_audio"]
            targets.append((jp, ref, rec))

    # Dry run: emit results and stop BEFORE applying (this is the bug the QA caught)
    if not args.apply:
        if quiet:
            print(json.dumps({"voices": results}))
        elif not targets:
            print("no silence-gap voices to trim")
        else:
            print(f"would process {len(targets)} voice(s):")
            for jp, ref, _ in targets:
                print(f"  {jp.stem}  ({ref.name})")
            print("\ndry run — pass --apply to actually trim and rewrite transcripts")
        return 1 if any(r["gap_count"] for r in results) else 0

    # Apply path
    for jp, ref, rec in targets:
        backup = ref.with_suffix(ref.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(ref, backup)
        tmp = ref.with_suffix(".trimmed.wav")
        trim_wav(ref, tmp)
        tmp.replace(ref)

        # Re-transcribe trimmed audio
        new_text = audit.transcribe(ref, model, "en")
        # Also recompute duration for the notes line
        import soundfile as sf
        info = sf.info(str(ref))

        profile = json.loads(jp.read_text())
        old_text = profile.get("reference_text", "")
        profile["reference_text"] = new_text
        notes = profile.get("notes", "")
        addition = (
            f"Reference re-trimmed via ffmpeg silenceremove "
            f"(now {info.duration:.1f}s dense). Transcript refreshed from Whisper."
        )
        profile["notes"] = (notes + " " + addition).strip() if notes else addition

        jp.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n")
        rec["changed"] = True
        if not quiet:
            print(f"  ✓ {jp.stem}: {info.duration:.1f}s")
            if old_text != new_text:
                print(f"      old: {old_text[:80]}")
                print(f"      new: {new_text[:80]}")

    if quiet:
        print(json.dumps({"voices": results}))
    elif targets:
        print(f"\ntrimmed {len(targets)} voice(s). re-run audit to verify.")
    return 0   # apply succeeded — exit 0 (Unix convention). Dry-run returns 1 for "gaps found".


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
