"""Follow completed OpenCode v2 assistant messages, retaining unfinished rows."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from watcher.state import load, lock, save, state_root
from watcher.queue import resume


def poll(db: Path, state: dict, deliver) -> None:
    with sqlite3.connect(f'{db.as_uri()}?mode=ro', uri=True) as con:
        rows = con.execute("SELECT m.id, m.session_id, m.data, s.directory "
            "FROM session_message m JOIN session_v2 s ON s.id=m.session_id "
            "WHERE m.type='assistant' ORDER BY m.rowid").fetchall()
    if 'seen' not in state:
        # Historical completed messages are baselined, unfinished messages are
        # retained so the first post-install completion is delivered.
        state['seen'] = [mid for mid, _, raw, _ in rows
                         if (json.loads(raw).get('time') or {}).get('completed')]
        return
    seen = set(state['seen'])
    for mid, session, raw, cwd in rows:
        if mid in seen:
            continue
        data = json.loads(raw)
        if not (data.get('time') or {}).get('completed'):
            continue
        text = ' '.join(part.get('text', '') for part in data.get('content', [])
                        if part.get('type') == 'text' and not part.get('synthetic'))
        if text.strip():
            deliver(session, mid, cwd, text)
        state['seen'].append(mid)
        seen.add(mid)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--db', type=Path, default=Path.home() / '.local/share/opencode/opencode.db')
    args = parser.parse_args()
    root = state_root()
    ownership = lock(root / 'opencode.lock')
    state_path = root / 'opencode.json'
    state = load(state_path)
    def deliver(session, mid, cwd, text):
        subprocess.run(['bash', str(REPO / 'opencode/tts-hook-opencode.sh'),
                        session, mid, cwd], input=text, text=True, check=True,
                       timeout=60, env=dict(os.environ, AFTERWORDS_WATCH_STATE=str(root)))
    while True:
        resume(root, 'opencode')
        try:
            poll(args.db.resolve(), state, deliver)
            save(state_path, state)
        except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
            print(f'opencode watcher: {type(error).__name__}', file=sys.stderr, flush=True)
        if args.once:
            return 0
        time.sleep(2)
    ownership.close()


if __name__ == '__main__':
    raise SystemExit(main())
