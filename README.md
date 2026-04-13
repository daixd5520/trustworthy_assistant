[English](README.md) | [中文](README.zh.md)

# Trustworthy Assistant

<div align="center">

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](https://opensource.org/licenses/MIT)

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
- 💬 **Personal WeChat Bot** - iLink / ClawBot bridge for personal WeChat login
- 🛡️ **Supervisor Workflow** - Plan-execute-review-verify with policies and gates

---

## 🏗️ Architecture

```text
trustworthy_assistant/
├── src/
│   └── trustworthy_assistant/ # Python package
│       ├── channels/          # Multi-channel support
│       │   └── wecom.py       # WeCom (Enterprise WeChat) integration
│       │   └── wechat.py      # Personal WeChat iLink integration
│       ├── memory/            # Trustworthy Memory System
│       │   ├── models.py      # Memory data models
│       │   ├── repository.py  # Memory persistence (ledger)
│       │   ├── retriever.py   # Keyword/hybrid search
│       │   ├── vector_store.py # Vector embeddings + ChromaDB
│       │   ├── projector.py   # Memory projection to Markdown
│       │   └── service.py     # Main memory service
│       ├── runtime/           # Core runtime
│       │   ├── agents.py      # Agent registry & profiles
│       │   ├── sessions.py    # Session management
│       │   ├── turns.py       # Turn processor (with streaming!)
│       │   └── maintenance.py # Maintenance service
│       ├── supervisor/        # Supervisor workflow
│       │   ├── models.py      # Data models
│       │   ├── policies.py    # Review policies
│       │   ├── reviewer.py    # Rule-based reviewer
│       │   ├── gates.py       # Verification gates
│       │   └── workflow.py    # Plan-execute-review-verify
│       ├── providers/         # LLM provider utilities
│       │   └── normalization.py # Response normalization
│       ├── eval/              # Evaluation & benchmarks
│       │   ├── benchmarks.py  # Benchmark suite
│       │   └── replay.py      # Replay harness
│       ├── app.py             # Application factory
│       ├── cli.py             # CLI interface
│       ├── config.py          # Configuration management
│       ├── run_wechat_bot.py  # Personal WeChat bot entrypoint
│       ├── run_wechat_login.py # Personal WeChat login entrypoint
│       └── run_wecom_bot.py   # WeCom bot entrypoint
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
├── pyproject.toml             # Packaging config
├── README.md                  # Project documentation
└── .env.example               # Environment template
```

### Execution Flow

```mermaid
flowchart TD
    A["User Input or Channel Message"] --> B["CLI or Channel Adapter"]
    B --> C["Build App"]
    C --> D["Load Bootstrap Skills and Memory Context"]
    D --> E["Supervisor Plan and Task Intent"]
    E --> F["TurnProcessor"]
    F --> G["Model Inference"]
    G --> H{"Tool Call Needed"}
    H -- Yes --> I["ToolRegistry Dispatch"]
    I --> J["Tool Result"]
    J --> F
    H -- No --> K["Draft Response"]
    K --> L["Supervisor Review"]
    L --> M{"Pass Review"}
    M -- No --> N["Revise Retry or Gate Feedback"]
    N --> F
    M -- Yes --> O["Supervisor Verify Gates"]
    O --> P{"Approved"}
    P -- No --> Q["Flag Issues or Needs Revision"]
    Q --> F
    P -- Yes --> R["Stream or Return Final Response"]
    R --> S["Persist Session and Memory Ledger"]
```

The `supervisor` layer acts in three places:
- Before execution: shapes the task intent and workflow state
- After drafting: reviews the output for findings and policy issues
- Before final return: runs verification gates to approve or request revision

---

## 📦 Installation

### From Source
```bash
git clone <your-repo-url>
cd trustworthy_assistant
python -m pip install -e .
```

### Prerequisites
- Python 3.11+
- An API key for Anthropic (or compatible provider)
- (Optional) OpenAI API key for better embeddings
- (Optional) WeCom credentials for WeChat bot
- (Optional) iLink / ClawBot access for personal WeChat

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

**Optional (Personal WeChat via iLink / ClawBot):**
```env
WECHAT_ILINK_BASE_URL=https://ilinkai.weixin.qq.com
WECHAT_QR_BOT_TYPE=3
WECHAT_ACCOUNT_ID=
```

### 3. Run the CLI (with Streaming!)
```bash
trustworthy-cli
# or
python -m trustworthy_assistant.cli
```
Run this from the repository root after `python -m pip install -e .`.
If `workspace/CRON.json` exists, the CLI also starts the background cron scheduler automatically.

### 4. Run WeCom Bot
```bash
trustworthy-wecom
# or
python -m trustworthy_assistant.run_wecom_bot
```

Then configure your WeCom webhook URL: `http://your-domain:8000/wecom/webhook`
The WeCom process also starts the cron scheduler automatically.

### 5. Login Personal WeChat
```bash
trustworthy-wechat-login
```

Scan the QR code with WeChat. After login, the account token is stored locally under `.wechat_personal/`.

### 6. Run Personal WeChat Bot
```bash
trustworthy-wechat
# or
python -m trustworthy_assistant.run_wechat_bot
```

---

## 📚 CLI Commands

```text
You > /memory stats         # Show memory statistics
You > /memory list          # List stored memories
You > /memory candidates   # List candidate memories
You > /memory trace        # Show last retrieval trace
You > /memory conflicts    # List memory conflicts
You > /memory confirm <id>  # Confirm a candidate memory
You > /memory reject <id>   # Reject a candidate memory
You > /memory forget <id>   # Forget a memory
You > /memory show <id>     # Show memory details
You > /memory sync         # Sync MEMORY.md projection
You > /search <query>       # Search memories
You > /prompt              # Show full system prompt
You > /bootstrap           # Show loaded bootstrap files
You > /agents              # List available agents
You > /switch <agent_id>   # Switch to another agent
You > /sessions            # List persisted sessions
You > /maintain            # Run maintenance once
You > /cron                # Show cron scheduler status
You > /cron reload         # Reload jobs from CRON.json
You > /cron run <job_id>   # Trigger a cron job immediately
You > /skills              # List discovered skills
You > /benchmarks          # Run benchmark suite
You > /supervisor          # Show supervisor status
You > /review              # Show last review findings
You > /verify              # Run verification gates
You > /workflow            # Show workflow report
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

## 💬 Personal WeChat Integration

### Setup
1. Run `trustworthy-wechat-login`
2. Scan the QR code with your personal WeChat account
3. Wait until the login flow stores `account_id` and token locally
4. Start the long-poll bot with `trustworthy-wechat`

### Notes
- Uses the iLink / ClawBot HTTP bridge style API
- Stores account state under `.wechat_personal/`
- Supports text messages, quoted replies, and image understanding via the built-in `read_image` tool
- Reuses the same `turn_processor` and session pipeline as the CLI

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

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">
  <b>Made with ❤️</b>
  <br>
  <br>
  If you find this project useful, please consider giving it a ⭐️!
</div>
