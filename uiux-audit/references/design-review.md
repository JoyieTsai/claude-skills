# Mode A — Reviewing design files

Input is an image, PDF, Figma export, or mockup. You are judging **intent**, before
implementation cost is sunk. This is the cheapest possible moment to catch a problem.

## Read the file properly first

Use the Read tool on each image. For PDFs, use the `pages` parameter. If given a folder,
list it and read every screen — reviewing one frame of a five-frame flow produces
misleading conclusions about navigation and consistency.

If the user gives a Figma *link* rather than a file, you cannot see it. Say so and ask
for an export (PNG at 2x, or PDF). Don't guess from the URL or the layer names.

## Look before you judge

Describe what you actually see, to yourself, before evaluating: screen type, the visible
elements, the apparent primary action. This forces genuine observation rather than
pattern-matching to a generic "here are 10 UI tips" response — which is the main failure
mode of design review.

## Then apply the rubric, with these adjustments

Some dimensions can't be assessed from a static image. Be explicit about which.

| Dimension | In a static design |
|---|---|
| Hierarchy, spacing, typography, colour, layout, content, consistency | **Fully assessable** — this is where to focus |
| Interactive states | Only if the designer drew them. If absent, that *is* the finding: "no hover/focus/disabled states specified — implementation will invent them" |
| Responsiveness | Only if multiple breakpoints provided. If one desktop frame only, flag: "mobile layout unspecified" and note which elements will be hardest to reflow (wide tables, multi-column, fixed-width sidebars) |
| Feedback, loading, empty, error states | Usually missing from designs. Name the specific missing states for each async surface — this is one of the highest-value findings you can give |
| Keyboard/screen-reader a11y | Not assessable. Say so. Contrast and target size *are* assessable |

## Measuring from an image

You can estimate, but be honest about precision:

- **Contrast:** you can read colours off the image with reasonable accuracy. Compute the
  ratio with `scripts/contrast.mjs` and report the number. If the sample is over a
  gradient, photo, or transparency, say the value is approximate.
- **Spacing:** relative comparisons are reliable ("the gap above this label is visibly
  larger than below it"); absolute pixel values are not, unless the export scale is known.
  Prefer stating the *relationship* that's wrong.
- **Touch targets:** estimate from the ratio to known elements (body text height, a
  standard 44px row). Flag anything that looks under ~40px on a mobile frame.

Never state a fabricated precise number. "Roughly 12px, under the 44px minimum" is
honest; "exactly 11.5px" from a screenshot is not.

## Design-specific checks not in the main rubric

- **Content realism.** Does it use real-length content, or convenient short strings? Ask:
  what happens with a 60-character product name, an empty list, 400 rows, a user with no
  avatar, a number in the millions? Designs built on ideal data break on contact with
  production. This is consistently the most valuable finding in a design review.
- **Localisation headroom.** German/French run ~30% longer than English; CJK is shorter
  but taller. Tight-fitting buttons and fixed-width labels will break. Relevant for these
  projects specifically, which mix Chinese and English.
- **State coverage per surface.** For each list, form, and async panel, ask whether
  loading / empty / error / partial / too-many were designed. Enumerate the gaps.
- **Implementation cost flags.** Call out where the design will be expensive or fragile:
  custom scrollbars, non-standard form controls, text over uncontrolled imagery,
  pixel-perfect overlaps, anything requiring a bespoke component where the existing
  library has one that's close.
- **Deviation from their own system.** If the project has a design system (Vuetify,
  Tailwind config, Bootstrap theme), check whether the design's values are reachable
  with existing tokens, or whether it silently introduces a new grey, a new radius, a
  new shadow. Each new value is ongoing maintenance cost.

## Design-vs-built diff

When you have both a design and its implementation, additionally report divergences —
and characterise each one, because not all divergence is error:

- **Regression** — built version is worse (wrong spacing, dropped state, weaker contrast)
- **Improvement** — built version solved something the design missed; consider updating the design
- **Deliberate** — a documented constraint or platform convention; note and move on

Focus on divergences that change behaviour or accessibility. A 2px padding difference is
not worth a line in the report unless it breaks alignment with something adjacent.

## Reporting

Same template and severity scale as Mode B. For location, reference the frame and region
instead of file:line — e.g. `login.png — email field, mid-left` or
`checkout-flow.pdf p.3 — order summary card`. Be specific enough that the user can find
it without hunting.
