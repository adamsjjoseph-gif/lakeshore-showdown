#!/bin/sh
# Dev helper: (re)start the server in the background on $PORT (default 8787), pid in /tmp/spiff_server.pid
cd "$(dirname "$0")/.."
PORT=${PORT:-8787}
[ -f /tmp/spiff_server.pid ] && kill "$(cat /tmp/spiff_server.pid)" 2>/dev/null && sleep 0.5
PORT=$PORT nohup python3 server.py > /tmp/spiff_server.log 2>&1 &
echo $! > /tmp/spiff_server.pid
sleep 1; echo "server pid $(cat /tmp/spiff_server.pid) on port $PORT"
