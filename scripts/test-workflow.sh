#!/bin/sh
set -eu
umask 077
printf 'Testing workflow with isolated command stubs; no real cluster is modified.\n'
ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
mkdir -p "$ROOT/.local"
SANDBOX=$(mktemp -d "$ROOT/.local/workflow-tests.XXXXXX")
cleanup() {
    find "$SANDBOX" -type f -delete
    find "$SANDBOX" -depth -type d -empty -delete
}
trap cleanup 0
mkdir -p "$SANDBOX/bin" "$SANDBOX/scripts" "$SANDBOX/.local"
cp "$ROOT/scripts/common.sh" "$ROOT/scripts/dev.sh" "$SANDBOX/scripts/"
WORKFLOW_TEST_ROOT=$SANDBOX
export WORKFLOW_TEST_ROOT
UI_PORT=18420 API_PORT=18421 DB_PORT=18422 VITE_PORT=18423
export UI_PORT API_PORT DB_PORT VITE_PORT

cat > "$SANDBOX/bin/docker" <<'EOF'
#!/bin/sh
set -eu
context=active-desktop
if [ "$1" = --context ]; then context=$2; shift 2; fi
case "$1" in
    context) printf 'active-desktop\n';;
    info) printf '%s\n' "${WORKFLOW_DOCKER_OS:-linux}";;
    ps) [ ! -f "$WORKFLOW_TEST_ROOT/present" ] || jq -r .id "$WORKFLOW_TEST_ROOT/node.json";;
    inspect) cat "$WORKFLOW_TEST_ROOT/node.json";;
    build) printf 'build:%s\n' "$context" >> "$WORKFLOW_TEST_ROOT/actions";;
    *) exit 99;;
esac
EOF
cat > "$SANDBOX/bin/kind" <<'EOF'
#!/bin/sh
set -eu
[ "$DOCKER_CONTEXT" = recorded-desktop ] || exit 98
printf 'kind:%s:%s\n' "$DOCKER_CONTEXT" "$*" >> "$WORKFLOW_TEST_ROOT/actions"
if [ "$1" = delete ]; then rm -f "$WORKFLOW_TEST_ROOT/present"; fi
EOF
cat > "$SANDBOX/bin/kubectl" <<'EOF'
#!/bin/sh
set -eu
case "$*" in
    *"config view"*) printf 'https://127.0.0.1:53653';;
    *"get secret postgres"*) cat "$WORKFLOW_TEST_ROOT/remote-secret.json";;
    *) printf 'Kubernetes API deliberately unavailable in this fixture.\n' >&2; exit 97;;
esac
EOF
chmod +x "$SANDBOX/bin/docker" "$SANDBOX/bin/kind" "$SANDBOX/bin/kubectl"
PATH="$SANDBOX/bin:$PATH"
export PATH

reset_fixture() {
    printf x > "$SANDBOX/present"
    : > "$SANDBOX/actions"
    printf '%064d' 1 > "$SANDBOX/.local/db-password"
    encoded=$(openssl base64 -A < "$SANDBOX/.local/db-password")
    jq -n --arg password "$encoded" '{data:{password:$password}}' > "$SANDBOX/remote-secret.json"
    jq -n --arg root "$SANDBOX" '{
        container_id:"fixture-container-id", docker_context:"recorded-desktop",
        project_root:$root, api_server:"https://127.0.0.1:53653", ui_port:18420
    }' > "$SANDBOX/.local/owner.json"
    printf '{}' > "$SANDBOX/.local/kubeconfig"
    printf '%s' '{"id":"fixture-container-id","name":"/model-catalogue-control-plane","cluster":"model-catalogue","ports":{"30420/tcp":[{"HostIp":"127.0.0.1","HostPort":"18420"}],"6443/tcp":[{"HostIp":"127.0.0.1","HostPort":"53653"}]}}' > "$SANDBOX/node.json"
}

expect_rejected() {
    expected=$1
    shift
    if "$@" > "$SANDBOX/result" 2>&1; then
        printf 'Expected workflow rejection: %s\n' "$expected" >&2
        exit 1
    fi
    grep -q "$expected" "$SANDBOX/result" || { cat "$SANDBOX/result" >&2; exit 1; }
    [ ! -s "$SANDBOX/actions" ] || { cat "$SANDBOX/actions" >&2; exit 1; }
}

reset_fixture
sh "$SANDBOX/scripts/dev.sh" down
grep -q 'kind:recorded-desktop:delete' "$SANDBOX/actions"
[ ! -f "$SANDBOX/present" ]
sh "$SANDBOX/scripts/dev.sh" down
printf 'PASS: recorded Docker context, API-independent teardown, idempotent teardown\n'

reset_fixture
jq '.id = "unrelated-container"' "$SANDBOX/node.json" > "$SANDBOX/new-node.json"
mv "$SANDBOX/new-node.json" "$SANDBOX/node.json"
expect_rejected 'Cluster identity' sh "$SANDBOX/scripts/dev.sh" down
printf 'PASS: unrelated container cannot be deleted\n'

reset_fixture
jq '.ports = {}' "$SANDBOX/node.json" > "$SANDBOX/new-node.json"
mv "$SANDBOX/new-node.json" "$SANDBOX/node.json"
sh "$SANDBOX/scripts/dev.sh" down
grep -q 'kind:recorded-desktop:delete' "$SANDBOX/actions"
printf 'PASS: an owned stopped container can be removed without network mappings\n'

reset_fixture
expect_rejected 'Linux containers' env WORKFLOW_DOCKER_OS=windows sh "$SANDBOX/scripts/dev.sh" up
printf 'PASS: non-Linux containers are rejected before mutation\n'

reset_fixture
expect_rejected 'UI_PORT changed' env UI_PORT=18425 sh "$SANDBOX/scripts/dev.sh" up
printf 'PASS: host mapping drift is rejected before mutation\n'

reset_fixture
printf '\n' >> "$SANDBOX/.local/db-password"
expect_rejected 'trailing whitespace' sh "$SANDBOX/scripts/dev.sh" up
printf 'PASS: whitespace-padded credentials are rejected\n'

reset_fixture
printf '%064d' 2 > "$SANDBOX/.local/db-password"
expect_rejected 'Local credentials differ' sh "$SANDBOX/scripts/dev.sh" up
printf 'PASS: credential drift is rejected before mutation\n'

reset_fixture
rm "$SANDBOX/.local/db-password"
expect_rejected 'password file is missing' sh "$SANDBOX/scripts/dev.sh" up
printf 'PASS: missing credentials are not regenerated for an existing cluster\n'

mkdir -p "$SANDBOX/code" "$SANDBOX/fail-bin"
printf 'pass\n' > "$SANDBOX/code/example.py"
printf '#!/bin/sh\nexit 37\n' > "$SANDBOX/fail-bin/find"
chmod +x "$SANDBOX/fail-bin/find"
if PATH="$SANDBOX/fail-bin:$PATH" sh "$ROOT/scripts/source-hashes.sh" "$SANDBOX/code" shasum > "$SANDBOX/result" 2>&1; then
    printf 'A failed source enumeration was accepted.\n' >&2
    exit 1
fi
rm "$SANDBOX/fail-bin/find"
printf '#!/bin/sh\nexit 38\n' > "$SANDBOX/fail-bin/shasum"
chmod +x "$SANDBOX/fail-bin/shasum"
if PATH="$SANDBOX/fail-bin:$PATH" sh "$ROOT/scripts/source-hashes.sh" "$SANDBOX/code" shasum > "$SANDBOX/result" 2>&1; then
    printf 'A failed source hash was accepted.\n' >&2
    exit 1
fi
printf 'PASS: source enumeration and hashing failures propagate\n'
