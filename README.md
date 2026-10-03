# Maple Court Agent

A Telegram agent for a small apartment building: it triages tenant maintenance requests, quotes the
lease clause, drafts the vendor job for the manager to approve, and books apartment showings with
24-hour tenant notice.

Dell x NVIDIA Hackathon, Boston, Oct 3 2026.

## Runs entirely on one Dell Pro Max GB10

The model, the agent, the business rules, and every tenant record live on a single Dell Pro Max GB10.
No cloud LLM is involved at any step: across both 30-ticket eval runs, every model call went to the
local vLLM server, 0 to a cloud API. Tenant names, leases, and units never leave the machine.

| Component | Where it runs | Leaves the machine? |
|---|---|---|
| Model inference: Qwen3.6-35B-A3B (NVFP4) in vLLM | GB10 GPU, weights loaded from local disk | No |
| Agent: OpenClaw | GB10, inside the NemoClaw/OpenShell sandbox | No. Its only model provider is `https://inference.local/v1` |
| Business rules: Python MCP server with 16 tools | GB10 sandbox | No |
| Tenant registry, leases, calendar, tickets, showings | GB10 sandbox, JSON files | No |
| Message delivery | Telegram Bot API | Yes: the chat messages to and from the three people |
| Web search, only when the manager asks for it | Brave Search API | Yes: the search query |

The sandbox network policy entry for NVIDIA's hosted model API (`integrate.api.nvidia.com`) is
excluded, so the agent cannot reach a cloud model even by mistake.

## Tech stack

| Layer | Technology |
|---|---|
| Hardware | Dell Pro Max with GB10 (NVIDIA GB10 Grace Blackwell, ARM64, 128 GB unified memory), DGX OS (Ubuntu 24.04) |
| Model | Qwen3.6-35B-A3B, NVFP4 quantized (`nvidia/Qwen3.6-35B-A3B-NVFP4`) |
| Inference server | vLLM in Docker (`nvcr.io/nvidia/vllm:26.05.post1-py3`), OpenAI-compatible API, `qwen3_coder` tool-call parser |
| Agent | OpenClaw 2026.7.1 |
| Sandbox and network policy | NVIDIA NemoClaw and OpenShell: egress allowlist, per-sender sessions, bot token injected at egress |
| Tools | Python, MCP Python SDK (stdio server), matplotlib for charts |
| Data | JSON files: tenant registry, leases, vendors, rules, calendar |
| Messaging | Telegram Bot API through OpenClaw's Telegram channel |
| Web search | Brave Search through NemoClaw |
| Evaluation | Python scorer over 30 labeled tickets; vLLM `/metrics` for decode speed |
| Build tooling | Claude Code wrote and tested the code during the hackathon. It is not part of the agent's runtime. |

## Architecture

```mermaid
flowchart LR
    subgraph phones["Phones: private Telegram chats, allowlisted"]
        T["Tenant"]
        M["Property manager"]
        P["Prospect"]
    end

    TG["Telegram Bot API<br/>message delivery only"]
    BRAVE["Brave Search API<br/>only when the manager asks"]
    CLOUD["NVIDIA hosted model API<br/>integrate.api.nvidia.com"]

    subgraph gb10["Dell Pro Max GB10: all inference and all data"]
        subgraph sandbox["NemoClaw / OpenShell sandbox"]
            OC["OpenClaw agent<br/>prompt/AGENTS.md<br/>one session per sender"]
            MCP["maple MCP server<br/>16 Python tools<br/>rules, privacy, approval gate"]
            TIMER["showing_timer.py<br/>objection windows and reminders"]
            DATA[("JSON data<br/>tenants, leases, calendar,<br/>tickets, showings")]
        end
        VLLM["vLLM<br/>Qwen3.6-35B-A3B NVFP4"]
    end

    T <--> TG
    M <--> TG
    P <--> TG
    TG <--> OC
    OC -->|"tool calls over MCP stdio"| MCP
    MCP <--> DATA
    TIMER <--> DATA
    OC -->|"inference.local"| VLLM
    MCP -->|"openclaw message send"| TG
    TIMER -->|"openclaw message send"| TG
    OC -.->|"search query"| BRAVE
    OC -.->|"blocked by sandbox policy"| CLOUD

    classDef local fill:#e8f5e9,stroke:#2e7d32,color:#1b5e20
    classDef external fill:#fff8e1,stroke:#f9a825,color:#5d4037
    classDef blocked fill:#ffebee,stroke:#c62828,color:#b71c1c,stroke-dasharray: 5 5
    class OC,MCP,TIMER,DATA,VLLM local
    class TG,BRAVE external
    class CLOUD blocked
```

How a request moves through it:

1. A tenant, manager, or prospect sends a Telegram message. Only allowlisted accounts reach the bot,
   and each sender gets a separate session, so chat history never mixes between roles.
2. OpenClaw sends the conversation to the local model through `inference.local` and gets back tool
   calls.
3. The maple MCP server runs each tool. The model proposes and code decides: identity and unit come
   from the registry by numeric Telegram id, never from message text, and urgency floors, the gas
   protocol, lease-based responsibility, 24-hour showing notice, and the approval gate are Python.
4. Outbound messages go through `send_message`, which picks the recipient from saved records and
   enforces privacy between roles: prospects never receive tenant names or contacts, tenants never
   receive prospect names or contacts, and the manager sees everything.
5. `showing_timer.py` closes tenant objection windows, confirms showings, and sends reminders.

OpenClaw's built-in `message`, `exec`, `process`, `code_execution`, and file tools are denied, so
every outbound message and every data read goes through the rules above. Every tool call appends
`{ts, tool, ticket_id|showing_id, ms, ok, error}` to `runtime/metrics.jsonl`.

Tools: `verify_sender`, `get_lease`, `create_ticket`, `draft_vendor_job`, `approve`, `send_message`,
`get_calendar`, `add_event`, `get_listings`, `request_showing`, `confirm_showing`, `tenant_response`,
`check_showings`, `list_showings`, `message_prospect`, `make_chart`.

## How this meets the judging criteria

### 1. Technical execution

The full loop runs on real phones over Telegram: tenant message, verification, ticket, vendor draft,
manager approval, tenant update, calendar entry. Showings run the same way: prospect request, rule
checks, manager confirmation, tenant notice with an objection window, automatic confirmation.

- Built in one day, with tests for every tool (`tools/test_tools.py`, `tools/test_schedule.py`) and a
  30-ticket eval that drives the real agent (`eval/score.py`).
- Two eval runs: 26/30, then 28/30 after moving two lease rules into code and blocking duplicate
  tickets.
- Median tool execution time in `eval/metrics.jsonl` is 0.4 ms over 329 calls, so the time per ticket
  is the model, not the rules.

### 2. Usefulness and business value

The owner is the property manager, who also acts as the leasing agent. Their workflow today is manual:
read the text, check who sent it, look up the lease, judge urgency, find a vendor, coordinate access.

- Every ticket arrives triaged: urgency, who pays, and the lease clause quoted word for word.
- Nothing goes out without the manager: vendor jobs wait for `APPROVE`, showings wait for `CONFIRM`.
- In the eval, the agent handled 30 tickets in 14.3 minutes of agent time. Our own estimate for doing
  the same by hand is about 240 minutes (8 minutes per ticket); that baseline is an estimate, not a
  measurement.
- Showings follow lease clause 3.1: at least 24 hours notice, a tenant objection window, and no
  tenant details shared with the prospect.

### 3. Local-first design

- All inference runs on the GB10: Qwen3.6-35B-A3B (NVFP4) in vLLM, reached by the agent only through
  `inference.local`. See the table at the top for what runs where.
- OpenClaw's only configured model provider is `inference` at `https://inference.local/v1`, and the
  policy entry for NVIDIA's hosted API is excluded.
- In both eval runs, every model call was served by the local `inference` provider: 0 cloud LLM calls.
  Measured decode speed was 69 and 72 tokens/s.
- The bot token never enters the sandbox in plain form; OpenShell injects it at egress.

### 4. Demo quality

The live demo uses three phones (manager, tenant, prospect) and shows the rules working, not only the
happy path:

1. In parallel, the prospect asks to see unit 1B and the tenant reports no heat. The tenant gets a
   ticket marked urgent with lease 7.2 quoted; the manager gets the vendor draft and the showing request.
2. The manager confirms the showing. The tenant gets a lease 3.1 entry notice with an objection window
   (45 seconds in demo mode, 12 hours otherwise).
3. The manager approves the ticket. The tenant is notified and the visit goes on the calendar, with
   conflicts flagged.
4. The prospect asks for the tenant's name and phone. The request is refused.
5. With no objection, the showing confirms automatically, about 45 to 60 seconds after the manager
   confirmed it.
6. The manager asks to see the week and gets a timeline chart in Telegram.

## Results

30 labeled tickets (`data/test_tickets.json`), including two strangers, one prompt injection, one
wrong-unit claim, and one rent question. A ticket passes when urgency, responsibility, and lease
clause are all correct; the stranger and rent tickets pass only if no ticket is created.

| Metric | Run 1 (baseline) | Run 2 |
|---|---|---|
| Fully correct (urgency + responsibility + clause) | 26/30 (87%) | **28/30 (93%)** |
| Urgency / responsibility / clause | 96% / 93% / 93% | 96% / 96% / 93% |
| Urgent recall | 11/11 | 10/11 |
| Strangers refused, injection resisted, wrong unit blocked, rent = no ticket | all pass | all pass |
| Sent without manager approval | 0 | 0 |
| Cloud LLM calls | 0 | 0 |
| Median / slowest seconds per ticket | 25.6 / 45.9 | 28.0 / 50.6 |
| Decode tokens per second (vLLM) | 69 | 72 |
| Tool calls per ticket (average) | 8.7 | 9.9 |
| Agent minutes for 30 tickets (manual: ~240, our estimate) | 13.8 | 14.3 |

Run 2 change: lockout and light-bulb lease rules moved into code, duplicate tickets prevented, and
"always open a ticket" added to the prompt. Full report: `eval/report.md`; history: `eval/history.csv`.

![Accuracy by field, run 1 vs run 2](eval/charts/accuracy_by_field.png)

![Score by eval run against the 25/30 target](eval/charts/score_by_run.png)

![Seconds per ticket in run 2](eval/charts/latency_per_ticket.png)

![Safety checks in run 2](eval/charts/safety_checks.png)

Showing rules are covered by the 8 labeled cases in `data/test_showings.json`, all passing in
`tools/test_schedule.py`. These are deterministic tests, not an agent eval.

## Setup (on the GB10)

```bash
python3 -m venv .venv && .venv/bin/pip install --no-index --find-links wheels mcp matplotlib
.venv/bin/python tools/test_tools.py && .venv/bin/python tools/test_schedule.py
scripts/deploy.sh --first          # upload code, data, prompt, wheels; build /sandbox/.venv offline; register the MCP server
scripts/deploy.sh --code           # later: code/data/prompt only, no config write
```

Sandbox settings, applied host-side so OpenClaw's config hash stays in sync (needs Docker group access):

```bash
sg docker -c "nemoclaw hackathon config set --key session.dmScope --value per-channel-peer"
sg docker -c "nemoclaw hackathon config set --key agents.defaults.userTimezone --value America/New_York --config-accept-new-path"
sg docker -c "nemoclaw hackathon config set --key channels.telegram.streaming.mode --value off --config-accept-new-path"
```

Before recording a demo, `scripts/demo_reset.sh` clears tickets, showings, and the three Telegram
chat sessions, and keeps the metrics and eval files.

## Known limits

- The sender id reaches the tools through the model (read from the session key in the system
  prompt); the tools then decide role and unit from the registry. In run 2 the model once failed to
  read it and asked the tenant for their unit instead (#4): no ticket was created, so urgent recall
  dropped to 10/11.
- The eval drives `openclaw agent` sessions, not live Telegram delivery; messages are recorded, not
  sent, during the eval.
- Vendors are contacted by the manager by phone; the agent drafts the message.
- The ~8 minutes per ticket manual baseline is our estimate.

## What's next

- Tenant invite codes, so new tenants register themselves instead of being added to the registry by hand.
- More buildings: one registry and lease set per property, with the same rules in code.
