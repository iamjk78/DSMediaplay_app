#!/usr/bin/env bash
# Starts the given executable: its self-test passes, then it stays alive and serves its bundled documentation.
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

# The application builds its main window and reaches the credential store (the documentation server alone starts
# before any of that, so it would be served even by an application that never gets a window)
"$1" --self-test &
test_pid=$!
for _ in $(seq 1 60); do
  kill -0 $test_pid 2>/dev/null || break
  sleep 1
done
if kill -0 $test_pid 2>/dev/null; then
  kill $test_pid 2>/dev/null || true
  command -v taskkill >/dev/null 2>&1 && taskkill //F //IM DSMediaplay_app.exe >/dev/null 2>&1
  echo "The self-test did not finish in 60 seconds"; exit 1
fi
wait $test_pid || { echo "The self-test of the application failed"; exit 1; }

# A configuration of its own: with none, a clean runner shows the dialog that asks for the language and waits in it, and
# on a computer of a person the application would open that person's accounts (and ask the credential store for them)
config_dir=$(mktemp -d)
echo '{"lang": "cz", "font": ["Helvetica", 12], "default": ["", ""], "logins": {}}' > "$config_dir/logins.json"
config="$config_dir/logins.json"
command -v cygpath >/dev/null 2>&1 && config=$(cygpath -w "$config")

"$1" -j "$config" &
app_pid=$!
ok=0
for _ in $(seq 1 30); do
  if curl -sf -o /dev/null http://127.0.0.1:8080/en/; then ok=1; break; fi
  sleep 1
done
alive=0
kill -0 $app_pid 2>/dev/null && alive=1

kill $app_pid 2>/dev/null || true
command -v taskkill >/dev/null 2>&1 && taskkill //F //IM DSMediaplay_app.exe >/dev/null 2>&1
sleep 2

rm -rf "$config_dir"
[ "$ok" = "1" ] && [ "$alive" = "1" ] || { echo "Application did not start or crashed"; exit 1; }
echo "Application started and served its documentation"
