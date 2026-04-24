# 24-Hour Sprint Plan — 2026-04-24

## Overview

Four features, ordered by dependency. Items 1-2 are coupled (re-clone generates audio for demo site). Items 3-4 are independent.

## Items

### 1. Re-clone flagship voices with `--all-backends` (GH #6)
**Status:** Not started — needs brainstorming answer (A vs B: 3 flagships or all 20)
**Effort:** ~1-2 hours wall time (model inference)
**Prerequisites:** Server running with all 4 backends loaded

Run `clone-voice.sh --all-backends` for selected voices. Generates per-backend slugged profiles (e.g. `picard-qwen3-06b`, `picard-chatterbox`, etc.) sharing the same ref WAV.

### 2. Demo site backend comparison player (GH #7)
**Status:** Not started — needs design (brainstorming was in progress)
**Effort:** ~2-3 hours
**Depends on:** #1 (audio files)

New section in docs/index.html with backend toggle per flagship voice. Also update hero stats (4 backends, ~10 GB peak, 32 GB recommended).

### 3. Hot-reload `/reload` endpoint (GH #8)
**Status:** Not started — needs spec
**Effort:** ~3-4 hours (spec + implement + test)
**Independent**

`POST /reload` re-walks `voices/*.json`, diffs against VOICES, adds/updates/removes under locks. Plus `afterwords reload` CLI.

### 4. Multilingual routing (GH #9)
**Status:** Not started — needs spec (open questions remain)
**Effort:** ~3-4 hours (spec + implement + test)
**Independent**

Optional `lang` param on synthesize endpoints; route to a backend that supports it. `supported_langs` already populated on all backends but not exposed.

## Execution Order

1. Brainstorm items 1+2 together (coupled), then 3 and 4
2. Write specs (possibly combined for 1+2, separate for 3 and 4)
3. Plan and implement via subagent-driven-development

## Open Decisions

- **Item 1:** 3 flagships (A) or all 20 voices (B)? Recommend A — focused, faster, sufficient for demo.
- **Item 4:** Automatic lang routing or opt-in? Needs brainstorming.
