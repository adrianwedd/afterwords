"""Build a stable, idempotent TTS event from a Claude Code Stop hook payload."""
from __future__ import annotations

import hashlib
import json
import sys
import unicodedata
from pathlib import Path


def _text_from_record(record: dict) -> str:
    message = record.get('message') or {}
    content = message.get('content', '')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(part.get('text', '') for part in content
                       if isinstance(part, dict) and part.get('type') == 'text')
    return ''


def _normal(text: str) -> str:
    return ' '.join(unicodedata.normalize('NFC', text).split())


def event(payload: dict) -> dict | None:
    text = payload.get('last_assistant_message')
    if not isinstance(text, str) or not text.strip():
        return None
    hook = payload.get('hook_event_name', 'Stop')
    if hook == 'SubagentStop' and payload.get('agent_type') in {'Explore', 'Plan', 'general-purpose'}:
        return None
    if hook == 'Stop' and payload.get('stop_hook_active'):
        return None

    session = str(payload.get('session_id') or '')
    transcript = payload.get('agent_transcript_path') if hook == 'SubagentStop' else None
    transcript = transcript or payload.get('transcript_path') or ''
    transcript_path = Path(transcript).expanduser() if transcript else None
    matched_uuid = ''
    last_assistant_uuid = ''
    if transcript_path and transcript_path.is_file():
        try:
            with transcript_path.open(encoding='utf-8') as stream:
                for line in reversed(stream.readlines()):
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if record.get('type') != 'assistant':
                        continue
                    message = record.get('message') or {}
                    record_text = _text_from_record(record)
                    if not record_text:
                        continue
                    last_assistant_uuid = str(record.get('uuid') or '')
                    if _normal(record_text) == _normal(text):
                        matched_uuid = last_assistant_uuid
                        break
        except OSError:
            pass

    identity = matched_uuid or last_assistant_uuid or hashlib.sha256(
        _normal(text).encode('utf-8')).hexdigest()
    content_hash = hashlib.sha256(_normal(text).encode('utf-8')).hexdigest()
    voice_agent = str(payload.get('agent_type') or 'claude')
    event_id = f'{hook}:{voice_agent}:{identity}:{content_hash}'
    return {'session': session or str(transcript_path or payload.get('cwd') or 'claude'),
            'event_id': event_id, 'project': str(payload.get('cwd') or ''),
            'text': text, 'voice_agent': voice_agent}


def main() -> int:
    try:
        result = event(json.load(sys.stdin))
    except (json.JSONDecodeError, OSError):
        return 0
    if result:
        json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
