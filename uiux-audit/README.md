# uiux-audit

A Claude Code skill that audits UI/UX quality and produces a prioritised findings report.

Two modes:

- **Design review** — you point at an image, PDF, or Figma export
- **Project audit** — static review of implemented UI code, with optional live browser
  screenshots and an axe-core accessibility scan

Stack-agnostic: Vue/Nuxt/Vuetify, React/Tailwind, Bootstrap, or plain HTML/CSS.

## Install on another machine

This skill lives in the `claude-skills` repo, which is cloned directly to
`~/.claude/skills/` — see that repo's README for the clone step. The skill itself is
~70KB of Markdown and two Node scripts; `node_modules/` (21MB) and the Playwright browser
cache (~1.6GB) are **not** tracked and are reinstalled per machine.

### Enable browser capture (optional)

```bash
bash ~/.claude/skills/uiux-audit/install.sh
```

Installs `playwright` + `axe-core` into the skill directory and downloads the matching
Chromium build. Idempotent — safe to re-run.

**Everything except `scripts/capture.mjs` works without this step.** Design review, code
audit, and `contrast.mjs` need only Node. Skip it if you don't need screenshots.

### Check it loaded

Start Claude Code and run `/skills` — `uiux-audit` should be listed. Then just ask:

```
audit the login page of this project
審核這個設計 <attach image>
```

## Usage

Ask in plain language; the skill decides which mode applies.

**Design review** — attach or point at an image, PDF, or Figma export. Note that a Figma
*link* isn't readable; export to PNG/PDF first.

**Project audit** — name a route, component, or feature. Scoping it beats "audit
everything", which produces a shallow report.

For live browser evidence, start your dev server first, then say so — the skill won't
launch your project unprompted. It captures at 360/768/1024/1440px and runs axe-core.

Output is `UIUX-AUDIT.md` with findings graded P0–P3. The report is the deliverable; the
skill doesn't edit code unless you then ask it to.

## Requirements

- **Node 20+** — `capture.mjs` uses `import.meta.dirname`. Node 18 works for everything else.
- Nothing else. No global installs, no API keys.

## Layout

```
uiux-audit/
├── SKILL.md                     # the workflow Claude follows
├── install.sh                   # optional dependency bootstrap
├── references/
│   ├── rubric.md                # 12 audit dimensions with concrete thresholds
│   ├── design-review.md         # design-file mode
│   ├── code-audit.md            # code-audit mode, per-stack notes
│   └── report-template.md       # report structure and P0–P3 severity scale
└── scripts/
    ├── contrast.mjs             # WCAG contrast calculator (no deps)
    └── capture.mjs              # screenshots + axe scan (needs install.sh)
```

## Notes for future edits

Two things that are easy to break in `capture.mjs`:

- Playwright's entry point is CJS, so `import { chromium } from 'playwright'` yields
  `undefined`. Read `mod?.chromium ?? mod?.default?.chromium`.
- Each Playwright version pins an exact browser build. After bumping the dependency, run
  `npx playwright install chromium` again or launching fails on a build-number mismatch.
