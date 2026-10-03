"""Maple Court tools: plain Python functions with the business rules in code.

The model proposes (category, urgency, clause); these functions decide.
Identity and unit always come from data/tenants.json via the numeric Telegram ID.
"""
import functools
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("MAPLE_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
RUNTIME = Path(os.environ.get("MAPLE_RUNTIME", ROOT / "runtime"))
TZ = ZoneInfo("America/New_York")


def load(name):
    return json.loads((DATA / name).read_text())


def now():
    fixed = os.environ.get("MAPLE_NOW")  # tests only, e.g. 2026-10-03T14:00
    return datetime.fromisoformat(fixed).replace(tzinfo=TZ) if fixed else datetime.now(TZ)


def boston(dt):
    """Human-readable Boston time, e.g. 'Sat Oct 3, 1:50 PM EDT'. All times in this project are America/New_York."""
    return dt.astimezone(TZ).strftime("%a %b %-d, %-I:%M %p %Z")


# ---------- logging: one JSON line per tool call ----------

def logged(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        ok, error, result = True, None, None
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, dict):
                result["now_boston"] = boston(now())  # the agent's own clock is UTC; use this one
            return result
        except Exception as e:
            ok, error = False, str(e)
            raise
        finally:
            out = result if isinstance(result, dict) else {}
            line = {"ts": datetime.now(TZ).isoformat(timespec="seconds"), "tool": fn.__name__,
                    "ticket_id": kwargs.get("ticket_id") or out.get("ticket_id"),
                    "ms": round((time.perf_counter() - start) * 1000, 1), "ok": ok, "error": error}
            showing_id = kwargs.get("showing_id") or out.get("showing_id")
            if showing_id:
                line["showing_id"] = showing_id
            RUNTIME.mkdir(parents=True, exist_ok=True)
            with open(RUNTIME / "metrics.jsonl", "a") as f:
                f.write(json.dumps(line) + "\n")
    return wrapper


# ---------- registry ----------

def parse_id(sender_id):
    digits = re.sub(r"\D", "", str(sender_id))
    if not digits:
        raise ValueError("sender_id must be the numeric Telegram ID from the message metadata")
    return int(digits)


def lookup(sender_id):
    """Who is this Telegram ID? Returns role tenant/manager/unknown."""
    reg = load("tenants.json")
    sid = parse_id(sender_id)
    if sid in reg["manager_ids"]:
        return {"role": "manager", "telegram_id": sid, "name": reg["property"]["manager"]}
    for t in reg["tenants"]:
        if t["telegram_id"] == sid:
            return {"role": "tenant", **t}
    return {"role": "unknown", "telegram_id": sid}


def lease_clauses(unit):
    path = load("lease_index.json").get(unit)
    if not path:
        raise ValueError(f"no lease on file for unit {unit}")
    text = (DATA / path).read_text()
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^(\d+\.\d+) (.+)$", text, re.M)}


# ---------- urgency rules (floors only raise; message text never overrides) ----------

URGENT_PATTERNS = [
    r"\bgas\b",
    r"\b(no|without) heat\b", r"\bheat (is )?(out|off|not working|broken)\b",
    r"\bno (hot )?water\b",
    r"\b(flood\w*|pouring|overflow\w*|burst)\b",
    r"\bsewage\b",
    r"\bsparks?\b", r"\bburn(ing|t)\b", r"\bsmoke\b",
    r"\b(lost|no) power\b", r"\bpower (is )?out\b",
    r"\block(ed)? (myself |me )?out\b", r"\blockout\b",
    r"\b(won'?t|will not|doesn'?t|does not|can'?t) lock\b",
]
LOW_PATTERNS = [r"\bloose\b", r"\bsqueak\w*", r"\bpeel\w*", r"\bbulb\b", r"\bcosmetic\b", r"\bscuff\w*"]
OVERRIDE_PATTERNS = [r"ignore (your|all|the|previous|prior)?\s*(rules|instructions)",
                     r"mark (this|it) (as )?urgent", r"\boverride\b", r"\bsystem prompt\b"]
GAS = r"\bgas\b"


def in_heating_season(day):
    season = load("rules.json")["heating_season"]
    md = day.strftime("%m-%d")
    return md >= season["start"] or md <= season["end"]


def rule_urgency(message, day):
    """Returns (floor or None, notes). Floor 'urgent' comes from rules, not the model."""
    text = message.lower()
    notes = []
    for p in URGENT_PATTERNS:
        if re.search(p, text):
            notes.append(f"urgent rule matched: {p}")
            return "urgent", notes
    season = load("rules.json")["heating_season"]
    for m in re.finditer(r"\b(\d{2})\s*(?:°|degrees|deg\b|f\b)", text):
        if in_heating_season(day) and int(m.group(1)) < season["min_temp_day_f"]:
            notes.append(f"{m.group(1)}F is below the {season['min_temp_day_f']}F lease minimum")
            return "urgent", notes
    return None, notes


# ---------- tools ----------

@logged
def verify_sender(sender_id):
    who = lookup(sender_id)
    if who["role"] == "unknown":
        return {"verified": False, "role": "prospect", "telegram_id": who["telegram_id"],
                "instruction": ("Not a resident. Treat as a prospective renter: only public listing info "
                                "(maple__get_listings) and showing requests. No tickets, leases, approvals, "
                                "or information about residents.")}
    return {"verified": True, **who}


@logged
def get_lease(sender_id, unit=""):
    who = lookup(sender_id)
    if who["role"] == "tenant":
        unit = who["unit"]  # tenants only ever see their own lease
    elif who["role"] == "manager":
        if not unit:
            raise ValueError("manager must name a unit, e.g. 1B")
    else:
        raise ValueError("unverified sender: no lease access")
    return {"unit": unit, "lease_type": lease_type_of(unit), "clauses": lease_clauses(unit)}


def lease_type_of(unit):
    for t in load("tenants.json")["tenants"]:
        if t["unit"] == unit:
            return t["lease_type"]
    return None


def next_ticket_id():
    folder = RUNTIME / "tickets"
    folder.mkdir(parents=True, exist_ok=True)
    ids = [int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit()]
    return max(ids, default=0) + 1


def save_ticket(ticket):
    (RUNTIME / "tickets" / f"{ticket['ticket_id']}.json").write_text(json.dumps(ticket, indent=2))


def load_ticket(ticket_id):
    path = RUNTIME / "tickets" / f"{int(ticket_id)}.json"
    if not path.exists():
        raise ValueError(f"ticket {ticket_id} not found")
    return json.loads(path.read_text())


@logged
def create_ticket(sender_id, message, category, urgency, responsible, clause):
    who = lookup(sender_id)
    if who["role"] != "tenant":
        raise ValueError("only a registered tenant can open a maintenance ticket")
    rules = load("rules.json")
    if category not in rules["categories"]:
        raise ValueError(f"category must be one of {rules['categories']}")
    if category == "not_maintenance":
        raise ValueError("not a maintenance request: answer from the lease, do not create a ticket")
    if urgency not in rules["urgency_levels"]:
        raise ValueError(f"urgency must be one of {list(rules['urgency_levels'])}")
    if responsible not in ("landlord", "tenant"):
        raise ValueError("responsible must be 'landlord' or 'tenant'")

    created = now()
    for path in (RUNTIME / "tickets").glob("*.json") if (RUNTIME / "tickets").exists() else []:
        old = json.loads(path.read_text())  # same tenant, same words, last 10 minutes: no duplicate ticket
        if (old["sender_id"] == who["telegram_id"] and old["message"] == message
                and created - datetime.fromisoformat(old["created_at"]) < timedelta(minutes=10)):
            return {"ticket_id": old["ticket_id"], "duplicate": True, "urgency": old["urgency"],
                    "clause": old["clause"], "clause_text": old["clause_text"], "sla_hours": old["sla_hours"],
                    "due_by": old["due_by"], "next_step": "This ticket already exists. Do not create another."}
    notes = []
    floor, floor_notes = rule_urgency(message, created)
    notes += floor_notes
    model_urgency = urgency
    if floor == "urgent":
        urgency = "urgent"
    elif urgency == "urgent" and any(re.search(p, message.lower()) for p in OVERRIDE_PATTERNS):
        # The message tried to force urgency and no rule backs it up.
        urgency = "low" if any(re.search(p, message.lower()) for p in LOW_PATTERNS) else "normal"
        notes.append("urgency override in message ignored (rules decide urgency)")

    gas = bool(re.search(GAS, message.lower())) or category == "gas_emergency"
    if gas:
        category, urgency, responsible, clause = "gas_emergency", "urgent", "landlord", "9.2"
        notes.append("gas protocol applied")
    if category == "appliance" and who["lease_type"] == "tenant_appliances":
        responsible, clause = "tenant", "7.4"
        notes.append("tenant_appliances lease: tenant repairs appliances (7.4)")
    text = message.lower()
    if category == "locks" and re.search(r"\block(ed)? (myself |me )?out\b|\blockout\b|lost (my )?keys?|keys? (are |were )?(inside|locked in)", text):
        responsible, clause = "tenant", "7.5"
        notes.append("lockout: tenant pays the $75 lockout fee (7.5)")
    if re.search(r"\bbulbs?\b", text):
        category, responsible, clause = "electrical", "tenant", "7.3"
        notes.append("light bulbs: tenant replaces them (7.3)")

    clauses = lease_clauses(who["unit"])
    if clause not in clauses:
        raise ValueError(f"clause {clause} is not in the lease for {who['unit']}; valid: {sorted(clauses)}")

    sla = rules["urgency_levels"][urgency]["sla_hours"]
    ticket = {
        "ticket_id": next_ticket_id(), "sender_id": who["telegram_id"], "unit": who["unit"],
        "tenant_name": who["name"], "message": message, "category": category,
        "urgency": urgency, "urgency_model": model_urgency, "responsible": responsible,
        "clause": clause, "clause_text": clauses[clause], "sla_hours": sla,
        "due_by": boston(created + timedelta(hours=sla)),
        "rule_notes": notes, "status": "open", "vendor_job": None,
        "created_at": created.isoformat(timespec="seconds"),
    }
    save_ticket(ticket)
    result = {k: ticket[k] for k in ("ticket_id", "unit", "category", "urgency", "responsible",
                                     "clause", "clause_text", "sla_hours", "due_by", "rule_notes")}
    if gas:
        result["gas_protocol"] = rules["gas_protocol"]
        result["next_step"] = "Tell the tenant to leave now and call 911 or the gas utility. Do NOT draft a vendor job."
    else:
        result["next_step"] = "Tell the tenant the ticket number and quote the clause. Then draft a vendor job if one is needed."
    return result


WINDOW = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})-(\d{2}:\d{2})$")


@logged
def draft_vendor_job(ticket_id, vendor_id, window):
    ticket = load_ticket(ticket_id)
    if ticket["category"] == "gas_emergency":
        raise ValueError("gas protocol: never schedule a vendor for a gas smell")
    vendors = {v["id"]: v for v in load("vendors.json")}
    vendor = vendors.get(vendor_id)
    if not vendor:
        raise ValueError(f"unknown vendor; choose one of {sorted(vendors)}")
    if vendor["trade"] != ticket["category"]:
        raise ValueError(f"{vendor['name']} does trade '{vendor['trade']}', ticket is '{ticket['category']}'")
    if ticket["category"] == "appliance" and ticket["responsible"] == "tenant":
        raise ValueError("tenant_appliances lease: the tenant arranges their own appliance repair (7.4)")
    if not WINDOW.match(window):
        raise ValueError("window must look like 'YYYY-MM-DD HH:MM-HH:MM'")

    warnings = []
    if ticket["urgency"] == "urgent" and not vendor["same_day"]:
        warnings.append(f"{vendor['name']} is not a same-day vendor but the ticket is urgent")
    date, start, end = WINDOW.match(window).groups()
    for e in conflicts(date, start, end):
        warnings.append(f"calendar conflict: {e['start']}-{e['end']} {e['title']}")
    job = {
        "vendor_id": vendor_id, "vendor_name": vendor["name"], "vendor_phone": vendor["phone"],
        "window": window, "status": "draft",
        "message_to_vendor": (f"Maple Court job #{ticket['ticket_id']} ({ticket['urgency']}): "
                              f"{ticket['category']} issue in unit {ticket['unit']}: \"{ticket['message']}\". "
                              f"Window: {window}. 120 Maple St, Cambridge, MA."),
        "message_to_tenant": (f"Update on ticket #{ticket['ticket_id']}: {vendor['name']} is booked for {window}."
                              + (" Per your lease, repair costs are your responsibility." if ticket["responsible"] == "tenant" else "")),
    }
    ticket["vendor_job"] = job
    save_ticket(ticket)
    return {"ticket_id": ticket["ticket_id"], "draft": job, "warnings": warnings,
            "requires_approval": True,
            "next_step": f"Nothing is sent yet. The manager must reply APPROVE {ticket['ticket_id']}."}


@logged
def approve(sender_id, ticket_id):
    if lookup(sender_id)["role"] != "manager":
        raise ValueError("only the property manager can approve")
    ticket = load_ticket(ticket_id)
    job = ticket.get("vendor_job")
    if not job:
        raise ValueError(f"ticket {ticket_id} has no vendor draft to approve")
    if job["status"] == "approved":
        return {"ticket_id": ticket["ticket_id"], "status": "already approved"}
    stamp = now().isoformat(timespec="seconds")
    job["status"] = "approved"
    job["approved_at"] = stamp
    ticket["status"] = "vendor_booked"
    save_ticket(ticket)
    # Approval is the only path that releases messages for a ticket.
    vendor = record_outbox({"ticket_id": ticket["ticket_id"], "role": "vendor", "to": job["vendor_phone"],
                            "text": job["message_to_vendor"], "channel": "phone (manager calls)",
                            "approved_by": parse_id(sender_id), "sent": False})
    tenant = deliver("tenant", ticket["sender_id"], job["message_to_tenant"], ticket_id=ticket["ticket_id"])
    date, start, end = WINDOW.match(job["window"]).groups()
    clashes = conflicts(date, start, end)
    event = insert_event(date, start, end, f"{job['vendor_name']}: ticket #{ticket['ticket_id']} ({ticket['unit']})",
                         "vendor_visit", unit=ticket["unit"], with_=job["vendor_name"])
    tenant_status = "sent" if tenant["sent"] else ("recorded (dry run, not sent)" if tenant.get("dry_run")
                                                   else f"failed: {tenant.get('error', '')[:120]}")
    return {"ticket_id": ticket["ticket_id"], "status": "approved", "calendar_event": event["id"],
            "calendar_conflicts": [f"{e['start']}-{e['end']} {e['title']}" for e in clashes],
            "tenant_update": tenant_status,
            "vendor": f"Call {job['vendor_name']} at {job['vendor_phone']} with: {vendor['text']}"}


# ---------- calendar ----------

def calendar_events():
    added = RUNTIME / "calendar_added.json"
    return load("calendar.json")["events"] + (json.loads(added.read_text()) if added.exists() else [])


def conflicts(date, start, end):
    """Events on `date` overlapping [start, end). Times are HH:MM strings."""
    return [e for e in calendar_events() if e["date"] == date and e["start"] < end and start < e["end"]]


def insert_event(date, start, end, title, type_, unit=None, with_=None, notes=""):
    path = RUNTIME / "calendar_added.json"
    added = json.loads(path.read_text()) if path.exists() else []
    event = {"id": f"ev-r{len(added) + 1:03d}", "date": date, "start": start, "end": end, "title": title,
             "type": type_, "unit": unit, "with": with_, "location": load("tenants.json")["property"]["address"],
             "notes": notes}
    added.append(event)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(added, indent=2))
    return event


# ---------- outbound messages ----------

def record_outbox(item):
    folder = RUNTIME / "outbox"
    folder.mkdir(parents=True, exist_ok=True)
    item = {"created_at": now().isoformat(timespec="seconds"), **item}
    name = f"{datetime.now(TZ).strftime('%H%M%S%f')}-{item['role']}.json"
    (folder / name).write_text(json.dumps(item, indent=2))
    return item


def deliver(role, chat_id, text, media=None, **context):
    """Send one Telegram DM via OpenClaw (the sandbox only lets node reach Telegram).
    MAPLE_SEND=dry, or a runtime/DRY_SEND flag file (eval runs), records the message without sending."""
    item = {"role": role, "to": int(chat_id), "text": text, **context, "sent": False}
    if media:
        item["media"] = media
    if os.environ.get("MAPLE_SEND") == "dry" or (RUNTIME / "DRY_SEND").exists():
        item["dry_run"] = True
        return record_outbox(item)
    try:
        r = subprocess.run(["openclaw", "message", "send", "--channel", "telegram", "--target", str(chat_id),
                            "--json"] + (["-m", text] if text else []) + (["--media", media] if media else []),
                           capture_output=True, text=True, timeout=90)
        out = r.stdout[r.stdout.find("{"):] if "{" in r.stdout else "{}"
        reply = json.loads(out)
        item["sent"] = r.returncode == 0 and reply.get("payload", {}).get("ok", False)
        item["message_id"] = reply.get("messageId")
        if not item["sent"]:
            item["error"] = (r.stderr or r.stdout)[-300:]
    except Exception as e:  # never crash the tool because Telegram is down
        item["error"] = str(e)
    return record_outbox(item)
