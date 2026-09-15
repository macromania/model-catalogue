#!/bin/sh
set -eu
. "$(dirname "$0")/common.sh"

up() {
    need kind kubectl curl openssl nc
    docker_ready
    mkdir -p "$LOCAL"
    current_id=$(node_id) || die "Cannot list Docker containers."
    if [ -n "$current_id" ]; then
        check_owner
        check_network
        check_kubeconfig
        check_host_mapping
        check_credentials
    else
        if nc -z 127.0.0.1 "$UI_PORT" >/dev/null 2>&1; then
            die "UI_PORT $UI_PORT is occupied. No process was stopped."
        fi
        if [ ! -f "$PASSWORD_FILE" ]; then
            generated_password=$(openssl rand -hex 32) || die "Cannot generate database credentials."
            printf '%s' "$generated_password" > "$PASSWORD_FILE"
        fi
        validate_password
    fi

    d build -t "$API_IMAGE" backend
    d build --build-arg "UI_PORT=$UI_PORT" --build-arg "VITE_PORT=$VITE_PORT" -t "$UI_IMAGE" frontend
    if [ -z "$current_id" ]; then
        cat > "$LOCAL/kind.yaml" <<EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
networking:
  apiServerAddress: 127.0.0.1
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30420
        hostPort: $UI_PORT
        listenAddress: 127.0.0.1
        protocol: TCP
EOF
        if kind create cluster --name "$CLUSTER" --config "$LOCAL/kind.yaml" --kubeconfig "$KUBECONFIG" --wait 180s; then
            save_owner
        else
            die "Kind creation failed before ownership was recorded. No existing cluster was adopted."
        fi
    fi
    check_owner
    kind load docker-image "$API_IMAGE" "$UI_IMAGE" --name "$CLUSTER"
    printf '{"apiVersion":"v1","kind":"Namespace","metadata":{"name":"%s"}}' "$NAMESPACE" | k apply -f -
    check_credentials
    secret=$(k create secret generic postgres "--from-file=password=$PASSWORD_FILE" --dry-run=client -o json) || die "Cannot prepare database Secret."
    printf '%s' "$secret" | k apply -f -
    k apply -f k8s/app.yaml
    k rollout status statefulset/postgres --timeout=180s
    k rollout restart deployment/api deployment/ui
    k rollout status deployment/api --timeout=180s
    k rollout status deployment/ui --timeout=180s
    ready=$(curl --fail --silent --show-error --max-time 5 --retry 20 \
        --retry-connrefused --retry-delay 1 --retry-max-time 60 \
        "http://127.0.0.1:$UI_PORT/api/health/ready") || die "The UI proxy cannot reach the API."
    printf '%s' "$ready" | jq -e '.status == "ok"' >/dev/null || die "Unexpected readiness response."
    printf '\nDashboard: http://127.0.0.1:%s\nPopulate or refresh it with make seed.\n' "$UI_PORT"
}

seed() {
    need uv
    set -- uv run --frozen --directory "$ROOT/backend" python -m app.seed
    if [ -n "${CATALOG_FILE:-}" ]; then
        case "$CATALOG_FILE" in /*) catalog_file=$CATALOG_FILE;; *) catalog_file="$ROOT/$CATALOG_FILE";; esac
        set -- "$@" --catalog-file "$catalog_file"
    fi
    if [ -n "${AZURE_FILE:-}" ]; then
        case "$AZURE_FILE" in /*) azure_file=$AZURE_FILE;; *) azure_file="$ROOT/$AZURE_FILE";; esac
        set -- "$@" --azure-file "$azure_file"
    fi
    sh "$ROOT/scripts/with-db.sh" "$@"
}

verify() {
    need kubectl curl uv npm shasum cmp
    require_cluster
    sh "$ROOT/scripts/with-db.sh" env TEST_POSTGRES=1 uv run --frozen --directory "$ROOT/backend" pytest
    state=$(api_get /api/status) || die "Cannot read snapshot status."
    printf '%s' "$state" | jq -e '.seeded_at != null and .model_count > 0' >/dev/null || die "Run make seed before make verify."
    page=$(api_get '/api/models?limit=1') || die "Cannot read models."
    expected_count=$(printf '%s' "$state" | jq -er '.model_count')
    printf '%s' "$page" | jq -e --argjson count "$expected_count" '.total == $count and (.items | length) == 1' >/dev/null || die "List and snapshot counts differ."
    id=$(printf '%s' "$page" | jq -er '.items[0].id')
    detail=$(api_get "/api/models/$id") || die "Cannot read model details."
    printf '%s' "$detail" | jq -e 'has("raw") and has("azure_source")' >/dev/null || die "Source properties are missing."
    catalogue=$(api_get /api/catalogue/status) || die "Cannot read the model catalogue."
    model_count=$(printf '%s' "$catalogue" | jq -er '.model_count')
    model_page=$(api_get '/api/catalogue/models?limit=1') || die "Cannot read master models."
    printf '%s' "$model_page" | jq -e --argjson count "$model_count" '.total==$count and .total>0' >/dev/null ||
        die "The model catalogue is empty or its counts disagree."
    model_id=$(printf '%s' "$model_page" | jq -er '.items[0].id')
    model_detail=$(api_get "/api/catalogue/models/$model_id") || die "Cannot read a master model."
    printf '%s' "$model_detail" | jq -e 'has("providers") and has("azure_support")' >/dev/null ||
        die "The master model is missing provider metadata or Azure support evidence."

    expected=$(mktemp "$LOCAL/api-expected.XXXXXX")
    actual=$(mktemp "$LOCAL/api-actual.XXXXXX")
    downloaded=$(mktemp "$LOCAL/ui-asset.XXXXXX")
    trap 'rm -f "$expected" "$expected.raw" "$actual" "$actual.raw" "$downloaded"' 0
    sh scripts/source-hashes.sh backend/app shasum > "$expected.raw" || die "Cannot hash current API source."
    LC_ALL=C sort "$expected.raw" > "$expected" || die "Cannot sort current API hashes."
    k exec -i deployment/api -- sh -s -- /app/app sha256sum < scripts/source-hashes.sh > "$actual.raw" || die "Cannot hash deployed API source."
    LC_ALL=C sort "$actual.raw" > "$actual" || die "Cannot sort deployed API hashes."
    cmp -s "$expected" "$actual" || die "The running API source differs from this checkout. Run make up."

    (cd frontend && npm run build)
    [ -f "$ROOT/frontend/dist/index.html" ] || die "The frontend build has no index.html."
    files=$(find "$ROOT/frontend/dist" -type f) || die "Cannot enumerate the frontend build."
    [ -n "$files" ] || die "The frontend build manifest is empty."
    while IFS= read -r file; do
        relative=${file#"$ROOT/frontend/dist/"}
        encoded=$(jq -rn --arg path "$relative" '$path | split("/") | map(@uri) | join("/")')
        api_get "/$encoded" > "$downloaded" || die "Cannot fetch built UI asset $relative."
        cmp -s "$file" "$downloaded" || die "Deployed UI asset $relative differs from the current build. Run make up."
    done <<EOF
$files
EOF
    printf 'Verified current API source, exact compiled UI assets, %s models and %s retained offerings.\n' "$model_count" "$expected_count"
}

down() {
    need kind
    docker_ready
    current_id=$(node_id) || die "Cannot inspect Docker cluster state."
    if [ -z "$current_id" ]; then
        if [ -f "$OWNER" ]; then rm -f "$OWNER" "$KUBECONFIG"; fi
        printf 'The local cluster is already absent.\n'
        return
    fi
    check_owner
    printf 'Deleting the verified local kind cluster and its PostgreSQL volume.\n'
    kind delete cluster --name "$CLUSTER" --kubeconfig "$KUBECONFIG"
    rm -f "$OWNER" "$KUBECONFIG"
}

case "${1:-}" in
    up) up;;
    seed) seed;;
    verify) verify;;
    down) down;;
    logs) require_cluster; k logs -l app.kubernetes.io/part-of=model-catalogue --all-containers --tail=80;;
    *) die "Use make up, seed, verify, down, or logs.";;
esac
