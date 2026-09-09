"""Tests for the strip-markdown text transform.

Every regex pattern in the pipeline has a dedicated test.
The golden test (test_real_claude_response) exercises all
patterns together on a realistic Claude response.
"""
from strip_markdown import strip_markdown


def test_preserves_plain_text():
    assert strip_markdown("Hello world") == "Hello world"


def test_inline_code_keeps_content():
    assert strip_markdown("`--server-only` flag") == "--server-only flag"


def test_multiple_inline_code_spans():
    assert strip_markdown("Use `foo` and `bar`") == "Use foo and bar"


def test_inline_code_special_chars():
    assert strip_markdown("`--flag=value` option") == "--flag=value option"


def test_fenced_code_block_removed():
    text = "before\n```bash\ncurl localhost:7860/health\n```\nafter"
    result = strip_markdown(text)
    assert "curl" not in result
    assert "before" in result
    assert "after" in result


def test_bold_stripped():
    assert strip_markdown("**important** thing") == "important thing"


def test_italic_stripped():
    assert strip_markdown("*emphasis* here") == "emphasis here"


def test_heading_stripped():
    assert strip_markdown("## Section Title") == "Section Title."


def test_bullet_list_stripped():
    result = strip_markdown("- item one\n- item two")
    assert "item one" in result
    assert "item two" in result
    assert result.startswith("-") is False


def test_bullet_list_pauses_between_items():
    result = strip_markdown("- First point\n- Second point\n- Third point")
    assert "First point." in result
    assert "Second point." in result
    assert "Third point." in result
    # Items must be separate spoken beats, not a run-on clause.
    assert result.index("First point.") < result.index("Second point.")
    assert ". Second point." in result or result.count(". ") >= 2


def test_numbered_list_stripped():
    result = strip_markdown("1. first\n2. second")
    assert "first" in result
    assert "second" in result
    assert "1." not in result


def test_numbered_list_pauses_between_items():
    result = strip_markdown("1. Install deps\n2. Restart the server\n3. Verify health")
    assert "Install deps." in result
    assert "Restart the server." in result
    assert "Verify health." in result


def test_heading_becomes_spoken_sentence():
    result = strip_markdown("## Voice Configuration\n\nBody text here.")
    assert "Voice Configuration." in result
    assert "##" not in result


def test_em_dash_becomes_comma_pause():
    result = strip_markdown("galadriel — ethereal, ancient")
    assert "—" not in result
    assert "galadriel, ethereal" in result


def test_urls_are_dropped():
    result = strip_markdown("See https://example.com/docs for details.")
    assert "https://" not in result
    assert "example.com" not in result
    assert "See" in result
    assert "for details." in result


def test_file_path_keeps_basename():
    result = strip_markdown("Updated /Users/chris/local/dev/afterwords/server.py today.")
    assert "/Users/" not in result
    assert "server.py" in result


def test_snake_case_spoken_as_words():
    result = strip_markdown("Fixed strip_markdown and chunk_text helpers.")
    assert "strip markdown" in result
    assert "chunk text" in result


def test_arrow_becomes_pause():
    result = strip_markdown("hook → worker → speaker")
    assert "→" not in result
    assert "hook, worker, speaker" in result


def test_link_keeps_text():
    assert strip_markdown("[click here](http://example.com)") == "click here"


def test_image_stripped():
    assert strip_markdown("![alt text](http://example.com/img.png)") == "alt text"


def test_blockquote_stripped():
    result = strip_markdown("> quoted text")
    assert "quoted text" in result
    assert ">" not in result


def test_strikethrough_stripped():
    assert strip_markdown("~~deleted~~ kept") == "deleted kept"


def test_bold_italic_triple_asterisk():
    assert strip_markdown("***bold italic*** text") == "bold italic text"


def test_table_removed():
    text = "before\n| Name | Value |\n|---|---|\n| a | b |\nafter"
    result = strip_markdown(text)
    assert "before" in result
    assert "after" in result
    assert "|" not in result


def test_truncates_at_1000_chars():
    text = "word " * 400  # 2000 chars
    result = strip_markdown(text)
    assert len(result) <= 1000


def test_max_chars_none_preserves_full_text():
    text = "word " * 400
    result = strip_markdown(text, max_chars=None)
    assert len(result) > 1000
    assert result.startswith("word")


def test_cli_default_does_not_truncate():
    """Hook CLI must not silently cut speech at 1000 chars."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    script = Path(__file__).resolve().parent.parent / "strip_markdown.py"
    long = ("Hello world. " * 200).strip()
    env = os.environ.copy()
    env.pop("STRIP_MARKDOWN_MAX_CHARS", None)
    out = subprocess.check_output(
        [sys.executable, str(script)],
        input=long.encode(),
        env=env,
    ).decode()
    assert len(out.strip()) > 1000
    assert out.strip().startswith("Hello world")


def test_collapses_whitespace():
    assert strip_markdown("too   many    spaces") == "too many spaces"


def test_real_claude_response():
    """Golden test — a realistic Claude response with every markdown feature."""
    text = """## Voice Configuration

You can set a **per-project voice** using the `.afterwords` file:

```bash
echo "snape" > .afterwords
```

The `--server-only` flag skips Claude Code integration. Available voices:

1. `galadriel` — ethereal, ancient
2. `snape` — velvet menace

| Voice | Source |
|---|---|
| galadriel | Cate Blanchett |
| snape | Alan Rickman |

Features:

- Zero-shot cloning
- Real-time synthesis

> Note: this is ***experimental*** and ~~may change~~ at any time.

For more details, see the [README](https://github.com/adrianwedd/afterwords)."""

    result = strip_markdown(text)
    # Headings stripped
    assert "##" not in result
    # Fenced code block removed
    assert "echo" not in result
    # Inline code content preserved
    assert "--server-only" in result
    assert "galadriel" in result
    assert "snape" in result
    # Bold stripped
    assert "**" not in result
    # Table removed
    assert "|" not in result
    # Bullet list markers stripped, content preserved as separate sentences
    assert "Zero-shot cloning." in result
    assert "Real-time synthesis." in result
    assert result.count("- ") == 0  # no bullet markers remain
    # Numbered list items also get spoken pauses (em dash → comma)
    assert "galadriel, ethereal, ancient." in result
    assert "snape, velvet menace." in result
    # Blockquote stripped
    assert ">" not in result
    assert "experimental" in result
    # Bold-italic (triple asterisk) stripped
    assert "***" not in result
    # Strikethrough stripped
    assert "~~" not in result
    assert "may change" in result
    # Link text preserved, URL removed
    assert "README" in result
    assert "github.com" not in result
    # No backticks remain
    assert "`" not in result
