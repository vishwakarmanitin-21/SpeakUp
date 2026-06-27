# CLAUDE.md — Speak-up

Voice-to-structured-text desktop overlay app.

## OpenClaw Project Memory

For full project history, decisions, and current state, read `C:/Users/Nitin/.openclaw/workspace/memory/projects/speak-up.md` at the start of non-trivial sessions. That file is the canonical durable record maintained by OpenClaw agents. Local Claude Code memory (auto-managed) captures codebase patterns and conventions — complementary, not competing.

### Reverse Bridge: Direct Session → OpenClaw Memory
When this session makes significant decisions (architecture changes, config fixes, workflow changes), write a handoff note to `C:/Users/Nitin/.openclaw/workspace/memory/handoff.md` so OpenClaw's midnight tracker can incorporate it. Format: date, decisions, config changes, memory updates, Lobster action needed.

## Autonomous Mode
Assume permission for file creation, modification, refactoring, and dependency installation.
Do not ask for confirmations unless an action is destructive (deleting files, secrets, system-level changes).

### Documentation & Backlog

- **README.md** is the source of truth for the product — what's built, how it
  works, configuration. Keep it current as features ship.
- **backlog.html** is the single backlog and status tracker (priority-ordered,
  filterable, status saved in-browser). Add new pending work there and update
  each item's status as it progresses.
- The **Notion mirror has been retired** — do not sync to Notion.
  `Requirements.md` is also retired; its backlog moved into `backlog.html`.

### Success Criteria
- Code compiles/runs without errors
- README.md reflects what's implemented
- backlog.html reflects pending work and current status
