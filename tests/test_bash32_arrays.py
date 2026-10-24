"""Speech scripts must survive macOS's stock Bash 3.2 under `set -u`.

Bash before 4.4 treats "${EMPTY[@]}" as an unbound variable. The optional
curl credential array is empty on every unauthenticated route (including the
default 7860), so an unguarded expansion aborts synthesis on a stock Mac while
Bash 5 on CI passes. Optional arrays must use ${NAME[@]+"${NAME[@]}"}.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OPTIONAL_ARRAYS = ("CURL_AUTH",)
SCRIPTS = ("scripts/afterwords-tts-command.sh", "scripts/afterwords-post-llm.sh")


def test_optional_arrays_use_bash32_safe_expansion():
    for script in SCRIPTS:
        text = (REPO / script).read_text()
        for name in OPTIONAL_ARRAYS:
            assert f'{name}=()' in text, f"{script} no longer declares {name}"
            unguarded = re.findall(r'(?<![+\w])"\$\{' + name + r'\[@\]\}"', text)
            guarded = text.count(f'${{{name}[@]+"${{{name}[@]}}"}}')
            assert not unguarded, f"{script}: unguarded {name} expansion"
            assert guarded, f"{script} no longer uses {name}"
