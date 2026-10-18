"""Loopback-only full-audio service with an isolated, cancellable MLX worker.

Run: .venv-drama3/bin/python -m expressive.sidecar
The public contract remains complete WAV audio; internal chunks are not played.
"""
import asyncio
import base64
import io
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response
from expressive.contracts import MODEL, REVISION, SOURCE_REVISION, validate_options, directed_text


class WorkerPool:
    def __init__(self, command=None, capacity=4, timeout=180):
        self.command = command or [sys.executable, '-u', '-m', 'expressive.worker']
        self.capacity = capacity
        self.timeout = timeout
        self.pending = 0
        self.lock = asyncio.Lock()
        self.process = None

    async def stop(self):
        process, self.process = self.process, None
        if process is not None and process.returncode is None:
            process.kill()
            await process.wait()

    async def _run(self, payload):
        if self.process is None or self.process.returncode is not None:
            import psutil
            if psutil.virtual_memory().available < 64 * 1024**3:
                raise RuntimeError('insufficient memory headroom for Drama 3 worker')
            self.process = await asyncio.create_subprocess_exec(
                *self.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                cwd=Path(__file__).resolve().parents[1], limit=4 * 1024**2,
                env={**os.environ, 'HF_HUB_OFFLINE': '1'})
        process = self.process
        process.stdin.write(json.dumps(payload).encode() + b'\n')
        await process.stdin.drain()
        chunks = []
        samples = 0
        while True:
            line = await process.stdout.readline()
            if not line:
                raise RuntimeError('expressive worker exited before completion')
            event = json.loads(line)
            if event['kind'] == 'error':
                raise RuntimeError(event['error'])
            if event['kind'] == 'chunk':
                if event['sample_rate'] != 44100:
                    raise RuntimeError('unexpected sample rate')
                chunk = np.frombuffer(base64.b64decode(event['audio'], validate=True), dtype='<f4')
                if not np.isfinite(chunk).all():
                    raise RuntimeError('nonfinite audio')
                chunks.append(chunk)
                samples += len(chunk)
                if samples > 44100 * 300:
                    raise RuntimeError('audio output exceeds limit')
            elif event['kind'] == 'done':
                if not samples or event['samples'] != samples or event['sample_rate'] != 44100:
                    raise RuntimeError('incomplete audio output')
                from expressive.audio_audit import validate_delivery
                audio = np.concatenate(chunks)
                measurement = validate_delivery(audio, 44100)
                event['longest_silence_seconds'] = measurement['longest_silence_seconds']
                output = io.BytesIO()
                sf.write(output, audio, 44100, format='WAV', subtype='PCM_16')
                return output.getvalue(), event
            else:
                raise RuntimeError('unexpected worker event')

    async def synthesize(self, payload):
        # Runs on one event loop; admission and increment have no intervening await.
        if self.pending >= self.capacity:
            raise HTTPException(429, 'expressive synthesis queue full')
        self.pending += 1
        try:
            async with asyncio.timeout(self.timeout):
                async with self.lock:
                    try:
                        return await self._run(payload)
                    except BaseException:
                        # Cancellation must finish killing this worker before another
                        # request obtains the lock. A timeout never leaves GPU work alive.
                        await self.stop()
                        raise
        finally:
            self.pending -= 1


pool = WorkerPool()


@asynccontextmanager
async def lifespan(app):
    yield
    await pool.stop()


app = FastAPI(lifespan=lifespan)


@app.get('/health')
async def health():
    return dict(service='afterwords-expressive', model=MODEL, revision=REVISION,
                source_revision=SOURCE_REVISION, pending=pool.pending, capacity=pool.capacity,
                worker_alive=pool.process is not None and pool.process.returncode is None,
                contract='complete-wav', native_model_streaming=True)


@app.post('/release')
async def release(request: Request):
    from expressive.auth import authenticate_request
    authenticate_request(request)
    if pool.pending:
        raise HTTPException(409, 'requests active; refusing to interrupt synthesis')
    async with pool.lock:
        # Recheck after acquiring the lock: admission may have changed.
        if pool.pending:
            raise HTTPException(409, 'requests active; refusing to interrupt synthesis')
        await pool.stop()
    return {'released': True}


@app.post('/synthesize')
async def synthesize(request: Request):
    from expressive.auth import authenticate_request
    authenticate_request(request)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 6 * 1024**2:
            raise HTTPException(413, 'request too large')
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict) or set(payload) - {'text', 'reference_wav', 'reference_text', 'performance'}:
            raise ValueError('unsupported request fields')
        options = validate_options(payload.get('performance', {}))
        directed_text(payload['text'], options)
        if not isinstance(payload.get('reference_wav'), str) or not isinstance(payload.get('reference_text'), str):
            raise ValueError('reference WAV and transcript required')
        if not 1 <= len(payload['reference_text']) <= 8000:
            raise ValueError('reference transcript length invalid')
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    task = asyncio.create_task(pool.synthesize(payload))
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=0.1)
            if done:
                break
            if await request.is_disconnected():
                task.cancel()
                raise HTTPException(499, 'client disconnected')
        audio, metrics = await task
        return Response(audio, media_type='audio/wav', headers={
            'X-Afterwords-Backend': 'fish-drama3',
            'X-Afterwords-Metrics': json.dumps(metrics, separators=(',', ':'))})
    except TimeoutError as exc:
        raise HTTPException(504, 'expressive synthesis deadline exceeded') from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=7861)
