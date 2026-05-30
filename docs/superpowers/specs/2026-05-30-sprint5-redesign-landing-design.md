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

Near-identical to the mockup already (same hero, sections, headings). Known
delta: pricing-section heading `"Simple, transparent pricing."` →
`"One tier. No surprises."` — apply **only if** it does not contradict live
pricing (authority rule 3; if live billing is multi-tier, keep live copy and flag
it). Enumerate and apply any remaining spacing/section deltas. Static page, no
islands.

### A2. Surface 2c — API docs (`pages/docs.astro`, ~538 ln)

Both live and mockup are large (538 vs 593 ln) with differing heading structure;
the precise delta is enumerated at implementation time via a page-level diff.
Static page. Keep all documented endpoints/params accurate to the live API
(`openapi.yaml` is the source of truth for API facts, not the mockup).

### A3. Surface 2b — dashboard (`pages/dashboard/index.astro` + islands)

Highest care. The live dashboard runs **6 React islands wired to `lib/api.ts`**:
`VoiceUpload`, `VoiceList`, `UsageGraph`, `KeyDisplay`, `ApiKeyInput`,
`CodeSnippets`. The mockup is a single static 709-ln HTML.

**Hard rule — untouchable:** the islands, their `client:*` directives, their
props/mount points, every form, and every `lib/api.ts` call. Only the surrounding
markup and styling may change. Any layout port that would alter an island's props
or mount point is rejected; if the mockup's layout cannot be achieved without
touching an island boundary, stop and flag it rather than rewiring.

## Part B — afterwords-app (static)

### B1. Surface 3 — app site (`docs/index.html`, ~418 ln)

Static GitHub Pages site; nothing functional to preserve. Reconcile against the
331-ln Surface 3 mockup under the same authority rules (live data wins for counts
and download/release URLs). Lower risk than Part A.

## Verification

| Gate | Part A (cloud) | Part B (app) |
|---|---|---|
| Build | `astro build` passes (`dashboard/`) | n/a (static) |
| Tests | `npm test` in `api/` stays green (~59) | n/a |
| Visual | each page checked side-by-side vs its mockup | page checked vs Surface 3 |
| Functional | 2b islands hydrate; live-API smoke test (upload/list/usage round-trip vs the live Worker) succeeds | links resolve |
| No data drift | counts/URLs match live truth, not the mockup | same |

A page is "landed" only when its build, visual, and (for 2b) functional gates all
pass and the "Open conflicts" note is either empty or acknowledged by the user.

## Deliverables & placement

- This sprint design doc lives here in `afterwords` (consistent with prior sprints).
- **Implementation plans live with the code** they drive:
  - `afterwords-cloud/docs/superpowers/plans/2026-05-30-sprint5-cloud.md` (Part A)
  - `afterwords-app/docs/superpowers/plans/2026-05-30-sprint5-app.md` (Part B)
- The `afterwords-redesign/` folder stays untracked — reference, not a deliverable.
- Each repo ships its own commit(s); no cross-repo coupling. Cloud is deployed via
  CF Pages; the app site via GitHub Pages.

## Open conflicts

(Populated during implementation when a mockup contradicts live reality — e.g.
pricing tiers, endpoint shapes, voice counts. Each entry: page, what the mockup
shows, what's live, the resolution taken. Empty at design time.)

## Sequencing

Part A (2a → 2c → 2b) fully landed and verified before Part B. Each part is an
independent commit cycle in its own repo; no shared state between them.
