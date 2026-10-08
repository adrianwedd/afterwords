#!/usr/bin/env python3
"""Apply an orchestrator-approved, hash-bound reference edit and provenance.

Plans are written after native candidate review. This tool checks evidence and
sample integrity; it cannot independently establish perceptual suitability.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

import numpy as np
import soundfile as sf

from voice_corpus import inspect_audio
from listen_voice_corpus import parsed_observation


def admit(root: Path, plan: dict):
    qa = root / "qa/voice-reference-remediation"
    baseline = json.loads((qa / "baseline.json").read_text())
    original = next(r for r in baseline["records"] if r["wav"] == plan["wav"])
    destination = root / "voices" / plan["wav"]
    assert inspect_audio(destination)["sha256"] == original["audio"]["sha256"], "already edited; revise plan"
    assert plan["approved"] is True and plan["adjudication"].strip()
    candidate = Path(plan["candidate"])
    result_audio = inspect_audio(candidate)
    evidence_paths = {}
    for phase, expected in [("original", original["audio"]["sha256"]),
                            ("result", result_audio["sha256"])]:
        source = Path(plan[f"native_{phase}_evidence"])
        data = json.loads(source.read_text())
        assert data["native_audio_proven"] and data["source_sha256"] == expected
        assert data["result"]["status"] == "SUCCESS"
        assert parsed_observation(data["result"]) is not None, "reviewer did not return native observations"
        if phase == "result":
            assert data.get("transcript_scope", "full") == "full", "excerpt review cannot admit a full transcript"
        assert data["attachment_evidence"]
        assert all(e["media_sha256"] == expected for e in data["attachment_evidence"])
        evidence_paths[phase] = (source, qa / "evidence" / f"{plan['wav'].removesuffix('-ref.wav')}-{phase}.json")
    operation = plan["operation"]
    if operation["type"] == "lossless_pcm_frame_slice":
        old, rate = sf.read(destination, dtype="int16", always_2d=True)
        new, new_rate = sf.read(candidate, dtype="int16", always_2d=True)
        assert original["audio"]["subtype"] == result_audio["subtype"] == "PCM_16"
        assert rate == new_rate == operation["sample_rate"]
        assert np.array_equal(new, old[operation["start_frame"]:operation["end_frame_exclusive"]])
    elif operation["type"] == "text_only":
        assert result_audio["sha256"] == original["audio"]["sha256"]
    else:
        assert operation["type"] == "replacement" and plan["replacement_provenance"]
    updates = []
    for profile in original["profiles"]:
        path = root / profile["path"]
        data = json.loads(path.read_text())
        assert data["reference_audio"] == plan["wav"]
        assert data.get("reference_text") == profile["reference_text"], "profile changed since baseline"
        data["reference_text"] = plan["reference_text"]
        start = plan.get("segment_start_s", profile["segment_start_s"])
        if start is not None:
            data["segment_start_s"] = start
        if "source_url" in plan:
            data["source_url"] = plan["source_url"]
        if "notes" in data:
            data["notes"] = plan.get("notes", "Reference remediated; see qa/voice-reference-remediation/changes.json for provenance and native listening evidence.")
        updates.append((path, data, {
            "path": profile["path"], "old_reference_text": profile["reference_text"],
            "new_reference_text": plan["reference_text"],
            "old_segment_start_s": profile["segment_start_s"], "new_segment_start_s": start,
        }))
    assert updates
    manifest_path = qa / "changes.json"
    manifest = json.loads(manifest_path.read_text())
    assert not any(c["wav"] == plan["wav"] for c in manifest["changes"])
    change = {
        "wav": plan["wav"], "remediation": plan["remediation"],
        "old_disposition": original["prior_audit_hypothesis"]["decision"],
        "original_audio": original["audio"], "resulting_audio": result_audio,
        "operation": operation, "profiles": [u[2] for u in updates],
        "source_url": plan.get("source_url", original["profiles"][0]["source_url"]),
        "adjudication": plan["adjudication"],
        "deterministic_qa": {"audio_integrity": True, "sample_exact_slice": operation["type"] == "lossless_pcm_frame_slice"},
        "delivery_commit_locator": f"git log -- voices/{plan['wav']} qa/voice-reference-remediation/changes.json",
        "final_corpus_acceptance": "pending",
    }
    if "replacement_provenance" in plan:
        change["replacement_provenance"] = plan["replacement_provenance"]
    for phase, (source, target) in evidence_paths.items():
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        change[f"native_{phase}_evidence"] = str(target.relative_to(root))
    for path, data, _ in updates:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    if operation["type"] != "text_only":
        shutil.copyfile(candidate, destination)
    manifest["changes"].append(change)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print(f"Admitted {plan['wav']}; updated {len(updates)} profiles")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    admit(args.root, json.loads(args.plan.read_text()))
