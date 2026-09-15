#!/bin/sh
set -eu
. "$(dirname "$0")/common.sh"
require_cluster
child_file=$(mktemp "$LOCAL/tunnel-child.XXXXXX")
grandchild_file=$(mktemp "$LOCAL/tunnel-grandchild.XXXXXX")
wrapper_pid=
cleanup() {
    for file in "$child_file" "$grandchild_file"; do
        pid=$(cat "$file")
        case "$pid" in ''|*[!0-9]*) ;; *) kill -KILL "$pid" 2>/dev/null || :;; esac
    done
    if [ -n "$wrapper_pid" ]; then kill -TERM "$wrapper_pid" 2>/dev/null || :; fi
    rm -f "$child_file" "$grandchild_file"
}
trap cleanup 0
sh "$ROOT/scripts/with-db.sh" sh -c '
    trap "" TERM
    printf "%s" "$$" > "$1"
    sleep 60 &
    printf "%s" "$!" > "$2"
    wait
' sh "$child_file" "$grandchild_file" &
wrapper_pid=$!
attempt=0
until [ -s "$child_file" ] && [ -s "$grandchild_file" ]; do
    kill -0 "$wrapper_pid" 2>/dev/null || die "Tunnel wrapper exited before the test command started."
    attempt=$((attempt + 1))
    [ "$attempt" -lt 15 ] || die "Timed out starting the tunnel cancellation test."
    sleep 1
done
started=$(date +%s)
kill -TERM "$wrapper_pid"
status=0
wait "$wrapper_pid" || status=$?
wrapper_pid=
[ "$status" -eq 143 ] || die "Tunnel wrapper did not preserve SIGTERM status."
[ "$(($(date +%s) - started))" -lt 8 ] || die "Tunnel cancellation was not bounded."
for file in "$child_file" "$grandchild_file"; do
    pid=$(cat "$file")
    if kill -0 "$pid" 2>/dev/null; then die "An owned command process survived cancellation."; fi
done
if nc -z 127.0.0.1 "$DB_PORT" >/dev/null 2>&1; then die "The database tunnel survived cancellation."; fi
printf 'PASS: wrapper cancellation stopped its TERM-resistant command tree and DB tunnel.\n'
