"""The audition renderer must authenticate to the private expressive API.

With AFTERWORDS_REQUIRE_EXPRESSIVE_AUTH=1 every non-health route on 7862
rejects unauthenticated callers, so a renderer without the credential header
would record every voice as a failed take.
"""
import importlib.util
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'render_fish_audition', REPO / 'scripts/render-fish-audition.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)


class _Response:
    headers = {'X-Backend': 'fish-drama3', 'X-Duration': '1.5'}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b'RIFF' + b'\0' * 64


def test_synthesis_request_carries_the_private_credential(tmp_path, monkeypatch):
    token = tmp_path / 'token'
    token.write_text('a' * 43)
    os.chmod(token, 0o600)
    monkeypatch.setenv('AFTERWORDS_SIDECAR_TOKEN_FILE', str(token))
    seen = []
    monkeypatch.setattr(renderer.urllib.request, 'urlopen',
                        lambda request, timeout: seen.append(request) or _Response())
    result = renderer.synthesize('http://127.0.0.1:7862', 'fish-aster', 'Hello.',
                                 tmp_path / 'take.wav', timeout=5)
    assert result['backend'] == 'fish-drama3'
    assert seen[0].get_header('Authorization') == 'Bearer ' + 'a' * 43
