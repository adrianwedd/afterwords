"""Follow complete Codex JSONL records using session metadata and durable offsets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from codex_session_hook import extract_final_text
from watcher.state import load, lock, save, state_root
from watcher.queue import resume


def poll(path: Path, state: dict, deliver, *, fresh: bool = False) -> None:
    """Consume only newline-terminated records; incomplete bytes stay on disk.

    First installation skips old history but retains a trailing partial record.
    Once enrolled, files are followed across downtime without mtime cutoffs.
    """
    key = str(path)
    stat = path.stat()
    entry = state.get(key)
    if entry is None:
        entry = {'offset': 0, 'session': '', 'cwd': '', 'inode': stat.st_ino,
                 'generation': 0}
        state[key] = entry
    if stat.st_ino != entry['inode'] or stat.st_size < entry['offset']:
        entry.update(offset=0, session='', cwd='', inode=stat.st_ino,
                     generation=entry['generation'] + 1)
    with path.open('rb') as stream:
        stream.seek(entry['offset'])
        while True:
            start = stream.tell()
            line = stream.readline()
            if not line.endswith(b'\n'):
                break
            event = json.loads(line)
            if event.get('type') == 'session_meta':
                payload = event.get('payload') or {}
                entry['session'] = payload.get('id', '')
                entry['cwd'] = payload.get('cwd', '')
            text = extract_final_text(line.decode('utf-8'))
            if text and not fresh:
                if not entry['session']:
                    raise ValueError('final answer has no session_meta identity')
                # Record identity distinguishes identical answers at different
                # positions; rename/reopen still retains the session identity.
                event_id = f"{entry['session']}:{entry['generation']}:{start}:" + hashlib.sha256(line).hexdigest()
                deliver(entry['session'], event_id, entry['cwd'], text)
            entry['offset'] = stream.tell()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--sessions', type=Path, default=Path.home() / '.codex/sessions')
    args = parser.parse_args()
    root = state_root()
    ownership = lock(root / 'codex.lock')
    state_path = root / 'codex.json'
    state = load(state_path)
    initialized = state.pop('_initialized', False)
    hook = REPO / '.claude/hooks/codex-tts-hook.sh'
    def deliver(session, event_id, cwd, text):
        env = dict(os.environ, CODEX_THREAD_ID=session, PROJECT_DIR=cwd,
                   AGENT_TYPE='codex', AFTERWORDS_EVENT_ID=event_id,
                   AFTERWORDS_WATCH_STATE=str(root))
        event = {'type': 'response_item', 'payload': {'type': 'message',
            'role': 'assistant', 'phase': 'final_answer',
            'content': [{'type': 'output_text', 'text': text}]}}
        subprocess.run(['bash', str(hook)], input=json.dumps(event),
                       text=True, env=env, check=True, timeout=60)
    while True:
        resume(root, 'codex')
        for path in sorted(args.sessions.glob('*/*/*/rollout-*.jsonl')):
            try:
                poll(path, state, deliver, fresh=not initialized and str(path) not in state)
                save(state_path, {**state, '_initialized': initialized})
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f'codex watcher: {type(error).__name__}', file=sys.stderr, flush=True)
        initialized = True
        save(state_path, {**state, '_initialized': True})
        if args.once:
            return 0
        time.sleep(2)
    ownership.close()


if __name__ == '__main__':
    raise SystemExit(main())
