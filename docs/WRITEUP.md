# Maple Court Agent: write-up

**Problem.** A small-building property manager handles maintenance texts, lease questions, vendor
booking, and apartment showings by hand. Each request means checking who is writing, reading the
lease, judging urgency, finding a vendor, and coordinating tenants and prospects.

**Solution.** A Telegram agent that triages maintenance requests (urgency, who pays, lease clause
quoted word for word), drafts the vendor job, and waits for the manager's `APPROVE`. It also books
showings: the prospect proposes times, rules filter them (24-hour notice per lease 3.1, showing hours,
calendar conflicts), the manager confirms, and the tenant gets a notice with an objection window.

**Why local.** Tenant names, leases, and unit numbers never leave the building. The model
(Qwen3.6-35B-A3B, NVFP4) runs in vLLM on the Dell Pro Max GB10, and the agent (OpenClaw inside a
NemoClaw/OpenShell sandbox) reaches it only through `inference.local`. The eval recorded 0 cloud LLM calls.

**How it works.** The model proposes; code decides. A Python MCP server enforces identity and unit
from the registry, urgency floors, the gas protocol, the approval gate, and role privacy (prospects
never see tenant details; tenants never see prospect details). Outbound messages go only through
that server; the agent's built-in messaging, shell, and file tools are disabled.

**Measured results** (30 labeled tickets, eval run 2): 28/30 fully correct (93%), up from 26/30 in
run 1. Urgency 26/27, responsibility 26/27, clause 26/28, urgent recall 10/11. All safety checks
passed: strangers refused, prompt injection resisted, wrong-unit claim blocked, 0 messages sent
without approval. Median 28.0 s per ticket (slowest 50.6 s), 72 tokens/s decode. The 30 tickets took
14.3 agent minutes, against our estimate of about 240 manual minutes.

**What's next.** Pass the Telegram sender id to tools without going through the model, a vendor
channel, and more eval cases for showings.
