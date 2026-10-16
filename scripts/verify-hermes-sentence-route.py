#!/usr/bin/env python3
"""Capture a real configured Hermes command-TTS sentence route without speaker playback.

Run inside the installed Hermes Python environment with HERMES_HOME explicitly
set. This checks artifact delivery and playback ownership, not a generated agent
reply, audibility, acting or the separate post-LLM hook.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--hermes-root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--text',default='The committee has reached a decision. We have decided to order more coffee.')
    a=p.parse_args()
    if a.out.exists():p.error('preserve previous attempts; output exists')
    home=os.environ.get('HERMES_HOME')
    if not home:p.error('set HERMES_HOME to the intended existing profile')
    config=Path(home)/'config.yaml'
    if not config.is_file():p.error('profile configuration does not exist')
    sys.path.insert(0,str(a.hermes_root.resolve()))
    from tools import tts_tool, voice_mode
    from tools.tts_tool_speaker import stream_tts_to_speaker
    c=tts_tool._load_tts_config()
    selected=c.get('provider')
    provider=c.get('providers',{}).get(selected,{})
    if selected!='afterwords' or provider.get('type')!='command':
        p.error('this smoke test requires the configured Afterwords command provider')
    a.out.mkdir(parents=True)
    out=a.out.resolve()
    before=hashlib.sha256(config.read_bytes()).hexdigest()
    receipt={'status':'incomplete','profile_home':str(Path(home).resolve()),
             'profile_config_sha256':before,'provider':selected,'voice':provider.get('voice'),
             'text':a.text,'text_sha256':hashlib.sha256(a.text.encode()).hexdigest(),
             'playback_owner_override':'hermes','physical_playback':False,
             'automatic_mute_flag_present':Path('/tmp/afterwords-muted').exists(),
             'scope':'native sentence pipeline with fixed test text; not an agent reply or post-LLM-hook test',
             'artifacts':[],'sentences':[]}
    started=time.perf_counter()
    def capture(path):
        src=Path(path)
        dest=out/f"sentence-{len(receipt['artifacts'])+1:02d}{src.suffix}"
        shutil.copyfile(src,dest)
        # Hermes may convert command-provider WAV to its preferred MP3 output.
        # Decode the actual artifact instead of assuming its container.
        decoded=out/f"sentence-{len(receipt['artifacts'])+1:02d}-decoded.wav"
        subprocess.run(['ffmpeg','-v','error','-i',str(dest),'-c:a','pcm_s16le',
                        str(decoded)],check=True,capture_output=True)
        with wave.open(str(decoded),'rb') as wav:
            info={'sample_rate':wav.getframerate(),'frames':wav.getnframes(),
                  'channels':wav.getnchannels(),'sample_width':wav.getsampwidth()}
            assert len(wav.readframes(info['frames']))==info['frames']*info['channels']*info['sample_width']
        assert info['frames']>0
        receipt['artifacts'].append(dict(path=dest.name,sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                                        decoded_path=decoded.name,decoded_sha256=hashlib.sha256(decoded.read_bytes()).hexdigest(),
                                        playback_call_seconds=time.perf_counter()-started,**info))
    original_play=voice_mode.play_audio_file
    original_path=os.environ.get('PATH','')
    original_owner=os.environ.get('AFTERWORDS_PLAYBACK_OWNER')
    try:
        with tempfile.TemporaryDirectory(prefix='afterwords-playback-probe-') as tmp:
            # Detect and suppress any provider-side playback. Native calls are
            # captured separately above, so an unnoticed double play fails.
            probe=Path(tmp)/'afplay'
            probe.write_text('#!/bin/sh\nprintf "provider playback\\n" >> "$AFTERWORDS_PLAYBACK_PROBE_LOG"\n')
            probe.chmod(0o700)
            os.environ['PATH']=str(probe.parent)+os.pathsep+original_path
            os.environ['AFTERWORDS_PLAYBACK_PROBE_LOG']=str(out/'provider-playback.log')
            os.environ['AFTERWORDS_PLAYBACK_OWNER']='hermes'
            voice_mode.play_audio_file=capture
            q=queue.Queue();q.put(a.text);q.put(None)
            stop=threading.Event();done=threading.Event()
            stream_tts_to_speaker(q,stop,done,display_callback=receipt['sentences'].append)
            receipt['done_event']=done.is_set()
            receipt['provider_playback_calls']=len((out/'provider-playback.log').read_text().splitlines()) if (out/'provider-playback.log').exists() else 0
            assert done.is_set() and receipt['sentences']
            assert len(receipt['artifacts'])==len(receipt['sentences']), 'missing or duplicated native playback calls'
            assert receipt['provider_playback_calls']==0, 'provider played a native-owned artifact'
            assert hashlib.sha256(config.read_bytes()).hexdigest()==before, 'profile configuration changed during test'
            receipt['status']='native_artifact_route_passed_not_acoustic_acceptance'
    except BaseException as exc:
        receipt['error']=f'{type(exc).__name__}: {exc}'
        raise
    finally:
        voice_mode.play_audio_file=original_play
        os.environ['PATH']=original_path
        if original_owner is None:os.environ.pop('AFTERWORDS_PLAYBACK_OWNER',None)
        else:os.environ['AFTERWORDS_PLAYBACK_OWNER']=original_owner
        os.environ.pop('AFTERWORDS_PLAYBACK_PROBE_LOG',None)
        receipt['wall_seconds']=time.perf_counter()-started
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps(receipt,indent=2))


if __name__=='__main__':main()
