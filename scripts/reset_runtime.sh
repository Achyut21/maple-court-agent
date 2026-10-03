#!/usr/bin/env bash
# Clear demo state in the sandbox runtime: tickets, showings, outbox, and calendar additions.
# Keeps metrics.jsonl (speed history), the showing timer, and eval/ on the host.
set -u
nemoclaw hackathon exec --timeout 60 -- sh -c '
  cd /sandbox/maple/runtime &&
  rm -rf tickets showings outbox charts calendar_added.json reminders_sent.json DRY_SEND &&
  mkdir -p tickets showings outbox &&
  echo "runtime now:" && ls -A' 2>&1 | grep -v 'permission cleanup\|Active gateway'
