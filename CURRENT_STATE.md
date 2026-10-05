# Current onboarding work

Snapshot checked on 2026-10-05. Refresh GitHub metadata and runtime evidence before relying on these status statements later.

The published release is v1.0.7. GitHub main remains `060b3752d064ae04019e5b96e5f503a2e9f633ce`; the onboarding work is local on `fix/deterministic-baseline-onboarding` and has not been deployed or pushed. These facts were read from GitHub's branch/release API and the local Git history.

Start at [ONBOARDING.md](ONBOARDING.md). The intended baseline is bundled voices, Qwen 0.6B, ARM Python, loopback HTTP, and no hooks or cloning tools. The first useful remaining task is live baseline acceptance after owner approval, then one integration from [INTEGRATIONS.md](INTEGRATIONS.md).

| Audit requirement | Repository result | Remaining proof or limitation |
|---|---|---|
| Honest backend readiness | Registered/unselected/loaded/failed state; unavailable Qwen and failed warmup abort startup | Real model startup and successful audible speech |
| Baseline model only | Qwen 0.6B default; explicit experiment selection persisted in generated plists | Real launchd restart with the same selection |
| Fresh installation destinations | Plist generator creates parent directories and escapes XML-sensitive paths; CLI directory created and PATH checked | Fresh macOS install, permissions and launchd behavior |
| Process identity | CLI rejects foreign listeners; preflight verifies owning process plus HTTP identity, and rejects unknown ownership | Live start/stop/recovery |
| Gallery reload | Separate local reload permission enabled by default for installed loopback service; HTTP failures exit nonzero | Live gallery rescan after startup |
| Explicit install scope | Server-only default; opt-in cloning/integrations; read-only preflight; unknown flags rejected | Unattended install on a fresh Mac; sudo may still be required for system CLI directory |
| Integration isolation | Cursor-only shared helpers fixed; non-Claude agents no longer register Claude hooks; per-agent disposable-HOME install/config tests | One final reply speaks once and archives for the selected live integration |
| Current documentation | Integration matrix, Hermes real-artifact contract, current chunk/queue budgets, baseline and privacy boundaries reconciled | Other historical documentation may need further cleanup |
| Reproducibility/platform bounds | mlx-audio compatibility cap retained; documentation distinguishes tested Python from dependency resolution | Full dependency/model revision locks; tested macOS minimum and upper Python runtime bound |

Main includes the persistent-bind changes from PR #119, the real-artifact command-provider delivery contract from PR #121, and the bounded fidelity probe from PR #124. Git history and the corresponding current source verify those capabilities. The probe is diagnostic; it does not fix synthesis fidelity.

GitHub issue [#122](https://github.com/adrianwedd/afterwords/issues/122) remains open for leading-token loss and multi-second silence. PR [#123](https://github.com/adrianwedd/afterwords/pull/123) remains open and unmerged for `configure --speak-full`. Do not treat those proposed flags as available on main or claim acoustic acceptance of #122. These statuses were checked through GitHub's issue/pull API on the snapshot date.

Unit tests and disposable-HOME installer checks cover repository behavior. They do not establish a fresh installation, real MLX compatibility, audible output, live hook execution, or recovery. No installed hook configuration or live service has been changed by this work. STRATEGY.md requires owner approval before running setup against the in-use installation, restarting it, modifying installed hooks, or publishing to main.
