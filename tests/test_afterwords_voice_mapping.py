import subprocess
import textwrap


RESOLVE_SNIPPET = r'''
AW_FILE="$1"
AGENT="${2:-}"
VOICE=""
if [ -f "$AW_FILE" ]; then
    if grep -q ':' "$AW_FILE" 2>/dev/null; then
        VOICE=$(awk -v agent="$AGENT" '
            function trim(s) { gsub(/^[[:space:]]+|[[:space:]]+$/, "", s); return s }
            /^[[:space:]]*#/ || /^[[:space:]]*$/ { next }
            {
                pos = 0
                for (i = 1; i <= length($0); i++) {
                    if (substr($0, i, 1) == ":") pos = i
                }
                if (!pos) next
                key = trim(substr($0, 1, pos - 1))
                val = trim(substr($0, pos + 1))
                if (agent != "" && key == agent) { print val; found = 1; exit }
                if (key == "default" && fallback == "") fallback = val
            }
            END { if (!found && fallback != "") print fallback }
        ' "$AW_FILE" 2>/dev/null)
    else
        VOICE=$(head -1 "$AW_FILE" 2>/dev/null | tr -d '[:space:]')
    fi
fi
printf '%s' "$VOICE"
'''


def resolve_voice(tmp_path, content, agent=""):
    voice_file = tmp_path / ".afterwords"
    voice_file.write_text(textwrap.dedent(content).lstrip(), encoding="utf-8")
    result = subprocess.run(
        ["bash", "-c", RESOLVE_SNIPPET, "resolve", str(voice_file), agent],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def test_mapping_supports_default_without_space(tmp_path):
    assert resolve_voice(tmp_path, "default:data\n") == "data"


def test_mapping_supports_default_with_space(tmp_path):
    assert resolve_voice(tmp_path, "default: seven-of-nine\n") == "seven-of-nine"


def test_mapping_prefers_exact_agent_over_default(tmp_path):
    assert (
        resolve_voice(
            tmp_path,
            """
            default: seven-of-nine
            codex: spock
            """,
            "codex",
        )
        == "spock"
    )


def test_mapping_supports_compound_agent_keys(tmp_path):
    assert (
        resolve_voice(
            tmp_path,
            """
            default: seven-of-nine
            feature-dev:code-reviewer: spock
            """,
            "feature-dev:code-reviewer",
        )
        == "spock"
    )


def test_mapping_supports_compound_agent_keys_without_space(tmp_path):
    assert (
        resolve_voice(
            tmp_path,
            """
            default:seven-of-nine
            feature-dev:code-reviewer:spock
            """,
            "feature-dev:code-reviewer",
        )
        == "spock"
    )


def test_simple_voice_file_still_works(tmp_path):
    assert resolve_voice(tmp_path, "galadriel\n") == "galadriel"
