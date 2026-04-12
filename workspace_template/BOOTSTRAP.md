# Bootstrap

This file provides additional context loaded at agent startup.

## Project Context

This agent is configured with a trustworthy memory system that tracks facts,
preferences, and context over time. The workspace directory contains configuration
files that shape the agent's behavior:

- SOUL.md: Personality and communication style
- IDENTITY.md: Role definition and boundaries
- TOOLS.md: Available tools and usage guidance
- MEMORY.md: Long-term facts and preferences
- HEARTBEAT.md: Proactive behavior instructions
- BOOTSTRAP.md: This file -- additional startup context
- AGENTS.md: Multi-agent coordination notes
- USER.md: User context and preferences

## Workspace Layout

```
workspace/
  *.md          -- Bootstrap files (loaded into system prompt)
  CRON.json     -- Cron job definitions
  memory/       -- Daily memory logs
  skills/       -- Skill definitions
  .sessions/    -- Session transcripts (auto-managed)
  .agents/      -- Per-agent state (auto-managed)
```
