from codex_session_hook import extract_agent_type, extract_final_text


def test_extracts_final_assistant_text():
    line = (
        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
        '"phase":"final_answer","content":[{"type":"output_text","text":"Hello world"}]}}'
    )
    assert extract_final_text(line) == "Hello world"


def test_ignores_non_final_messages():
    line = (
        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
        '"content":[{"type":"output_text","text":"working"}]}}'
    )
    assert extract_final_text(line) is None


def test_ignores_non_assistant_messages():
    line = (
        '{"type":"response_item","payload":{"type":"message","role":"user",'
        '"phase":"final_answer","content":[{"type":"output_text","text":"Hello"}]}}'
    )
    assert extract_final_text(line) is None


def test_joins_multiple_output_chunks():
    line = (
        '{"type":"response_item","payload":{"type":"message","role":"assistant",'
        '"phase":"final_answer","content":['
        '{"type":"output_text","text":"First"},'
        '{"type":"output_text","text":"Second"}]}}'
    )
    assert extract_final_text(line) == "First\nSecond"


def test_extract_agent_type_from_payload():
    line = '{"type":"response_item","payload":{"agent_type":"Explore","type":"message"}}'
    assert extract_agent_type(line) == "Explore"


def test_extract_agent_type_from_top_level():
    line = '{"type":"response_item","agent_type":"Plan","payload":{}}'
    assert extract_agent_type(line) == "Plan"


def test_extract_agent_type_returns_none_when_absent():
    line = '{"type":"response_item","payload":{"type":"message","role":"assistant"}}'
    assert extract_agent_type(line) is None


def test_extract_agent_type_returns_none_for_invalid_json():
    assert extract_agent_type("not json") is None


def test_main_agent_type_flag(capsys):
    from codex_session_hook import main
    line = '{"type":"response_item","payload":{"agent_type":"Explore"}}'
    import sys
    from io import StringIO
    old_stdin = sys.stdin
    sys.stdin = StringIO(line)
    try:
        ret = main(["--agent-type"])
    finally:
        sys.stdin = old_stdin
    assert ret == 0
    assert capsys.readouterr().out == "Explore"


def test_main_agent_type_flag_silent_when_absent(capsys):
    from codex_session_hook import main
    import sys
    from io import StringIO
    old_stdin = sys.stdin
    sys.stdin = StringIO('{"type":"other"}')
    try:
        ret = main(["--agent-type"])
    finally:
        sys.stdin = old_stdin
    assert ret == 0
    assert capsys.readouterr().out == ""
