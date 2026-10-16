"""Real child-process cancellation and transport/fallback regression tests."""
import asyncio
import base64
import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from expressive.contracts import directed_text, validate_options
from expressive.sidecar import WorkerPool
from backends.fish_drama3 import FishDrama3Backend


@pytest.mark.parametrize('options', [{'temperature': float('nan')}, {'max_frames': True},
    {'top_k': 2.5}, {'instruct': 'invented support'}, {'cues': [{'offset': 0, 'cue': 'unknown'}]}])
def test_invalid_controls_rejected(options):
    with pytest.raises(ValueError):
        validate_options(options)


def test_direction_preserves_transcript_and_rejects_midword():
    text = 'Well. That worked.'
    assert directed_text(text, validate_options({'cues': [{'offset': 6, 'cue': 'whispers'}]})) == 'Well. [whispers] That worked.'
    with pytest.raises(ValueError):
        directed_text(text, validate_options({'cues': [{'offset': 2, 'cue': 'whispers'}]}))


@pytest.fixture
def memory_headroom(monkeypatch):
    monkeypatch.setitem(sys.modules, 'psutil', SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(available=100*1024**3)))


def child(code):
    return [sys.executable, '-u', '-c', code]


def test_sustained_silence_across_chunks_rejects_entire_delivery(memory_headroom):
    # Valid protocol completion must not turn a silent model failure into audio.
    async def run():
        # Send compact generated events rather than an oversized command line.
        code = ('import sys,json,base64\nsys.stdin.readline()\n'
                "e={'kind':'chunk','audio':base64.b64encode(bytes(44100*6*4)).decode(),'sample_rate':44100}\n"
                "print(json.dumps(e),flush=True)\nprint(json.dumps(e),flush=True)\n"
                "print(json.dumps({'kind':'done','samples':44100*12,'sample_rate':44100}),flush=True)\n")
        pool = WorkerPool(child(code))
        with pytest.raises(RuntimeError, match='sustained silence'):
            await pool.synthesize({})
        assert pool.process is None
        assert pool.pending == 0
    asyncio.run(run())


def test_deadline_kills_real_worker_and_releases_capacity(memory_headroom):
    async def run():
        pool = WorkerPool(child('import time; time.sleep(30)'), timeout=0.1)
        with pytest.raises(TimeoutError):
            await pool.synthesize({})
        assert pool.process is None
        assert pool.pending == 0
        assert not pool.lock.locked()
    asyncio.run(run())


def test_cancel_queued_request_does_not_kill_active_worker(memory_headroom):
    async def run():
        pool = WorkerPool(child('import time; time.sleep(30)'), capacity=2, timeout=5)
        first = asyncio.create_task(pool.synthesize({}))
        for _ in range(100):
            if pool.process:
                break
            await asyncio.sleep(.01)
        process = pool.process
        assert process is not None
        queued = asyncio.create_task(pool.synthesize({}))
        await asyncio.sleep(.02)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc:
            await pool.synthesize({})
        assert exc.value.status_code == 429
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert process.returncode is None
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert process.returncode is not None
        assert pool.pending == 0
    asyncio.run(run())


def test_chunks_are_concatenated_once_and_require_completion(memory_headroom):
    samples = np.array([.1, .2, .3], dtype='<f4')
    chunk = {'kind': 'chunk', 'audio': base64.b64encode(samples.tobytes()).decode(), 'sample_rate':44100}
    async def run(events):
        code = 'import sys,json\nsys.stdin.readline()\n'
        code += '\n'.join('print('+repr(json.dumps(e))+', flush=True)' for e in events)
        pool = WorkerPool(child(code))
        try:
            return await pool.synthesize({})
        finally:
            await pool.stop()
    raw, _ = asyncio.run(run([chunk, chunk, {'kind':'done','samples':6,'sample_rate':44100}]))
    audio, rate = sf.read(io.BytesIO(raw))
    assert rate == 44100
    np.testing.assert_allclose(audio, np.tile(samples,2), atol=1/32768)
    with pytest.raises(RuntimeError, match='before completion'):
        asyncio.run(run([chunk]))
    with pytest.raises(RuntimeError, match='incomplete'):
        asyncio.run(run([chunk, {'kind':'done','samples':4,'sample_rate':44100}]))


def test_fallback_receives_original_text_and_buffered_reference(tmp_path, monkeypatch):
    ref = tmp_path/'ref.wav'
    sf.write(ref, np.zeros(24000), 24000)
    backend = FishDrama3Backend()
    prepared = backend.prepare_voice(str(ref), 'Reference words.', {'cues':[{'offset':0,'cue':'laughs'}]})
    ref.unlink()
    import urllib.request
    opener = Mock()
    opener.open.side_effect = OSError('offline')
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *args: opener)
    qwen = Mock(name='Qwen')
    qwen.name = 'qwen3-0.6b'
    # A known tone checks actual conversion, rather than a changed WAV label.
    source = .5 * np.sin(2 * np.pi * 440 * np.arange(24000) / 24000)
    qwen.synthesize.return_value = (source, 24000)
    import backends
    monkeypatch.setattr(backends, 'get', lambda name: qwen)
    audio, rate = backend.synthesize('Actual answer.', prepared, 'en')
    assert rate == 44100 and len(audio) == 44100
    assert audio.dtype == np.float32 and np.isfinite(audio).all()
    peak_hz = np.argmax(abs(np.fft.rfft(audio))) * rate / len(audio)
    assert peak_hz == 440
    assert np.sqrt(np.mean(audio[100:-100] ** 2)) == pytest.approx(.5 / np.sqrt(2), abs=.002)
    text, voice, lang = qwen.synthesize.call_args.args
    assert text == 'Actual answer.' and voice.data == prepared.data and lang == 'en'
    assert backend.last_delivery_backend == 'qwen3-0.6b'


def test_fallback_can_be_disabled(tmp_path, monkeypatch):
    ref = tmp_path/'ref.wav'
    sf.write(ref, np.zeros(24000), 24000)
    backend = FishDrama3Backend()
    prepared = backend.prepare_voice(str(ref),'Words.', {'qwen_fallback':False})
    import urllib.request
    opener = Mock()
    opener.open.side_effect = OSError('offline')
    monkeypatch.setattr(urllib.request,'build_opener',lambda *args:opener)
    with pytest.raises(RuntimeError, match='fallback disabled'):
        backend.synthesize('Hello.',prepared,'en')


def test_request_controls_are_isolated_and_fallback_header_is_truthful(client, sample_voice, monkeypatch):
    import backends
    import server
    from dataclasses import replace
    backend = FishDrama3Backend()
    backends.register(backend)
    original = server.VOICES[sample_voice]
    server.VOICES[sample_voice] = replace(original, backend='fish-drama3')
    seen = []
    def synth(text, prepared, lang):
        seen.append(dict(prepared.extras))
        backend.last_delivery_backend = 'qwen3-0.6b'
        return np.zeros(240), 24000
    monkeypatch.setattr(backend, 'synthesize', synth)
    response = client.get('/synthesize', params={'text':'Hello.', 'voice':sample_voice,
                          'performance':json.dumps({'temperature':0.8})})
    assert response.status_code == 200
    assert response.headers['X-Backend'] == 'qwen3-0.6b'
    assert response.headers['X-Requested-Backend'] == 'fish-drama3'
    assert seen == [{'temperature':0.8}]
    assert dict(server.VOICES[sample_voice].prepared.extras) == {}
    response = client.get('/synthesize', params={'text':'Hello.', 'voice':sample_voice,'performance':'{"instruct":"unsupported"}'})
    assert response.status_code == 400
    assert len(seen) == 1


def test_controls_reject_ordinary_backend_and_invalid_json(client, sample_voice):
    for value in ['{"temperature":0.8}', '[]', '{broken']:
        response = client.get('/synthesize', params={'text':'Hello.', 'voice':sample_voice,'performance':value})
        assert response.status_code == 400


def test_original_reference_generator_preserves_prior_attempts(tmp_path):
    import subprocess
    from pathlib import Path
    path = tmp_path/'cast-aster.json'
    path.write_text('{"status":"failed prior attempt"}')
    script = Path(__file__).resolve().parents[1]/'scripts/generate-original-references.py'
    result = subprocess.run([sys.executable,str(script),'--name','cast-aster:101','--out',str(tmp_path)],capture_output=True,text=True)
    assert result.returncode == 2
    assert 'preserve previous attempts' in result.stderr
    assert path.read_text() == '{"status":"failed prior attempt"}'


def test_model_lease_excludes_concurrent_processes_and_releases_on_exit(tmp_path):
    import os
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ,'HOME':str(tmp_path),'PYTHONPATH':str(root)}
    code = 'from expressive.resources import acquire_model_lease; acquire_model_lease()'
    first = subprocess.Popen([sys.executable,'-u','-c',code+'; print("leased",flush=True); input()'],
                             stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    try:
        assert first.stdout.readline().strip()==b'leased'
        second = subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,env=env,timeout=5)
        assert second.returncode != 0
        assert 'another expressive model is resident' in second.stderr
    finally:
        first.terminate();first.wait(timeout=5)
    third = subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,env=env,timeout=5)
    assert third.returncode == 0, third.stderr


def test_release_refuses_active_requests(monkeypatch):
    from expressive import sidecar
    from starlette.testclient import TestClient
    monkeypatch.setattr(sidecar.pool,'pending',1)
    response=TestClient(sidecar.app).post('/release')
    assert response.status_code==409


def test_stereo_reference_downmix_is_explicit_and_fallback_bytes_unchanged(tmp_path):
    from expressive.reference import normalize_reference
    ref=tmp_path/'stereo.wav'
    stereo=np.column_stack([np.full(44100,.2),np.full(44100,.6)])
    sf.write(ref,stereo,44100,subtype='PCM_16')
    raw=ref.read_bytes()
    normalized,conversion=normalize_reference(raw)
    audio,rate=sf.read(io.BytesIO(normalized))
    assert conversion=='stereo-mean-to-mono' and rate==44100 and audio.ndim==1
    np.testing.assert_allclose(audio,.4,atol=2/32768)
    prepared=FishDrama3Backend().prepare_voice(str(ref),'Reference text.',{})
    assert prepared.data==raw


def test_adapter_cancellation_closes_real_socket_without_fallback(tmp_path, monkeypatch):
    import concurrent.futures
    import http.client
    import socket
    import threading
    from dataclasses import replace
    from expressive import transport
    ref = tmp_path/'ref.wav'
    sf.write(ref, np.zeros(24000), 24000)
    backend = FishDrama3Backend()
    cancelled = threading.Event()
    prepared = replace(backend.prepare_voice(str(ref), 'Words.', {}), cancel_event=cancelled)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0));listener.listen(1);listener.settimeout(5)
    port = listener.getsockname()[1]
    original = http.client.HTTPConnection
    monkeypatch.setattr(transport.http.client, 'HTTPConnection',
                        lambda host, ignored, timeout: original(host, port, timeout=timeout))
    import backends
    fallback = Mock()
    monkeypatch.setattr(backends, 'get', fallback)
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(backend.synthesize, 'Actual words.', prepared, 'en')
        connection, _ = listener.accept()
        try:
            connection.settimeout(2)
            assert connection.recv(65536)
            cancelled.set()
            with pytest.raises(transport.SynthesisCancelled):
                future.result(timeout=3)
            # Drain any request body already sent; peer must close without a reply.
            while connection.recv(65536):
                pass
            fallback.assert_not_called()
        finally:
            connection.close();listener.close()


def test_http_disconnect_waits_for_adapter_cancellation(monkeypatch):
    import threading
    import server
    from expressive.transport import SynthesisCancelled
    stopped = threading.Event()
    def synth(text, profile, lang, performance, cancelled):
        assert cancelled.wait(2)
        stopped.set()
        return server.Response(status_code=499)
    monkeypatch.setattr(server, '_synthesize_audio', synth)
    class Disconnected:
        async def is_disconnected(self): return True
    response = asyncio.run(server._synthesize_for_request(
        Disconnected(), 'Hello.', SimpleNamespace(backend='fish-drama3'), 'en', None))
    assert response.status_code == 499
    assert stopped.is_set()


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_disconnect_through_real_http_middleware(monkeypatch, method):
    import threading
    import server
    started = threading.Event()
    stopped = threading.Event()
    def synth(text, profile, lang, performance, cancelled):
        started.set()
        if cancelled.wait(2):
            stopped.set()
        return server.Response(status_code=499)
    monkeypatch.setattr(server, '_synthesize_audio', synth)
    monkeypatch.setattr(server, '_ready', SimpleNamespace(is_set=lambda: True))
    monkeypatch.setattr(server, '_clone_enabled', True)
    monkeypatch.setattr(server, '_resolve_voice', lambda name, **kw: SimpleNamespace(backend='fish-drama3'))
    async def run():
        incoming = asyncio.Queue()
        body = json.dumps({'text': 'Hello.', 'voice': 'test'}).encode() if method == 'POST' else b''
        await incoming.put({'type': 'http.request', 'body': body, 'more_body': False})
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                 'method': method, 'scheme': 'http', 'path': '/synthesize',
                 'raw_path': b'/synthesize', 'query_string': b'text=Hello.&voice=test',
                 'headers': [(b'host', b'127.0.0.1'), (b'content-type', b'application/json')],
                 'client': ('127.0.0.1', 1234), 'server': ('127.0.0.1', 7862)}
        async def send(message): pass
        task = asyncio.create_task(server.app(scope, incoming.get, send))
        assert await asyncio.to_thread(started.wait, 1)
        await incoming.put({'type': 'http.disconnect'})
        await asyncio.wait_for(task, 3)
    asyncio.run(run())
    assert stopped.is_set(), 'middleware must deliver disconnect to the synthesis owner'


def test_cancel_during_main_queue_wait_does_not_take_active_lock():
    import concurrent.futures
    import threading
    import server
    from expressive.transport import SynthesisCancelled
    cancelled = threading.Event()
    def queued():
        with server._synthesis_admission('fish-drama3', cancelled):
            pytest.fail('cancelled request entered synthesis')
    with server._synth_lock:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(queued)
            cancelled.set()
            with pytest.raises(SynthesisCancelled):
                future.result(timeout=2)
        assert server._synth_lock.locked()


@pytest.mark.parametrize('status', [200, 400, 503])
def test_cancellable_transport_preserves_audio_and_http_errors(monkeypatch, status):
    import http.client
    import http.server
    import threading
    import urllib.error
    from expressive import transport
    wav = io.BytesIO()
    sf.write(wav, np.full(4410, .2), 44100, format='WAV', subtype='PCM_16')
    payload = wav.getvalue()
    seen = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(status)
            self.send_header('Content-Type', 'audio/wav')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers();self.wfile.write(payload)
        def log_message(self, *args): pass
    httpd = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.handle_request)
    thread.start()
    original = http.client.HTTPConnection
    monkeypatch.setattr(transport.http.client, 'HTTPConnection',
                        lambda host, ignored, timeout: original(host, httpd.server_port, timeout=timeout))
    try:
        if status == 200:
            assert transport.request_wav(b'{"text":"Hello"}', threading.Event()) == payload
        else:
            with pytest.raises(urllib.error.HTTPError) as error:
                transport.request_wav(b'{"text":"Hello"}', threading.Event())
            assert error.value.code == status
        assert seen == [b'{"text":"Hello"}']
    finally:
        thread.join(timeout=3);httpd.server_close()


def test_http_admission_rejects_before_thread_submission(monkeypatch):
    import threading
    import server
    slots = threading.BoundedSemaphore(1)
    slots.acquire()
    monkeypatch.setattr(server, '_expressive_http_slots', slots)
    worker = Mock(side_effect=AssertionError('must not enqueue synthesis'))
    monkeypatch.setattr(server, '_synthesize_audio', worker)
    result = asyncio.run(server._synthesize_for_request(
        None, 'Hello.', SimpleNamespace(backend='fish-drama3'), 'en', None))
    assert result.status_code == 503
    worker.assert_not_called()
