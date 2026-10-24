"""Diagnostics validate the command actually registered, not a nearby copy."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest
from watcher.manage import FILES

ROOT = Path(__file__).resolve().parents[1]


def status_module(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('integration_status', ROOT/'scripts/integrations-status.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runtime = tmp_path/'Library/Application Support/Afterwords/watchers/runtime'
    for relative in FILES:
        target = runtime/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/relative, target)
    monkeypatch.setattr(module, 'HOME', tmp_path)
    monkeypatch.setattr(module, 'RUNTIME', runtime)
    monkeypatch.setattr(module.shutil, 'which', lambda name: None)
    reports = []
    monkeypatch.setattr(module, 'report', lambda name,state,detail='': reports.append((name,state)))
    return module, runtime, reports


@pytest.mark.parametrize('agent', ['claude', 'agy'])
@pytest.mark.parametrize('shape', ['managed', 'managed-with-unrelated-mentions', 'legacy', 'repository', 'mixed', 'echo', 'wrong-event', 'missing-chunker'])
def test_managed_hook_status_requires_actual_runtime_target(tmp_path, monkeypatch, agent, shape):
    module, runtime, reports = status_module(tmp_path, monkeypatch)
    filename = f'{agent}-tts-hook.sh'
    command = f'AFTERWORDS_PYTHON="/configured/python" bash "{runtime/".claude/hooks"/filename}"'
    if shape == 'legacy': command = f'bash ~/.claude/hooks/{filename}'
    elif shape == 'repository': command = f'bash "{ROOT/".claude/hooks"/filename}"'
    elif shape == 'echo': command = 'echo '+command
    hooks = [{'type':'command','command':command}]
    if shape == 'managed-with-unrelated-mentions':
        hooks += [{'type':'command','command':f'echo {filename}'},
                  {'type':'command','command':f'bash /separate/owner/{filename}'},
                  {'type':'prompt','command':command}]
    if shape == 'mixed': hooks += [{'type':'command','command':f'bash ~/.claude/hooks/{filename}'}]
    if shape == 'missing-chunker': (runtime/'chunks.py').unlink()
    if agent == 'claude':
        path = tmp_path/'.claude/settings.json'
        events = {'Stop':[{'hooks':hooks}], 'SubagentStop':[{'hooks':hooks}]}
        if shape == 'wrong-event': events = {'AfterAgent':[{'hooks':hooks}]}
        data = {'hooks':events}
        name = 'Claude Code'
    else:
        path = tmp_path/'.gemini/config/hooks.json'
        data = {'afterwords-tts':{'AfterAgent' if shape=='wrong-event' else 'Stop':hooks}}
        name = 'Antigravity'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    module.main()
    assert (name, 'OK' if shape in ('managed','managed-with-unrelated-mentions') else 'MISSING') in reports


def test_unrelated_hooks_do_not_invalidate_the_managed_target(tmp_path, monkeypatch):
    module, runtime, reports = status_module(tmp_path, monkeypatch)
    command = f'env AFTERWORDS_PYTHON=/configured/python /bin/bash "{runtime/".claude/hooks/claude-tts-hook.sh"}"'
    hooks = [{'hooks':[{'type':'command','command':command}, {'type':'command','command':'echo unrelated'}]}]
    path = tmp_path/'.claude/settings.json'
    path.parent.mkdir()
    path.write_text(json.dumps({'hooks':{'Stop':hooks,'SubagentStop':hooks}}))
    module.main()
    assert ('Claude Code','OK') in reports


@pytest.mark.parametrize('agent,event_name,name', [
    ('gemini','AfterAgent','Gemini CLI'), ('cursor','afterAgentResponse','Cursor')])
@pytest.mark.parametrize('shape', ['valid-with-mentions','echo-only','wrong-event'])
def test_adapter_status_uses_actual_target_on_correct_event(tmp_path,monkeypatch,agent,event_name,name,shape):
    module,runtime,reports = status_module(tmp_path,monkeypatch)
    adapter = tmp_path/f'.claude/hooks/{agent}-tts-hook.sh'
    adapter.parent.mkdir(parents=True,exist_ok=True);adapter.write_text('fixture')
    hooks = [{'type':'command','command':f'echo {adapter.name}'},
             {'type':'command','command':f'bash /separate/owner/{adapter.name}'}]
    if shape != 'echo-only':
        hooks += [{'type':'command','command':f'bash ~/.claude/hooks/{adapter.name}'}]
    event = 'OtherEvent' if shape == 'wrong-event' else event_name
    path = tmp_path/('.gemini/settings.json' if agent=='gemini' else '.cursor/hooks.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'hooks':{event:hooks}}))
    module.main()
    expected = 'OK' if shape=='valid-with-mentions' else ('MANUAL' if agent=='gemini' else 'MISSING')
    assert (name,expected) in reports
