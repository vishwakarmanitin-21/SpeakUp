# CLAUDE.md — Speak-up

Voice-to-structured-text desktop overlay app.

## OpenClaw Project Memory

For full project history, decisions, and current state, read `C:/Users/Nitin/.openclaw/workspace/memory/projects/speak-up.md` at the start of non-trivial sessions. That file is the canonical durable record maintained by OpenClaw agents. Local Claude Code memory (auto-managed) captures codebase patterns and conventions — complementary, not competing.

### Reverse Bridge: Direct Session → OpenClaw Memory
When this session makes significant decisions (architecture changes, config fixes, workflow changes), write a handoff note to `C:/Users/Nitin/.openclaw/workspace/memory/handoff.md` so OpenClaw's midnight tracker can incorporate it. Format: date, decisions, config changes, memory updates, Lobster action needed.

## Autonomous Mode
Assume permission for file creation, modification, refactoring, and dependency installation.
Do not ask for confirmations unless an action is destructive (deleting files, secrets, system-level changes).

### Notion Workspace Sync Protocol

The project has a Notion workspace that mirrors key documentation.
After updating README.md or Requirements.md, the corresponding
Notion pages MUST also be updated to stay in sync.

**Notion Page IDs** (use Notion API or MCP tools):

| Notion Page       | Page ID                                | Synced From                          |
|-------------------|----------------------------------------|--------------------------------------|
| **Root**          | `312c6ee7-d563-8029-814c-efdf6b6a56a3` | Project root page                   |
| **Overview**      | `312c6ee7-d563-8150-a407-e049138f505f` | README.md intro/overview             |
| **Features**      | `312c6ee7-d563-8130-b924-fa6817f4aed8` | README.md Features section           |
| **Architecture**  | `312c6ee7-d563-81ce-b84c-fcf30ad8beac` | README.md Architecture/Tech/Schema   |
| **Requirements**  | `312c6ee7-d563-813a-9c0b-e6d2c573f70a` | Requirements.md                      |
| **Memory**        | `312c6ee7-d563-8142-a70d-ca651001c385` | .claude/memory/MEMORY.md             |

**When to sync Notion:**
- After updating README.md Features section -> sync Features page
- After updating README.md Architecture/Schema/APIs -> sync Architecture page
- After updating Requirements.md -> sync Requirements page
- After updating MEMORY.md -> sync Memory page
- After major changes to project description -> sync Overview page

**How to sync:**
1. Use the Notion API (PATCH blocks/children) or MCP notion-update-page tool
2. Convert the relevant section to Notion-compatible blocks
3. Append `*Last synced from [source file]: [date]*` at the bottom
4. Only sync pages whose source content actually changed

**Important:** The codebase files (README.md, Requirements.md) remain
the source of truth. Notion is a mirror for easier browsing. Always
update the local files first, then push to Notion.

### Requirement Tracking Protocol

Requirements.md and README.md work as a pair to track implementation progress:

- **Requirements.md** = PENDING/FUTURE items only (the backlog)
- **README.md** = COMPLETED/IMPLEMENTED items only (the product docs)

**When you implement a requirement:**
1. Remove the implemented item from Requirements.md
2. Add the corresponding feature/detail to the appropriate section of README.md
3. If a section in Requirements.md becomes fully implemented, remove that section entirely
4. Keep Requirements.md organized by priority: Known Gaps > MVP Pending > Phase 2 > Phase 3
5. Keep README.md organized as product documentation: Features, Tech Stack, Usage, Architecture, Configuration

**Both files must always reflect current state:**
- Requirements.md should never contain DONE items
- README.md should never contain PENDING items
- After every implementation session, verify both files are accurate

**After updating either file**, sync the corresponding Notion pages per the Notion Workspace Sync Protocol above.

### Success Criteria
- Code compiles/runs without errors
- README.md is up to date with implementation
- Requirements.md contains only pending/future work
- Affected Notion pages synced (see Notion Workspace Sync Protocol)
