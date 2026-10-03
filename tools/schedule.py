"""Calendar, messaging, and the showing scheduler. Rules live here, not in the prompt.

Showing states: proposed -> agent_confirmed -> tenant_notified -> confirmed | rejected
(vacant units skip tenant_notified).
"""
import json
import os
import re
from datetime import datetime, timedelta

from maple import (RUNTIME, TZ, boston, conflicts, deliver, insert_event, load, load_ticket, logged,
                   lookup, now, parse_id, calendar_events)

SHOWINGS = RUNTIME / "showings"
PHONE = re.compile(r"\b\d{3}[-. ]\d{3}[-. ]\d{4}\b")
TIME = "%Y-%m-%d %H:%M"


def require_manager(sender_id):
    if lookup(sender_id)["role"] != "manager":
        raise ValueError("only the property manager / leasing agent can do this")


def manager_id():
    return load("tenants.json")["manager_ids"][0]


def tenant_of(unit):
    return next((t for t in load("tenants.json")["tenants"] if t["unit"] == unit), None)


# ---------- calendar ----------

@logged
def get_calendar(sender_id, start_date, end_date=""):
    require_manager(sender_id)
    end_date = end_date or start_date
    events = [e for e in calendar_events() if start_date <= e["date"] <= end_date]
    return {"events": sorted(events, key=lambda e: (e["date"], e["start"]))}


@logged
def add_event(sender_id, date, start, end, title, type, unit="", with_="", allow_conflict=False, in_minutes=0):
    require_manager(sender_id)
    if in_minutes:  # "remind me in 3 minutes": the code computes the time from Boston now, not the model
        at = now() + timedelta(minutes=int(in_minutes))
        date, start, end = at.strftime("%Y-%m-%d"), at.strftime("%H:%M"), (at + timedelta(minutes=15)).strftime("%H:%M")
    datetime.strptime(f"{date} {start}", TIME), datetime.strptime(f"{date} {end}", TIME)
    if start >= end:
        raise ValueError("end must be after start")
    clashes = [] if type == "reminder" else conflicts(date, start, end)  # a reminder never blocks the calendar
    if clashes and not allow_conflict:
        return {"added": False, "conflicts": [f"{e['start']}-{e['end']} {e['title']}" for e in clashes],
                "next_step": "Tell the manager about the conflict; add only if they confirm (allow_conflict=true)."}
    event = insert_event(date, start, end, title, type, unit=unit or None, with_=with_ or None)
    when = boston(datetime.strptime(f"{date} {start}", TIME).replace(tzinfo=TZ))
    return {"added": True, "event": event, "at_boston": when, "conflicts": [f"{e['start']}-{e['end']} {e['title']}" for e in clashes]}


# ---------- messaging with privacy rules ----------

def privacy_check(role, text, showing=None):
    """Prospects never see tenant names/contacts; tenants never see prospect names/contacts."""
    low = text.lower()
    if role == "prospect":
        for t in load("tenants.json")["tenants"]:
            if t["name"].lower() in low or t["name"].split()[-1].lower() in low or str(t["telegram_id"]) in text:
                raise ValueError("privacy: a prospect may not receive tenant names or contacts")
        if PHONE.search(text):
            raise ValueError("privacy: no phone numbers to prospects")
    if role == "tenant":
        for s in all_showings():
            name = s.get("prospect_name") or ""
            if str(s["prospect_id"]) in text or any(tok.lower() in low for tok in name.split() if len(tok) > 2):
                raise ValueError("privacy: a tenant may not receive prospect names or contacts")
        if showing and PHONE.search(text):
            raise ValueError("privacy: no phone numbers in showing notices")


def send(role, chat_id, text, showing=None, **context):
    privacy_check(role, text, showing)
    return deliver(role, chat_id, text, **context)


@logged
def send_message(role, text, ticket_id=None, showing_id=None):
    """Recipients come only from the registry / saved records, never from the model."""
    if role == "manager":
        return send("manager", manager_id(), text, ticket_id=ticket_id, showing_id=showing_id)
    if role == "tenant" and ticket_id:
        ticket = load_ticket(ticket_id)
        if ticket["status"] != "vendor_booked":
            raise ValueError("nothing goes to the tenant about a ticket before the manager approves it")
        return send("tenant", ticket["sender_id"], text, ticket_id=ticket["ticket_id"])
    if role in ("tenant", "prospect") and showing_id:
        s = load_showing(showing_id)
        if s["state"] == "proposed":
            raise ValueError("the leasing agent has not confirmed this showing yet")
        to = tenant_of(s["unit"])["telegram_id"] if role == "tenant" else s["prospect_id"]
        return send(role, to, text, showing=s, showing_id=s["showing_id"])
    raise ValueError("role must be manager, tenant (with ticket_id or showing_id) or prospect (with showing_id)")


@logged
def list_showings(sender_id):
    """Manager only: all showings, newest first, with who proposed which times."""
    require_manager(sender_id)
    return {"showings": [{"showing_id": s["showing_id"], "unit": s["unit"], "state": s["state"],
                          "prospect": s["prospect_name"] or "prospect", "times_proposed_by_prospect": s["valid_times"],
                          "time": s.get("time")} for s in reversed(all_showings())]}


@logged
def message_prospect(sender_id, showing_id, text):
    """Manager relays a message to the prospect of a showing (any state). Recipient comes from the record."""
    require_manager(sender_id)
    s = load_showing(showing_id)
    return send("prospect", s["prospect_id"], text, showing=s, showing_id=s["showing_id"])


# ---------- listings ----------

@logged
def get_listings(unit=""):
    units = load("listings.json")["units"]
    if unit and unit not in units:
        return {"available": False, "message": f"Unit {unit} is not available. Listed units: {', '.join(units)}."}
    return {"available": True, "listings": [{"unit": u, "available_from": v["available_from"], **v["public"]}
                                            for u, v in units.items() if not unit or u == unit]}


# ---------- showings ----------

def all_showings():
    return [json.loads(p.read_text()) for p in sorted(SHOWINGS.glob("S*.json"))] if SHOWINGS.exists() else []


def load_showing(showing_id):
    showing_id = "S" + re.sub(r"\D", "", str(showing_id))  # accept 2, "2", "S2", "s2"
    path = SHOWINGS / f"{showing_id}.json"
    if not path.exists():
        raise ValueError(f"showing {showing_id} not found")
    return json.loads(path.read_text())


def save_showing(s, event):
    s.setdefault("history", []).append({"at": now().isoformat(timespec="seconds"), "event": event, "state": s["state"]})
    SHOWINGS.mkdir(parents=True, exist_ok=True)
    (SHOWINGS / f"{s['showing_id']}.json").write_text(json.dumps(s, indent=2))


def check_time(unit, slot, current):
    """Returns None if the slot is allowed, else the rule that rejects it."""
    rules = load("rules.json")["showings"]
    try:
        start = datetime.strptime(slot, TIME).replace(tzinfo=TZ)
    except ValueError:
        return "format"
    end = start + timedelta(minutes=rules["duration_min"])
    if start <= current:
        return "past"
    if load("listings.json")["units"][unit]["tenant_notice_required"] and start - current < timedelta(hours=rules["notice_hours"]):
        return "notice"
    if start.weekday() == 6:  # Mon-Sat
        return "days"
    if start.strftime("%H:%M") < rules["hours"]["start"] or end.strftime("%H:%M") > rules["hours"]["end"]:
        return "hours"
    if conflicts(start.strftime("%Y-%m-%d"), start.strftime("%H:%M"), end.strftime("%H:%M")):
        return "conflict"
    return None


REASONS = {"format": "use the format YYYY-MM-DD HH:MM", "past": "that time has passed",
           "notice": "the current tenant needs at least 24 hours notice (lease 3.1)",
           "days": "showings are Monday to Saturday", "hours": "showings run 09:00-19:00",
           "conflict": "the leasing agent is busy then"}


@logged
def request_showing(sender_id, unit, times, prospect_name=""):
    who = lookup(sender_id)
    if who["role"] != "unknown":
        raise ValueError("showing requests come from prospects; residents and staff should talk to the manager")
    listing = load("listings.json")["units"].get(unit)
    if not listing:
        return {"available": False, "message": f"Unit {unit} is not available for showings."}
    rules = load("rules.json")["showings"]
    if not times or len(times) > rules["max_times_from_prospect"]:
        raise ValueError(f"give 1 to {rules['max_times_from_prospect']} times as 'YYYY-MM-DD HH:MM'")
    current = now()
    rejected = [{"time": t, "reason": REASONS[r]} for t in times if (r := check_time(unit, t, current))]
    valid = [t for t in times if not check_time(unit, t, current)]
    result = {"unit": unit, "valid_times": valid, "rejected": rejected}
    if not valid:
        return {**result, "showing_id": None,
                "next_step": "No proposed time works. Explain why and ask for up to 3 other times."}
    s = {"showing_id": f"S{len(all_showings()) + 1}", "unit": unit, "prospect_id": who["telegram_id"],
         "prospect_name": prospect_name, "valid_times": valid, "state": "proposed",
         "tenant_notice_required": listing["tenant_notice_required"]}
    save_showing(s, "requested")
    send("manager", manager_id(),
         f"Showing request {s['showing_id']}: unit {unit}, prospect {prospect_name or who['telegram_id']}. "
         f"Possible times: {', '.join(valid)}. Reply CONFIRM {s['showing_id']} <time>.",
         showing_id=s["showing_id"])
    return {**result, "showing_id": s["showing_id"], "state": "proposed",
            "next_step": "Tell the prospect the leasing agent will confirm a time. Nothing is booked yet."}


def objection_window():
    rules = load("rules.json")["showings"]
    if os.environ.get("DEMO_MODE") == "1":
        return timedelta(minutes=rules["demo_mode_objection_window_min"])
    return timedelta(hours=rules["tenant_objection_window_hours"])


def finalize(s):
    start = datetime.strptime(s["time"], TIME)
    end = (start + timedelta(minutes=load("rules.json")["showings"]["duration_min"])).strftime("%H:%M")
    event = insert_event(start.strftime("%Y-%m-%d"), start.strftime("%H:%M"), end, f"Showing: unit {s['unit']}",
                         "showing", unit=s["unit"], with_=f"{s['prospect_name'] or 'prospect'} (prospect)")
    s["state"], s["calendar_event"] = "confirmed", event["id"]
    save_showing(s, "confirmed")
    address = load("tenants.json")["property"]["address"]
    send("prospect", s["prospect_id"], f"Your showing of unit {s['unit']} is confirmed for {s['time']} at {address}. "
         "The leasing agent will meet you at the front door.", showing=s, showing_id=s["showing_id"])
    send("manager", manager_id(), f"Showing {s['showing_id']} confirmed: unit {s['unit']} at {s['time']} "
         f"with {s['prospect_name'] or s['prospect_id']}. Added to your calendar.", showing_id=s["showing_id"])
    return s


@logged
def confirm_showing(sender_id, showing_id, time):
    require_manager(sender_id)
    s = load_showing(showing_id)
    showing_id = s["showing_id"]
    if s["state"] != "proposed":
        raise ValueError(f"showing {showing_id} is {s['state']}, not waiting for the agent")
    if not time and len(s["valid_times"]) == 1:
        time = s["valid_times"][0]  # "CONFIRM S3" with a single proposed time
    if time not in s["valid_times"]:
        raise ValueError(f"pick one of {s['valid_times']}")
    reason = check_time(s["unit"], time, now())
    if reason:
        raise ValueError(f"{time} no longer works: {REASONS[reason]}")
    s["time"], s["state"] = time, "agent_confirmed"
    save_showing(s, "agent confirmed")
    if not s["tenant_notice_required"]:
        done = finalize(s)
        return {"showing_id": showing_id, "state": done["state"], "calendar_event": done["calendar_event"],
                "done": f"Confirmed {showing_id} for {boston(datetime.strptime(time, TIME).replace(tzinfo=TZ))}. "
                        "Vacant unit, so no tenant notice; prospect and calendar updated."}
    deadline = now() + objection_window()
    s["objection_deadline"] = deadline.isoformat(timespec="seconds")
    send("tenant", tenant_of(s["unit"])["telegram_id"],
         f"Notice of entry (lease 3.1): the leasing agent will show your unit {s['unit']} to a prospective tenant "
         f"on {time} for about 30 minutes. If this time does not work, reply OBJECT {showing_id} before "
         f"{boston(deadline)}. Otherwise no reply is needed.", showing=s, showing_id=showing_id)
    s["state"] = "tenant_notified"
    save_showing(s, "tenant notified")
    return {"showing_id": showing_id, "state": s["state"], "objection_deadline": boston(deadline),
            "done": (f"Confirmed {showing_id} for {boston(datetime.strptime(time, TIME).replace(tzinfo=TZ))}. "
                     f"Tenant notified; objection window closes {boston(deadline)}. The prospect is confirmed "
                     "automatically if there is no objection.")}


@logged
def tenant_response(sender_id, showing_id, objects):
    s = load_showing(showing_id)
    showing_id = s["showing_id"]
    tenant = tenant_of(s["unit"])
    if parse_id(sender_id) != tenant["telegram_id"]:
        raise ValueError("only the tenant of this unit can respond to this notice")
    if s["state"] != "tenant_notified":
        raise ValueError(f"showing {showing_id} is {s['state']}")
    if not objects:
        return {"showing_id": showing_id, **{k: finalize(s)[k] for k in ("state", "time")}}
    if now() > datetime.fromisoformat(s["objection_deadline"]):
        raise ValueError("the objection window has closed")
    s["state"] = "rejected"
    save_showing(s, "tenant objected")
    send("prospect", s["prospect_id"], f"Sorry, {s['time']} no longer works for unit {s['unit']}. Please send up to "
         "3 other times (Mon-Sat, 09:00-19:00, at least 24 hours ahead).", showing=s, showing_id=showing_id)
    send("manager", manager_id(), f"Tenant objected to showing {showing_id} ({s['unit']} at {s['time']}). "
         "The prospect was asked for new times.", showing_id=showing_id)
    return {"showing_id": showing_id, "state": "rejected", "next_step": "Tell the tenant the showing is cancelled."}


@logged
def check_showings():
    """Confirm showings whose tenant objection window passed with no objection."""
    done = []
    for s in all_showings():
        if s["state"] == "tenant_notified" and now() > datetime.fromisoformat(s["objection_deadline"]):
            done.append(finalize(s)["showing_id"])
    return {"confirmed": done}


# ---------- reminders (run by showing_timer.py) ----------

def reminder_lead():
    if os.environ.get("DEMO_MODE") == "1":
        return timedelta(minutes=2)
    return timedelta(minutes=load("calendar.json")["reminder_defaults_min"])


def due_reminders():
    """Send each due reminder once. Calendar events: lead time before start, manager only.
    Reminder events ("remind me at 4 PM ..."): at their time, manager only. Confirmed showings:
    also the unit's tenant (if notice applies) and the prospect, each privacy-filtered."""
    path = RUNTIME / "reminders_sent.json"
    sent = set(json.loads(path.read_text())) if path.exists() else set()
    current, lead, out = now(), reminder_lead(), []
    showings = {s.get("calendar_event"): s for s in all_showings() if s["state"] == "confirmed"}
    for e in calendar_events():
        start = datetime.strptime(f"{e['date']} {e['start']}", TIME).replace(tzinfo=TZ)
        if e["type"] == "reminder":
            due = start <= current < start + timedelta(minutes=5)
        else:
            due = start - lead <= current < start  # never for past events
        if not due:
            continue
        at = boston(start)
        messages = [("manager", manager_id(), f"Reminder: {e['title']}" + ("" if e["type"] == "reminder"
                     else f" at {at} ({e.get('location') or 'no location'})."))]
        s = showings.get(e["id"])
        if s:
            if s["tenant_notice_required"]:
                messages.append(("tenant", tenant_of(s["unit"])["telegram_id"],
                                 f"Reminder (lease 3.1): the showing of your unit {s['unit']} is at {at}, about 30 minutes."))
            messages.append(("prospect", s["prospect_id"],
                             f"Reminder: your showing of unit {s['unit']} is at {at}, "
                             f"{load('tenants.json')['property']['address']}."))
        for role, to, text in messages:
            key = f"{e['id']}:{role}"
            if key in sent:
                continue
            send(role, to, text, showing=s, showing_id=s["showing_id"] if s else None, reminder_for=e["id"])
            sent.add(key)
            out.append(key)
    if out:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(sent)))
    return {"sent": out}
