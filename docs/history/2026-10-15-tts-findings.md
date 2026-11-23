# Historical findings: TTS truncation, voice routing and timeout fragility

Date: 2026-10-15 · Found by: Vixen (M5, Hermes vixen profile)

Reconciled 23 November 2026: caller chunking/timeouts and deterministic project
routing are addressed in the trustworthy-voice candidate. The server-level
single-request 96-second cap remains historical evidence and has not been
reproduced against the candidate. This file is evidence, not current status;
see `CURRENT_STATE.md`.
Evidence root: /tmp/tts_budget/ (full.wav, halfA/B.wav, summary.log), /tmp/probe_*.wav, /tmp/claude-tts-server.log

## Defect 1 — /synthesize silent truncation at 96.0 s of audio  (CONFIRMED)
Inputs that would exceed ~96.0 s of audio return HTTP 200 with a valid WAV of
EXACTLY 2,304,000 frames @ 24 kHz; the spoken tail is silently lost.
- probe_900.wav (900 chars)  → 96.0 s (complete — exactly at cap)
- probe_1800.wav (1800 chars) → 96.0 s, DIFFERENT md5, SAME frame count → truncated
Steady-state speech rate ~22 chars/s, so the cap bites around ~2100 raw prose chars
(repetitive probe text hit it sooner).

Likely source: Qwen3-TTS per-call generation budget inside mlx_audio generate
(`backends/qwen3.py` concatenates `out_*.wav` correctly, but no input splitting
occurs for this model — only one segment is produced).

Worse interaction: `scripts/afterwords-tts-command.sh` falls back to **speaking the
whole reply as one chunk** when chunks.py is unresolvable (`CHUNKS=("$CLEANED")`).
In that state any reply whose audio exceeds 96 s loses its tail silently while the
contract still exits 0 — the exact "lie" the script header forbids, via a second route.

Suggested guard (not applied — maintainer's call):
- Backend: flag/413 when produced audio hits the cap, or split input server-side at
  ~800 chars and concatenate.
- Command script: refuse the one-chunk fallback above ~1400 chars; fail loudly.

## Defect 2 — voice resolution nondeterminism between callers  (CONFIRMED)
Gateway-side Hermes TTS calls resolve to DIFFERENT voices per process within one
profile session; observed same day, vixen profile, via server log:
  12:55:57 chars → seven-of-nine · 13:05:36 → seven-of-nine · 16:35:33 → seydoux
while direct shell runs pass voice explicitly and land `vixen`.
Mechanism: gateway supplies empty {voice}; the script falls back to ~/.afterwords
agent-key resolution (hermes → seven-of-nine; vixen → seydoux) which depends on the
launching process environment — same conversation, different voice, no error.
Hermes profile config `tts.voice: vixen` (set 09:50 2026-10-15) never took effect
through the gateway path, though `voice_compatible: true` from the same file did.
Fix candidates (owner's call): pin the vixen agent's line in ~/.afterwords, or fix
why the command provider drops profile tts.voice.

## Defect 3 — 300 s provider timeout fragile under shared-server contention  (OBSERVED)
Steady-state throughput ~0.023 s/char: the full 1,843-char fixture synthesized
end-to-end in 41 s on an idle server (/tmp/tts_budget/, rc=0, 81.7 s audio,
0/40 silent blocks). But the server is SHARED across concurrent Hermes sessions and
serialises synthesis: one ~2,470-char note (13:58–14:04) queued its chunks behind
other sessions' traffic and exceeded the Hermes command-provider 300 s timeout.
The identical pipeline completed fine at 16:28 the same day.
Client-side mitigation shipped 2026-10-15: voice notes ≤ ~1400 chars (fewer chunks
= less queue exposure). Structural options: raise provider timeout, or expose
queue-position so clients back off.

## Honesty log (corrected hypothesis)
Initial hypothesis "throughput ~0.19 s/char, long texts cannot fit 300 s" was WRONG:
the first probes hit a contended/cold server and were ~10x inflated. Disproved by my
own evidence run; true failure mode is contention (Defect 3), not raw throughput.
