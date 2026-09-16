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
