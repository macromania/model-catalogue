#!/bin/sh
set -eu
. "$(dirname "$0")/azure-common.sh"

compile() {
    prepare_context
    for template in main seed-job apps; do
        azc bicep build --file "infra/$template.bicep" --outfile "$STATE/$template.template.json"
    done
}

validate() {
    compile
    section "Validate Azure foundation"
    azc deployment sub validate --name "$DEPLOYMENT_PREFIX-validate" --location "$LOCATION" --template-file infra/main.bicep \
        --parameters "@$STATE/foundation.parameters.json" \
        --query '{state:properties.provisioningState,error:error}' -o json
    azc deployment sub what-if --name "$DEPLOYMENT_PREFIX-preview" --location "$LOCATION" \
        --template-file infra/main.bicep --parameters "@$STATE/foundation.parameters.json" \
        --result-format ResourceIdOnly --no-pretty-print \
        --query '{status:status,changes:changes[].{resourceId:resourceId,changeType:changeType}}' -o json
}

job_parameters() {
    jq -n --slurpfile f "$FOUNDATION" --slurpfile c "$CONTEXT" --slurpfile i "$IMAGES" '{
        parameters: (
            ($f[0] | with_entries(select(.key as $k |
                ["environmentId","registryServer","seedIdentityId","seedIdentityClientId","postgresHost","postgresAdmin","adminSecretUrl","readerSecretUrl"] | index($k))) |
                map_values({value:.}))
            + {location:{value:$c[0].location},apiImage:{value:$i[0].api},
               modelSubscriptionId:{value:$c[0].subscription},modelRegions:{value:$c[0].modelRegions}}
        )
    }' > "$STATE/job.parameters.json"
}

app_parameters() {
    jq -n --slurpfile f "$FOUNDATION" --slurpfile c "$CONTEXT" --slurpfile i "$IMAGES" '{
        parameters: (
            ($f[0] | with_entries(select(.key as $k |
                ["environmentId","registryServer","uiIdentityId","apiIdentityId","postgresHost","readerSecretUrl"] | index($k))) |
                map_values({value:.}))
            + {location:{value:$c[0].location},apiImage:{value:$i[0].api},
               uiImage:{value:$i[0].ui}}
        )
    }' > "$STATE/apps.parameters.json"
}

build_images() {
    need docker git cmp
    registry=$(foundation_value registryName)
    server=$(foundation_value registryServer)
    tag=$(git rev-parse --short=12 HEAD)
    [ -z "$(git status --porcelain)" ] || fail "Commit source changes before publishing deployment images."
    api_tag="$server/catalogue-api:$tag"
    ui_tag="$server/catalogue-ui:$tag"
    section "Build Linux amd64 images"
    docker build --platform linux/amd64 -t "$api_tag" backend
    docker build --platform linux/amd64 --build-arg UI_PORT=18420 --build-arg VITE_PORT=18423 -t "$ui_tag" frontend
    sh scripts/source-hashes.sh backend/app shasum > "$STATE/source.unsorted"
    sort "$STATE/source.unsorted" > "$STATE/source.expected"
    docker run --rm --platform linux/amd64 -i --entrypoint sh "$api_tag" -s -- /app/app sha256sum \
        < scripts/source-hashes.sh > "$STATE/source.image.unsorted"
    sort "$STATE/source.image.unsorted" > "$STATE/source.image"
    cmp "$STATE/source.expected" "$STATE/source.image" || fail "Backend image content does not match the checkout."
    (cd frontend && npm run build)
    files=$(find frontend/dist -type f) || fail "Cannot enumerate the frontend build."
    [ -n "$files" ] || fail "The frontend build is empty."
    while IFS= read -r file; do
        relative=${file#frontend/dist/}
        expected=$(shasum -a 256 "$file")
        actual=$(docker run --rm --platform linux/amd64 --entrypoint sha256sum "$ui_tag" "/usr/share/nginx/html/$relative")
        [ "${expected%% *}" = "${actual%% *}" ] || fail "Frontend image asset $relative differs from the current build."
    done <<EOF
$files
EOF
    section "Push verified images"
    azc acr login --name "$registry"
    docker push "$api_tag"
    docker push "$ui_tag"
    api_digest=$(azc acr repository show --name "$registry" --image "catalogue-api:$tag" --query digest -o tsv)
    ui_digest=$(azc acr repository show --name "$registry" --image "catalogue-ui:$tag" --query digest -o tsv)
    for digest in "$api_digest" "$ui_digest"; do
        printf '%s' "$digest" | grep -E '^sha256:[a-f0-9]{64}$' >/dev/null ||
            fail "Registry returned an invalid image digest."
    done
    docker image inspect "$api_tag" --format '{{json .RepoDigests}}' |
        jq -e --arg reference "$server/catalogue-api@$api_digest" 'index($reference)!=null' >/dev/null ||
        fail "The published API digest does not match the inspected local image."
    docker image inspect "$ui_tag" --format '{{json .RepoDigests}}' |
        jq -e --arg reference "$server/catalogue-ui@$ui_digest" 'index($reference)!=null' >/dev/null ||
        fail "The published UI digest does not match the inspected local image."
    jq -n --arg api "$server/catalogue-api@$api_digest" --arg ui "$server/catalogue-ui@$ui_digest" \
        --arg commit "$(git rev-parse HEAD)" '{api:$api,ui:$ui,commit:$commit}' > "$IMAGES"
}

check_environment_capacity() {
    environment=$(foundation_value environmentName)
    azc containerapp env list-usages -g "$RG" -n "$environment" -o json > "$STATE/environment-usage.json"
    jq -e '
        (if type=="array" then . else .value end) |
        any( .name.value == "ManagedEnvironmentConsumptionCores"
            and ((.limit - .currentValue) >= 2) )
    ' "$STATE/environment-usage.json" >/dev/null ||
        fail "The environment did not report at least two available Consumption cores; inspect environment-usage.json."
}

seed_cloud() {
    require_state
    [ -f "$IMAGES" ] || fail "Image references are missing."
    section "Run the exact cloud seed execution"
    started=$(azc containerapp job start -g "$RG" -n mc-seed -o json)
    execution=$(printf '%s' "$started" | jq -er '.name')
    case "$execution" in mc-seed-*) ;; *) fail "Unexpected seed execution name.";; esac
    printf '%s' "$execution" > "$STATE/latest-execution"
    attempt=0
    while [ "$attempt" -lt 180 ]; do
        azc containerapp job execution show -g "$RG" -n mc-seed --job-execution-name "$execution" \
            -o json > "$STATE/execution.json"
        status=$(jq -er '.properties.status' "$STATE/execution.json")
        case "$status" in
            Succeeded)
                jq -e --slurpfile images "$IMAGES" \
                    '.properties.template.containers[0].image == $images[0].api' "$STATE/execution.json" >/dev/null ||
                    fail "Seed execution image differs from the intended digest."
                printf 'Seed execution %s succeeded.\n' "$execution"
                return;;
            Failed|Stopped) fail "Seed execution $execution ended with $status; inspect the job logs.";;
            Running|Pending|Processing|Unknown) ;;
            *) fail "Unexpected seed execution status: $status";;
        esac
        attempt=$((attempt + 1))
        sleep 5
    done
    fail "Seed execution $execution did not finish within the verification window."
}

deploy() {
    need git docker npm
    [ -z "$(git status --porcelain)" ] || fail "Commit source changes before provisioning or publishing deployment images."
    validate
    section "Deploy Azure foundation"
    azc deployment sub create --name "$DEPLOYMENT_PREFIX-foundation" --location "$LOCATION" \
        --template-file infra/main.bicep --parameters "@$STATE/foundation.parameters.json" \
        --query 'properties.outputs.foundation.value' -o json > "$FOUNDATION.pending"
    jq -e 'has("environmentId") and has("postgresHost") and has("registryServer")' "$FOUNDATION.pending" >/dev/null ||
        fail "Foundation deployment did not produce expected outputs."
    mv "$FOUNDATION.pending" "$FOUNDATION"
    check_environment_capacity
    build_images
    release
}

release() {
    prepare_context
    require_state
    job_parameters
    section "Deploy private seed job"
    azc deployment group create -g "$RG" --name model-catalogue-seed-job --template-file infra/seed-job.bicep \
        --parameters "@$STATE/job.parameters.json" --query properties.provisioningState -o tsv
    seed_cloud
    deploy_apps
}

deploy_apps() {
    app_parameters
    section "Deploy internal API and public dashboard"
    azc deployment group create -g "$RG" --name model-catalogue-apps --template-file infra/apps.bicep \
        --parameters "@$STATE/apps.parameters.json" --query properties.outputs -o json > "$APPS.pending"
    jq -e '.frontendUrl.value | startswith("https://")' "$APPS.pending" >/dev/null || fail "App deployment URL is missing."
    mv "$APPS.pending" "$APPS"
    jq -er '.frontendUrl.value' "$APPS"
}

configure_apps() {
    require_state
    prepare_context
    [ -f "$IMAGES" ] || fail "Image references are missing; deploy the application first."
    app_parameters
    section "Validate application configuration"
    azc deployment group validate -g "$RG" --name model-catalogue-apps-validate \
        --template-file infra/apps.bicep --parameters "@$STATE/apps.parameters.json" \
        --query properties.provisioningState -o tsv
    deploy_apps
}

update_apps() {
    prepare_context
    require_state
    check_environment_capacity
    build_images
    release
}

verify_cloud() {
    require_state
    [ -f "$APPS" ] && [ -f "$IMAGES" ] || fail "Cloud app state is missing."
    execution=$(cat "$STATE/latest-execution")
    azc containerapp job execution show -g "$RG" -n mc-seed --job-execution-name "$execution" -o json > "$STATE/execution.json"
    jq -e --slurpfile images "$IMAGES" \
        '.properties.status=="Succeeded" and .properties.template.containers[0].image==$images[0].api' \
        "$STATE/execution.json" >/dev/null || fail "The requested seed execution has not succeeded with the intended image."
    url=$(jq -er '.frontendUrl.value' "$APPS")
    section "Verify public cloud endpoint"
    curl --disable --fail --silent --show-error --max-time 60 --retry 10 --retry-delay 5 "$url/api/health/ready"
    curl --disable --fail --silent --show-error --max-time 60 "$url/api/catalogue/status" > "$STATE/status.json"
    jq -e '.model_count>0 and .sources.azure.status=="live" and .sources.azure.count>0' "$STATE/status.json" >/dev/null ||
        fail "The cloud catalogue does not contain live Azure metadata."
    for name in mc-api mc-ui; do
        azc containerapp show -g "$RG" -n "$name" -o json > "$STATE/$name.json"
        revision=$(jq -er '.properties.latestRevisionName' "$STATE/$name.json")
        jq -e --arg revision "$revision" \
            '.properties.latestReadyRevisionName==$revision and .properties.configuration.activeRevisionsMode=="Single"
             and .properties.template.scale.minReplicas==1 and .properties.template.scale.maxReplicas==1' \
            "$STATE/$name.json" >/dev/null || fail "The intended $name revision is not ready."
        jq -e --arg revision "$revision" '
            .properties.configuration.ingress.traffic as $traffic |
            ($traffic|length)>0 and ([$traffic[].weight]|add)==100
            and ([$traffic[]|select(.latestRevision==true or .revisionName==$revision)|.weight]|add)==100
        ' "$STATE/$name.json" >/dev/null || fail "$name traffic is not entirely assigned to the intended revision."
        azc containerapp revision show -g "$RG" -n "$name" --revision "$revision" -o json > "$STATE/$name-revision.json"
        key=ui
        [ "$name" != mc-api ] || key=api
        expected=$(jq -er --arg key "$key" '.[$key]' "$IMAGES")
        jq -e --arg image "$expected" \
            '.properties.active==true and .properties.healthState=="Healthy" and .properties.template.containers[0].image==$image' \
            "$STATE/$name-revision.json" >/dev/null || fail "$name is not serving the expected healthy image."
        azc containerapp replica list -g "$RG" -n "$name" --revision "$revision" -o json > "$STATE/$name-replicas.json"
        jq -e 'length==1' "$STATE/$name-replicas.json" >/dev/null ||
            fail "$name has not converged to one running replica."
    done
    jq -e '.properties.configuration.ingress.external==false' "$STATE/mc-api.json" >/dev/null ||
        fail "The API must not have external ingress."
    jq -e '
        .properties.configuration.ingress as $i | $i.external==true and $i.allowInsecure==false
        and ($i.ipSecurityRestrictions|length)==0
    ' "$STATE/mc-ui.json" >/dev/null || fail "The dashboard must have public HTTPS ingress without IP restrictions."
    azc containerapp auth show -g "$RG" -n mc-ui -o json > "$STATE/mc-ui-auth.json"
    jq -e 'type=="object" and (.platform==null or .platform.enabled==false)' \
        "$STATE/mc-ui-auth.json" >/dev/null || fail "The public dashboard must not require platform authentication."
    postgres=$(foundation_value postgresName)
    azc postgres flexible-server show -g "$RG" -n "$postgres" -o json > "$STATE/postgres.json"
    jq -e '.network.publicNetworkAccess=="Disabled"' "$STATE/postgres.json" >/dev/null ||
        fail "PostgreSQL public access is not disabled."
    vault=$(foundation_value vaultName)
    vault_access=$(azc keyvault show -g "$RG" -n "$vault" --query properties.publicNetworkAccess -o tsv)
    [ "$vault_access" = Disabled ] || fail "Key Vault public access is not disabled."
    (cd frontend && CATALOGUE_BASE_URL="$url" npm run test:e2e)
    printf '\nVerified cloud dashboard: %s\n' "$url"
}

repair_network() {
    require_state
    vault=$(foundation_value vaultName)
    section "Validate private Key Vault connectivity"
    azc deployment group validate -g "$RG" --name model-catalogue-vault-network \
        --template-file infra/vault-network.bicep --parameters vaultName="$vault" location="$LOCATION" \
        --query properties.provisioningState -o tsv
    azc deployment group create -g "$RG" --name model-catalogue-vault-network \
        --template-file infra/vault-network.bicep --parameters vaultName="$vault" location="$LOCATION" \
        --query properties.provisioningState -o tsv
    azc keyvault update -g "$RG" -n "$vault" --enabled-for-template-deployment true \
        --query properties.enabledForTemplateDeployment -o tsv
}

case "${1:-}" in
    prepare) compile;;
    validate) validate;;
    deploy) deploy;;
    update) update_apps;;
    configure) configure_apps;;
    seed) seed_cloud;;
    verify) verify_cloud;;
    repair-network) repair_network;;
    status)
        require_state
        azc containerapp list -g "$RG" --query '[].{name:name,state:properties.provisioningState,url:properties.configuration.ingress.fqdn}' -o table
        ;;
    *) fail "Use prepare, validate, deploy, update, configure, seed, status, verify or repair-network.";;
esac
