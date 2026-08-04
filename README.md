# claude-skills

Personal [Claude Code](https://claude.com/claude-code) skills, shared across machines.

**This repo *is* `~/.claude/skills/`.** Each top-level directory is one skill, which is
exactly where Claude Code looks for them — so there are no symlinks and no configuration.

## Skills

| Skill | What it does |
|---|---|
| [`uiux-audit`](uiux-audit/) | Audits UI/UX quality — design files or implemented code — and produces a prioritised findings report. Includes a WCAG contrast calculator and a Playwright screenshot + axe-core scanner. |

## Set up on a new machine

If `~/.claude/skills/` doesn't exist yet:

```bash
git clone <this-repo-url> ~/.claude/skills
```

If it already exists with skills you want to keep, clone elsewhere and move them in:

```bash
git clone <this-repo-url> ~/claude-skills
mv ~/claude-skills/* ~/claude-skills/.git* ~/.claude/skills/
```

Then run any per-skill install scripts (only needed for skills with dependencies):

```bash
bash ~/.claude/skills/uiux-audit/install.sh   # optional: enables browser capture
```

Verify with `/skills` in Claude Code.

## Adding a skill

```
~/.claude/skills/<skill-name>/
└── SKILL.md          # required: YAML frontmatter with `name` and `description`
```

The `description` is what Claude matches against to decide when to load the skill, so make
it concrete about *when* to use it, not just what it is. Everything else is optional:
`references/` for detail loaded on demand, `scripts/` for executable helpers.

Keep `SKILL.md` short — it's the always-loaded part. Push depth into `references/` and have
`SKILL.md` point at it.

## Conventions

- **No hardcoded absolute paths.** Resolve relative to the script (`import.meta.dirname`)
  so a skill works regardless of where the repo is cloned.
- **Dependencies stay inside the skill's own directory**, gitignored, installed by its own
  script. Never assume a global install.
- **Commit lockfiles** so every machine resolves the same versions.
- **A skill should degrade gracefully.** If an optional dependency is missing, say so and
  continue with reduced function rather than failing outright.

## Syncing

`git pull` on each machine. Dependencies aren't tracked, so after pulling a skill that
gained one, re-run its install script.
