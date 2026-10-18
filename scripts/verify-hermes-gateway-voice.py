#!/usr/bin/env python3
"""Exercise installed gateway voice synthesis, capturing its adapter handoff locally.

Uses the real configured TTS provider and gateway routing/dedup methods. A
capture adapter replaces network delivery; no bot is started and no message is
sent. This is not proof of live Telegram receipt or acoustic acceptance.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hermes-root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--text', default='The biscuits have cleared committee review. I remain cautiously optimistic.')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('preserve prior attempts; output exists')
    home = Path(os.environ.get('HERMES_HOME', ''))
    if not home.is_absolute() or not (home / 'config.yaml').is_file():
        parser.error('set HERMES_HOME to the existing profile')
    sys.path.insert(0, str(args.hermes_root.resolve()))
    os.environ['_HERMES_GATEWAY'] = '1'
    # Deliberately omit the platform marker, as post-handler auto-TTS does.
    os.environ.pop('HERMES_SESSION_PLATFORM', None)
    from gateway.authz_mixin import GatewayAuthorizationMixin
    from gateway.run_voice import GatewayVoiceMixin
    from gateway.config import Platform
    from gateway.session import SessionSource
    from gateway.platforms.event import MessageEvent, MessageType
    from gateway.platforms.base import _reply_anchor_for_event as reply_anchor, _thread_metadata_for_source as thread_metadata
    from tools.tts_tool import _load_tts_config
    config = _load_tts_config()
    provider = config.get('providers', {}).get(config.get('provider'), {})
    if config.get('provider') != 'afterwords' or provider.get('type') != 'command':
        parser.error('configured Afterwords command provider required')
    args.out.mkdir(parents=True)
    profile = home.name
    receipt = {'status': 'incomplete', 'scope': 'installed gateway methods with captured adapter handoff',
               'external_messages_sent': 0, 'profile': profile, 'voice': provider.get('voice'),
               'text': args.text, 'text_sha256': hashlib.sha256(args.text.encode()).hexdigest(),
               'artifacts': [], 'acoustic_acceptance': 'unverified'}
    started = time.perf_counter()

    class CaptureAdapter:
        platform = Platform.TELEGRAM
        _owner_profile = profile
        def _should_auto_tts_for_chat(self, chat_id):
            return True
        async def send_voice(self, *, chat_id, audio_path, reply_to, metadata):
            assert chat_id == 'synthetic-local-capture' and reply_to == 'probe-message'
            assert metadata['notify'] is True
            dest = args.out / ('gateway-voice' + Path(audio_path).suffix)
            assert not dest.exists(), 'duplicate gateway handoff'
            shutil.copyfile(audio_path, dest)
            result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                                     'stream=codec_name,sample_rate,channels:format=duration',
                                     '-of', 'json', str(dest)], check=True, capture_output=True, text=True)
            info = json.loads(result.stdout)
            assert info['streams'][0]['codec_name'] == 'opus'
            receipt['artifacts'].append({'path': dest.name, 'sha256': hashlib.sha256(dest.read_bytes()).hexdigest(),
                                         'format': info, 'owner_profile': profile})

    class DefaultAdapter:
        async def send_voice(self, **kwargs):
            raise AssertionError('Vixen audio must not use the default bot')

    class Runner(GatewayVoiceMixin, GatewayAuthorizationMixin):
        _reply_anchor_for_event = staticmethod(reply_anchor)
        _thread_metadata_for_source = staticmethod(thread_metadata)

    runner = Runner()
    adapter = CaptureAdapter()
    runner.adapters = {Platform.TELEGRAM: DefaultAdapter()}
    runner._profile_adapters = {profile: {Platform.TELEGRAM: adapter}}
    runner._primary_profile_name = 'default'
    runner.config = SimpleNamespace(multiplex_profiles=True, profile_routes=[])
    runner._voice_mode = {}
    source = SessionSource(platform=Platform.TELEGRAM, chat_id='synthetic-local-capture', profile=profile)
    event = MessageEvent(text='synthetic input', source=source, message_id='probe-message', message_type=MessageType.TEXT)
    history = [{'role': 'user', 'content': 'synthetic input'}]
    try:
        assert runner._delivery_adapter_for(source) is adapter
        assert runner._should_send_voice_reply(event, args.text, history)
        asyncio.run(asyncio.wait_for(runner._send_voice_reply(event, args.text), timeout=180))
        assert len(receipt['artifacts']) == 1
        already_spoken = history + [{'role': 'assistant', 'tool_calls': [{'function': {'name': 'text_to_speech'}}]}]
        assert not runner._should_send_voice_reply(event, args.text, already_spoken)
        runner._profile_adapters[profile] = {}
        assert runner._delivery_adapter_for(source) is None
        receipt.update(status='captured_gateway_handoff_passed_not_external_delivery',
                       native_tool_dedup=True, disconnected_profile_fails_closed=True)
    except BaseException as exc:
        receipt['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        receipt['wall_seconds'] = time.perf_counter() - started
        (args.out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
