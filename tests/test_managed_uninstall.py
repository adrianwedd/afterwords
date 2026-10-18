"""Exercise uninstall against disposable settings/LaunchAgents and a fake controller."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


def environment(tmp_path):
    repo, home, bindir = tmp_path/'repo', tmp_path/'home', tmp_path/'bin'
    for p in (repo/'scripts',repo/'watcher',home,bindir): p.mkdir(parents=True,exist_ok=True)
    for rel in ('afterwords.sh','scripts/remove-integrations.py','watcher/manage.py'):
        shutil.copy2(ROOT/rel,repo/rel)
    (bindir/'afterwords').symlink_to(repo/'afterwords.sh')
    (bindir/'lsof').write_text('#!/bin/bash\nexit 0\n')
    log = tmp_path/'launchctl.jsonl'
    (bindir/'launchctl').write_text(f'#!{sys.executable}\n'
        'import sys,os,json\nfrom pathlib import Path\n'
        f'with open({str(log)!r},"a") as stream: stream.write(json.dumps(sys.argv[1:])+"\\n")\n'
        'if sys.argv[1]=="print":\n'
        ' label=sys.argv[2].rsplit("/",1)[-1]\n'
        ' raise SystemExit(0 if (Path(os.environ["HOME"])/"Library/LaunchAgents"/(label+".plist")).exists() else 1)\n')
    for p in (bindir/'lsof',bindir/'launchctl'): p.chmod(0o755)
    runtime = home/'Library/Application Support/Afterwords/watchers/runtime'
    owned = f'AFTERWORDS_PYTHON="/configured/python" bash "{runtime/".claude/hooks/claude-tts-hook.sh"}"'
    agy = f'bash "{runtime/".claude/hooks/agy-tts-hook.sh"}"'
    unrelated = {'type':'command','command':'echo unrelated claude-tts-hook.sh'}
    settings = {
        '.claude/settings.json':{'other':'keep','hooks':{
            'Stop':[{'hooks':[{'type':'command','command':owned},unrelated]}],
            'SubagentStop':[{'hooks':[{'type':'command','command':owned}]}]}},
        '.gemini/config/hooks.json':{'other-owner':{'Stop':[unrelated]},'afterwords-tts':{'Stop':[{'type':'command','command':agy}]}},
        '.gemini/settings.json':{'other':'keep','hooks':{'AfterAgent':[{'hooks':[{'type':'command','command':'bash ~/.claude/hooks/gemini-tts-hook.sh'},unrelated]}]}},
        '.cursor/hooks.json':{'version':1,'hooks':{'afterAgentResponse':[{'type':'command','command':'bash ~/.claude/hooks/cursor-tts-hook.sh'},unrelated]}},
    }
    for rel,data in settings.items():
        p=home/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(data));p.chmod(0o600)
    plists = home/'Library/LaunchAgents';plists.mkdir(parents=True)
    server = plists/'com.afterwords.tts-server.plist';server.write_text('fixture')
    for agent in ('codex','opencode'):(plists/f'au.wedd.afterwords-{agent}-watch.plist').write_text('fixture')
    state = home/'Library/Application Support/Afterwords/watchers/queues/test'
    state.mkdir(parents=True);(state/'event.playing').write_text('retained terminal receipt')
    (runtime/'source').parent.mkdir(parents=True);(runtime/'source').write_text('retained runtime')
    env={**os.environ,'HOME':str(home),'PATH':str(bindir)+':'+os.environ['PATH'],
         'AFTERWORDS_PYTHON':sys.executable,'AFTERWORDS_PLIST_PATH':str(server)}
    return repo,home,env,settings,log


@pytest.mark.parametrize('consent',[True,False])
def test_uninstall_respects_consent_and_removes_only_owned_integrations(tmp_path,consent):
    repo,home,env,settings,log=environment(tmp_path)
    result=subprocess.run(['bash',str(repo/'afterwords.sh'),'uninstall'],input='y\n' if consent else 'n\n',
                          capture_output=True,text=True,env=env,timeout=15)
    assert result.returncode==0,result.stderr
    assert 'server and CLI uninstalled' in result.stdout
    for rel,original in settings.items():
        value=json.loads((home/rel).read_text())
        assert (home/rel).stat().st_mode & 0o777 == 0o600
        if not consent: assert value==original
        else:
            if rel == '.gemini/config/hooks.json':
                assert value['other-owner'] == original['other-owner']
            else:
                assert 'echo unrelated claude-tts-hook.sh' in json.dumps(value)
            for marker in ('/runtime/.claude/hooks/claude-tts-hook.sh','/runtime/.claude/hooks/agy-tts-hook.sh',
                           'bash ~/.claude/hooks/gemini-tts-hook.sh','bash ~/.claude/hooks/cursor-tts-hook.sh'):
                assert marker not in json.dumps(value)
    for agent in ('codex','opencode'):
        assert (home/f'Library/LaunchAgents/au.wedd.afterwords-{agent}-watch.plist').exists() != consent
    calls=[json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    assert len([call for call in calls if call[0]=='bootout']) == (2 if consent else 0)
    assert (home/'Library/Application Support/Afterwords/watchers/queues/test/event.playing').read_text()=='retained terminal receipt'
    assert (home/'Library/Application Support/Afterwords/watchers/runtime/source').read_text()=='retained runtime'


def test_registration_removal_aborts_on_concurrent_edit(tmp_path):
    repo,home,env,settings,log=environment(tmp_path)
    spec=importlib.util.spec_from_file_location('remove_integrations',repo/'scripts/remove-integrations.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    plans=module.plans(home,repo)
    path=plans[0][0];path.write_text('{"new_owner_edit":true}')
    with pytest.raises(ValueError,match='settings changed'):
        module.apply_plans(plans)
    assert json.loads(path.read_text())=={'new_owner_edit':True}
