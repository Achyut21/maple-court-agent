"""Tests for calendar, messaging privacy, and the showing scheduler (data/test_showings.json).
Run: .venv/bin/python tools/test_schedule.py"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["MAPLE_RUNTIME"] = tempfile.mkdtemp(prefix="maple-sched-")
os.environ["MAPLE_SEND"] = "dry"  # never send real Telegram messages from tests
sys.path.insert(0, str(Path(__file__).parent))
import maple  # noqa: E402
import schedule  # noqa: E402

MANAGER, PROSPECT = "7747927489", "8245611231"
TENANT_1B = str(next(t["telegram_id"] for t in maple.load("tenants.json")["tenants"] if t["unit"] == "1B"))
CASES = json.loads((maple.DATA / "test_showings.json").read_text())


def fresh(now):
    shutil.rmtree(maple.RUNTIME, ignore_errors=True)
    os.environ["MAPLE_NOW"] = now


def sent(role):
    items = [json.loads(p.read_text()) for p in sorted((maple.RUNTIME / "outbox").glob("*.json"))]
    return [i for i in items if i["role"] == role]


def raises(fn, **kwargs):
    try:
        fn(**kwargs)
    except ValueError as e:
        return str(e)
    raise AssertionError(f"{fn.__name__} should have refused {kwargs}")


def run_case(c):
    fresh(c["now"])
    exp = c["expected"]
    if exp["outcome"] == "not_available":
        assert schedule.get_listings(unit=c["unit"])["available"] is False
        assert schedule.request_showing(sender_id=PROSPECT, unit=c["unit"], times=["2026-10-06 11:00"])["available"] is False
        return
    if exp["outcome"] == "refused":  # prospect asks for tenant contact: nothing private can reach them
        listing = json.dumps(schedule.get_listings(unit=c["unit"]))
        assert "Marcus" not in listing and TENANT_1B not in listing
        r = schedule.request_showing(sender_id=PROSPECT, unit=c["unit"], times=["2026-10-05 11:00"])
        schedule.confirm_showing(sender_id=MANAGER, showing_id=r["showing_id"], time="2026-10-05 11:00")
        raises(schedule.send_message, role="prospect", text="The tenant is Marcus Hill",
               showing_id=r["showing_id"])
        return
    r = schedule.request_showing(sender_id=PROSPECT, unit=c["unit"], times=c["proposed_times"], prospect_name="Alex Kim")
    if exp["outcome"] == "rejected":
        assert r["showing_id"] is None and r["valid_times"] == []
        assert schedule.REASONS[exp["reason"]] == r["rejected"][0]["reason"], r
        return
    assert r["valid_times"] == c["proposed_times"] and r["state"] == "proposed"
    assert sent("manager"), "agent must be asked"
    if exp["outcome"] == "agent_asked":
        assert not sent("tenant") and not sent("prospect")
        return
    sid = r["showing_id"]
    c_res = schedule.confirm_showing(sender_id=MANAGER, showing_id=sid, time=c["proposed_times"][0])
    if exp["outcome"] == "confirmed":  # vacant 5B
        assert c_res["state"] == "confirmed" and not sent("tenant")
        assert any(e["title"] == "Showing: unit 5B" for e in maple.calendar_events())
        assert sent("prospect")
        return
    assert c_res["state"] == "tenant_notified"
    notice = sent("tenant")[0]["text"]
    assert "Alex" not in notice and PROSPECT not in notice  # tenant never sees prospect details
    raises(schedule.tenant_response, sender_id=PROSPECT, showing_id=sid, objects=True)
    t_res = schedule.tenant_response(sender_id=TENANT_1B, showing_id=sid, objects=True)
    assert t_res["state"] == exp["state"] == "rejected"
    assert "other times" in sent("prospect")[-1]["text"]


def test_showing_cases():
    for c in CASES:
        run_case(c)
        print(f"  case {c['id']} ok: {c['expected']['outcome']}")


def test_no_objection_confirms_after_window():
    fresh("2026-10-03T14:00")
    os.environ["DEMO_MODE"] = "1"
    r = schedule.request_showing(sender_id=PROSPECT, unit="1B", times=["2026-10-05 11:00"])
    schedule.confirm_showing(sender_id=MANAGER, showing_id=r["showing_id"], time="2026-10-05 11:00")
    assert schedule.check_showings()["confirmed"] == []
    os.environ["MAPLE_NOW"] = "2026-10-03T14:03"  # demo window is 2 minutes
    assert schedule.check_showings()["confirmed"] == [r["showing_id"]]
    assert schedule.load_showing(r["showing_id"])["state"] == "confirmed"
    del os.environ["DEMO_MODE"]


def test_roles_and_calendar():
    fresh("2026-10-03T14:00")
    raises(schedule.confirm_showing, sender_id=TENANT_1B, showing_id="S1", time="2026-10-05 11:00")
    raises(schedule.get_calendar, sender_id=PROSPECT, start_date="2026-10-05")
    raises(schedule.request_showing, sender_id=TENANT_1B, unit="5B", times=["2026-10-06 11:00"])
    assert len(schedule.get_calendar(sender_id=MANAGER, start_date="2026-10-05")["events"]) == 2
    clash = schedule.add_event(sender_id=MANAGER, date="2026-10-05", start="09:30", end="10:00", title="x", type="admin")
    assert clash["added"] is False and clash["conflicts"]
    ok = schedule.add_event(sender_id=MANAGER, date="2026-10-05", start="11:00", end="11:30", title="Call", type="admin")
    assert ok["added"] is True


def test_manager_relay_and_boston_time():
    fresh("2026-10-03T13:50")
    r = schedule.request_showing(sender_id=PROSPECT, unit="1B", times=["2026-10-05 11:00"])
    assert r["now_boston"] == "Sat Oct 3, 1:50 PM EDT"
    m = schedule.message_prospect(sender_id=MANAGER, showing_id=r["showing_id"], text="Are you free at 11:00?")
    assert m["to"] == int(PROSPECT)  # works while still 'proposed'
    raises(schedule.message_prospect, sender_id=MANAGER, showing_id=r["showing_id"], text="Tenant is Marcus Hill")
    raises(schedule.message_prospect, sender_id=TENANT_1B, showing_id=r["showing_id"], text="hi")
    listed = schedule.list_showings(sender_id=MANAGER)["showings"][0]
    assert listed["times_proposed_by_prospect"] == ["2026-10-05 11:00"]
    c = schedule.confirm_showing(sender_id=MANAGER, showing_id=r["showing_id"], time="")  # single option
    assert c["objection_deadline"] == "Sun Oct 4, 1:50 AM EDT"  # 12h window outside DEMO_MODE
    assert c["done"].startswith(f"Confirmed {r['showing_id']} for Mon Oct 5, 11:00 AM EDT")
    t = maple.create_ticket(sender_id=TENANT_1B, message="No heat", category="heating_cooling",
                            urgency="urgent", responsible="landlord", clause="7.2")
    assert t["due_by"] == "Sun Oct 4, 1:50 PM EDT"


def test_reminders():
    fresh("2026-10-05T10:00")
    os.environ["DEMO_MODE"] = "1"  # 2-minute lead
    # a confirmed 1B showing at 11:00 Monday (requested Saturday, tenant did not object)
    os.environ["MAPLE_NOW"] = "2026-10-03T14:00"
    r = schedule.request_showing(sender_id=PROSPECT, unit="1B", times=["2026-10-05 11:00"], prospect_name="Satvik Rao")
    schedule.confirm_showing(sender_id=MANAGER, showing_id=r["showing_id"], time="2026-10-05 11:00")
    os.environ["MAPLE_NOW"] = "2026-10-03T14:03"
    schedule.check_showings()
    schedule.add_event(sender_id=MANAGER, date="2026-10-05", start="10:30", end="10:45", title="Call HeatPro", type="reminder")
    before = len(sent("manager"))
    os.environ["MAPLE_NOW"] = "2026-10-05T10:29"
    assert schedule.due_reminders()["sent"] == []  # reminder fires at its time, not before
    os.environ["MAPLE_NOW"] = "2026-10-05T10:30"
    assert [k.split(":")[1] for k in schedule.due_reminders()["sent"]] == ["manager"]
    os.environ["MAPLE_NOW"] = "2026-10-05T10:58"  # 2 min before the showing
    keys = schedule.due_reminders()["sent"]
    assert sorted(k.split(":")[1] for k in keys) == ["manager", "prospect", "tenant"], keys
    assert schedule.due_reminders()["sent"] == []  # never repeats
    tenant_msg, prospect_msg = sent("tenant")[-1]["text"], sent("prospect")[-1]["text"]
    assert "Satvik" not in tenant_msg and PROSPECT not in tenant_msg and "Marcus" not in prospect_msg
    assert "11:00 AM EDT" in prospect_msg and len(sent("manager")) == before + 2
    os.environ["MAPLE_NOW"] = "2026-10-05T11:05"
    assert schedule.due_reminders()["sent"] == []  # past events: nothing
    del os.environ["DEMO_MODE"]


def test_make_chart():
    import charts
    fresh("2026-10-03T14:00")
    maple.create_ticket(sender_id=TENANT_1B, message="No heat", category="heating_cooling",
                        urgency="urgent", responsible="landlord", clause="7.2")
    raises(charts.make_chart, sender_id=TENANT_1B, kind="week")
    for kind in ("week", "tickets"):
        r = charts.make_chart(sender_id=MANAGER, kind=kind)
        item = sent("manager")[-1]
        assert r["dry_run"] and r["summary"] and item["text"] == ""  # image only, no caption
        assert Path(item["media"]).stat().st_size > 10_000


def test_reminder_in_minutes():
    fresh("2026-10-03T16:02")
    r = schedule.add_event(sender_id=MANAGER, title="Call HeatPro", type="reminder", date="", start="", end="", in_minutes=3)
    assert r["event"]["start"] == "16:05" and r["at_boston"] == "Sat Oct 3, 4:05 PM EDT"
    os.environ["MAPLE_NOW"] = "2026-10-03T16:04"
    assert schedule.due_reminders()["sent"] == []
    os.environ["MAPLE_NOW"] = "2026-10-03T16:05"
    assert schedule.due_reminders()["sent"] == [f"{r['event']['id']}:manager"]


def test_send_message_rules():
    fresh("2026-10-03T14:00")
    t = maple.create_ticket(sender_id=TENANT_1B, message="No heat", category="heating_cooling",
                            urgency="urgent", responsible="landlord", clause="7.2")
    raises(schedule.send_message, role="tenant", text="Vendor booked", ticket_id=t["ticket_id"])  # not approved
    assert schedule.send_message(role="manager", text="New urgent ticket", ticket_id=t["ticket_id"])["to"] == int(MANAGER)
    raises(schedule.send_message, role="prospect", text="hi")  # no showing -> no recipient


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)}/{len(tests)} passed")
