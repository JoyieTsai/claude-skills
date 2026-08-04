# Mode B — Auditing an implemented project

Static review of the real UI code. Goal: findings anchored to `file:line` that the user
can act on immediately.

## Step 1 — Scope it

Auditing every file in a large app produces a shallow report. Narrow first:

- If the user named a route, component, or feature → audit that and its dependencies.
- If not → ask which surface matters, or pick the highest-traffic entry points
  (login, home/dashboard, the main list view, the primary form) and **say what you chose**.

Rule of thumb: 3–8 screens or 15–30 components is a real audit. More than that, and you
are skimming — better to go deep on the important surface and say what you skipped.

## Step 2 — Read the design system before the components

You cannot flag an inconsistency without knowing the standard. Read config first:

```bash
# tokens / theme
fd -H -t f '(tailwind|vuetify|nuxt|vite)\.config\.(js|ts|mjs)$' -E node_modules
fd -H -t f '(variables|settings|theme|tokens|_vars)\.(s?css|less)$' -E node_modules
rg -n '^\s*(--[\w-]+|\$[\w-]+)\s*:' --glob '!node_modules' -g '*.{css,scss,less}' | head -60
```

Note the spacing scale, type scale, colour tokens, radius and shadow steps. These are
your comparison baseline for dimension 12.

## Step 3 — Sweep for high-signal patterns

These greps find real bugs fast. Verify each hit in context — many are false positives.

```bash
# --- Accessibility: usually the densest source of true P0/P1 ---
rg -n 'outline:\s*(none|0)' --glob '!node_modules'                 # killed focus ring
rg -n '<img(?![^>]*\balt=)' -P --glob '!node_modules'              # missing alt
rg -n 'onClick|@click' --glob '!node_modules' -g '*.{vue,jsx,tsx,html}' \
   | rg -v '<(button|a|input|select|textarea|v-btn|VBtn|NuxtLink|RouterLink)'  # non-semantic clickable
rg -n 'tabindex=["\x27]-?[1-9]' --glob '!node_modules'             # tabindex hacks
rg -n 'placeholder=' --glob '!node_modules' -g '*.{vue,jsx,tsx,html}'  # then check each has a real label
rg -n 'aria-hidden' --glob '!node_modules'                         # hiding focusable content?
rg -n 'user-select:\s*none' --glob '!node_modules'

# --- Hardcoded values that should be tokens ---
rg -n '#[0-9a-fA-F]{3,8}\b' --glob '!node_modules' -g '*.{vue,jsx,tsx,css,scss}' | head -50
rg -n ':\s*\d+px' --glob '!node_modules' -g '*.{css,scss,vue}' | head -60

# --- Layout fragility ---
rg -n '\bwidth:\s*\d{3,}px|\bheight:\s*\d{3,}px' --glob '!node_modules'   # fixed dims
rg -n 'white-space:\s*nowrap|overflow:\s*hidden' --glob '!node_modules'
rg -n 'z-index:\s*\d{3,}' --glob '!node_modules'                   # stacking chaos
rg -n 'position:\s*absolute' --glob '!node_modules' -c             # density signal

# --- Escape hatches = design-system drift ---
rg -n '!important' --glob '!node_modules' -c
rg -n ':deep\(|::v-deep|/deep/' --glob '!node_modules'

# --- Missing states ---
rg -n 'v-if|useState|isLoading|loading' --glob '!node_modules' -g '*.{vue,jsx,tsx}' | head -40
rg -n 'await |\.then\(' --glob '!node_modules' -g '*.{vue,jsx,tsx}' | head -40
# ^ for each async call: is there a loading state? an error state? a disabled submit?

# --- Motion safety ---
rg -n 'prefers-reduced-motion' --glob '!node_modules'   # absence in an animated app is a finding
rg -n 'transition|animation' --glob '!node_modules' -g '*.{css,scss}' -c
```

If `rg`/`fd` are unavailable, fall back to `grep -rn` / `find`.

## Step 4 — Read the components properly

Greps find symptoms; reading finds causes. For each in-scope component, read the whole
file and check:

- **Semantics** — right element for the job, heading levels correct, landmarks present.
- **All five interactive states** — especially focus. Trace where the style comes from;
  it may be global (`assets/main.css`, a reset, the UI library's defaults). Do not report
  "no focus style" without checking the global layer.
- **Async completeness** — for every request: loading indicator, error surface,
  empty result, double-submit guard. This is where most real P1s live.
- **Responsive behaviour** — does it depend on a fixed width? What happens at 360px?
- **Form correctness** — label association, `type`/`inputmode`/`autocomplete`, error
  placement and announcement.
- **Token use vs hardcoded values** — compare against Step 2's baseline.

## Stack-specific notes

**Vue / Nuxt / Vuetify**
- Vuetify gives you a11y and focus states largely for free — check whether they've been
  overridden with `:deep()` or `!important`. Heavy deep-selector use is a finding in itself.
- `v-model` on custom components: does it handle the invalid/error state?
- Prefer Vuetify's `density`, `variant`, `color` props over custom CSS; overriding
  suggests the wrong component was chosen.
- Nuxt: check `<Head>`/`useHead` for `title` and `lang`; `<NuxtLink>` vs raw `<a>` for
  internal routes.
- Watch for `v-html` (both XSS and unstyled-content risk).

**React / Tailwind**
- Long utility strings hide inconsistency — extract and compare the actual values across
  sibling components. Two cards with `p-4` and `p-5` for the same role is dimension 12.
- Check for arbitrary values (`w-[327px]`, `text-[13px]`) — these bypass the scale.
- `focus:outline-none` without `focus-visible:ring-*` is a P0.
- Conditional class strings: verify every branch produces a valid, contrasting result —
  especially disabled and error variants.
- Component libraries (Radix, Headless UI, shadcn) handle focus trap and ARIA; hand-rolled
  modals/dropdowns usually don't. Check which you have.

**Bootstrap**
- Verify utility classes exist in the version in use (v4 vs v5 renamed many: `ml-*` →
  `ms-*`, `.form-group` removed). A typo'd class silently does nothing — a real and
  invisible bug.
- `.sr-only` (v4) vs `.visually-hidden` (v5).

**Plain HTML/CSS**
- Check the reset/normalize doesn't strip focus outlines.
- Check `<meta name="viewport" content="width=device-width, initial-scale=1">` exists and
  does not set `maximum-scale=1` or `user-scalable=no` (blocks zoom — an a11y failure).

## Step 5 — Optional live verification

Run `scripts/capture.mjs` (see SKILL.md) if the app starts. Screenshots catch what code
review cannot: actual rendered spacing, overflow at 360px, real computed contrast, and
whether the page even looks like the design.

Read the resulting PNGs. Cross-check axe findings against your static ones — agreement
raises confidence; a static finding the browser contradicts should be dropped.

## What not to report

- Anything already handled globally that you didn't check for.
- Code-quality issues with no user-facing effect (naming, file structure, dead CSS) —
  out of scope; that's a code review.
- Framework defaults presented as the team's mistakes.
- A long list of hardcoded hex values as separate findings. Collapse into one finding:
  "N hardcoded colours bypass the theme — here are the 5 worst and the full list."
