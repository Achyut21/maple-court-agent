"""Manager charts as PNGs for Telegram: the week ahead and open tickets. matplotlib, Agg backend."""
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from maple import RUNTIME, TZ, boston, calendar_events, deliver, logged, now  # noqa: E402
from schedule import manager_id, require_manager  # noqa: E402

# Reference palette (dataviz skill), light mode.
SURFACE, INK, INK_2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE, CRITICAL = "#2a78d6", "#eb6834", "#d03b3b"
SEND_DIR = Path("/sandbox/.openclaw/workspace/charts")  # an outbound-media root OpenClaw always allows


def style(ax):
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def minutes(hhmm):
    h, m = map(int, hhmm.split(":"))
    return h + m / 60


def lanes(events):
    """Greedy lane per event so overlapping events sit side by side instead of on top of each other."""
    ends, out = [], {}
    for e in sorted(events, key=lambda e: e["start"]):
        lane = next((i for i, end in enumerate(ends) if end <= e["start"]), len(ends))
        if lane == len(ends):
            ends.append(e["end"])
        else:
            ends[lane] = e["end"]
        out[id(e)] = lane
    return out, max(len(ends), 1)


def week_chart(path):
    today = now().date()
    days = [today + timedelta(days=i) for i in range(7)]
    all_events = calendar_events()
    fig, ax = plt.subplots(figsize=(10, 5.4), facecolor=SURFACE)
    style(ax)
    clashes = 0
    for row, day in enumerate(days):
        events = [e for e in all_events if e["date"] == day.isoformat()]
        lane_of, n = lanes(events)
        height = 0.76 / n
        for e in events:
            clash = any(o is not e and o["start"] < e["end"] and e["start"] < o["end"] for o in events)
            clashes += clash
            start, end = minutes(e["start"]), minutes(e["end"])
            top = row - 0.38 + lane_of[id(e)] * height
            ax.broken_barh([(start, max(end - start, 0.25))], (top, height),
                           facecolors=CRITICAL if clash else BLUE, edgecolor=SURFACE, linewidth=2)
            # label in the free space after the bar, up to the next event in the same lane
            later = [minutes(o["start"]) for o in events if lane_of[id(o)] == lane_of[id(e)] and o["start"] >= e["end"]]
            room = (min(later) if later else 21) - end - 0.1
            chars = int(room * 11)
            label = ("! " if clash else "") + e["title"]
            if chars >= 4:
                ax.text(end + 0.08, top + height / 2, label if len(label) <= chars else label[:chars - 1] + "…",
                        va="center", fontsize=7 if n > 1 else 7.5, color=INK)
    ax.set_yticks(range(7), [d.strftime("%a %b %-d") for d in days])
    ax.set_ylim(6.6, -0.6)
    ax.set_xlim(8, 21)
    ax.set_xticks(range(8, 22, 2), [f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}" for h in range(8, 22, 2)])
    ax.set_title(f"Your week at Maple Court (Boston time, from {boston(now())})", loc="left",
                 fontsize=12, color=INK, pad=24)
    ax.legend(handles=[Patch(color=BLUE, label="Event"), Patch(color=CRITICAL, label="! Conflict (overlaps)")],
              loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2, frameon=False, fontsize=8, labelcolor=INK_2)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return f"Your next 7 days: {clashes} events in conflict (marked red, with !)."


def tickets_chart(path):
    folder = RUNTIME / "tickets"
    tickets = [json.loads(p.read_text()) for p in folder.glob("*.json")] if folder.exists() else []
    levels = ["urgent", "normal", "low"]
    waiting = [sum(t["urgency"] == u and t["status"] == "open" for t in tickets) for u in levels]
    booked = [sum(t["urgency"] == u and t["status"] == "vendor_booked" for t in tickets) for u in levels]
    fig, ax = plt.subplots(figsize=(8, 3.6), facecolor=SURFACE)
    style(ax)
    ax.barh(levels, waiting, color=BLUE, edgecolor=SURFACE, linewidth=2, label="Open (awaiting approval)")
    ax.barh(levels, booked, left=waiting, color=ORANGE, edgecolor=SURFACE, linewidth=2, label="Vendor booked")
    for i, (w, b) in enumerate(zip(waiting, booked)):
        ax.text(w + b + 0.05, i, f"{w + b}", va="center", fontsize=9, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, max([w + b for w, b in zip(waiting, booked)] + [1]) * 1.15)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.set_title(f"Tickets by urgency ({boston(now())})", loc="left", fontsize=12, color=INK, pad=24)
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2, frameon=False, fontsize=8, labelcolor=INK_2)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    plt.close(fig)
    return f"Tickets: {sum(waiting)} awaiting approval, {sum(booked)} with a vendor booked."


@logged
def make_chart(sender_id, kind):
    require_manager(sender_id)
    if kind not in ("week", "tickets"):
        raise ValueError("kind must be 'week' or 'tickets'")
    folder = RUNTIME / "charts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{kind}-{datetime.now(TZ).strftime('%H%M%S')}.png"
    caption = (week_chart if kind == "week" else tickets_chart)(path)
    media = path
    if SEND_DIR.parent.exists():  # inside the sandbox: hand OpenClaw a copy from an allowed media root
        SEND_DIR.mkdir(exist_ok=True)
        media = Path(shutil.copy(path, SEND_DIR / path.name))
    item = deliver("manager", manager_id(), "", media=str(media), chart=str(path))  # image only, no caption
    return {"sent": item["sent"], "dry_run": item.get("dry_run", False), "summary": caption,
            "next_step": f"The chart image is already in the manager's chat. Reply with exactly this one line: {caption}"}
