#!/usr/bin/env bash
# Deploy the Maple Court tools into the NemoClaw sandbox and register them with OpenClaw.
#   scripts/deploy.sh          upload tools/ + data/ + prompt, (re)register the MCP server
#   scripts/deploy.sh --first  also upload wheels/ and build /sandbox/.venv offline
#   scripts/deploy.sh --code   upload code/data/prompt and reload only (no openclaw.json write)
# Note: `nemoclaw exec` can exit 1 on a host-side cleanup warning even when the command
# succeeded, so check the printed output rather than exit codes.
set -u
cd "$(dirname "$0")/.."
SB=hackathon
run() { nemoclaw "$SB" exec --timeout 300 -- sh -c "$1" 2>&1 | grep -v 'permission cleanup\|Active gateway\|UNDICI\|trace-warnings'; }

if [ "${1:-}" = "--first" ]; then
  nemoclaw "$SB" upload wheels /sandbox/maple/
  run 'python3 -m venv /sandbox/.venv &&
       /sandbox/.venv/bin/pip install -q --no-index --find-links /sandbox/maple/wheels mcp &&
       /sandbox/.venv/bin/python -c "import mcp.server.fastmcp; print(\"mcp installed\")"'
fi

run 'rm -rf /sandbox/maple/tools /sandbox/maple/data'
nemoclaw "$SB" upload tools /sandbox/maple/
nemoclaw "$SB" upload data /sandbox/maple/
nemoclaw "$SB" upload prompt/AGENTS.md /sandbox/.openclaw/workspace/AGENTS.md  # original: prompt/original/
# DRY_SEND=1 scripts/deploy.sh records outbound Telegram messages in runtime/outbox without sending.
SEND=live; [ "${DRY_SEND:-}" = "1" ] && SEND=dry
ENV="\"DEMO_MODE\":\"1\",\"MAPLE_SEND\":\"$SEND\""
if [ "${1:-}" = "--code" ]; then
  run "openclaw mcp reload"
else
run "openclaw mcp set maple '{\"command\":\"/sandbox/.venv/bin/python\",\"args\":[\"/sandbox/maple/tools/server.py\"],\"cwd\":\"/sandbox/maple\",\"env\":{$ENV}}' &&
     openclaw mcp reload && openclaw mcp show maple"
fi
# Showing timer: confirms showings once the tenant objection window passes (DEMO_MODE: 2 minutes).
run "P=/sandbox/maple/runtime/timer.pid; [ -f \$P ] && kill \$(cat \$P) 2>/dev/null; cd /sandbox/maple/tools &&
     DEMO_MODE=1 MAPLE_SEND=$SEND setsid nohup /sandbox/.venv/bin/python showing_timer.py >> /sandbox/maple/runtime/timer.log 2>&1 < /dev/null &
     echo \$! > \$P; sleep 2; kill -0 \$(cat \$P) && echo \"showing timer running (pid \$(cat \$P), send=$SEND)\""
