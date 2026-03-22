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
    assert strip_markdown("## Section Title") == "Section Title"


def test_bullet_list_stripped():
    result = strip_markdown("- item one\n- item two")
    assert "item one" in result
    assert "item two" in result
    assert result.startswith("-") is False


def test_numbered_list_stripped():
    result = strip_markdown("1. first\n2. second")
    assert "first" in result
    assert "second" in result
    assert "1." not in result


def test_link_keeps_text():
    assert strip_markdown("[click here](http://example.com)") == "click here"


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
    # Bullet list markers stripped, content preserved
    assert "Zero-shot cloning" in result
    assert result.count("- ") == 0  # no bullet markers remain
    # Link text preserved, URL removed
    assert "README" in result
    assert "github.com" not in result
    # No backticks remain
    assert "`" not in result
