"""Evidence integrity checks; these do not establish auditory suitability."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import io
import hashlib
import subprocess

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audio_inventory_rejects_empty_reference(tmp_path):
    path = tmp_path / "empty.wav"
    sf.write(path, np.zeros(0), 24000)
    with pytest.raises(ValueError, match="empty or non-finite"):
        load_script("voice_corpus").inspect_audio(path)


def test_baseline_is_complete_and_explicitly_unaccepted():
    baseline = json.loads((ROOT / "qa/voice-reference-remediation/baseline.json").read_text())
    records = baseline["records"]
    assert len(records) == 105
    assert len({r["wav"] for r in records}) == 105
    assert sum(len(r["profiles"]) for r in records) == 198
    assert all(len(r["audio"]["sha256"]) == 64 for r in records)
    assert all(r["native_listening"]["status"] == "pending" for r in records)
    assert all(r["final_disposition"] == "pending" for r in records)


def test_native_evidence_rejects_wrong_audio_bytes(tmp_path, monkeypatch):
    listener = load_script("listen_voice_corpus")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    base = tmp_path / ".gemini/antigravity-cli"
    (base / "conversations").mkdir(parents=True)
    media = base / "brain/test/.tempmediaStorage/clip.wav"
    media.parent.mkdir(parents=True)
    sf.write(media, np.ones(100) * 0.1, 24000)
    with sqlite3.connect(base / "conversations/test.db") as db:
        db.execute("CREATE TABLE steps (idx INTEGER, step_payload BLOB)")
        db.execute("INSERT INTO steps VALUES (?, ?)",
                   (2, b"audio/wav\x00" + str(media).encode() + b"\x00"))
    assert not listener.attachment_evidence("test", "0" * 64)
    assert listener.attachment_evidence("test", listener.digest(media))


def test_attachment_cannot_override_reviewer_reporting_native_audio_unavailable():
    listener = load_script("listen_voice_corpus")
    assert listener.parsed_observation({"status": "SUCCESS", "response": "NATIVE_AUDIO_UNAVAILABLE"}) is None
    assert listener.parsed_observation({"response": "I cannot hear this file."}) is None


def test_valid_json_cannot_override_reviewer_reporting_transcript_only_review():
    listener = load_script("listen_voice_corpus")
    payload = {"speaker_count": 1, "literal_transcript": "I cannot hear you.",
               "uncertainty": "Timings are approximate perceptual estimates."}
    assert listener.parsed_observation({"status": "SUCCESS", "response": json.dumps(payload)})
    payload["uncertainty"] = (
        "Audio was interpreted through a text-based transcription layer "
        "rather than native acoustic signal analysis.")
    assert listener.parsed_observation({"status": "SUCCESS", "response": json.dumps(payload)}) is None
    payload["uncertainty"] = (
        "Acoustic properties, overlap, and timing boundaries are highly uncertain "
        "as the ingestion tool provided a textual transcript rather than granular "
        "auditory features or timestamps.")
    assert listener.parsed_observation({"status": "SUCCESS", "response": json.dumps(payload)}) is None
    payload["uncertainty"] = (
        "Exact boundary estimates are extrapolated from the text layout. "
        "The presence of long pauses is inferred from significant line breaks.")
    assert listener.parsed_observation({"status": "SUCCESS", "response": json.dumps(payload)}) is None


def test_review_parser_accepts_single_fenced_result_without_ambiguous_multiple_results():
    listener = load_script("listen_voice_corpus")
    payload = '{"speaker_count": 1, "literal_transcript": "hello"}'
    assert listener.parsed_observation({"response": "女```json\n" + payload + "\n```"})
    assert listener.parsed_observation({"response": "```json\n" + payload + "\n```\n```json\n" + payload + "\n```"}) is None


def test_excerpt_only_result_cannot_admit_reference(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    admission = load_script("admit_voice_reference")
    baseline = json.loads((ROOT / "qa/voice-reference-remediation/baseline.json").read_text())
    record = next(r for r in baseline["records"] if r["wav"] == "bob-jones-ref.wav")
    qa = tmp_path / "qa/voice-reference-remediation"
    qa.mkdir(parents=True)
    (qa / "baseline.json").write_text(json.dumps({"records": [record]}))
    (tmp_path / "voices").mkdir()
    wav = tmp_path / "voices/bob-jones-ref.wav"
    wav.write_bytes((ROOT / "voices/bob-jones-ref.wav").read_bytes())
    original = ROOT / "qa/voice-reference-remediation/evidence/bob-jones-original.json"
    evidence = json.loads(original.read_text())
    evidence["transcript_scope"] = "excerpt"
    result = tmp_path / "excerpt.json"
    result.write_text(json.dumps(evidence))
    plan = {"wav": record["wav"], "approved": True, "adjudication": "must reject before mutation",
            "candidate": str(wav), "native_original_evidence": str(original),
            "native_result_evidence": str(result)}
    with pytest.raises(AssertionError, match="excerpt review cannot admit"):
        admission.admit(tmp_path, plan)
    assert wav.read_bytes() == (ROOT / "voices/bob-jones-ref.wav").read_bytes()


def test_every_changed_reference_has_hash_bound_provenance():
    baseline = json.loads((ROOT / "qa/voice-reference-remediation/baseline.json").read_text())
    manifest = json.loads((ROOT / "qa/voice-reference-remediation/changes.json").read_text())
    changes = {c["wav"]: c for c in manifest["changes"]}
    exclusions = {c["wav"]: c for c in manifest.get("exclusions", [])}
    audio = load_script("voice_corpus")
    for record in baseline["records"]:
        path = ROOT / "voices" / record["wav"]
        if not path.exists():
            exclusion = exclusions[record["wav"]]
            assert exclusion["original_audio"] == record["audio"]
            assert exclusion["reason"].strip()
            assert exclusion["production_disposition"] == "excluded"
            assert not record["profiles"], "profile exclusion needs explicit migration coverage"
            continue
        actual = audio.inspect_audio(path)
        text_changed = any(json.loads((ROOT / p["path"]).read_text()).get("reference_text") != p["reference_text"]
                           for p in record["profiles"])
        if actual["sha256"] == record["audio"]["sha256"] and not text_changed:
            continue
        change = changes[record["wav"]]
        assert change["original_audio"] == record["audio"]
        assert actual == change["resulting_audio"]
        for field, expected in [("native_original_evidence", record["audio"]["sha256"]),
                                ("native_result_evidence", actual["sha256"])]:
            evidence = json.loads((ROOT / change[field]).read_text())
            assert evidence["native_audio_proven"]
            assert evidence["result"]["status"] == "SUCCESS"
            assert load_script("listen_voice_corpus").parsed_observation(evidence["result"])
            if field == "native_result_evidence":
                assert evidence.get("transcript_scope", "full") == "full"
            assert evidence["source_sha256"] == expected
            assert all(e["media_sha256"] == expected for e in evidence["attachment_evidence"])
        for profile in change["profiles"]:
            current = json.loads((ROOT / profile["path"]).read_text())
            assert current["reference_audio"] == record["wav"]
            assert current["reference_text"] == profile["new_reference_text"]
            assert current.get("segment_start_s") == profile["new_segment_start_s"]
        assert {p["path"] for p in change["profiles"]} == {p["path"] for p in record["profiles"]}
        if resolution := change.get("transcript_resolution"):
            evidence = json.loads((ROOT / resolution["evidence"]).read_text())
            assert resolution["source_sha256"] == actual["sha256"]
            assert evidence["native_audio_proven"] and evidence["result"]["status"] == "SUCCESS"
            assert evidence["source_sha256"] == resolution["rendered_sha256"]
            assert all(e["media_sha256"] == resolution["rendered_sha256"] for e in evidence["attachment_evidence"])
            samples, rate = sf.read(path, dtype="int16", always_2d=True)
            bounds = resolution["operation"]
            assert bounds["type"] == "lossless_pcm_frame_slice" and bounds["sample_rate"] == rate
            probe = io.BytesIO()
            sf.write(probe, samples[bounds["start_frame"]:bounds["end_frame_exclusive"]],
                     rate, format="WAV", subtype="PCM_16")
            assert hashlib.sha256(probe.getvalue()).hexdigest() == resolution["rendered_sha256"]
        operation = change["operation"]
        if operation["type"] == "lossless_pcm_frame_slice":
            old_bytes = subprocess.check_output([
                "git", "show", f"{baseline['baseline_commit']}:voices/{record['wav']}"], cwd=ROOT)
            old, rate = sf.read(io.BytesIO(old_bytes), dtype="int16", always_2d=True)
            new, new_rate = sf.read(path, dtype="int16", always_2d=True)
            assert new_rate == rate == operation["sample_rate"]
            np.testing.assert_array_equal(
                new, old[operation["start_frame"]:operation["end_frame_exclusive"]])


def test_no_unexplained_production_orphan_or_missing_reference():
    inventory = load_script("voice_corpus").inventory(ROOT)
    assert not [r["wav"] for r in inventory["records"] if r["orphan"]]
    for record in inventory["records"]:
        assert record["audio"]["duration_s"] >= 3
        assert record["audio"]["rms"] > 0
