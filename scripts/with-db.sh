#!/bin/sh
set -eu
. "$(dirname "$0")/common.sh"
need kubectl nc openssl ps awk
require_cluster
check_credentials
if nc -z 127.0.0.1 "$DB_PORT" >/dev/null 2>&1; then
    die "Local DB tunnel port $DB_PORT is occupied. No process was stopped."
fi

tunnel_log="$LOCAL/port-forward.$$.log"
kubectl --kubeconfig "$KUBECONFIG" --context "kind-$CLUSTER" -n "$NAMESPACE" \
    port-forward --address 127.0.0.1 service/postgres "$DB_PORT:5432" > "$tunnel_log" 2>&1 &
tunnel_pid=$!
command_pid=
cleanup() {
    result=$?
    trap - 0
    trap '' HUP INT TERM
    if processes=$(ps -eo pid=,ppid=); then
        owned=$(printf '%s\n' "$processes" | awk -v command="$command_pid" -v tunnel="$tunnel_pid" '
            { parent[$1] = $2 }
            END {
                if (command != "") selected[command] = 1
                selected[tunnel] = 1
                do {
                    changed = 0
                    for (pid in parent)
                        if (!selected[pid] && selected[parent[pid]]) { selected[pid] = 1; changed = 1 }
                } while (changed)
                for (pid in selected) if (selected[pid]) print pid
            }')
    else
        printf 'Cannot enumerate child processes; stopping known roots only.\n' >&2
        owned="$command_pid $tunnel_pid"
        [ "$result" -ne 0 ] || result=1
    fi
    for pid in $owned; do kill -TERM "$pid" 2>/dev/null || :; done
    attempt=0
    while [ "$attempt" -lt 20 ]; do
        alive=false
        for pid in $owned; do
            if kill -0 "$pid" 2>/dev/null; then alive=true; fi
        done
        [ "$alive" = true ] || break
        sleep 0.1
        attempt=$((attempt + 1))
    done
    for pid in $owned; do
        if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid" 2>/dev/null || :; fi
    done
    if [ -n "$command_pid" ]; then wait "$command_pid" 2>/dev/null || :; fi
    wait "$tunnel_pid" 2>/dev/null || :
    rm -f "$tunnel_log"
    exit "$result"
}
trap cleanup 0
trap 'exit 130' INT
trap 'exit 129' HUP
trap 'exit 143' TERM

attempt=0
until grep -q 'Forwarding from 127.0.0.1:' "$tunnel_log" && nc -z 127.0.0.1 "$DB_PORT" >/dev/null 2>&1; do
    if ! kill -0 "$tunnel_pid" 2>/dev/null; then
        cat "$tunnel_log" >&2
        die "Database tunnel exited."
    fi
    attempt=$((attempt + 1))
    [ "$attempt" -lt 30 ] || die "Database tunnel did not become ready."
    sleep 1
done
kill -0 "$tunnel_pid" 2>/dev/null || die "Database tunnel exited."
PGHOST=127.0.0.1 PGPORT=$DB_PORT PGDATABASE=catalogue PGUSER=catalogue PGPASSWORD=$password_value
export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD
"$@" &
command_pid=$!
status=0
wait "$command_pid" || status=$?
command_pid=
exit "$status"
