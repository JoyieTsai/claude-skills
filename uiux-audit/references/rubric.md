# The 12-dimension rubric

Work through all 12. Each has checks with thresholds — prefer a measurable claim
("14px on a 44px target" ) over an impression ("feels cramped").

---

## 1. Visual hierarchy

The eye should land on the primary action first, without being told.

- Exactly **one** primary action per view. Two competing filled buttons = no primary.
- Size, weight, and colour should agree on what matters. A 32px heading in light grey
  next to 14px bold black text sends conflicting signals.
- Headings must nest correctly (h1 → h2 → h3, no skips). This is both hierarchy and a11y.
- Squint test: blur the screen mentally — do the important blocks still dominate?

**Common failure:** every card has the same visual weight, so the page reads as an
undifferentiated grid and the user scans it linearly instead of jumping to what matters.

---

## 2. Spacing & rhythm

- Spacing should come from a scale (4/8px base, or the project's tokens). Flag
  one-off values: `margin-top: 13px`, `padding: 7px 11px`.
- **Proximity encodes relationship.** A label 16px from its input but 8px from the
  *previous* input is actively misleading.
- Related items must be closer to each other than to unrelated items. This is the single
  most common spacing bug.
- Vertical rhythm: consistent section gaps. Flag alternating 24/40/32/48 with no reason.

**Threshold:** more than ~3 distinct spacing values in one component usually means
no system is being followed.

---

## 3. Typography

- **Scale size:** more than 6–7 distinct font sizes in an app is unmanaged.
- **Line length:** body text at 45–75 characters. Full-width paragraphs on a 1440px
  screen are unreadable — flag any text block without a `max-width`.
- **Line height:** ≥1.4 for body, tighter (1.1–1.25) for large headings. Flag body
  text at 1.0–1.2.
- **Minimum size:** 14px body (16px preferred; 16px on mobile inputs prevents iOS
  zoom-on-focus). Flag 11px or 12px used for anything a user must read.
- Font weight: 300 or lighter for body text on white fails legibility for many users.
- Avoid ALL-CAPS for anything longer than a short label.

---

## 4. Colour & contrast

Compute ratios — do not estimate. Use `scripts/contrast.mjs`.

| Content | WCAG AA minimum |
|---|---|
| Body text (<18.66px, or <24px bold) | **4.5:1** |
| Large text (≥18.66px bold, or ≥24px) | **3:1** |
| UI component borders, icons, focus rings, form outlines | **3:1** |
| Disabled elements | exempt, but should still read as disabled |

- **Colour must never be the only carrier of meaning.** Red/green status dots, "required
  fields in red", chart series distinguished only by hue — all fail for colourblind
  users. Add an icon, label, shape, or pattern.
- Check dark mode separately if it exists; a palette that passes in light often fails
  inverted. Semi-transparent overlays are the usual culprit.
- Placeholder text is very often the worst offender in a codebase — check it.

---

## 5. Layout & responsiveness

Test 360px, 768px, 1024px, 1440px minimum.

- **360px is the real floor** — not 375px. Test it.
- Horizontal scroll at any width is a bug. Usual causes: fixed `width` in px,
  `white-space: nowrap` on long content, wide tables, unconstrained images.
- Fixed heights (`height: 240px`) break when text wraps or a translation is longer.
  Prefer `min-height`.
- Tables: need a responsive strategy (horizontal scroll container, or card layout below
  a breakpoint). A 9-column table on a phone is a broken screen.
- Modals/sheets must fit small viewports and stay scrollable — check that the confirm
  button is reachable at 360×640.
- Content should reflow, not just shrink. Text scaled to 9px is not responsive.

---

## 6. Interactive states

Every interactive element needs all five. Missing states are the most-skipped audit item.

| State | Requirement |
|---|---|
| Default | Looks interactive — affordance is visible without hovering |
| Hover | Visible change (desktop only; never rely on it for information) |
| **Focus** | **Visible ring, ≥3:1 against adjacent colour.** `outline: none` with no replacement is a P0 |
| Active/pressed | Confirms the tap registered |
| Disabled | Visually distinct; ideally explain *why* it's disabled |

- Also: loading state (async actions need a spinner or skeleton and must block
  double-submit), and selected/current state for nav and toggles.
- **Touch targets ≥44×44px** (WCAG 2.5.5 / Apple HIG). A 16px icon button with no
  padding is a P1 on mobile. Includes spacing between adjacent targets.
- Cursor: `pointer` on clickables, and *not* on non-clickables.

---

## 7. Forms

Forms are where users abandon. Audit them hard.

- Every input needs a **persistent visible label**. Placeholder-as-label is a P1 — it
  vanishes on focus, fails a11y, and breaks autofill review.
- Label must be programmatically associated (`for`/`id`, or wrapping `<label>`).
- Errors: **inline, next to the field**, specific ("Password needs 8+ characters" not
  "Invalid input"), and announced via `aria-live` / `aria-describedby`. A single error
  summary at the top of a long form is a P1.
- Validate at the right time: on blur or submit, not on every keystroke while typing.
- Required vs optional must be explicit — mark whichever is rarer, and don't rely on
  colour or a bare asterisk alone.
- Set `type`, `inputmode`, and `autocomplete` (`email`, `tel`, `current-password`…) —
  cheap, big mobile win.
- Never destroy user input on a validation failure or navigation.
- Destructive actions need confirmation *or* undo. Undo is better.

---

## 8. Content & microcopy

- **Button labels must name the action:** "Save changes", not "OK"/"Submit".
- No unexplained jargon or internal system names leaking into the UI.
- Error messages must say what happened *and* what to do next. "Error 500" is a
  failure of the UI, not of the user.
- Consistent terminology — pick "delete" or "remove" and use it everywhere.
- Sentence case for UI text is more readable than Title Case; either is fine, but
  be consistent.
- Truncation must be avoidable: if a name is cut off, expose the full value somewhere
  (tooltip, `title`, expandable).
- Mixed-language UI (common in these projects): check for stray untranslated strings
  and that CJK text has adequate line-height (CJK needs ≥1.5–1.7).

---

## 9. Feedback & system state

Nielsen's first heuristic: the system should always keep the user informed.

- Every async action produces visible feedback within ~100ms, and it must be
  **near the trigger** — a toast in the corner for an inline edit is easy to miss.
- Distinguish the four states properly: loading, empty, error, success. Most UIs
  implement loading and success and forget the other two.
- **Empty states** must explain what goes here and offer the action to create it.
  A blank panel is a dead end.
- Long operations: show progress, not an indefinite spinner. Skeletons that match the
  final layout beat centred spinners (less layout shift).
- Optimistic updates need a rollback path when the request fails.

---

## 10. Navigation & information architecture

- User can always answer: where am I, how do I get back, what else is here.
- Current location is marked in nav (not just by URL).
- Back button and browser history behave sanely; modals shouldn't trap it.
- Destructive or irreversible steps are not adjacent to routine ones.
- Grouping matches user mental models, not the backend schema or team org chart.
- Breadcrumbs for hierarchies more than 2 levels deep.

---

## 11. Accessibility (beyond contrast)

- **Keyboard:** every interactive element reachable by Tab, in a logical order, and
  operable by Enter/Space. `<div onClick>` with no `tabindex`/`role`/key handler is a
  P0 — prefer a real `<button>`.
- **Semantics:** use `<button>`, `<a>`, `<nav>`, `<main>`, `<table>` for their purpose.
  ARIA is a patch for when you can't; native elements are better.
- Images: meaningful ones need descriptive `alt`; decorative ones need `alt=""`.
  Never `alt="image"`.
- Icon-only buttons need an accessible name (`aria-label` or visually-hidden text).
- Focus management: opening a modal moves focus in and traps it; closing returns focus
  to the trigger.
- Dynamic content changes announced (`aria-live="polite"` for status, `assertive` sparingly).
- Respect `prefers-reduced-motion` — required for vestibular safety, and trivial to add.
- Zoom to 200% must not break layout or hide content.
- Page has a `lang` attribute and a unique, descriptive `<title>`.

---

## 12. Consistency & design-system adherence

- Same concept → same component. Three different card styles for the same entity is a
  P2 with wide blast radius.
- Values come from tokens. Hardcoded `#3b82f6` next to a `primary` token is a finding.
- Icon set is uniform in style and weight; don't mix outline and filled arbitrarily.
- Border radius, shadow depth, and transition duration follow a small set of steps.
- Component variants match the library's intended API rather than being overridden with
  `!important` / deep selectors — that's a maintainability smell worth flagging.

---

## Also worth checking (cheap, high value)

- **Perceived performance:** layout shift on load (`width`/`height` on images and
  embeds), unoptimised hero images, fonts causing FOUT/FOIT.
- **Motion:** transitions 150–300ms for UI feedback. >500ms feels sluggish; animating
  `width`/`height`/`top` instead of `transform`/`opacity` causes jank.
- **Z-index sanity:** ad-hoc `z-index: 9999` values indicate a stacking problem that
  will bite later.
- **Text selection / copyability:** don't disable selection on content users need to copy.
