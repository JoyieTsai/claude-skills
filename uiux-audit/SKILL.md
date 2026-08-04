---
name: uiux-audit
description: Audit UI/UX quality and produce a prioritised findings report. Two modes — (A) review design files (Figma exports, screenshots, mockups, images of a UI) and (B) audit a project's implemented UI (static code review of templates/CSS/components, plus optional live browser screenshots and axe-core a11y scan). Use when asked to "audit UI", "review UX", "check accessibility", "看一下這個設計", "審查介面", "UI/UX 檢查", "review this mockup", "why does this page look off", or before shipping a redesign. Stack-agnostic — works with Vue/Nuxt/Vuetify, React/Tailwind, Bootstrap, or plain HTML/CSS.
---

# UI/UX Audit

Produce a **prioritised, evidence-backed** audit. Every finding must cite a concrete
location (file:line, or a region of an image) and state what to change. No vague advice.

## Step 1 — Pick the mode

| Signal | Mode |
|---|---|
| User attaches/points to an image, Figma export, PDF, mockup, screenshot | **A — Design review** |
| User points at a repo, route, component, or says "this project/page" | **B — Project audit** |
| Both are available | Run **B**, and use the design as the intended-state reference (design-vs-built diff) |

If genuinely ambiguous, ask once. Otherwise pick and proceed.

## Step 2 — Establish the baseline (do not skip)

An audit without context produces generic advice. Before judging anything, determine:

1. **What is this screen for?** The primary user task. A finding only matters if it
   obstructs that task.
2. **Who uses it?** Internal admin tool vs public marketing site vs mobile web have
   different bars. Ask the user if not inferable.
3. **What is the existing system?** Read the design tokens / theme config / utility
   config *first*, so you flag deviations from *their* system rather than imposing yours.
   - Vuetify: `vuetify.config.*`, `theme` in `nuxt.config.*`, `settings.scss`
   - Tailwind: `tailwind.config.*`, `@theme` in CSS, `index.css`
   - Bootstrap: `_variables.scss`, `custom.scss`
   - Plain: `:root` custom properties
4. **Is there a stated design intent?** `CLAUDE.md`, `README`, design docs, style guide.

State the baseline in one short paragraph at the top of the report. If you had to
assume something, say so there.

## Step 3 — Audit against the rubric

Read `references/rubric.md` — 12 dimensions, each with concrete checks and thresholds.
Work through it; do not freestyle. Then:

- **Mode A** → also read `references/design-review.md`
- **Mode B** → also read `references/code-audit.md`

Cover every dimension. If a dimension is not applicable or you could not assess it
(e.g. hover states are invisible in a static image), say so explicitly rather than
staying silent — silence reads as "checked, fine".

## Step 4 — Verify before reporting

Weak audits are full of plausible-but-wrong findings. Before writing each one:

- **Re-read the source.** Confirm the line still says what you think. Contrast ratios:
  compute them, don't eyeball — see `scripts/contrast.mjs`.
- **Check for an existing answer.** A missing focus style may be handled globally; a
  hardcoded colour may be an intentional one-off. Grep before claiming.
- **Ask "so what?"** If you cannot name a user who is blocked, slowed, or confused,
  it is P3 at best — or not a finding.

Drop anything that fails these. A short report of real problems beats a long one
padded with noise.

## Step 5 — Report

Write to `UIUX-AUDIT.md` in the project root (Mode B) or the directory holding the
design file (Mode A). If the file exists, overwrite it but preserve any section titled
`## Decisions` — that is the user's.

Use the structure in `references/report-template.md`. Severity:

| | Meaning | Bar |
|---|---|---|
| **P0** | Blocks a user from completing the primary task, or a legal/a11y violation | Fix before ship |
| **P1** | Task is completable but materially harder, slower, or error-prone | Fix this cycle |
| **P2** | Inconsistency or friction a user would notice but work around | Backlog |
| **P3** | Polish; no behavioural impact | Optional |

Rules:
- Order by severity, then by blast radius (shared component > single page).
- Cap at ~20 findings. If there are more, group repeated instances into one finding
  with a list of locations, and say how many you collapsed.
- Never invent a severity to pad the top. An audit that finds no P0 should say
  "No P0 findings" — that is a valid, useful result.

Then in chat: give the count by severity, the 3 findings you'd fix first, and the
report path. Do not paste the whole report into chat.

## Step 6 — Fixing (only if asked)

Do not edit code during the audit; the report is the deliverable. If the user then
asks for fixes, prefer this order and confirm before the risky tiers:

1. **Safe** — add `alt`, `aria-label`, `label` association, `focus-visible`, `lang`,
   `autocomplete`, touch-target padding, `width`/`height` on `<img>`. Apply freely.
2. **Token swaps** — replace a hardcoded value with the existing token. Apply freely,
   but verify the token resolves to a visually equivalent value.
3. **Visual changes** — spacing, type scale, colour, layout. These change how the
   product looks. Confirm scope with the user first.
4. **Structural** — component splits, flow reordering, new states. Propose, don't do.

After tier 1–2 edits, re-run the relevant check to confirm the fix landed.

## Optional — Live browser evidence (Mode B)

Static review misses rendered spacing, overflow, and real contrast. If the app can be
started, `scripts/capture.mjs` screenshots routes at 4 breakpoints and runs axe-core.

```bash
# 1. start the dev server yourself (npm run dev / nuxt dev / vite) and note the URL
# 2. then:
node ~/.claude/skills/uiux-audit/scripts/capture.mjs \
  --url http://localhost:3000 \
  --routes /,/login,/dashboard \
  --out ./.uiux-audit
```

It writes PNGs plus `axe-report.json`. **Read the PNGs with the Read tool** — that is
the point; the files alone prove nothing. Treat axe output as leads to verify, not
findings to copy: it has false positives, and it catches maybe a third of real a11y
problems. Keyboard-only navigation and focus order still need your judgement.

If the server won't start, say so and deliver the static audit. Don't stall on it.
