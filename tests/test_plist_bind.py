"""Regression tests for launchd plist generation in afterwords.sh.

The bug these lock down: `write_plist()` emitted ONLY `--with-1.7b`, so every
plist regeneration (`afterwords configure --with-1.7b`, `setup.sh`) silently
dropped `--host`/`--bind-public`. A server deliberately bound to a LAN address
(e.g. for voice satellites) reverted to loopback on the next configure run and
every remote client broke. Conversely, a hand-edited plist was clobbered.

The fix persists the bind in ~/.afterwords-server (HOST / BIND_PUBLIC) and falls
back to reading the existing plist, so a regenerate is non-destructive.
"""
from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AFTERWORDS = REPO / "afterwords.sh"


def _shq(value: str) -> str:
    """Single-quote a value for safe interpolation into the generated bash."""
    return "'" + value.replace("'", "'\\''") + "'"


def _helper_function_source(*names: str) -> str:
    """Extract named bash function definitions from afterwords.sh.

    Sourced in isolation so a test can exercise a helper without running the
    script's top-level dispatch (which would need a real venv and launchd).
    """
    text = AFTERWORDS.read_text()
    out = []
    for name in names:
        marker = f"\n{name}() {{"
        start = text.index(marker)
        # Walk braces to find the function's closing line.
        depth = 0
        i = text.index("{", start)
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        out.append(text[start + 1 : i + 1])
    return "\n".join(out)


def _run_configure(tmp_path, *args, config_lines=(), installed=True):
    """Invoke `afterwords configure` against temp plist + config paths.

    Both the plist and the server config are redirected so the real
    ~/Library/LaunchAgents plist is never touched. `installed=True` pre-creates
    the plist, mirroring a machine where the launchd service is set up — which
    is the only case where `configure` regenerates it.
    """
    config = tmp_path / "server-config"
    if not config.exists():
        config.write_text("\n".join(config_lines) + ("\n" if config_lines else ""))
    plist = tmp_path / "test.plist"
    if installed and not plist.exists():
        with open(plist, "wb") as f:
            plistlib.dump({"Label": "com.afterwords.tts-server", "ProgramArguments": [
                str(tmp_path / ".venv" / "bin" / "python3"),
                str(tmp_path / "server.py"),
            ]}, f)
    env = os.environ.copy()
    env["AFTERWORDS_PLIST_PATH"] = str(plist)
    env["AFTERWORDS_SERVER_CONFIG"] = str(config)
    env["AFTERWORDS_REPO_DIR"] = str(tmp_path)
    # Never touch the operator's real launchd service: `launchctl list <Label>`
    # is machine-global regardless of which plist path we point at.
    env["AFTERWORDS_NO_LAUNCHCTL"] = "1"
    result = subprocess.run(
        ["bash", str(AFTERWORDS), "configure", *args],
        capture_output=True, text=True, env=env,
    )
    return result, plist, config


def _program_args(plist: Path) -> list[str]:
    with open(plist, "rb") as f:
        return plistlib.load(f).get("ProgramArguments", [])


def test_configure_bind_persists_host_and_bind_public(tmp_path):
    """--bind <addr> must write HOST + BIND_PUBLIC and emit them into the plist."""
    _, plist, config = _run_configure(tmp_path, "--bind", "192.168.0.249")

    args = _program_args(plist)
    assert "--host" in args, "bind address was dropped from the plist"
    assert args[args.index("--host") + 1] == "192.168.0.249"
    assert "--bind-public" in args, "--bind-public missing for a non-loopback bind"

    text = config.read_text()
    assert "HOST=192.168.0.249" in text
    assert "BIND_PUBLIC=true" in text


def test_bind_survives_unrelated_reconfigure(tmp_path):
    """The core regression: enabling 1.7B must NOT revert a LAN bind to loopback."""
    _, plist, _ = _run_configure(tmp_path, "--bind", "192.168.0.249")
    assert "--host" in _program_args(plist)

    # A later, unrelated configure run regenerates the plist.
    _, plist2, _ = _run_configure(tmp_path, "--with-1.7b")
    args = _program_args(plist2)

    assert "--host" in args, "reconfigure silently dropped the LAN bind"
    assert args[args.index("--host") + 1] == "192.168.0.249"
    assert "--bind-public" in args
    assert "--with-1.7b" in args, "the requested setting was not applied"


def test_bind_loopback_reverts_to_default(tmp_path):
    """--bind loopback must return the server to 127.0.0.1.

    It sets HOST=127.0.0.1 explicitly rather than clearing the key: an empty
    HOST would let write_plist fall back to the live plist and resurrect the
    LAN bind, silently making the revert a no-op.
    """
    _run_configure(tmp_path, "--bind", "192.168.0.249")
    _, plist, config = _run_configure(tmp_path, "--bind", "loopback")

    args = _program_args(plist)
    assert "--bind-public" not in args, "loopback bind must not be --bind-public"
    if "--host" in args:
        assert args[args.index("--host") + 1] == "127.0.0.1", "not a loopback address"
    assert "HOST=127.0.0.1" in config.read_text()


def test_legacy_plist_host_is_preserved_when_config_lacks_it(tmp_path):
    """A hand-edited plist (no HOST config key yet) must not be clobbered."""
    config = tmp_path / "server-config"
    config.write_text("WITH_17B=false\n")
    plist = tmp_path / "legacy.plist"
    with open(plist, "wb") as f:
        plistlib.dump({"ProgramArguments": [
            "/usr/bin/python3", "server.py",
            "--host", "0.0.0.0", "--bind-public",
        ]}, f)

    env = os.environ.copy()
    env["AFTERWORDS_PLIST_PATH"] = str(plist)
    env["AFTERWORDS_SERVER_CONFIG"] = str(config)
    env["AFTERWORDS_REPO_DIR"] = str(tmp_path)
    env["AFTERWORDS_NO_LAUNCHCTL"] = "1"
    subprocess.run(
        ["bash", str(AFTERWORDS), "configure", "--with-1.7b"],
        capture_output=True, text=True, env=env,
    )

    args = _program_args(plist)
    assert "--host" in args, "a pre-existing LAN bind was clobbered"
    assert args[args.index("--host") + 1] == "0.0.0.0"
    assert "--bind-public" in args


def test_default_plist_is_loopback(tmp_path):
    """With no bind configured, the plist omits --host (server defaults to loopback)."""
    _, plist, _ = _run_configure(tmp_path, "--with-1.7b")

    args = _program_args(plist)
    assert "--host" not in args
    assert "--bind-public" not in args
    assert args[0].endswith("python3")


def test_configure_bind_without_value_fails(tmp_path):
    """--bind with no address is a usage error, not a silent no-op."""
    result, _, _ = _run_configure(tmp_path, "--bind")

    assert result.returncode != 0
    assert "Usage" in result.stdout + result.stderr


def test_generated_plist_is_valid_plist_xml(tmp_path):
    """The emitted plist must parse — malformed XML would fail to load in launchd."""
    _, plist, _ = _run_configure(tmp_path, "--bind", "192.168.0.249")

    lint = subprocess.run(
        ["plutil", "-lint", str(plist)], capture_output=True, text=True,
    )
    assert lint.returncode == 0, f"plutil rejected the plist: {lint.stdout}{lint.stderr}"


def test_config_values_with_sed_metacharacters_are_literal(tmp_path):
    """`&`, `|` and `\\` in a value must be stored verbatim.

    server_config_set() originally used `sed -i "s|^K=.*|K=V|"`, where sed
    reads `&` in the replacement as "the matched text" and `|` as the
    delimiter. A value containing either corrupted the file into something
    like `HOST=aHOST=0.0.0.2b`, and that corrupted string was then re-emitted
    as --host on every regeneration. awk sets the value literally.

    The values are written through `server_config_set` directly rather than
    `configure --bind`, because `--bind` now validates addresses and would
    (correctly) reject them — this test is about the storage layer.
    """
    _, _, config = _run_configure(tmp_path, "--bind", "192.168.0.249")
    helpers = _helper_function_source("server_config_set")

    for value in ("a&b", "0.0.0.0|x", r"back\slash"):
        script = f'''
set -uo pipefail
AFTERWORDS_SERVER_CONFIG={config}
{helpers}
server_config_set HOST {_shq(value)}
'''
        subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        text = config.read_text()
        assert f"HOST={value}" in text, (
            f"value {value!r} was mangled; config is:\n{text}"
        )
        # The corruption signature: the old value spliced into the new one.
        assert "HOST=aHOST=" not in text and text.count("HOST=") == 1, (
            f"config corrupted by a metacharacter in {value!r}:\n{text}"
        )


def test_config_set_does_not_duplicate_keys(tmp_path):
    """Repeated sets must replace in place, never append a second key."""
    for value in ("10.0.0.1", "10.0.0.2", "10.0.0.3"):
        _run_configure(tmp_path, "--bind", value)

    config = tmp_path / "server-config"
    text = config.read_text()
    assert text.count("HOST=") == 1, f"duplicated HOST key:\n{text}"
    assert "HOST=10.0.0.3" in text


def test_loopback_bind_is_not_labelled_non_loopback(tmp_path):
    """`configure --bind loopback` sets HOST=127.0.0.1; the settings display
    (`configure` with no flag) must not then claim it is a LAN-reachable
    non-loopback address."""
    for value in ("loopback", "127.0.0.1", "localhost"):
        _run_configure(tmp_path, "--bind", value)
        # Read the settings display, not the --bind confirmation message.
        shown = _run_configure(tmp_path)[0].stdout
        bind_line = next(
            (ln for ln in shown.splitlines() if "Bind" in ln), ""
        )
        assert "loopback" in bind_line.lower(), (
            f"no loopback label for {value!r}; bind line was {bind_line!r}"
        )
        assert "non-loopback" not in bind_line, (
            f"{value!r} was labelled non-loopback: {bind_line!r}"
        )


def test_real_bind_keeps_non_loopback_label(tmp_path):
    """A genuine LAN bind must still be flagged as LAN-reachable."""
    _run_configure(tmp_path, "--bind", "192.168.0.249")
    shown = _run_configure(tmp_path)[0].stdout

    bind_line = next((ln for ln in shown.splitlines() if "Bind" in ln), "")
    assert "non-loopback" in bind_line, f"bind line was {bind_line!r}"


def test_corrupt_plist_does_not_break_generation(tmp_path):
    """A truncated/garbage plist must not crash write_plist (it is read for
    --host fallback before being overwritten)."""
    plist = tmp_path / "test.plist"
    plist.write_text("this is not xml\n")
    config = tmp_path / "server-config"
    config.write_text("")

    env = os.environ.copy()
    env["AFTERWORDS_PLIST_PATH"] = str(plist)
    env["AFTERWORDS_SERVER_CONFIG"] = str(config)
    env["AFTERWORDS_REPO_DIR"] = str(tmp_path)
    env["AFTERWORDS_NO_LAUNCHCTL"] = "1"
    result = subprocess.run(
        ["bash", str(AFTERWORDS), "configure", "--bind", "0.0.0.0"],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, f"crashed on a corrupt plist: {result.stderr}"
    args = _program_args(plist)
    assert args[args.index("--host") + 1] == "0.0.0.0"


def test_host_as_last_arg_with_no_value_is_safe(tmp_path):
    """A plist whose final argument is a bare `--host` must not crash or
    read past the end of the list."""
    plist = tmp_path / "test.plist"
    with open(plist, "wb") as f:
        plistlib.dump({"ProgramArguments": ["py", "server.py", "--host"]}, f)
    config = tmp_path / "server-config"
    config.write_text("")

    env = os.environ.copy()
    env["AFTERWORDS_PLIST_PATH"] = str(plist)
    env["AFTERWORDS_SERVER_CONFIG"] = str(config)
    env["AFTERWORDS_REPO_DIR"] = str(tmp_path)
    env["AFTERWORDS_NO_LAUNCHCTL"] = "1"
    result = subprocess.run(
        ["bash", str(AFTERWORDS), "configure", "--bind", "0.0.0.0"],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, f"crashed on a bare --host: {result.stderr}"
    assert "IndexError" not in result.stderr


# ── Findings from adversarial QA (agy, 2026-09-16) ────────────────────
# The tests below lock down six defects found by an independent reviewer.
# Three were in setup.sh and three in afterwords.sh; all six reproduced.


def test_bad_bind_address_is_rejected_not_written(tmp_path):
    """An address with XML metacharacters must be rejected at the CLI.

    Otherwise write_plist interpolates it into plist XML and launchd refuses
    to load the result — a failure discovered only at next login.
    """
    _, plist, config = _run_configure(tmp_path, "--bind", "192.168.0.249")

    for bad in ("foo<bar>", "a&b", "has space", 'quo"te', "semi;colon", "$(whoami)"):
        result, plist_after, config_after = _run_configure(tmp_path, "--bind", bad)
        assert result.returncode != 0, f"{bad!r} was accepted"
        # The good value must survive untouched.
        assert "HOST=192.168.0.249" in config_after.read_text()
        lint = subprocess.run(["plutil", "-lint", str(plist_after)],
                              capture_output=True, text=True)
        assert lint.returncode == 0, f"plist invalid after {bad!r}: {lint.stdout}"


def test_good_bind_addresses_are_accepted(tmp_path):
    """Validation must not reject legitimate addresses."""
    for good in ("0.0.0.0", "192.168.0.249", "127.0.0.1", "localhost",
                 "::1", "fe80::1%en0"):
        result, plist, _ = _run_configure(tmp_path, "--bind", good)
        assert result.returncode == 0, f"{good!r} was wrongly rejected: {result.stdout}"
        lint = subprocess.run(["plutil", "-lint", str(plist)],
                              capture_output=True, text=True)
        assert lint.returncode == 0, f"plist invalid for {good!r}"


def test_unsafe_host_in_config_degrades_to_loopback(tmp_path):
    """A hand-edited unsafe HOST= must not brick the plist; it is ignored."""
    plist = tmp_path / "test.plist"
    with open(plist, "wb") as f:
        plistlib.dump({"Label": "x", "ProgramArguments": ["py", "server.py"]}, f)
    config = tmp_path / "server-config"
    config.write_text("HOST=evil<addr>&x\nBIND_PUBLIC=true\n")

    env = os.environ.copy()
    env["AFTERWORDS_PLIST_PATH"] = str(plist)
    env["AFTERWORDS_SERVER_CONFIG"] = str(config)
    env["AFTERWORDS_REPO_DIR"] = str(tmp_path)
    env["AFTERWORDS_NO_LAUNCHCTL"] = "1"
    result = subprocess.run(
        ["bash", str(AFTERWORDS), "configure", "--with-1.7b"],
        capture_output=True, text=True, env=env,
    )

    assert result.returncode == 0, f"crashed on unsafe HOST: {result.stderr}"
    lint = subprocess.run(["plutil", "-lint", str(plist)],
                          capture_output=True, text=True)
    assert lint.returncode == 0, f"emitted an unparseable plist: {lint.stdout}"
    assert "--host" not in _program_args(plist), "unsafe host was emitted anyway"


def test_server_config_set_tolerates_missing_second_arg(tmp_path):
    """`server_config_set KEY` (clear form) must not trip `set -u`.

    The function's own comment documents a clear-by-empty-value call, but
    `local value="$2"` aborts with 'unbound variable' under set -u.
    """
    config = tmp_path / "cfg"
    config.write_text("HOST=1.2.3.4\n")
    script = f'''
set -uo pipefail
AFTERWORDS_SERVER_CONFIG={config}
{_helper_function_source("server_config_set")}
server_config_set HOST
echo "REACHED_END"
cat "$AFTERWORDS_SERVER_CONFIG"
'''
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert "unbound variable" not in result.stderr, result.stderr
    assert "REACHED_END" in result.stdout, f"aborted early: {result.stderr}"
    assert "HOST=" not in result.stdout, "key was not cleared"


def _prepare_repo_dir(tmp_path):
    """Minimal repo dir so afterwords.sh resolves REPO_DIR without a real venv."""
    (tmp_path / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
    (tmp_path / "server.py").write_text("")
    return tmp_path


def _setup_plist_block() -> str:
    """The plist-generation block from setup.sh, as a runnable snippet.

    Anchor on the redirect at the block's END, matched from the last
    occurrence — the block's own explanatory comment mentions
    `} > "$PLIST_PATH"`, so a naive forward search would stop inside the
    comment and silently truncate the extracted snippet.
    """
    body = (REPO / "setup.sh").read_text()
    start = body.index('PLIST_NAME="com.afterwords.tts-server"')
    end = body.rindex('} > "$PLIST_PATH"') + len('} > "$PLIST_PATH"')
    return body[start:end]


def test_setup_sh_plist_generation_survives_empty_config(tmp_path):
    """setup.sh runs under `set -euo pipefail`: resolving HOST from a config
    with no HOST= line must not abort the script (grep exits 1, pipefail
    propagates, set -e kills the script mid-write and truncates the plist)."""
    repo = _prepare_repo_dir(tmp_path)
    config = tmp_path / ".afterwords-server"
    config.write_text("")                       # no HOST= line at all
    # The block derives PLIST_PATH from $HOME, so the sandbox HOME determines
    # where the plist lands.
    plist = tmp_path / "Library" / "LaunchAgents" / "com.afterwords.tts-server.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)

    block = _setup_plist_block()
    # HOME=tmp_path makes the block's own PLIST_PATH/AFTERWORDS_SERVER_CONFIG
    # resolve inside the sandbox — do not override them after the block source,
    # since the block assigns them itself.
    script = f'''
set -euo pipefail
SCRIPT_DIR={repo}
HOME={tmp_path}
mkdir -p "$HOME/Library/LaunchAgents"
{block}
echo "REACHED_END"
'''
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert "REACHED_END" in result.stdout, (
        f"setup.sh aborted before finishing the plist:\n{result.stderr}"
    )
    lint = subprocess.run(["plutil", "-lint", str(plist)],
                          capture_output=True, text=True)
    assert lint.returncode == 0, f"truncated/invalid plist: {lint.stdout}"


def test_setup_sh_preserves_existing_plist_host(tmp_path):
    """The --host fallback must read the pre-existing plist.

    The block is wrapped in `{ ... } > "$PLIST_PATH"`, which truncates the file
    the moment the redirect opens — so any read of $PLIST_PATH from *inside*
    the braces always sees an empty file and the fallback can never fire.
    Resolution therefore has to happen before the redirect.
    """
    repo = _prepare_repo_dir(tmp_path)
    home = tmp_path
    la = home / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    plist = la / "com.afterwords.tts-server.plist"
    with open(plist, "wb") as f:
        plistlib.dump({"Label": "com.afterwords.tts-server", "ProgramArguments": [
            "python3", "server.py", "--host", "192.168.0.249", "--bind-public",
        ]}, f)
    (home / ".afterwords-server").write_text("")   # no HOST= key

    script = f'''
set -euo pipefail
SCRIPT_DIR={repo}
HOME={home}
{_setup_plist_block()}
'''
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, f"setup.sh block failed: {result.stderr}"

    args = _program_args(plist)
    assert "--host" in args, (
        f"pre-existing LAN bind was clobbered; args={args}"
    )
    assert args[args.index("--host") + 1] == "192.168.0.249"
    assert "--bind-public" in args


def test_setup_sh_respects_explicit_bind_public_false(tmp_path):
    """An explicit BIND_PUBLIC=false must win over a stale --bind-public in the
    plist, matching afterwords.sh's write_plist precedence."""
    repo = _prepare_repo_dir(tmp_path)
    home = tmp_path
    la = home / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    plist = la / "com.afterwords.tts-server.plist"
    with open(plist, "wb") as f:
        plistlib.dump({"Label": "x", "ProgramArguments": [
            "python3", "server.py", "--host", "0.0.0.0", "--bind-public",
        ]}, f)
    (home / ".afterwords-server").write_text("HOST=0.0.0.0\nBIND_PUBLIC=false\n")

    script = f'''
set -euo pipefail
SCRIPT_DIR={repo}
HOME={home}
{_setup_plist_block()}
'''
    subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    args = _program_args(plist)
    assert "--bind-public" not in args, (
        f"BIND_PUBLIC=false was ignored; args={args}"
    )
    assert args[args.index("--host") + 1] == "0.0.0.0"


def test_setup_sh_block_scoped_under_strict_mode():
    """Every command substitution in the setup.sh block must be `|| true`-safe
    under `set -euo pipefail` when nothing matches."""
    for line in _setup_plist_block().splitlines():
        if "$(grep" in line:
            assert "|| true" in line, (
                f"unguarded grep substitution aborts setup.sh under set -e: {line.strip()}"
            )


# ── Round-2 QA findings ───────────────────────────────────────────────


def test_setup_sh_ignores_unsafe_host(tmp_path):
    """setup.sh must not interpolate an unsafe HOST into plist XML.

    A hand-edited `HOST=evil<addr>&x` in ~/.afterwords-server otherwise emits a
    plist plutil rejects and launchd cannot load, breaking the whole install.
    """
    repo = _prepare_repo_dir(tmp_path)
    home = tmp_path
    la = home / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    plist = la / "com.afterwords.tts-server.plist"
    (home / ".afterwords-server").write_text("HOST=evil<addr>&x\nBIND_PUBLIC=true\n")

    script = f'''
set -euo pipefail
SCRIPT_DIR={repo}
HOME={home}
{_setup_plist_block()}
'''
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, f"block failed: {result.stderr}"

    lint = subprocess.run(["plutil", "-lint", str(plist)],
                          capture_output=True, text=True)
    assert lint.returncode == 0, f"emitted unparseable plist: {lint.stdout}"
    assert "evil" not in plist.read_text(), "unsafe HOST reached the plist"
    assert "unsafe" in result.stderr.lower(), "no warning was emitted"


def test_setup_sh_ignores_host_with_leading_dash(tmp_path):
    """A leading `-` makes argparse read the value as an option, not --host's
    argument; under launchd KeepAlive that is an endless restart loop."""
    repo = _prepare_repo_dir(tmp_path)
    home = tmp_path
    la = home / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    plist = la / "com.afterwords.tts-server.plist"
    (home / ".afterwords-server").write_text("HOST=-leading-dash\nBIND_PUBLIC=true\n")

    script = f'''
set -euo pipefail
SCRIPT_DIR={repo}
HOME={home}
{_setup_plist_block()}
'''
    subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    assert "--host" not in _program_args(plist), "leading-dash host was emitted"
    # And no orphan --bind-public either.
    assert "--bind-public" not in _program_args(plist)


def test_leading_dash_bind_is_rejected(tmp_path):
    """`configure --bind -leading-dash` must be refused at the CLI."""
    for bad in ("-leading-dash", "--help", "-v", "--host"):
        result, plist, _ = _run_configure(tmp_path, "--bind", bad)
        assert result.returncode != 0, f"{bad!r} was accepted"
        assert "--host" not in _program_args(plist), f"{bad!r} reached the plist"


def test_config_file_permissions_are_preserved(tmp_path):
    """Updating the config must not widen its permissions.

    The temp file is created under the ambient umask (022 → 644); without an
    explicit chmod, a config the operator tightened to 600 silently becomes
    world-readable after any update.
    """
    config = tmp_path / "cfg"
    config.write_text("HOST=1.2.3.4\n")
    os.chmod(config, 0o600)

    script = f'''
set -uo pipefail
AFTERWORDS_SERVER_CONFIG={config}
{_helper_function_source("server_config_set")}
server_config_set HOST 5.6.7.8
'''
    subprocess.run(["bash", "-c", script], capture_output=True, text=True)

    mode = oct(config.stat().st_mode & 0o777)
    assert mode == oct(0o600), f"permissions changed to {mode}"
    assert "HOST=5.6.7.8" in config.read_text()


def test_status_warns_when_health_check_fails(tmp_path):
    """The LAN-bind diagnostic must be reachable.

    It was previously chained as `|| warn` to the python3 renderer INSIDE the
    `if health_check; then` block, so it could never fire when health_check
    (the condition) failed — exactly the case it was written for.
    """
    fake_home = tmp_path
    (fake_home / "Library" / "LaunchAgents").mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["AFTERWORDS_PLIST_PATH"] = str(tmp_path / "nonexistent.plist")
    env["AFTERWORDS_SERVER_CONFIG"] = str(tmp_path / "cfg")
    env["AFTERWORDS_NO_LAUNCHCTL"] = "1"
    env["AFTERWORDS_REPO_DIR"] = str(tmp_path)
    # Point at a dead port so health_check fails while a PID is reported.
    result = subprocess.run(
        ["bash", "-c", f'''
PORT=9
HEALTH_URL="http://127.0.0.1:$PORT/health"
AFTERWORDS_SERVER_CONFIG={tmp_path}/cfg
AFTERWORDS_PLIST_PATH={tmp_path}/nonexistent.plist
# Minimal output helpers, mirroring afterwords.sh's own.
GREEN=""; RED=""; YELLOW=""; CYAN=""; DIM=""; BOLD=""; NC=""
warn() {{ echo "WARN: $*"; }}
ok() {{ echo "OK: $*"; }}
fail() {{ echo "FAIL: $*"; }}
rule() {{ echo "---"; }}
{_helper_function_source("plist_loaded", "cmd_status")}
server_pid() {{ echo 99999; }}
plist_loaded() {{ return 0; }}
plist_exists() {{ return 0; }}
MUTE_FILE=/nonexistent
with_17b_enabled() {{ return 1; }}
health_check() {{ return 1; }}
cmd_status
'''],
        capture_output=True, text=True, env=env,
    )
    output = result.stdout + result.stderr
    assert "not responding" in output, (
        f"status printed no warning when /health failed:\n{output}"
    )
    # The message must name both plausible causes: a cold start (the model
    # takes 60-180s to bind) and a non-loopback bind. Naming only the bind
    # would send an operator chasing a config bug during a normal warmup.
    assert "warming up" in output, f"warning omits the warmup case:\n{output}"
    assert "bound elsewhere" in output, f"warning omits the bind case:\n{output}"
    assert "configure" in output, f"warning omits the remedy:\n{output}"

