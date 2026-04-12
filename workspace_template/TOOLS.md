# Tool Usage Guidelines

## Memory Tools

The assistant has access to memory tools for storing and retrieving information:

### memory_write

Save important facts or observations to long-term memory.

- **content**: The fact or observation to remember
- **category**: One of: preference, fact, context, project, decision, constraint, profile

Example: `memory_write(content="User prefers concise answers", category="preference")`

### memory_search

Search stored memories for relevant information.

- **query**: Search query
- **top_k**: Maximum number of results (default: 5)

Example: `memory_search(query="user preferences", top_k=3)`

## Guidelines

1. Use `memory_write` when you learn something important about the user
2. Use `memory_search` when you need to recall specific information
3. Reference memories naturally in conversation, don't say "According to my records"
4. Focus on meaningful details: preferences, ongoing projects, important context
