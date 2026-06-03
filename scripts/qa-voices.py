#!/usr/bin/env python3
"""
QA all base voice profiles: transcribe ref WAV, synthesize a test phrase,
transcribe synthesis output. Reports ref WER and synth WER per voice.

Usage:
    python3 scripts/qa-voices.py [--synth] [--ref-only] [--voice NAME] [--out results.tsv]

--synth      Also run synthesis tests (slow, ~10-30s per voice).
--ref-only   Only transcribe ref WAVs, skip synthesis even if --synth is set.
--voice NAME Test a single voice by name.
--out        Output file (default: /tmp/voice-qa.tsv)
"""
import argparse, json, os, re, sys, tempfile, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

REPO = Path(__file__).parent.parent
TEST_PHRASE = "Good morning. Testing one, two, three. The quick brown fox jumps over the lazy dog."
SERVER = "http://localhost:7860"

VARIANT_SUFFIXES = re.compile(r'-qwen3-\d+|-(ibuki|sanchin|picard)$')

TEST_WORDS = TEST_PHRASE.lower().split()


def edit_distance(a: list, b: list) -> int:
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + cost)
    return d[len(a)][len(b)]


def wer(ref: str, hyp: str) -> float:
    ref_w = ref.lower().split()
    hyp_w = hyp.lower().split()
    if not ref_w:
        return 0.0
    return edit_distance(ref_w, hyp_w) / len(ref_w)


def phrase_wer(ref: str, hyp: str) -> float:
    """WER against best-matching window in hyp — ignores preamble before the test phrase."""
    ref_w = ref.lower().split()
    hyp_w = hyp.lower().split()
    n = len(ref_w)
    if not n:
        return 0.0
    if not hyp_w:
        return 1.0
    # Slide a window of size n..n+n//2 over hyp and take the best WER
    slack = n // 2
    best = 1.0
    for start in range(len(hyp_w)):
        window = hyp_w[start:start + n + slack]
        if not window:
            break
        d = edit_distance(ref_w, window[:n])
        best = min(best, d / n)
        if best == 0.0:
            break
    return best


def transcribe(path: str, model):
    segs, info = model.transcribe(path, beam_size=3)
    text = " ".join(s.text.strip() for s in segs).strip()
    return text, info.language, info.language_probability


def build_flags(ref_wer: float, ref_lang: str, synth_wer: float | None) -> str:
    flags = []
    if ref_lang not in ("en", None, "") and ref_lang is not None:
        flags.append(f"WARN-REF-LANG({ref_lang})")
    if ref_wer > 0.6:
        flags.append("WARN-REF")
    if synth_wer is None:
        if not flags:
            return "REF-OK"
    else:
        if synth_wer > 0.4:
            flags.append("WARN-SYNTH")
    return "|".join(flags) if flags else "PASS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synth", action="store_true")
    ap.add_argument("--ref-only", action="store_true")
    ap.add_argument("--voice", default="")
    ap.add_argument("--out", default="/tmp/voice-qa.tsv")
    args = ap.parse_args()

    run_synth = args.synth and not args.ref_only

    import faster_whisper
    print("Loading Whisper base model...", flush=True)
    model = faster_whisper.WhisperModel("base", device="cpu", compute_type="int8")

    jsons = sorted(p for p in (REPO / "voices").glob("*.json")
                   if not VARIANT_SUFFIXES.search(p.stem))

    if args.voice:
        jsons = [p for p in jsons if p.stem == args.voice or
                 json.loads(p.read_text()).get("name") == args.voice]
        if not jsons:
            print(f"Voice '{args.voice}' not found.", file=sys.stderr)
            sys.exit(1)

    print(f"Found {len(jsons)} base voice profiles.\n", flush=True)

    rows = []
    header = ["voice", "ref_wer", "ref_lang", "ref_transcript", "ref_stored",
              "synth_wer", "synth_transcript", "flag"]

    for i, jpath in enumerate(jsons, 1):
        with open(jpath) as f:
            profile = json.load(f)

        name = profile.get("name", jpath.stem)
        stored_ref = profile.get("reference_text", "")
        ref_wav = REPO / "voices" / profile.get("reference_audio", f"{name}-ref.wav")

        print(f"[{i:03d}/{len(jsons)}] {name}", end="  ", flush=True)

        # --- Ref WAV transcription ---
        if ref_wav.exists():
            ref_transcript, ref_lang, ref_lang_prob = transcribe(str(ref_wav), model)
            r_wer = wer(stored_ref, ref_transcript)
        else:
            ref_transcript = "MISSING"
            ref_lang = ""
            ref_lang_prob = 0.0
            r_wer = 1.0

        print(f"ref_wer={r_wer:.2f}", end="", flush=True)
        if ref_lang and ref_lang != "en":
            print(f"(lang={ref_lang}:{ref_lang_prob:.0%})", end="", flush=True)

        # --- Synthesis test ---
        s_wer = None
        synth_transcript = ""
        if run_synth:
            try:
                url = (f"{SERVER}/synthesize"
                       f"?text={urllib.parse.quote(TEST_PHRASE)}"
                       f"&voice={urllib.parse.quote(name)}")
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                    tmp_path = tmp.name
                req = urllib.request.Request(url, headers={"Accept": "audio/wav"})
                with urllib.request.urlopen(req, timeout=90) as resp:
                    with open(tmp_path, "wb") as f:
                        f.write(resp.read())
                synth_transcript, _, _ = transcribe(tmp_path, model)
                s_wer = phrase_wer(TEST_PHRASE, synth_transcript)
                os.unlink(tmp_path)
                print(f"  synth_wer={s_wer:.2f}", end="", flush=True)
            except Exception as e:
                synth_transcript = f"ERROR: {e}"
                s_wer = 1.0
                print(f"  synth=ERROR", end="", flush=True)

        f_str = build_flags(r_wer, ref_lang, s_wer)
        print(f"  [{f_str}]", flush=True)

        rows.append([
            name,
            f"{r_wer:.3f}",
            ref_lang,
            ref_transcript,
            stored_ref,
            f"{s_wer:.3f}" if s_wer is not None else "",
            synth_transcript,
            f_str,
        ])

    with open(args.out, "w") as f:
        f.write("\t".join(header) + "\n")
        for row in rows:
            f.write("\t".join(str(c) for c in row) + "\n")

    print(f"\nResults written to {args.out}")

    warn = [r for r in rows if "WARN" in r[-1]]
    print(f"\nSummary: {len(rows)} voices, {len(warn)} warnings")
    if warn:
        print("\nWarnings:")
        for r in warn:
            print(f"  {r[0]:30s}  ref_wer={r[1]}  {r[-1]}")
            print(f"    stored:      {r[4][:80]}")
            print(f"    transcribed: {r[3][:80]}")


if __name__ == "__main__":
    main()
