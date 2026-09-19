#!/usr/bin/env bash
# Starts the given executable and checks that it stays alive and serves its bundled documentation.
# Usage: packaging/smoke_test.sh <path to executable>
set -u

# The check is meaningless if something else already answers on the documentation port
for _ in $(seq 1 10); do
  curl -sf -o /dev/null http://127.0.0.1:8080/en/ || break
  sleep 1
done
if curl -sf -o /dev/null http://127.0.0.1:8080/en/; then
  echo "Port 8080 is already in use, the result would not prove anything"; exit 1
fi

"$1" &
app_pid=$!
ok=0
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null http://127.0.0.1:8080/en/; then ok=1; break; fi
  sleep 1
done
alive=0
kill -0 $app_pid 2>/dev/null && alive=1

kill $app_pid 2>/dev/null || true
command -v taskkill >/dev/null 2>&1 && taskkill //F //IM DSM_GUI.exe >/dev/null 2>&1
sleep 2

[ "$ok" = "1" ] && [ "$alive" = "1" ] || { echo "Application did not start or crashed"; exit 1; }
echo "Application started and served its documentation"
