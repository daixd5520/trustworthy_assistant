# Trustworthy Assistant

<div align="center">

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![PyPI version](https://img.shields.io/pypi/v/trustworthy-assistant.svg)](https://pypi.org/project/trustworthy-assistant/)

**Production-ready AI Agent Gateway with Memory, Streaming, and Multi-Channel Support**

[Features](#-features) • [Quick Start](#-quick-start) • [Installation](#-installation) • [Documentation](#-documentation)

</div>

---

## 🚀 Features

### Core Capabilities
- ✅ **Agent Loop** - The foundation: `while True` + `stop_reason`
- ✅ **Tool Use** - Schema-based tool calling with dispatch table
- ✅ **Sessions & Context** - Persistent conversations with overflow handling
- ✅ **Gateway & Routing** - 5-tier binding with session isolation
- ✅ **Intelligence** - Soul, memory, skills, and 8-layer prompt assembly
- ✅ **Heartbeat & Cron** - Proactive agent with scheduled tasks
- ✅ **Delivery** - Reliable message queue with exponential backoff
- ✅ **Resilience** - 3-layer retry onion + auth profile rotation
- ✅ **Concurrency** - Named lanes with FIFO queues and generation tracking

### Enhanced Features
- 🎯 **Streaming Output** - Real-time response generation for better UX
- 🧠 **Vector Memory** - Semantic search using embeddings (OpenAI + ChromaDB)
- 💬 **WeCom Bot** - Enterprise WeChat integration as a new channel
- 🛡️ **Supervisor Workflow** - Plan-execute-review-verify with policies and gates

---

## 🏗️ Architecture

```
trustworthy_assistant/
├── channels/                  # Multi-channel support
│   └── wecom.py              # WeCom (Enterprise WeChat) integration
├── memory/                    # Trustworthy Memory System
│   ├── models.py             # Memory data models
│   ├── repository.py         # Memory persistence (ledger)
│   ├── retriever.py          # Keyword/hybrid search
│   ├── vector_store.py       # Vector embeddings + ChromaDB
│   ├── projector.py          # Memory projection to Markdown
│   └── service.py            # Main memory service
├── runtime/                   # Core runtime
│   ├── agents.py             # Agent registry & profiles
│   ├── sessions.py           # Session management
│   ├── turns.py              # Turn processor (with streaming!)
│   └── maintenance.py        # Maintenance service
├── supervisor/                # Supervisor workflow
│   ├── models.py             # Data models
│   ├── policies.py           # Review policies
│   ├── reviewer.py           # Rule-based reviewer
│   ├── gates.py              # Verification gates
│   └── workflow.py           # Plan-execute-review-verify
├── providers/                 # LLM provider utilities
│   └── normalization.py      # Response normalization
├── eval/                      # Evaluation & benchmarks
│   ├── benchmarks.py         # Benchmark suite
│   └── replay.py             # Replay harness
├── workspace_template/        # Workspace template
│   ├── SOUL.md
│   ├── IDENTITY.md
│   ├── TOOLS.md
│   ├── USER.md
│   ├── MEMORY.md
│   ├── HEARTBEAT.md
│   ├── BOOTSTRAP.md
│   ├── AGENTS.md
│   ├── CRON.json
│   └── skills/
│       └── example-skill/
│           └── SKILL.md
├── app.py                     # Application factory
├── cli.py                     # CLI interface
├── config.py                  # Configuration management
├── bootstrap.py               # Bootstrap file loader
├── prompting.py               # Prompt builder
├── skills.py                  # Skills catalog
├── tools.py                   # Tool registry
└── run_wecom_bot.py          # WeCom bot startup script
```

---

## 📦 Installation

### From PyPI (coming soon)
```bash
pip install trustworthy-assistant
```

### From Source
```bash
git clone https://github.com/shareAI-lab/claw0.git
cd claw0/trustworthy_assistant
pip install -e .
```

### Prerequisites
- Python 3.11+
- An API key for Anthropic (or compatible provider)
- (Optional) OpenAI API key for better embeddings
- (Optional) WeCom credentials for WeChat bot

---

## 🎯 Quick Start

### 1. Setup Workspace
```bash
cp -r workspace_template workspace
```

### 2. Configure Environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

**Required Configuration:**
```env
ANTHROPIC_API_KEY=sk-ant-xxxxx
MODEL_ID=claude-sonnet-4-20250514
```

**Optional (Vector Memory):**
```env
OPENAI_API_KEY=sk-xxxxx
OPENAI_BASE_URL=https://api.openai.com/v1
EMBEDDING_MODEL=text-embedding-3-small
CHROMA_PERSIST_DIR=./chroma
```

**Optional (WeCom Bot):**
```env
WECOM_CORP_ID=wwxxxxxxxxx
WECOM_AGENT_ID=1000001
WECOM_SECRET=xxxxxxxxxxxxx
```

### 3. Run the CLI (with Streaming!)
```bash
trustworthy-cli
# or
python -m trustworthy_assistant.cli
```

### 4. Run WeCom Bot
```bash
trustworthy-wecom
# or
python -m trustworthy_assistant.run_wecom_bot
```

Then configure your WeCom webhook URL: `http://your-domain:8000/wecom/webhook`

---

## 📚 CLI Commands

```
You > /memory stats        # Show memory statistics
You > /memory list          # List stored memories
You > /memory candidates   # List candidate memories
You > /memory conflicts    # List memory conflicts
You > /memory confirm <id>  # Confirm a candidate memory
You > /memory reject <id>   # Reject a candidate memory
You > /memory show <id>     # Show memory details
You > /search <query>       # Search memories
You > /prompt              # Show full system prompt
You > /agents              # List available agents
You > /switch <agent_id>   # Switch to another agent
You > /skills              # List discovered skills
You > /benchmarks          # Run benchmark suite
You > /supervisor          # Show supervisor status
You > /workflow           # Show workflow report
You > exit                 # Exit the REPL
```

---

## 🧠 Memory System

The trustworthy memory system uses a **ledger-based approach** with optional vector embeddings:

### Memory Status Flow
```
candidate → confirmed → deprecated → archived
    ↓
  disputed (when conflicts detected)
```

### Hybrid Search
Combines three search strategies:
1. **Keyword Search** - TF-IDF based
2. **Hash Vector Search** - Simple local embeddings
3. **Vector Embedding Search** - OpenAI embeddings + ChromaDB (optional, better results)

---

## 💬 WeCom (Enterprise WeChat) Integration

### Setup
1. Create a self-built application in [WeCom Admin Console](https://work.weixin.qq.com/)
2. Get your `Corp ID`, `Agent ID`, and `Secret`
3. Configure webhook URL: `https://your-domain:8000/wecom/webhook`
4. Set the token to your Corp ID

### Run
```bash
trustworthy-wecom
```

---

## 🔧 Configuration

### Workspace Files
The assistant reads bootstrap files from the workspace directory:

| File | Purpose |
|------|---------|
| `SOUL.md` | Personality and character definition |
| `IDENTITY.md` | Assistant identity and role |
| `TOOLS.md` | Tool usage guidelines |
| `USER.md` | User context and preferences |
| `MEMORY.md` | Long-term evergreen memory |
| `HEARTBEAT.md` | Heartbeat/background task config |
| `BOOTSTRAP.md` | Additional bootstrap content |
| `AGENTS.md` | Agent configuration |
| `CRON.json` | Scheduled cron tasks |

---

## 🛡️ Supervisor Workflow

Plan-Execute-Review-Verify workflow with:
- **Rule-based Reviewer** - Policy-based validation
- **Verification Gates** - Post-execution checks
- **Gate Decisions** - Approved, Needs Revision, Rejected

---

## 🤝 Contributing

Contributions are welcome! Here's how you can help:

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please make sure to update tests as appropriate.

---

## 📖 Related Projects

- **[claw0](https://github.com/shareAI-lab/claw0)** - The parent teaching repository with 10 progressive sections
- **[learn-claude-code](https://github.com/shareAI-lab/learn-claude-code)** - A companion teaching repo that builds an agent framework from scratch

---

## 💬 Community

<div align="center">
  <img width="260" src="https://github.com/user-attachments/assets/fe8b852b-97da-4061-a467-9694906b5edf" alt="WeChat QR Code" /><br>
  <br>
  Scan with WeChat to follow us, or follow on X:
  <br>
  <a href="https://x.com/baicai003">
    <img src="https://img.shields.io/twitter/follow/baicai003?style=social" alt="X (formerly Twitter) Follow" />
  </a>
</div>

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Thanks to all contributors who have helped shape this project
- Inspired by production-grade agent systems and the open-source AI community

---

<div align="center">
  <b>Made with ❤️ by shareAI-lab</b>
  <br>
  <br>
  If you find this project useful, please consider giving it a ⭐️!
</div>
