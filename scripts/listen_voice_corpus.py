#!/usr/bin/env python3
"""Serial, resumable agy native-audio observations, isolated from corpus metadata.

This collects evidence, not final acceptance. Reviewers cannot edit the corpus.
An observation is valid only while its source hash matches; changed files need
another pass. A completed view_file call alone does not prove audio ingestion:
the stored audio/wav media must hash identically to the reviewed WAV.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess

PROMPT = """Auditory QA only. Use view_file to ingest {path} as native audio.
Do not use terminal, ASR, metadata, other files, transcripts or online sources.
Do not edit files or delegate. If native ingestion fails report
NATIVE_AUDIO_UNAVAILABLE. Listen before deciding. Return a JSON object with:
speaker_count, speaker_change_intervals_s, literal_transcript, music, crowd,
laughter, sound_effects, acoustic_changes, beginning_cutoff, ending_cutoff,
long_pauses, apparent_splices, raw_reference_usable, salvageable_by_trim,
fatal_defect, candidate_clean_intervals_s, uncertainty. State uncertainty in
wording and boundary estimates explicitly. Do not identify actors/characters
or substitute remembered scripts. Assess isolation of a single speaker and
complete usable phrases for conditioning. These are perceptual estimates.
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def attachment_evidence(conversation, expected_hash):
    base = Path.home() / ".gemini/antigravity-cli"
    db = base / "conversations" / f"{conversation}.db"
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as connection:
        evidence = []
        for index, payload in connection.execute("SELECT idx, step_payload FROM steps"):
            payload = payload or b""
            if b"audio/wav" not in payload:
                continue
            for raw in re.findall(rb"/[^\x00-\x20]+\.wav", payload):
                path = Path(raw.decode(errors="replace"))
                if ".tempmediaStorage" in str(path) and path.is_file():
                    sha = digest(path)
                    if sha == expected_hash:
                        evidence.append({"step_index": index, "mime": "audio/wav",
                                         "media_sha256": sha})
        return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gemini-3.1-pro-high")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # No voice names or profile contents in the reviewer's workspace.
    for number, wav in enumerate(sorted((args.root / "voices").glob("*-ref.wav")), 1):
        sha = digest(wav)
        dest = output / f"{number:03d}-{sha[:16]}"
        frozen = dest / "observation.json"
        if frozen.exists():
            existing = json.loads(frozen.read_text())
            if existing.get("source_sha256") == sha and existing.get("native_audio_proven"):
                continue
        dest.mkdir(exist_ok=True)
        clip = dest / "clip.wav"
        shutil.copyfile(wav, clip)
        print(f"Listening {number}: {wav.name} {sha}", flush=True)
        with (dest / "events.jsonl").open("w") as events, (dest / "stderr.log").open("w") as errors:
            result = subprocess.run([
                "agy", "--model", args.model, "--mode", "plan",
                "--output-format", "stream-json", "--print", PROMPT.format(path=clip)
            ], cwd=dest, stdout=events, stderr=errors)
        records = [json.loads(line) for line in (dest / "events.jsonl").read_text().splitlines()]
        final = next((r["result"] for r in reversed(records) if r.get("event") == "result"), {})
        conversation = final.get("conversation_id")
        proof = attachment_evidence(conversation, sha) if conversation else []
        tool_calls = [r.get("step_update", {}) for r in records
                      if r.get("step_update", {}).get("step_type") == "tool"
                      and r.get("step_update", {}).get("state") == "ACTIVE"]
        clean = all(t.get("tool_name") == "view_file" and
                    t.get("tool_info", {}).get("parameters", {}).get("AbsolutePath") == str(clip)
                    for t in tool_calls)
        observation = {
            "wav": wav.name, "source_sha256": sha, "model": args.model,
            "conversation_id": conversation, "native_audio_proven": bool(proof) and clean,
            "audio_first_protocol": clean, "attachment_evidence": proof,
            "exit_code": result.returncode, "result": final,
            "acceptance": "pending orchestrator adjudication",
        }
        frozen.write_text(json.dumps(observation, indent=2) + "\n")
        if result.returncode or not proof or not clean or final.get("status") != "SUCCESS":
            raise RuntimeError(f"Native listening gate failed: {wav.name}; inspect {dest}")
        print(f"Frozen {number}: native attachment proven", flush=True)


if __name__ == "__main__":
    main()
