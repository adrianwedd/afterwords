import os
import tempfile
from pathlib import Path
from agy_session_hook import extract_final_text, main


def test_extracts_final_text():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write('{"source":"MODEL","type":"PLANNER_RESPONSE","content":"Hello world"}\n')
        tmp_name = tmp.name

    try:
        assert extract_final_text(tmp_name) == "Hello world"
    finally:
        os.unlink(tmp_name)


def test_ignores_non_planner_responses():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write('{"source":"MODEL","type":"CODE_ACTION","content":"ignored"}\n')
        tmp_name = tmp.name

    try:
        assert extract_final_text(tmp_name) is None
    finally:
        os.unlink(tmp_name)


def test_ignores_non_model_events():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write('{"source":"USER_EXPLICIT","type":"PLANNER_RESPONSE","content":"Hello"}\n')
        tmp_name = tmp.name

    try:
        assert extract_final_text(tmp_name) is None
    finally:
        os.unlink(tmp_name)


def test_ignores_tool_calls():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write('{"source":"MODEL","type":"PLANNER_RESPONSE","tool_calls":[{"name":"ls"}]}\n')
        tmp_name = tmp.name

    try:
        assert extract_final_text(tmp_name) is None
    finally:
        os.unlink(tmp_name)


def test_finds_last_valid_response():
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write('{"source":"MODEL","type":"PLANNER_RESPONSE","content":"First"}\n')
        tmp.write('{"source":"MODEL","type":"PLANNER_RESPONSE","tool_calls":[{"name":"ls"}]}\n')
        tmp.write('{"source":"MODEL","type":"PLANNER_RESPONSE","content":"Second"}\n')
        tmp.write('{"source":"USER_EXPLICIT","type":"PLANNER_RESPONSE","content":"Third"}\n')
        tmp_name = tmp.name

    try:
        assert extract_final_text(tmp_name) == "Second"
    finally:
        os.unlink(tmp_name)


def test_main_flag_handling(capsys):
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write('{"source":"MODEL","type":"PLANNER_RESPONSE","content":"Hello"}\n')
        tmp_name = tmp.name

    try:
        ret = main([tmp_name])
        assert ret == 0
        assert capsys.readouterr().out == "Hello"
    finally:
        os.unlink(tmp_name)


def test_cli_accepts_transcript_path_without_strip_markdown(capsys):
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as tmp:
        tmp.write('{"source":"MODEL","type":"PLANNER_RESPONSE","content":"Hello"}\n')
        tmp_name = tmp.name

    try:
        ret = main([tmp_name])
        assert ret == 0
        assert capsys.readouterr().out == "Hello"
    finally:
        os.unlink(tmp_name)


def test_shell_hook_invokes_helper_without_unknown_flag():
    hook = Path(".claude/hooks/agy-tts-hook.sh").read_text(encoding="utf-8")
    assert "--strip-markdown" not in hook
    assert 'agy-session-hook.py" "$TRANSCRIPT_PATH"' in hook

