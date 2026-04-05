from codex_session_hook import extract_final_text


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
