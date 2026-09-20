"""Tests for summarize_for_tts — extractive fallback and .afterwords config."""
from pathlib import Path

import pytest

from summarize_for_tts import (
    extractive_summary,
    parse_afterwords_config,
    parse_speak_mode,
    summarize_for_tts,
)


@pytest.fixture(autouse=True)
def isolate_server_config(tmp_path, monkeypatch):
    """Do not read the developer's ~/.afterwords-server (SPEAK_MODE=full)."""
    monkeypatch.setenv(
        "AFTERWORDS_SERVER_CONFIG", str(tmp_path / "no-such-server-config")
    )


def test_parse_cursor_summarize_config(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text(
        "default: holly\ncursor: holly\ncursor_summarize: true\ncursor_summarize_min: 300\n",
        encoding="utf-8",
    )
    cfg = parse_afterwords_config(aw, "cursor")
    assert cfg["enabled"] is True
    assert cfg["min_chars"] == 300


def test_short_text_unchanged(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text("cursor_summarize: true\n", encoding="utf-8")
    text = "Done. The app is running."
    assert summarize_for_tts(text, agent="cursor", afterwords_path=aw) == text


def test_long_text_summarized_when_enabled(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text("cursor_summarize: true\ncursor_summarize_min: 50\n", encoding="utf-8")
    text = (
        "I cleared quarantine from the app bundle. "
        "Then I re-signed the Sparkle framework and nested components. "
        "Afterwords is now running and you can open it from Applications."
    )
    out = summarize_for_tts(text, agent="cursor", afterwords_path=aw)
    assert len(out) < len(text)
    assert "quarantine" in out
    assert "running" in out or "Applications" in out


def test_disabled_leaves_text_alone(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text("cursor_summarize: false\n", encoding="utf-8")
    text = "A" * 500
    assert summarize_for_tts(text, agent="cursor", afterwords_path=aw) == text


def test_ollama_model_tag_with_colon(tmp_path: Path):
    """Ollama tags like llama3.2:1b must survive .afterwords parsing."""
    aw = tmp_path / ".afterwords"
    aw.write_text(
        "cursor_summarize: true\ncursor_summarize_model: llama3.2:1b\n",
        encoding="utf-8",
    )
    cfg = parse_afterwords_config(aw, "cursor")
    assert cfg["enabled"] is True
    assert cfg["model"] == "llama3.2:1b"


def test_colon_containing_agent_key(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text(
        "feature-dev:code-architect_summarize: true\n"
        "feature-dev:code-architect_summarize_model: llama3.2:1b\n",
        encoding="utf-8",
    )
    cfg = parse_afterwords_config(aw, "feature-dev:code-architect")
    assert cfg["enabled"] is True
    assert cfg["model"] == "llama3.2:1b"


def test_ollama_timeout_is_short_for_tts_path():
    import inspect
    from summarize_for_tts import ollama_summarize

    # Worker should not block long on a slow Ollama — extractive fallback must win.
    assert inspect.signature(ollama_summarize).parameters["timeout"].default <= 10


def test_extractive_first_and_last_sentence():
    text = (
        "Fixed the Gatekeeper block. "
        "Removed quarantine flags from every file in the bundle. "
        "Re-signed Sparkle and the main app. "
        "You can launch Afterwords normally now."
    )
    out = extractive_summary(text, sentences=2, max_chars=200)
    assert out.startswith("Fixed the Gatekeeper block.")
    assert "normally now." in out


def test_agent_keys_win_regardless_of_line_order(tmp_path: Path):
    """Regression: a global key below an agent key used to overwrite it.

    parse_afterwords_config walked the file top-to-bottom and every matching
    line unconditionally wrote cfg[field], so whichever appeared LAST won —
    contradicting the function's own "agent-specific keys win" contract.
    """
    # agent key first, global key last -> agent must still win
    aw = tmp_path / ".afterwords"
    aw.write_text("cursor_summarize: true\nsummarize: false\n", encoding="utf-8")
    assert parse_afterwords_config(aw, "cursor")["enabled"] is True

    # global key first, agent key last -> agent wins (this direction always worked)
    aw.write_text("summarize: false\ncursor_summarize: true\n", encoding="utf-8")
    assert parse_afterwords_config(aw, "cursor")["enabled"] is True

    # an agent key turning the feature OFF must beat a global key turning it ON
    aw.write_text("cursor_summarize: false\nsummarize: true\n", encoding="utf-8")
    assert parse_afterwords_config(aw, "cursor")["enabled"] is False

    # numeric fields follow the same precedence
    aw.write_text(
        "cursor_summarize: true\n"
        "summarize_max_chars: 200\n"
        "cursor_summarize_max_chars: 500\n",
        encoding="utf-8",
    )
    assert parse_afterwords_config(aw, "cursor")["max_chars"] == 500


def test_parse_speak_mode_full_and_summarize(tmp_path: Path):
    cfg = tmp_path / "server"
    assert parse_speak_mode(cfg) == ""
    cfg.write_text("WITH_17B=true\nSPEAK_MODE=full\n", encoding="utf-8")
    assert parse_speak_mode(cfg) == "full"
    cfg.write_text("SPEAK_MODE=summarize\n", encoding="utf-8")
    assert parse_speak_mode(cfg) == "summarize"
    cfg.write_text("SPEAK_MODE=weird\n", encoding="utf-8")
    assert parse_speak_mode(cfg) == ""


def test_speak_mode_full_overrides_project_summarize(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text(
        "cursor_summarize: true\ncursor_summarize_min: 50\n",
        encoding="utf-8",
    )
    server = tmp_path / "server"
    server.write_text("SPEAK_MODE=full\n", encoding="utf-8")
    text = (
        "I cleared quarantine from the app bundle. "
        "Then I re-signed the Sparkle framework and nested components. "
        "Afterwords is now running and you can open it from Applications."
    )
    out = summarize_for_tts(
        text,
        agent="cursor",
        afterwords_path=aw,
        server_config_path=server,
    )
    assert out == text


def test_speak_mode_summarize_forces_when_project_disabled(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text(
        "cursor_summarize: false\ncursor_summarize_min: 50\n",
        encoding="utf-8",
    )
    server = tmp_path / "server"
    server.write_text("SPEAK_MODE=summarize\n", encoding="utf-8")
    text = (
        "I cleared quarantine from the app bundle. "
        "Then I re-signed the Sparkle framework and nested components. "
        "Afterwords is now running and you can open it from Applications."
    )
    out = summarize_for_tts(
        text,
        agent="cursor",
        afterwords_path=aw,
        server_config_path=server,
    )
    assert len(out) < len(text)
    assert "quarantine" in out


def test_speak_mode_unset_keeps_project_opt_in(tmp_path: Path):
    aw = tmp_path / ".afterwords"
    aw.write_text("cursor_summarize: false\n", encoding="utf-8")
    server = tmp_path / "server"
    server.write_text("WITH_17B=true\n", encoding="utf-8")
    text = "A" * 500
    assert (
        summarize_for_tts(
            text,
            agent="cursor",
            afterwords_path=aw,
            server_config_path=server,
        )
        == text
    )


def test_env_server_config_used_when_path_omitted(tmp_path: Path, monkeypatch):
    aw = tmp_path / ".afterwords"
    aw.write_text(
        "cursor_summarize: true\ncursor_summarize_min: 50\n",
        encoding="utf-8",
    )
    server = tmp_path / "from-env"
    server.write_text("SPEAK_MODE=full\n", encoding="utf-8")
    monkeypatch.setenv("AFTERWORDS_SERVER_CONFIG", str(server))
    text = (
        "I cleared quarantine from the app bundle. "
        "Then I re-signed the Sparkle framework and nested components. "
        "Afterwords is now running and you can open it from Applications."
    )
    assert summarize_for_tts(text, agent="cursor", afterwords_path=aw) == text
