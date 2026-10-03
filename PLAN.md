# Maple Court Agent: Team Plan (Dell x NVIDIA Hackathon, Boston, Oct 3)

**One line:** A property-management agent that triages tenant maintenance requests from Telegram, quotes the lease clause, drafts vendor jobs, and manages the property manager's calendar, all running locally on the Dell Pro Max GB10.

**Why local:** tenant names, leases, and payment history never leave the building.

## Demo story (30 seconds)
Tenant texts "No heat in 4B" -> agent verifies sender, marks URGENT (rule), quotes lease 7.2 -> tenant gets ticket #12 instantly -> manager gets the vendor draft plus a calendar conflict warning (3 PM showing) -> manager replies APPROVE 12 -> vendor booked, tenant updated, visit added to calendar. A stranger texts the bot -> refused.

## Stack
OpenClaw + NemoClaw + OpenShell (required) | Qwen3.6-35B via vLLM on GB10 | Python MCP server (our tools) | JSON data | Telegram (NemoClaw built-in) | Brave search (NemoClaw built-in) | matplotlib charts

## Tools we build (8) + 1 built-in
1 verify_sender, 2 get_lease, 3 create_ticket, 4 draft_vendor_job, 5 approve, 6 get_calendar, 7 add_event (conflict check), 8 make_chart, + web_search (NemoClaw/Brave)
**Rules in code, not AI:** identity + unit from registry (numeric Telegram ID), urgency floors, SLAs, gas protocol, nothing sent without approval.

## Timeline (cut scope, never extend time)
| Round | Time | Tasks | Checkpoint |
|---|---|---|---|
| 0 | 9:00-10:00 | Setup script, real Telegram IDs, Brave key in wizard | vLLM + NemoClaw up |
| 1 | 10:00-12:00 | Tools 1-5 + tests, connect to OpenClaw, "no heat 4B" in chat | Dry run passes in chat |
| 2 | 12:00-2:30 | Telegram, APPROVE flow, calendar + drafting, stranger/injection | Dry run on Telegram |
| 3 | 2:30-4:00 | 30-ticket eval to >=25/30, speed check, search + chart | Numbers in hand. FREEZE 4:00 |
| 4 | 4:00-5:45 | 3-min video, write-up + NVIDIA Qs, repo, rehearse x2 | SUBMIT 5:45 |

## Roles
A: tools (MCP server) + tool tests | B: OpenClaw prompt + Telegram + approvals | C: eval + metrics + demo video + write-up

## Metrics we show judges (all logged automatically)
| Metric | How measured | Target |
|---|---|---|
| Accuracy (all 3 fields right) | eval/score.py vs data/test_tickets.json | >= 25/30 |
| Per-field accuracy | urgency %, responsibility %, clause % | each >= 85% |
| Urgent recall (most important) | urgent tickets correctly flagged / all urgent | 100% |
| Security | strangers refused, injection resisted, wrong-unit blocked | 4/4 |
| Speed | median + slowest seconds per ticket (metrics.jsonl) | median < 60 s |
| Throughput | tokens/sec from vLLM /metrics on GB10 | report actual |
| Local proof | cloud LLM calls in runtime | 0 (route = inference.local) |
| Human control | tickets sent without approval | 0 |
| Business value | agent minutes vs manual estimate (~8 min/ticket, stated as our estimate) for 30 tickets | report actual |
| Improvement | every eval run logged in eval/history.csv | show the climb |

## Logging (build into tools from the start)
- Every tool call appends one line to runtime/metrics.jsonl: {ts, ticket_id, tool, ms, ok, error}
- create_ticket saves runtime/tickets/<id>.json: {test_id?, unit, urgency, category, responsible, clause, created_at}
- eval/score.py -> eval/report.md (fill eval/REPORT_TEMPLATE.md) + one row in eval/history.csv
- Before the pitch: screenshot report.md, vLLM tokens/sec, and the inference.local route

## Before 9 AM
Brave key (phone notes, never in repo) | real Telegram IDs for tenant + manager phones | phone hotspot charged | pendrive ejected safely
