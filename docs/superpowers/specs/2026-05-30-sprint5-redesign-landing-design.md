# Sprint 5 — Land the redesign

**Date:** 2026-05-30
**Status:** Design — awaiting user review
**Repos touched:** `afterwords-cloud` (Astro), `afterwords-app` (static). NOT `afterwords`.

## Goal

Land the finished 29-May design surfaces onto their live targets so the
afterwords-cloud and afterwords-app web surfaces match the agreed design system.
This is **visual/layout/copy reconciliation of pages that already exist and
already share the design tokens** — not a rebuild, and not new functionality.

Source mockups (untracked reference, staged in `afterwords/afterwords-redesign/`):

| Mockup file | Live target | Repo |
|---|---|---|
| `Surface 2a - cloud landing.html` | `dashboard/src/pages/index.astro` | afterwords-cloud |
| `Surface 2c - api docs.html` | `dashboard/src/pages/docs.astro` | afterwords-cloud |
| `Surface 2b - dashboard.html` | `dashboard/src/pages/dashboard/index.astro` + React islands | afterwords-cloud |
| `Surface 3 - afterwords app.html` | `docs/index.html` | afterwords-app |

**Out of scope:** Surface 1 (`afterwords/docs/index.html`) — already landed and
ahead of its mockup (live has corrected 98/275 counts and current URLs; the
mockup is the stale copy). Do not touch it.

## Approach (decided: A — in-place reconciliation)

For each page: open the live source and the mockup side-by-side, enumerate the
**visual/layout/copy/spacing deltas only**, and apply them to the existing source.
The mockup is the *visual spec*, never a file to copy wholesale. Rejected
alternatives: B (rebuild-from-mockup-then-rewire — throws away working code,
risks the live dashboard) and C (component-extraction refactor — scope creep into
architecture work).

The design tokens (`#1C1C1A`, `#EDE8DF`, copper `#B87333`, the full palette in
`dashboard/src/layouts/Base.astro`) already match the mockups across all five
pages. **No token changes.**

### Authority rules (decided)

1. **Mockup = visual authority only.** Layout, spacing, component arrangement,
   styling come from the mockup.
2. **Live data wins for copy.** Voice counts, profile counts, URLs, and any
   factual figures come from the current live pages, never the mockup — the
   mockups carry the stale `296 voices / 100` drift and old URLs that Surface 1
   already corrected. Do not re-introduce it.
3. **Live behavior wins over mockup, with a flag.** Where a mockup contradicts
   shipped reality (e.g. pricing tiers vs. the billing/rate-limiting that already
   shipped), keep the live truth and record the conflict in an
   "Open conflicts" note for user review. Do not change product behavior to match
   a mockup.

## Part A — afterwords-cloud (Astro)

Order: **2a → 2c → 2b** (cheapest/safest first, riskiest last).

### A1. Surface 2a — landing (`pages/index.astro`, ~201 ln)

Hero/sections/headings already align. **Pricing is the conflict (see C-1):** live
is **two-tier** (Hobby $5/mo + Pro $20/mo "Coming soon"); the mockup is single-tier
("One tier. No surprises."). Per authority rule 3 (live behavior wins), the live
two-tier layout and the `"Simple, transparent pricing."` heading **stay** — the
mockup's single-tier heading and single-card layout are **rejected**, because
applying them would delete a shipped tier. Apply only the non-pricing visual
deltas (spacing/section polish). Also see C-2 (1.7b copy) and C-3 (checkout CTA),
which surface on this page but are out of scope for visual landing. Static page,
no React mounts.

### A2. Surface 2c — API docs (`pages/docs.astro`, ~538 ln)

Both live and mockup are large (538 vs 593 ln) with differing heading structure;
the precise delta is enumerated at implementation time via a page-level diff.
Static page. Keep all documented endpoints/params accurate to the live API —
`openapi.yaml` is the source of truth, not the mockup. Note C-2: live `docs.astro`
examples reference `qwen3-1.7b` in several places (health backends list, the
`backend` enum description, a curl example, a JSON response), but `openapi.yaml`
states only `qwen3-0.6b` is accepted at launch. The docs examples are factually
wrong against the live API; **correcting them to 0.6b is in scope** (C-2 resolved
in scope).

### A3. Surface 2b — dashboard (highest care)

**Actual live structure** (corrected after QA — there are no Astro islands and no
`client:*` directives). The dashboard is **two route-level React `createRoot`
mounts**:

- `pages/dashboard/index.astro` (~247 ln) → `#dashboard-root`, renders a single
  monolithic `Dashboard()` component composing `ApiKeyInput`, `VoiceList`,
  `UsageGraph`, `CodeSnippets`, `KeyDisplay`, all calling `lib/api.ts`.
- `pages/dashboard/voices/new.astro` → `#upload-root`, renders `VoiceUpload`
  (`pages/dashboard/voices/[id].astro` also exists).

**Architecture-mismatch caveat (C-4):** the Surface 2b mockup depicts a
*different app* — multi-route with signup/key-gate/poller components that were
never built. It is **not** a cosmetic variant of the live dashboard. So 2b is
**partial visual reconciliation**: restyle only the sections that actually exist
in the live pages (key entry, voice list, usage, code snippets, upload).
Mockup-only routes/sections/components are explicitly **excluded** — do not build
them.

**Hard rule — untouchable:** the `createRoot` mount points (`#dashboard-root`,
`#upload-root`), the `Dashboard()` / `VoiceUpload` component trees and their props,
every form, and every `lib/api.ts` call. Only surrounding markup and styling may
change. If a mockup layout can't be reached without altering a mount point or a
component's props, stop and flag it rather than rewiring.

## Part B — afterwords-app (static)

### B1. Surface 3 — app site (`docs/index.html`, ~418 ln)

Static GitHub Pages site; nothing functional to preserve. Reconcile against the
331-ln Surface 3 mockup under the same authority rules (live data wins for counts
and download/release URLs). Lower risk than Part A.

## Verification

| Gate | Part A (cloud) | Part B (app) |
|---|---|---|
| Build | `astro build` from `dashboard/` passes (verified green, ~3.9s) | n/a (static) |
| Tests | `npm test` in `api/` stays green (**89** tests / 11 files, verified). **`dashboard/` has no test script** — no automated coverage on the surfaces being changed. | n/a |
| Visual | each page checked side-by-side vs its mockup | page checked vs Surface 3 |
| Functional (manual) | 2b: the two React roots (`#dashboard-root`, `#upload-root`) still render; live-API smoke test (key entry → voice list → usage → upload round-trip vs the live Worker) succeeds. Manual only — no dashboard tests exist. | links resolve |
| No data drift | counts/URLs/backend match live truth, not the mockup | same |

A page is "landed" only when its build + visual gates pass, the 2b functional
gate passes (manual), and every relevant Open conflict is resolved or
user-acknowledged. Because the dashboard has zero automated tests, the functional
gate for 2b is entirely manual and is the primary safety net — treat it as
mandatory, not optional.

## Deliverables & placement

- This sprint design doc lives here in `afterwords` (consistent with prior sprints).
- **Implementation plans live with the code** they drive:
  - `afterwords-cloud/docs/superpowers/plans/2026-05-30-sprint5-cloud.md` (Part A)
  - `afterwords-app/docs/superpowers/plans/2026-05-30-sprint5-app.md` (Part B)
- The `afterwords-redesign/` folder stays untracked — reference, not a deliverable.
- Each repo ships its own commit(s); no cross-repo coupling. Cloud is deployed via
  CF Pages; the app site via GitHub Pages.

## Open conflicts

Surfaced by codex + hermes QA (2026-05-30), verified against the live repos, and
**resolved by user decision 2026-05-30** (C-1, C-4, C-2 below).

- **C-1 (RESOLVED) — pricing tiers, Surface 2a.** Live `index.astro` has two tiers
  (Hobby $5/mo + Pro $20/mo "Coming soon"); the mockup shows one. **Decision: keep
  the live two-tier layout and `"Simple, transparent pricing."` heading.** The
  mockup's single-tier change is rejected — do not drop the shipped Pro tier.

- **C-4 (RESOLVED) — dashboard architecture mismatch, Surface 2b.** The 2b mockup
  is a different, never-built app (multi-route signup/key-gate/poller). **Decision:
  2b is partial visual reconciliation** of the sections that exist live; mockup-only
  routes/components are out of scope. No dashboard rebuild this sprint.

- **C-2 (RESOLVED — now IN SCOPE) — 1.7b backend drift, Surfaces 2a + 2c.** Live
  landing and docs market/example `qwen3-1.7b` in 5+ places, but `openapi.yaml`
  accepts only `qwen3-0.6b` at launch (1.7b rejected). **Decision: correct all 1.7b
  references to 0.6b** as part of this sprint (landing pricing copy + docs health
  list, enum description, curl example, JSON response). Truth-fix the user-facing
  copy to match the live API.

- **C-3 (pre-existing functional bug, out of scope) — checkout CTA, Surface 2a.**
  The pricing forms POST a hidden `price_id` to `/v1/checkout`, but `openapi.yaml`
  defines `/v1/checkout` as an email-based request returning `url` (the `/signup`
  flow). The CTA may be broken independent of the redesign. *Resolution:* note
  only; fixing the checkout flow is its own task, not this visual sprint. Flagged
  for separate triage.

- **C-5 (MINOR) — token naming, Surface 3.** `afterwords-app/docs/index.html`
  re-declares the palette with shorthand names (`--bg`, `--fg-m`, `--acc`) vs
  `Base.astro`'s `--color-*`. Cosmetic; no action required, noted for parity
  awareness.

## Sequencing

Part A (2a → 2c → 2b) fully landed and verified before Part B. Each part is an
independent commit cycle in its own repo; no shared state between them.
