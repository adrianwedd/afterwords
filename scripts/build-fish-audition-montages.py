#!/usr/bin/env python3
"""Concatenate a rendered fish audition set into listenable montages.

Reads <set>/manifest.json (voice -> take) and writes <set>/montages/:
  montage-NN.wav   up to --per-file verified takes, alphabetical, --gap seconds apart
  order-NN.txt     the order in that montage, with each take's start offset
Also prints total listening time so a full pass is predictable.

Usage:
  .venv/bin/python scripts/build-fish-audition-montages.py \
      --set qa/expressive-voice/fish-audition-20261018 --per-file 20 --gap 0.8
"""
from __future__ import annotations

import argparse
import json
import wave
from pathlib import Path


def read_wav(path: Path):
    with wave.open(str(path)) as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    return params, frames


def normalize_peak(frames: bytes, width: int, target: float = 0.707) -> tuple[bytes, float]:
    """Scale PCM toward a common peak so quiet takes are audible next to loud ones.

    Returns (frames, gain_db). Only the montage is normalised; the per-voice WAVs
    stay bit-exact as rendered.
    """
    import array
    import math

    if width != 2:
        return frames, 0.0
    samples = array.array("h", frames)
    peak = max((abs(x) for x in samples), default=0)
    if peak == 0:
        return frames, 0.0
    gain = (target * 32767) / peak
    if gain >= 1.0:
        return frames, 0.0
    out = array.array("h", (int(x * gain) for x in samples))
    return out.tobytes(), round(20 * math.log10(gain), 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", required=True)
    ap.add_argument("--per-file", type=int, default=20)
    ap.add_argument("--gap", type=float, default=0.8)
    args = ap.parse_args()

    root = Path(args.set)
    manifest = json.loads((root / "manifest.json").read_text())
    ok = sorted(v for v, r in manifest.items() if r.get("status") == "ok")
    if not ok:
        print("nothing verified yet")
        return 1

    out = root / "montages"
    out.mkdir(exist_ok=True)

    total = 0.0
    n = 0
    for n, start in enumerate(range(0, len(ok), args.per_file), 1):
        chunk = ok[start : start + args.per_file]
        params = None
        gap = b""
        pieces: list[bytes] = []
        order: list[str] = []
        cursor = 0.0
        for alias in chunk:
            p, frames = read_wav(root / "audio" / manifest[alias]["file"])
            if params is None:
                params = p
                gap = b"\x00" * (int(p.framerate * args.gap) * p.sampwidth * p.nchannels)
            frame_bytes = params.framerate * params.sampwidth * params.nchannels
            norm, gain_db = normalize_peak(frames, params.sampwidth)
            pieces.append(norm)
            pieces.append(gap)
            gain_note = f" gain {gain_db:+.1f}dB" if gain_db else ""
            order.append(f"{cursor:7.2f}s  {alias}  ({manifest[alias]['audio_seconds']}s){gain_note}")
            cursor += len(norm) / frame_bytes + args.gap
        dest = out / f"montage-{n:02d}.wav"
        with wave.open(str(dest), "wb") as w:
            w.setparams(params)
            for piece in pieces:
                w.writeframes(piece)
        (out / f"order-{n:02d}.txt").write_text("\n".join(order) + "\n")
        total += cursor
        print(f"{dest.name}: {len(chunk)} voices, {cursor/60:.1f} min")

    print(f"total listening time {total/60:.1f} min across {n} montages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
