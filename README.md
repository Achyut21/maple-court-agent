# Maple Court Agent

**A property-management agent on Telegram that triages tenant maintenance requests, quotes the lease,
drafts vendor jobs for manager approval, and books apartment showings with 24-hour tenant notice,
running entirely on a Dell Pro Max GB10.**

Dell x NVIDIA Hackathon, Boston, Oct 3 2026. Tenant names, leases, and units never leave the building.

## Architecture

```
Tenant / manager / prospect phones (Telegram DMs, allowlisted)
        |
NemoClaw sandbox "hackathon" (OpenShell policy, per-sender sessions)
  OpenClaw agent  --tool calls-->  maple MCP server (Python, stdio)          showing_timer.py
  prompt: prompt/AGENTS.md         tools/maple.py     tickets, leases, approve   objection windows,
        |                          tools/schedule.py  calendar, showings,        reminders
        | inference.local                             messaging + privacy
        v                          tools/charts.py    week / ticket charts
vLLM on the GB10: Qwen3.6-35B-A3B-NVFP4                    |
                                   outbound Telegram: `openclaw message send` (token injected by OpenShell)
```

- The model proposes and code decides. Identity and unit come from `data/tenants.json` by numeric
  Telegram id; urgency floors, the gas protocol, lease-based responsibility rules, 24-hour showing
  notice, and "nothing is sent without manager approval" are enforced in `tools/`.
- Privacy between roles is enforced when a message is sent: prospects never receive tenant
  names or contacts, tenants never receive prospect names or contacts, the manager sees everything.
  Recipients come from records, never from the model.
- Locked-down agent: OpenClaw's built-in `message`, `exec`, `process`, `code_execution`, and file
  tools are denied, so every outbound message goes through the rules above. Web search stays on.
- Logging: every tool call appends `{ts, tool, ticket_id|showing_id, ms, ok, error}` to
  `runtime/metrics.jsonl`; tickets, showings, and outbound messages are saved under `runtime/`.

## Tools (16, one MCP server)

`verify_sender`, `get_lease`, `create_ticket`, `draft_vendor_job`, `approve`, `send_message`,
`get_calendar`, `add_event`, `get_listings`, `request_showing`, `confirm_showing`, `tenant_response`,
`check_showings`, `list_showings`, `message_prospect`, `make_chart`. Web search is NemoClaw's
built-in Brave search.

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

## Demo

1. In parallel:
   - **Prospect:** "Could I see 1B Monday Oct 5 at 11am?" -> rules check notice, hours, and calendar;
     the manager gets the request.
   - **Tenant:** "No heat in my apartment since last night, it's freezing" -> ticket, urgent, Lease 7.2
     quoted; the manager gets the vendor draft.
2. **Manager:** `CONFIRM S<n>` -> tenant gets a lease 3.1 entry notice with an objection window
   (45 seconds in demo mode, 12 hours otherwise).
3. **Manager:** `APPROVE <n>` -> tenant notified, visit on the calendar, conflicts flagged.
4. **Prospect:** asks for the tenant's name and phone -> refused. A stranger -> no ticket, ever.
5. **Showing auto-confirms:** with no objection, prospect and manager get the confirmation, about
   45-60 s after `CONFIRM`.
6. **Manager:** "Show my week" -> timeline chart in Telegram; "Remind me at 4 PM to call HeatPro".

## Results (30 labeled tickets, `eval/score.py`)

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
| Agent minutes for 30 tickets (manual: ~240, our estimate) | 13.8 | 14.3 |

Run 2 change: lockout and light-bulb lease rules moved into code, duplicate tickets prevented, and
"always open a ticket". Full report: `eval/report.md`; charts: `eval/charts/`; history: `eval/history.csv`.
Showing rules are covered by the 8 labeled cases in `data/test_showings.json`, all passing in
`tools/test_schedule.py` (deterministic tests, not an agent eval).

## Known limits

- The sender id reaches the tools through the model (read from the session key in the system
  prompt); the tools then decide role and unit from the registry. In run 2 the model once failed to
  read it and asked the tenant for their unit instead (#4): no ticket was created, so urgent recall
  dropped to 10/11.
- The eval drives `openclaw agent` sessions, not live Telegram delivery; messages are recorded,
  not sent, during the eval.
- Vendors are contacted by the manager by phone; the agent drafts the message.
- The ~8 minutes per ticket manual baseline is our estimate.
