"""Evidence integrity checks; these do not establish auditory suitability."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import io
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


def test_every_changed_reference_has_hash_bound_provenance():
    baseline = json.loads((ROOT / "qa/voice-reference-remediation/baseline.json").read_text())
    manifest = json.loads((ROOT / "qa/voice-reference-remediation/changes.json").read_text())
    changes = {c["wav"]: c for c in manifest["changes"]}
    audio = load_script("voice_corpus")
    for record in baseline["records"]:
        path = ROOT / "voices" / record["wav"]
        actual = audio.inspect_audio(path)
        if actual["sha256"] == record["audio"]["sha256"]:
            continue
        change = changes[record["wav"]]
        assert change["original_audio"] == record["audio"]
        assert actual == change["resulting_audio"]
        for field, expected in [("native_original_evidence", record["audio"]["sha256"]),
                                ("native_result_evidence", actual["sha256"])]:
            evidence = json.loads((ROOT / change[field]).read_text())
            assert evidence["native_audio_proven"]
            assert evidence["source_sha256"] == expected
            assert all(e["media_sha256"] == expected for e in evidence["attachment_evidence"])
        for profile in change["profiles"]:
            current = json.loads((ROOT / profile["path"]).read_text())
            assert current["reference_audio"] == record["wav"]
            assert current["reference_text"] == profile["new_reference_text"]
            assert current["segment_start_s"] == profile["new_segment_start_s"]
        assert {p["path"] for p in change["profiles"]} == {p["path"] for p in record["profiles"]}
        operation = change["operation"]
        if operation["type"] == "lossless_pcm_frame_slice":
            old_bytes = subprocess.check_output([
                "git", "show", f"{baseline['baseline_commit']}:voices/{record['wav']}"], cwd=ROOT)
            old, rate = sf.read(io.BytesIO(old_bytes), dtype="int16", always_2d=True)
            new, new_rate = sf.read(path, dtype="int16", always_2d=True)
            assert new_rate == rate == operation["sample_rate"]
            np.testing.assert_array_equal(
                new, old[operation["start_frame"]:operation["end_frame_exclusive"]])
