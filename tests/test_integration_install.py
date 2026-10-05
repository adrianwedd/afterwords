"""Exercise hook installation for each detected agent in a disposable HOME."""
import json
import os
from pathlib import Path
import shlex
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('agent', ['claude', 'cursor', 'gemini', 'agy', 'none'])
def test_shared_hook_install_with_one_agent(tmp_path, agent):
    source = (REPO / 'setup.sh').read_text()
    start = source.index('# Shared hook installation')
    end = source.index('fi  # end shared hooks block', start) + len('fi  # end shared hooks block')
    block = source[start:end]
    sections = {
        'cursor': ('# ── Cursor IDE discovery', '# ── Afterwords menubar app'),
        'gemini': ('# ── Gemini CLI discovery', '# ── Antigravity'),
        'agy': ('# ── Antigravity', '# ── Cursor IDE discovery'),
    }
    if agent in sections:
        first, last = sections[agent]
        section_start = source.index(first)
        section_end = source.index(last, section_start)
        block += '\n' + source[section_start:section_end]
    script = '''
set -euo pipefail
info() { :; }
ok() { :; }
next_step() { :; }
rule() { :; }
warn() { :; }
CYAN=; NC=; BOLD=; DIM=
command() {
    if [ "${1:-}" = -v ] && { [ "${2:-}" = gemini ] || [ "${2:-}" = agy ]; }; then
        [ "$2" = "$TEST_AGENT" ]; return $?
    fi
    builtin command "$@"
}
'''
    script += f'HOME={shlex.quote(str(tmp_path))}\nSCRIPT_DIR={shlex.quote(str(REPO))}\n'
    script += f'HAS_CLAUDE={str(agent == "claude").lower()}\nHAS_CURSOR={str(agent == "cursor").lower()}\nSERVER_ONLY=false\n'
    result = subprocess.run(['bash', '-c', script + block],
                            env={**os.environ, 'TEST_AGENT': agent}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    hooks = tmp_path / '.claude/hooks'
    if agent == 'none':
        assert not hooks.exists()
        return
    for helper in ['tts-worker.sh', 'tts-hook.sh', 'strip-markdown.py', 'chunk-text.py',
                   'summarize-for-tts.py', f'{agent}-tts-hook.sh' if agent != 'claude' else 'tts-hook.sh']:
        assert (hooks / helper).is_file(), helper
    if agent == 'cursor':
        config = json.loads((tmp_path / '.cursor/hooks.json').read_text())
        assert config['hooks']['afterAgentResponse'][0]['command'].endswith('cursor-tts-hook.sh')
    if agent == 'agy':
        config = json.loads((tmp_path / '.gemini/config/hooks.json').read_text())
        assert config['afterwords-tts']['Stop'][0]['command'].endswith('agy-tts-hook.sh')
    if agent == 'gemini':
        assert not (tmp_path / '.gemini/settings.json').exists()
        assert 'AfterAgent' in result.stdout
    settings = tmp_path / '.claude/settings.json'
    assert settings.exists() is (agent == 'claude')
    result = subprocess.run(['python3', str(hooks / 'chunk-text.py')],
                            input='One sentence. Another sentence.', text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert 'One sentence.' in result.stdout
