#!/usr/bin/env bash
# Clean slate before recording: clear runtime demo state and the three Telegram chat sessions.
# Keeps runtime/metrics.jsonl, the showing timer, and everything in eval/.
#   scripts/demo_reset.sh            run now
#   scripts/demo_reset.sh --at 1655  wait until 16:55 Boston time, then run
set -u
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--at" ]; then
  until [ "$(TZ=America/New_York date +%H%M)" -ge "$2" ]; do sleep 20; done
fi
echo "== demo reset at $(TZ=America/New_York date '+%-I:%M:%S %p %Z')"
scripts/reset_runtime.sh
manager=$(python3 -c "import json; print(json.load(open('data/tenants.json'))['manager_ids'][0])")
tenant=$(python3 -c "import json; print(next(t['telegram_id'] for t in json.load(open('data/tenants.json'))['tenants'] if t['unit'] == '1B'))")
prospect=8245611231  # demo prospect (unregistered by design; see CLAUDE.md)
for id in "$manager" "$tenant" "$prospect"; do
  nemoclaw hackathon sessions reset "agent:main:telegram:direct:$id" --reason reset 2>&1 | grep -v "Active gateway"
done
nemoclaw hackathon exec --timeout 30 -- sh -c 'echo "metrics lines kept: $(wc -l < /sandbox/maple/runtime/metrics.jsonl)";
  kill -0 $(cat /sandbox/maple/runtime/timer.pid) && echo "showing timer alive"' 2>&1 | grep -v 'permission cleanup\|Active gateway'
