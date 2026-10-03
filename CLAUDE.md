# CLAUDE.md: Maple Court Agent (Dell x NVIDIA Hackathon, Boston, 2026-10-03)

You are the **build tool** for a hackathon team. You write and test code on this machine.
You are **never** part of the agent's runtime: the agent's reasoning must come only from the
local model on this machine. Submission deadline: **5:45 PM today**. Feature freeze: **4:30 PM**.

<goal>
A property-management agent that (1) triages tenant maintenance requests from Telegram, quotes
the lease clause, and drafts vendor jobs for manager approval, and (2) schedules apartment
showings between a prospect, the real estate agent, and the current tenant, with 24-hour notice.
Everything runs locally on the Dell Pro Max GB10. Judges score 4 criteria equally: works end to
end, business value, local-first (no cloud LLM calls), and demo quality.
</goal>

<verified_environment>
These facts were verified today. Treat them as ground truth; do not re-derive or "fix" them.
- Machine: Dell Pro Max GB10, DGX OS (Ubuntu 24.04.5), aarch64, user `dell`, Python 3.12.3.
- Project root: `~/hackathon/project` (this folder). Python env: `~/hackathon/project/.venv`
  (has `mcp` and `matplotlib`, installed offline). Offline wheels: `wheels/`.
- vLLM: Docker container `hackathon-vllm`, image `nvcr.io/nvidia/vllm:26.05.post1-py3`,
  endpoint `http://127.0.0.1:8000/v1`, served model id `nvidia/Qwen3.6-35B-A3B-NVFP4`,
  tool parser `qwen3_coder`, reasoning parser `qwen3`, max_model_len 65536.
  OpenAI-style tool calling was tested and works.
- NemoClaw/OpenClaw: sandbox name `hackathon`, OpenClaw 2026.7.1, provider `vllm-local`,
  inference route `inference.local`. Dashboard: `http://127.0.0.1:18789/`.
  Known commands: `nemoclaw launch hackathon`, `nemoclaw hackathon connect`,
  `nemoclaw hackathon status`, `nemoclaw hackathon logs --follow`,
  `nemoclaw hackathon policy add`, `nemoclaw hackathon dashboard-url --quiet`, `nemoclaw --help`.
- NemoClaw source and docs (local copy): `~/hackathon/NemoClaw/`.
- Telegram: connected through NemoClaw's built-in channel. DM allowlist (TELEGRAM_ALLOWED_IDS):
  7747927489, 8868695493, 8245611231 (prospect). Group chats disabled. Private chats only.
- Brave web search: enabled through NemoClaw's built-in web search. Do NOT build a search tool.
- Sandbox network policy (Balanced): npm, pypi, huggingface, brew, brave, local-inference,
  openclaw-pricing, telegram.
</verified_environment>

<data>
All mock data is in `data/`. Read the files before writing code; do not invent fields.
- `tenants.json`: {property, manager_ids, tenants[{telegram_id, name, unit, lease_type}], vacant_units}
- `leases/<unit>.md` + `lease_index.json`: lease text; clause numbers like 3.1, 7.2, 9.2
- `vendors.json`: [{id, name, trade, phone, same_day}]
- `rules.json`: urgency levels + SLAs, heating season, gas protocol, categories
- `calendar.json`: {owner, events[{id, date, start, end, title, type, unit, with, location, notes}]}
- `test_tickets.json`: 30 labeled tickets [{id, sender_telegram_id, date, message,
  expected{verified, urgency, category, responsible, clause, vendor}, note}]
Real people (update data/tenants.json in Step 1; keep all other records unchanged):
- Real estate agent / manager: 7747927489 → `manager_ids`
- Tenant in unit 1B: 8868695493 → replace 1B's `telegram_id`
- Prospect: unregistered; their ID will be added to the allowlist later.
Unit 1B's lease ends Nov 30 (see calendar event ev-002), so 1B is the unit listed for showings.
5B is vacant. Showing data (listings.json, showing rules, test_showings.json) does not exist yet;
it is created in Step 2a. Do not create it earlier.
</data>

<architecture>
- Tools live in `tools/` as one Python MCP server, run with `.venv/bin/python`.
- Rules are code, not prompts: identity and unit come from `tenants.json` (numeric Telegram
  ID), never from message text. Urgency floors, SLAs, the gas protocol, 24-hour showing notice,
  and "nothing is sent without manager approval" are all enforced in code.
- Logging: every tool call appends one JSON line to `runtime/metrics.jsonl`:
  {ts, tool, ticket_id|showing_id, ms, ok, error}. Tickets are saved to `runtime/tickets/<id>.json`,
  showings to `runtime/showings/<id>.json`, and approved outbound items to `runtime/outbox/`.
- Privacy between roles (enforced in `send_message`): the prospect never receives tenant names
  or contacts; the tenant never receives prospect names or contacts; the manager sees everything.
  Recipients come only from the registry.
- Secrets: the Telegram bot token goes in `.env` (TELEGRAM_BOT_TOKEN), and `.env` goes in
  `.gitignore`. Never print, log, or commit secrets.
</architecture>

<open_questions_verify_first>
These are NOT known. Investigate before building on them, using local docs
(`~/hackathon/NemoClaw/`), `--help` output, and small experiments. Never guess CLI flags or
config keys. For every claim, cite the file path or command output that proves it.
1. How to register a custom MCP server with OpenClaw inside a NemoClaw sandbox, and whether
   the server must run inside the sandbox (stdio) or on the host (and how the sandbox reaches it).
2. Whether the sandbox can read `~/hackathon/project/data` on the host, or whether data must be
   copied in or served by the MCP server.
3. Whether OpenClaw can send a Telegram DM to a specific chat ID on its own. If not, use our
   `send_message` tool calling the Telegram Bot API (api.telegram.org is allowed by the
   telegram policy; confirm the sandbox's policy actually lets our tool's process reach it).
4. How to set OpenClaw's system prompt / agent instructions for this sandbox.
Report findings as a short table (question | answer | evidence) and propose the architecture
before writing tool code.
</open_questions_verify_first>

<plan>
Step 0: Read PLAN.md, README.md, and every file in data/. Answer the open questions. Show me
        the findings table and a short build plan. **Wait for my OK.**
Step 1 (Round 1, until ~1:30 PM): update tenants.json with the real IDs; build tools
        verify_sender, get_lease, create_ticket, draft_vendor_job, approve, with metrics logging;
        a test per tool (plain Python, run with .venv); connect to OpenClaw; get the "No heat in 1B"
        flow working in OpenClaw chat.
Step 2a (start of Round 2, ~15 min): add the showing data below, then show me a diff summary.
        Change nothing else in data/.
        1. data/listings.json (new): 1B = {status: "occupied_listed", tenant_notice_required: true,
           available_from: "2026-12-01"}; 5B = {status: "vacant", tenant_notice_required: false,
           available_from: "2026-10-05"}. Give each unit a "public" block (beds, baths, sqft, rent,
           short description) and keep all private info out of it. Prospects only ever see "public".
        2. data/rules.json: add "showings": {notice_hours: 24, duration_min: 30,
           hours: {start: "09:00", end: "19:00"}, days: "Mon-Sat", max_times_from_prospect: 3,
           tenant_objection_window_hours: 12, demo_mode_objection_window_min: 0.75 (45 s), clause: "3.1"}.
        3. data/leases/*.md: append to clause 3.1: "This includes showings to prospective tenants or
           buyers during the last 60 days of the lease, with at least 24 hours notice."
        4. data/tenants.json: add "prospects": [] with a note that prospects are unregistered,
           can only ask about units in listings.json, and never create maintenance tickets.
        5. data/test_showings.json (new), 8 labeled cases with expected outcomes: valid slot ->
           agent asked; slot < 24h away -> rejected (notice rule); slot outside showing hours ->
           rejected; slot overlapping a calendar event (e.g. Oct 5 09:00-10:00 4B inspection) ->
           rejected (conflict); tenant objects -> prospect asked for new times; vacant 5B -> no
           tenant notice needed; prospect asks for the tenant's name/phone -> refused; prospect asks
           about an unlisted unit (2A) -> "not available".
Step 2 (Round 2, until ~3:30 PM): get_calendar; add_event (conflict check); send_message(role,
        text) with privacy rules; showing scheduler: prospect gives times → filter (>= 24h notice
        per lease 3.1, inside working hours, agent's calendar free) → agent picks → tenant notified
        with an objection window (DEMO_MODE shortens it to 45 seconds; auto-confirms in about 45-60 s; real mode stays 12h) → no objection =
        confirm to prospect + agent and add to calendar; objection = ask prospect for new times.
        Showing state machine: proposed → agent_confirmed → tenant_notified → confirmed | rejected.
Step 3 (Round 3, until 4:30 PM): eval/score.py runs the 30 test tickets and writes eval/report.md
        (from eval/REPORT_TEMPLATE.md) plus a row in eval/history.csv. Pass = urgency +
        responsibility + clause all correct; strangers and the rent question pass only if no
        ticket is created. Stretch, only if ahead: make_chart (matplotlib PNG for Telegram).
</plan>

<rules>
- Do exactly the current step. No extra features, refactors, abstractions, or "nice to haves".
- Before editing, say which files you will change and why (one line each). Prefer small diffs.
- Do not install new packages or download anything without asking (we may be offline).
- Do not touch Docker, vLLM, NemoClaw/OpenShell config, or network policies without asking
  first. Never restart `hackathon-vllm` or rerun `nemoclaw onboard` on your own.
- Do not rewrite README.md, PLAN.md, or the data files except where a step says so.
- No mocks of things we can test for real. If something can't be tested, say so explicitly.
- If you are unsure, say "unverified" and propose a quick test. Never present a guess as fact.
- Keep code simple and readable for a 3-minute demo; judges may look at it.
</rules>

<reporting_format>
After each step, reply with only:
1. Done: what changed (file list)
2. Verified: command run + key output
3. Not done / risks: anything unverified or failing
4. Next: the next step, waiting for my OK
</reporting_format>
