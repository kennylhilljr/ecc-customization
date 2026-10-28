# Shared skills

User-level skills every agent on this machine can use. `bootstrap.sh` links each folder here into `~/.claude/skills` (Claude Code) and `~/.agents/skills` (Codex and Gemini CLI). Each skill is a folder with a `SKILL.md` (Agent Skills format: `name` and `description` frontmatter, then instructions).

Project-specific skills do not belong here: they live in each repository's `.agents/skills` (templates in `../kit`). Once ctxd's shared skill library is running it becomes the distribution point; this folder stays the backed-up source.

Skills here now (folder name, which is also the link name, then the `name` in its frontmatter):

| Folder | Frontmatter `name` | Use |
| --- | --- | --- |
| `ecc-operator` | `ecc-operator` | Set a repository up for ECC and start, drive or check a milestone run |
| `ears-notation-1.0.0` | `EARS Notation` | Write testable requirements in EARS syntax |
| `prd-synch` | `product-requirements` | Gather requirements and write a PRD; the folder also holds the SDD reference documents and diagrams |
