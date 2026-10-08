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

    payload['uncertainty'] = (
        'High uncertainty because the audio was ingested and presented as a text transcript '
        'rather than raw playable audio with timing information.')
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


def test_attachment_cannot_override_explicit_inferred_acoustics():
    listener = load_script("listen_voice_corpus")
    payload = {"speaker_count": 1, "literal_transcript": "hello",
               "uncertainty": "Acoustic features were inferred from available representation rather than direct auditory waveform analysis."}
    assert listener.parsed_observation({"status": "SUCCESS", "response": json.dumps(payload)}) is None


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


@pytest.mark.parametrize("kind", ["replacement", "lossless_pcm_frame_slice"])
def test_admission_rejects_silently_clamped_frame_interval(tmp_path, monkeypatch, kind):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    admission = load_script("admit_voice_reference")
    baseline = json.loads((ROOT / "qa/voice-reference-remediation/baseline.json").read_text())
    record = next(r for r in baseline["records"] if r["wav"] == "bob-jones-ref.wav")
    qa = tmp_path / "qa/voice-reference-remediation"
    qa.mkdir(parents=True)
    (qa / "baseline.json").write_text(json.dumps({"records": [record]}))
    (tmp_path / "voices").mkdir()
    wav = tmp_path / "voices" / record["wav"]
    original_bytes = (ROOT / "voices" / record["wav"]).read_bytes()
    wav.write_bytes(original_bytes)
    evidence = ROOT / "qa/voice-reference-remediation/evidence/bob-jones-original.json"
    prefix = "source_" if kind == "replacement" else ""
    operation = {"type": kind, prefix + "start_frame": 0,
                 prefix + "end_frame_exclusive": record["audio"]["frames"] + 1}
    plan = {"wav": record["wav"], "approved": True, "adjudication": "reject before mutation",
            "candidate": str(wav), "native_original_evidence": str(evidence),
            "native_result_evidence": str(evidence), "operation": operation}
    with pytest.raises(AssertionError, match="slice"):
        admission.admit(tmp_path, plan)
    assert wav.read_bytes() == original_bytes
    assert not (qa / "changes.json").exists()


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
        start = operation.get("source_start_frame", operation.get("start_frame"))
        end = operation.get("source_end_frame_exclusive", operation.get("end_frame_exclusive"))
        if start is not None or end is not None:
            assert 0 <= start < end
            assert end - start == actual["frames"], "declared interval must not silently clamp"
        if operation["type"] == "lossless_pcm_frame_slice":
            assert end <= record["audio"]["frames"]
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


def test_final_snapshot_covers_tracked_corpus_without_private_disk_assets(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    preparation = load_script('prepare_voice_acceptance')
    qa = tmp_path / 'qa/voice-reference-remediation'
    qa.mkdir(parents=True)
    voices = tmp_path / 'voices'
    voices.mkdir()
    names = ['repaired-ref.wav', 'kept-ref.wav', 'excluded-ref.wav']
    (qa / 'baseline.json').write_text(json.dumps({'records': [{'wav': n} for n in names]}))
    (qa / 'changes.json').write_text(json.dumps({
        'changes': [{'wav': names[0]}],
        'exclusions': [{'wav': names[2], 'production_disposition': 'excluded'}]}))
    tracked = []
    for name in names[:2]:
        sf.write(voices / name, np.full(32000, 0.1), 8000)
        profile = name.replace('-ref.wav', '.json')
        (voices / profile).write_text(json.dumps({'reference_audio': name, 'reference_text': 'hello there'}))
        tracked.extend(['voices/' + name, 'voices/' + profile])
    sf.write(voices / 'private-ref.wav', np.full(32000, 0.2), 8000)
    monkeypatch.setattr(preparation.subprocess, 'check_output',
                        lambda args, **kwargs: '\n'.join(tracked) if args[1] == 'ls-files' else 'a' * 40)
    mirror, output = tmp_path / 'mirror', tmp_path / 'snapshot.json'
    with pytest.raises(AssertionError, match='Finish every individual disposition'):
        preparation.prepare(tmp_path, mirror, output, [])
    assert not mirror.exists()
    preparation.prepare(tmp_path, mirror, output, [names[1]])
    snapshot = json.loads(output.read_text())
    assert snapshot['production_count'] == 2
    assert {r['wav'] for r in snapshot['records']} == set(names[:2])
    assert len(list((mirror / 'voices').glob('*.wav'))) == 2
    for record in snapshot['records']:
        assert hashlib.sha256((mirror / 'voices' / record['anonymous_wav']).read_bytes()).hexdigest() == record['audio']['sha256']
        assert record['native_listening'] == 'pending'


def test_final_acceptance_is_bound_to_complete_fresh_production_scope(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    listener = load_script('listen_voice_corpus')
    snapshot = json.loads((ROOT / 'qa/voice-reference-remediation/final-snapshot.json').read_text())
    decisions = json.loads((ROOT / 'qa/voice-reference-remediation/final-acceptance.json').read_text())
    assert snapshot['known_baseline_count'] == 105
    assert snapshot['production_count'] == len(snapshot['records']) == 104
    assert sum(len(r['profiles']) for r in snapshot['records']) == 198
    expected = {r['wav']: r for r in snapshot['records']}
    assert {r['wav'] for r in decisions['records']} == set(expected)
    assert decisions['production_commit'] == snapshot['production_commit']
    for decision in decisions['records']:
        record = expected[decision['wav']]
        assert decision['sha256'] == record['audio']['sha256']
        assert hashlib.sha256((ROOT / 'voices' / decision['wav']).read_bytes()).hexdigest() == decision['sha256']
        if decision['status'] != 'accepted':
            continue
        assert decision['adjudication'].strip() and decision['evidence']
        for path in decision['evidence']:
            assert path.startswith('qa/voice-reference-remediation/final-evidence/')
            evidence = json.loads((ROOT / path).read_text())
            assert evidence['wav'] == record['anonymous_wav']
            assert evidence['source_sha256'] == decision['sha256']
            assert evidence['transcript_scope'] == 'full'
            assert evidence['native_audio_proven'] and evidence['exit_code'] == 0
            assert evidence['result']['status'] == 'SUCCESS'
            assert listener.parsed_observation(evidence['result']) is not None
            assert all(e['media_sha256'] == decision['sha256'] for e in evidence['attachment_evidence'])
    if decisions['corpus_status'] == 'accepted':
        assert all(r['status'] == 'accepted' for r in decisions['records'])


def test_final_signed_pcm_measurements_cover_both_endpoints():
    """Positive PCM16 saturation must not disappear behind normalized abs>=1."""
    snapshot = json.loads((ROOT / 'qa/voice-reference-remediation/final-snapshot.json').read_text())
    checks = json.loads((ROOT / 'qa/voice-reference-remediation/final-deterministic-checks.json').read_text())
    expected = {r['wav']: r for r in snapshot['records']}
    assert checks['scope_count'] == len(checks['records']) == len(expected) == 104
    assert {r['wav'] for r in checks['records']} == set(expected)
    for measurement in checks['records']:
        path = ROOT / 'voices' / measurement['wav']
        assert measurement['sha256'] == expected[measurement['wav']]['audio']['sha256']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == measurement['sha256']
        samples, rate = sf.read(path, dtype='int16', always_2d=True)
        negative = int(np.count_nonzero(samples == -32768))
        positive = int(np.count_nonzero(samples == 32767))
        assert measurement['negative_fullscale_samples'] == negative
        assert measurement['positive_fullscale_samples'] == positive
        assert measurement['signed_fullscale_samples'] == negative + positive
        assert measurement['signed_fullscale_fraction'] == (negative + positive) / samples.size
        frame_mask = np.any((samples == -32768) | (samples == 32767), axis=1)
        edges = np.diff(np.r_[False, frame_mask, False].astype(np.int8))
        lengths = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
        longest = int(lengths.max()) if lengths.size else 0
        assert measurement['longest_fullscale_run_frames'] == longest
        assert measurement['longest_fullscale_run_ms'] == pytest.approx(longest * 1000 / rate)


def test_fresh_revision_rejects_clamped_current_slice_before_mutation(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / 'scripts'))
    revision = load_script('revise_voice_reference')
    qa = tmp_path / 'qa/voice-reference-remediation'
    qa.mkdir(parents=True)
    (tmp_path / 'voices').mkdir()
    wav = tmp_path / 'voices/clip-ref.wav'
    sf.write(wav, np.full(32000, 0.1), 8000)
    before = wav.read_bytes()
    audio = revision.inspect_audio(wav)
    manifest = {'changes': [{'wav': wav.name, 'resulting_audio': audio, 'delivery_commit': 'a' * 40}]}
    (qa / 'changes.json').write_text(json.dumps(manifest))
    (qa / 'final-snapshot.json').write_text(json.dumps({'records': [{'wav': wav.name, 'audio': audio}]}))
    monkeypatch.setattr(revision.subprocess, 'check_output', lambda *args, **kwargs: before)
    plan = {'wav': wav.name, 'expected_sha256': audio['sha256'], 'approved': True,
            'adjudication': 'reject before mutation', 'candidate': str(wav),
            'operation': {'type': 'lossless_current_pcm_slice', 'start_frame': 0,
                          'end_frame_exclusive': audio['frames']+1, 'sample_rate': 8000}}
    with pytest.raises(AssertionError):
        revision.revise(tmp_path, plan)
    assert wav.read_bytes() == before
    assert json.loads((qa / 'changes.json').read_text()) == manifest


def test_post_remediation_revisions_preserve_reconstructable_operations():
    manifest = json.loads((ROOT / 'qa/voice-reference-remediation/changes.json').read_text())
    listener = load_script('listen_voice_corpus')
    for change in manifest['changes']:
        for revision in change.get('post_remediation_revisions', []):
            previous = subprocess.check_output(['git', 'show', revision['previous_delivery_commit'] + ':voices/' + change['wav']], cwd=ROOT)
            assert hashlib.sha256(previous).hexdigest() == revision['previous_audio']['sha256']
            assert revision['adjudication'].strip()
            op = revision['operation']
            if op['type'] == 'lossless_current_pcm_slice':
                samples, rate = sf.read(io.BytesIO(previous), dtype='int16', always_2d=True)
                assert 0 <= op['start_frame'] < op['end_frame_exclusive'] <= len(samples)
                assert rate == op['sample_rate']
                buffer = io.BytesIO()
                sf.write(buffer, samples[op['start_frame']:op['end_frame_exclusive']], rate, format='WAV', subtype='PCM_16')
                assert hashlib.sha256(buffer.getvalue()).hexdigest() == revision['resulting_audio']['sha256']
            else:
                assert op['type'] == 'text_only'
                assert revision['resulting_audio'] == revision['previous_audio']
            for path in revision['native_evidence']:
                evidence = json.loads((ROOT / path).read_text())
                assert evidence['source_sha256'] == revision['resulting_audio']['sha256']
                assert evidence['native_audio_proven'] and evidence['transcript_scope'] == 'full'
                assert listener.parsed_observation(evidence['result'])
