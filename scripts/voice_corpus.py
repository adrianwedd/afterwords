#!/usr/bin/env python3
"""Hash-bound reference inventory; measurements do not certify perception.

Use --output to freeze a baseline before remediation. Private references are
inventoried but must not be staged with public delivery artifacts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import numpy as np
import soundfile as sf


def inspect_audio(path: Path) -> dict:
    audio, rate = sf.read(path, always_2d=True, dtype="float64")
    info = sf.info(path)
    if not len(audio) or not np.isfinite(audio).all():
        raise ValueError(f"empty or non-finite audio: {path}")
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "frames": len(audio), "sample_rate": rate,
        "channels": audio.shape[1], "subtype": info.subtype,
        "duration_s": len(audio) / rate, "peak": peak, "rms": rms,
        "samples_at_full_scale": int(np.count_nonzero(np.abs(audio) >= 1)),
    }


def inventory(root: Path) -> dict:
    tracked = set(subprocess.check_output(
        ["git", "ls-files", "voices"], cwd=root, text=True).splitlines())
    profiles = {}
    for path in sorted((root / "voices").glob("*.json")):
        data = json.loads(path.read_text())
        ref = data["reference_audio"]
        if Path(ref).name != ref or not (root / "voices" / ref).is_file():
            raise ValueError(f"missing or nonlocal reference: {path.name}: {ref}")
        profiles.setdefault(ref, []).append({
            "path": str(path.relative_to(root)),
            "tracked": str(path.relative_to(root)) in tracked,
            "reference_text": data.get("reference_text"),
            "source_url": data.get("source_url"),
            "segment_start_s": data.get("segment_start_s"),
        })
    records = []
    for path in sorted((root / "voices").glob("*-ref.wav")):
        associated = profiles.get(path.name, [])
        records.append({
            "wav": path.name, "tracked": str(path.relative_to(root)) in tracked,
            "profiles": associated, "orphan": not associated,
            "divergent_texts": len({p["reference_text"] for p in associated}) > 1,
            "audio": inspect_audio(path),
            "native_listening": {"status": "pending"},
            "final_disposition": "pending",
        })
    return {
        "schema_version": 1,
        "baseline_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "perceptual_acceptance": "unproven: native listening required per resulting hash",
        "records": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inventory(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Inventoried {len(result['records'])} WAVs; perception remains unproven.")


if __name__ == "__main__":
    main()
