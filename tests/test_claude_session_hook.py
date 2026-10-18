import json

from claude_session_hook import event


def transcript(path, *records):
    path.write_text(''.join(json.dumps(record) + '\n' for record in records))
    return str(path)


def test_stop_event_uses_matching_transcript_uuid_and_stable_identity(tmp_path):
    path = tmp_path / 'session.jsonl'
    transcript(path,
        {'type': 'assistant', 'uuid': 'assistant-1',
         'message': {'content': [{'type': 'text', 'text': 'Final answer.'}]}},
        {'type': 'user', 'uuid': 'user-1', 'message': {'content': 'ignored'}},
    )
    payload = {'hook_event_name': 'Stop', 'session_id': 'session-1',
               'transcript_path': str(path), 'cwd': '/project',
               'last_assistant_message': ' Final   answer. '}

    first = event(payload)
    second = event(payload)

    assert first == second
    assert first['session'] == 'session-1'
    assert first['event_id'].startswith('Stop:claude:assistant-1:')
    assert first['text'] == ' Final   answer. '


def test_subagent_stop_uses_agent_transcript_and_agent_voice_key(tmp_path):
    path = tmp_path / 'agent.jsonl'
    transcript(path, {'type': 'assistant', 'uuid': 'agent-uuid',
                      'message': {'content': 'Subagent response.'}})

    result = event({'hook_event_name': 'SubagentStop', 'session_id': 'session-2',
                    'agent_transcript_path': str(path), 'transcript_path': 'ignored',
                    'cwd': '/project', 'agent_type': 'feature-dev:code-architect',
                    'last_assistant_message': 'Subagent response.'})

    assert result['event_id'].startswith('SubagentStop:feature-dev:code-architect:agent-uuid:')
    assert result['voice_agent'] == 'feature-dev:code-architect'
    assert result['project'] == '/project'


def test_event_defers_without_transcript_occurrence_identity(tmp_path):
    payload = {'hook_event_name': 'Stop', 'session_id': 'session-3',
               'cwd': '/project', 'transcript_path': str(tmp_path / 'missing.jsonl'),
               'last_assistant_message': 'A response.'}

    first = event(payload)
    second = event(payload)

    assert first is None
    assert second is None


def test_event_ignores_empty_text_and_active_stop_hook():
    assert event({'last_assistant_message': '  '}) is None
    assert event({'hook_event_name': 'Stop', 'stop_hook_active': True,
                  'last_assistant_message': 'Do not recurse.'}) is None


def test_builtin_subagents_never_publish_speech():
    for agent in ('Explore', 'Plan', 'general-purpose'):
        assert event({'hook_event_name': 'SubagentStop', 'agent_type': agent,
                      'last_assistant_message': 'Internal result repeated by the parent.'}) is None


def test_identical_claude_replies_have_distinct_occurrence_ids(tmp_path):
    path = tmp_path/'session.jsonl'
    payload = {'session_id': 'same-session', 'transcript_path': str(path),
               'last_assistant_message': 'Done.'}
    assert event(payload) is None
    transcript(path, {'type': 'assistant', 'uuid': 'first', 'message': {'content': 'Done.'}})
    first = event(payload)
    assert event(payload) == first
    transcript(path, {'type': 'assistant', 'uuid': 'second', 'message': {'content': 'Done.'}})
    second = event(payload)
    assert first['event_id'] != second['event_id']
    assert event(payload) == second


def test_hook_retries_transcript_write_lag(tmp_path, monkeypatch, capsys):
    import io
    import claude_session_hook as hook
    path = tmp_path/'late.jsonl'
    payload = {'session_id':'session', 'transcript_path':str(path),
               'last_assistant_message':'Done.'}
    monkeypatch.setattr(hook.sys, 'stdin', io.StringIO(json.dumps(payload)))
    def flush_transcript(_):
        transcript(path, {'type':'assistant', 'uuid':'late', 'message':{'content':'Done.'}})
    monkeypatch.setattr(hook.time, 'sleep', flush_transcript)
    assert hook.main() == 0
    assert json.loads(capsys.readouterr().out)['event_id'].startswith('Stop:claude:late:')
