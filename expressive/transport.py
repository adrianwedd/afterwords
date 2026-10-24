"""Cancellable loopback transport for the complete-audio adapter contract."""
import http.client
import io
import socket
import threading
import urllib.error


class SynthesisCancelled(Exception):
    """Explicit cancellation must never become a fallback synthesis request."""


def request_wav(payload, cancelled):
    from expressive.auth import authorization_headers
    headers = {'Content-Type': 'application/json', **authorization_headers()}
    connection = http.client.HTTPConnection('127.0.0.1', 7861, timeout=185)
    finished = threading.Event()

    def watch():
        while not finished.wait(.05):
            if cancelled.is_set():
                sock = connection.sock
                if sock is not None:
                    try:
                        sock.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                return

    watcher = threading.Thread(target=watch, name='expressive-disconnect', daemon=True)
    try:
        if cancelled.is_set():
            raise SynthesisCancelled()
        connection.connect()
        # Connect finishes before the watcher starts, so it cannot miss a socket.
        watcher.start()
        if cancelled.is_set():
            raise SynthesisCancelled()
        connection.request('POST', '/synthesize', body=payload,
                           headers=headers)
        response = connection.getresponse()
        if response.status != 200:
            # Keep the sidecar's diagnostic body. It used to be replaced with an
            # empty BytesIO, so every failure arrived upstream as "503:" with no
            # reason — the last place the evidence was being thrown away.
            detail = b''
            try:
                detail = response.read(2000)
            except (OSError, http.client.HTTPException):
                detail = b''
            raise urllib.error.HTTPError('http://127.0.0.1:7861/synthesize', response.status,
                                         response.reason, response.headers,
                                         io.BytesIO(detail))
        if response.headers.get_content_type() != 'audio/wav':
            raise RuntimeError('sidecar returned a non-WAV response')
        limit = 44100 * 300 * 2 + 65536
        raw = response.read(limit + 1)
        if len(raw) > limit:
            raise RuntimeError('sidecar output exceeds duration limit')
        if cancelled.is_set():
            raise SynthesisCancelled()
        return raw
    except Exception:
        if cancelled.is_set():
            raise SynthesisCancelled() from None
        raise
    finally:
        finished.set()
        connection.close()
        if watcher.ident is not None:
            watcher.join(timeout=1)
