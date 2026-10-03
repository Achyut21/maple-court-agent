"""Confirms showings once the tenant's objection window passes, and sends due reminders. Run next to the MCP server:
    /sandbox/.venv/bin/python /sandbox/maple/tools/showing_timer.py
"""
import time

import schedule

while True:
    due = schedule.check_showings.__wrapped__()  # unlogged: avoids a metrics line every tick
    if due["confirmed"]:
        print("confirmed:", due["confirmed"], flush=True)
    reminders = schedule.due_reminders()
    if reminders["sent"]:
        print("reminders:", reminders["sent"], flush=True)
    time.sleep(15)
