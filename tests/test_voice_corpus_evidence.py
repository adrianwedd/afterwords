"""Evidence integrity checks; these do not establish auditory suitability."""
import importlib.util
import json
from pathlib import Path
import sqlite3

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
