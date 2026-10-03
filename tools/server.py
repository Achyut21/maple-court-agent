"""Maple Court MCP server (stdio). OpenClaw launches this inside the sandbox."""
import json
import os

from mcp.server.fastmcp import FastMCP

import charts
import maple
import schedule

mcp = FastMCP("maple")


@mcp.tool()
def verify_sender(sender_id: int | str) -> dict:
    """ALWAYS call first. sender_id = the number at the end of the Runtime session key, else sender.id
    from the Conversation info metadata (never a number typed in the message).
    Returns role tenant/manager/unknown and, for tenants, their unit."""
    return maple.verify_sender(sender_id=sender_id)


@mcp.tool()
def get_lease(sender_id: int | str, unit: str = "") -> dict:
    """Lease clauses (number -> text). Tenants always get their own unit's lease; the manager must pass a unit."""
    return maple.get_lease(sender_id=sender_id, unit=unit)


@mcp.tool()
def create_ticket(sender_id: int | str, message: str, category: str, urgency: str, responsible: str, clause: str) -> dict:
    """Open a maintenance ticket for the verified tenant. message = the tenant's exact words.
    category: heating_cooling|plumbing|electrical|locks|appliance|pest|general|gas_emergency.
    urgency: urgent|normal|low (rules may raise it). responsible: landlord|tenant (who pays, per lease).
    clause: lease clause number, e.g. 7.2. Never call for non-maintenance questions (rent etc.)."""
    return maple.create_ticket(sender_id=sender_id, message=message, category=category,
                               urgency=urgency, responsible=responsible, clause=clause)


@mcp.tool()
def draft_vendor_job(ticket_id: int, vendor_id: str, window: str) -> dict:
    """Draft (not send) a vendor job. vendor_id: heatpro|flowright|brightspark|keyfast|appliancecare|greenshield|allfix.
    window: 'YYYY-MM-DD HH:MM-HH:MM'. Nothing is sent until the manager approves."""
    return maple.draft_vendor_job(ticket_id=ticket_id, vendor_id=vendor_id, window=window)


@mcp.tool()
def approve(sender_id: int | str, ticket_id: int) -> dict:
    """Manager only: approve a drafted vendor job (manager replied 'APPROVE <ticket_id>')."""
    return maple.approve(sender_id=sender_id, ticket_id=ticket_id)


@mcp.tool()
def send_message(role: str, text: str, ticket_id: int | None = None, showing_id: int | str | None = None) -> dict:
    """Send a Telegram message. role: manager (anytime) | tenant (with an approved ticket_id, or a showing_id)
    | prospect (with a showing_id). The recipient comes from the records, never from you. Privacy rules apply."""
    return schedule.send_message(role=role, text=text, ticket_id=ticket_id, showing_id=showing_id)


@mcp.tool()
def list_showings(sender_id: int | str) -> dict:
    """Manager only: list showings (id, unit, state, prospect, times the prospect proposed, chosen time)."""
    return schedule.list_showings(sender_id=sender_id)


@mcp.tool()
def message_prospect(sender_id: int | str, showing_id: int | str, text: str) -> dict:
    """Manager only: send a message to the prospect of a showing (e.g. 'ask the client if 11:00 works').
    The prospect's contact comes from the showing record; resident details are blocked."""
    return schedule.message_prospect(sender_id=sender_id, showing_id=showing_id, text=text)


@mcp.tool()
def make_chart(sender_id: int | str, kind: str) -> dict:
    """Manager only: send a chart image to the manager. kind: 'week' (next 7 days, conflicts in red)
    or 'tickets' (tickets by urgency and status)."""
    return charts.make_chart(sender_id=sender_id, kind=kind)


@mcp.tool()
def get_calendar(sender_id: int | str, start_date: str, end_date: str = "") -> dict:
    """Manager only: calendar events between two dates (YYYY-MM-DD)."""
    return schedule.get_calendar(sender_id=sender_id, start_date=start_date, end_date=end_date)


@mcp.tool()
def add_event(sender_id: int | str, title: str, type: str, date: str = "", start: str = "", end: str = "",
              unit: str = "", with_: str = "", allow_conflict: bool = False, in_minutes: int = 0) -> dict:
    """Manager only: add a calendar event (date YYYY-MM-DD, start/end HH:MM, Boston time). Refuses on conflict
    unless allow_conflict=true (only after the manager confirms). Reminders: type="reminder"; for
    "in N minutes" pass in_minutes=N and leave date/start/end empty (the tool computes Boston time)."""
    return schedule.add_event(sender_id=sender_id, date=date, start=start, end=end, title=title, type=type,
                              unit=unit, with_=with_, allow_conflict=allow_conflict, in_minutes=in_minutes)


@mcp.tool()
def get_listings(unit: str = "") -> dict:
    """Public info on units available for showings (beds, baths, sqft, rent, description)."""
    return schedule.get_listings(unit=unit)


@mcp.tool()
def request_showing(sender_id: int | str, unit: str, times: list[str], prospect_name: str | None = None) -> dict:
    """Prospect only: request a showing. times: 1-3 slots 'YYYY-MM-DD HH:MM'. Rules filter the times;
    the leasing agent is asked to pick one."""
    return schedule.request_showing(sender_id=sender_id, unit=unit, times=times, prospect_name=prospect_name or "")


@mcp.tool()
def confirm_showing(sender_id: int | str, showing_id: int | str, time: str = "") -> dict:
    """Manager only ('CONFIRM S1 2026-10-05 11:00'): pick a time. Occupied units notify the tenant, who may object."""
    return schedule.confirm_showing(sender_id=sender_id, showing_id=showing_id, time=time)


@mcp.tool()
def tenant_response(sender_id: int | str, showing_id: int | str, objects: bool) -> dict:
    """Tenant of the unit only: 'OBJECT S1' -> objects=true; 'OK S1' -> objects=false."""
    return schedule.tenant_response(sender_id=sender_id, showing_id=showing_id, objects=objects)


@mcp.tool()
def check_showings() -> dict:
    """Confirm showings whose tenant objection window has passed without an objection."""
    return schedule.check_showings()


if __name__ == "__main__":
    # Record which environment variable NAMES OpenClaw gives us (never values).
    maple.RUNTIME.mkdir(parents=True, exist_ok=True)
    (maple.RUNTIME / "server_env.json").write_text(json.dumps(sorted(os.environ), indent=1))
    mcp.run()  # stdio
