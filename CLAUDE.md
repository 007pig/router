@AGENTS.md

# Claude Code

Project-wide instructions live in `AGENTS.md` (imported above) and are shared
with Codex. Put only Claude Code-specific guidance in this file.

- Skills live only in `.agents/skills/`; `.claude/skills` is a symlink to that
  directory. Manage skills there, never under `.claude/skills/` directly.
- Personal, machine-local Claude Code settings belong in
  `.claude/settings.local.json` (git-ignored globally), not in this file.
