# STRATEGY.md — Afterwords

What is irreversible in this repo, and what needs the owner's OK first.

Architecture, conventions, and commands live in CLAUDE.md / AGENTS.md — this file
does not repeat them. It also records no counts, versions, SHAs, or "as of" dates:
facts with an expiry turn into false alarms, and a stale line here should never
stop anyone's work.

## Get the owner's OK first

- **Push or merge to `main`** — `docs/` is the public GitHub Pages site, so a
  merge publishes it. Same for tagging and releasing.
- **Deleting or rewriting tracked `voices/*.json` / `voices/*-ref.wav`** — they
  ship in releases and back the public demo site.
- **Stopping or restarting the launchd server, or running `setup.sh`** — that is
  the owner's live, in-use TTS, and `setup.sh` writes `~/.claude/`, a
  `/usr/local/bin` symlink, and a launchd plist.
- **Live-server mutations**: `POST /clone`, `/reload?prune=true`,
  `DELETE /session/*`, and `clone-voice.sh` (external download).
- **Editing another tool's hook config**: `~/.claude/hooks/`, `~/.gemini/`,
  `~/.cursor/`.

## Never

- `git add -A` / `git add .` — the tree deliberately carries untracked scratch and
  gitignored private voices. Stage named paths.
- Commit `.afterwords` (local voice preferences) or `voices/muse*` / `voices/vixen*`.
- Clear `/tmp/afterwords-play.lock` while its PID is alive — audio is playing.

## Safe without asking

Reading anything; `pytest`; `git log/diff/status`; read-only `curl localhost:7860`;
building patches on a branch.

Voice counts come from `git ls-files 'voices/*.json'`, never from `ls voices/` —
untracked and private voices inflate the on-disk number, and CI's OG-metadata
guard fails on the drift.
