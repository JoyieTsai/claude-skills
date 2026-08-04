# Report template

Copy this structure. Keep it tight — a reader should get the picture from the summary
table alone, and drill down only where they care.

---

```markdown
# UI/UX Audit — <project / screen name>

**Date:** <YYYY-MM-DD>
**Mode:** Design review | Project audit | Both (design-vs-built)
**Scope:** <exactly what was examined — routes, components, or design frames>
**Not covered:** <what you skipped and why — be honest, this protects the reader>

## Baseline

<One paragraph: what this screen is for, who uses it, what design system is in place,
and any assumption you had to make. If the user never told you the audience, say
"assumed internal admin users" rather than silently picking a bar.>

## Summary

| Severity | Count |
|---|---|
| P0 — blocks the task / a11y violation | 0 |
| P1 — materially harder | 0 |
| P2 — noticeable friction | 0 |
| P3 — polish | 0 |

**Fix first:** <the 3 highest-leverage items, one line each — usually not simply the
3 highest-severity ones. Weight by blast radius and effort.>

**Overall:** <2–3 sentences. What is genuinely good here, and what is the one systemic
theme behind most findings. Auditing is not only fault-finding — if the spacing system
is well followed, say so; it tells the user what to protect.>

---

## Findings

### P0-1 · <short imperative title>

- **Where:** `src/components/LoginForm.vue:42-58`  ← or `login.png — email field, mid-left`
- **Dimension:** Interactive states
- **Problem:** <what is wrong, factually. Include the measured value where relevant:
  "contrast 2.8:1, AA requires 4.5:1".>
- **Impact:** <who is affected and how. "Keyboard-only and screen-reader users cannot
  tell which field is focused, making the form unusable without a mouse." If you cannot
  write this sentence convincingly, the finding is not P0.>
- **Fix:** <specific and actionable — the actual property, token, or element to change.
  Include a snippet when it is short and unambiguous.>
- **Effort:** S | M | L

### P1-1 · <title>
...
```

---

## Writing the findings

**Titles** are imperative and specific: "Add visible focus ring to primary buttons",
not "Focus issues" or "Accessibility problem".

**One problem per finding.** If a component has bad contrast *and* no focus state, that
is two findings — they have different fixes and different severities.

**Collapse repetition.** The same missing `alt` across 14 images is one finding listing
14 locations, not 14 findings. Say how many you collapsed.

**Show the measurement.** "Contrast 3.1:1 (AA needs 4.5:1)", "38×38px target (needs
44×44px)", "line-height 1.15 on 15px body text". Numbers make a finding arguable in the
right way — the reader can check you.

**Fixes must be concrete.** Not "improve the spacing" but "change `mt-3` to `mt-6` so the
label groups with its own input rather than the field above". Where the project has a
token for it, name the token.

**Effort:** S = under an hour, one file. M = a few files or a component change.
L = structural, needs design input or a migration.

## Things that weaken a report

- Padding the count with P3 nitpicks to look thorough. The reader loses trust and stops
  reading, including the P0 at the top.
- Findings that just restate a rubric line without evidence from *this* codebase.
- "Consider possibly maybe reviewing whether..." — state the problem and the fix.
- Reporting a preference as a defect. "I would have used a card here" is not a finding.
  If it's a preference, put it in a short `## Suggestions` section at the end, clearly
  separated, or leave it out.
- Silence about what you could not check. Always fill in **Not covered**.
