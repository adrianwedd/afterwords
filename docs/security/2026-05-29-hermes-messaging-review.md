# Security Review — Hermes Messaging Integration

**Date:** 2026-05-29
**Reviewer:** Claude Code (`/security-review`, meticulous/whole-repository pass)
**Scope:** Uncommitted working-tree changes introducing TTS audio delivery to Discord/Telegram, plus untracked redesign and cache artifacts.
**Result:** ✅ **No HIGH or MEDIUM confidence (≥8) exploitable vulnerabilities found.**

---

## Files reviewed

| File | Status | Nature of change |
|------|--------|------------------|
| `scripts/afterwords-post-llm.sh` | modified | Platform routing — synthesize + send audio to Discord/Telegram as attachments |
| `scripts/afterwords-tts-command.sh` | modified | Slug-derived archive filenames |
| `scripts/strip-markdown.py` | modified | New footer-stripping regex |
| `scripts/tts-feed-send.py` | new | Archive watcher that forwards new MP3s to Discord/Telegram via `hermes send` |
| `afterwords-redesign/*.html` | new (untracked) | Static GitHub Pages redesign surfaces (mockups) |
| `.wrangler/cache/*.json` | new (untracked) | Cloudflare CLI cache (account ID only) |

---

## Threat model

The only externally-influenceable input on these paths is the **LLM response text**, which on a Hermes gateway originates from a remote Discord/Telegram user prompting the model. The review traced that text from ingress to every sink (subprocess args, URLs, filenames, DOM).

## Data-flow findings (all neutralized)

- **Command injection — not present.** Response text reaches `python3` only via stdin (`printf | python3`) or as a quoted `argv[1]`; it is never interpolated into a shell command string. `tts-feed-send.py` invokes every subprocess with list-form args (no `shell=True`).
- **Path traversal / filename injection — not present.** Every archive filename is built from a `SLUG` whitelisted to `[a-z0-9-]` and capped at 60 chars (`re.sub(r'[^a-z0-9]+','-',...)`), plus a timestamp. `/`, `.`, and `..` cannot survive.
- **SSRF — not present.** The only outbound HTTP target is the hardcoded loopback `http://127.0.0.1:7860/synthesize`; the attacker controls neither host nor protocol, only the URL-encoded `text` query parameter.
- **XSS — not present.** The lone `innerHTML` write (`afterwords-redesign/Email Templates.html:420`) interpolates a hardcoded constant (`tpl.subject`). The dashboard is a React mockup (auto-escaping, `MOCK_KEY`, no live backend). No attacker-controlled value reaches a DOM sink.
- **ffmpeg concat-demuxer injection — not reachable.** `tts-feed-send.py:79` embeds `c.absolute()` paths into a `-safe 0` concat file. Quote-breakout would require an attacker-named file in `~/.hermes`/`~/.claude/tts-archive`, i.e. pre-existing local write access. Filenames the system writes are sanitized slugs.
- **Secrets — none exposed.** `.wrangler/cache/wrangler-account.json` holds a Cloudflare *account ID* (an identifier, not a credential or API token).

## Noted (not a vulnerability — design surprise, tracked in Sprint 3)

The CLI tail of `afterwords-post-llm.sh` (lines 239–283) broadcasts every local assistant response to the user's Discord **and** Telegram whenever any `.afterwords` file is present — repurposing a local-playback config as an egress trigger. The destination is the user's *own* configured channels and the behavior is opt-in via that file, so it is **not** an externally-exploitable vulnerability. It is, however, a confused-deputy / least-surprise concern and is addressed as a hardening item in the Sprint 3 plan (gate egress behind an explicit `send_to:` directive rather than mere file presence).

## Conclusion

The messaging integration handles untrusted text correctly: URL-encoding before HTTP, whitelist slugging before filesystem use, and list-form subprocess calls throughout. No finding cleared the confidence-8 reporting threshold. The egress-on-file-presence behavior is a design item, not a security defect, and is folded into the next sprint.
