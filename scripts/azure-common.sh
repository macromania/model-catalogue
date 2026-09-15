#!/bin/sh
set -eu
umask 077
ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
STATE="$ROOT/.local/azure"
CONTEXT="$STATE/context.json"
FOUNDATION="$STATE/foundation.json"
IMAGES="$STATE/images.json"
APPS="$STATE/apps.json"
cd "$ROOT"

fail() { printf 'Error: %s\n' "$*" >&2; exit 1; }
need() { for tool in "$@"; do command -v "$tool" >/dev/null 2>&1 || fail "Missing $tool."; done; }
section() { sh "$ROOT/scripts/output.sh" section "$1"; }
azc() { az "$@" --subscription "$SUBSCRIPTION"; }

need az jq curl openssl shasum
mkdir -p "$STATE"
current=$(az account show -o json) || fail "Sign in with az login."
CURRENT_SUBSCRIPTION=$(printf '%s' "$current" | jq -er '.id')
if [ -f "$CONTEXT" ]; then
    SUBSCRIPTION=$(jq -er '.subscription' "$CONTEXT")
    [ "$CURRENT_SUBSCRIPTION" = "$SUBSCRIPTION" ] || fail "The signed-in subscription differs from this deployment's recorded subscription."
    RG=$(jq -er '.resourceGroup' "$CONTEXT")
    LOCATION=$(jq -er '.location' "$CONTEXT")
else
    SUBSCRIPTION=$CURRENT_SUBSCRIPTION
    RG=${AZURE_RESOURCE_GROUP:-rg-model-catalogue-dev-swc}
    LOCATION=${AZURE_LOCATION:-swedencentral}
fi
case "$RG" in rg-model-catalogue-*) ;; *) fail "Use a dedicated rg-model-catalogue-* resource group.";; esac
deployment_hash=$(printf '%s' "$SUBSCRIPTION/$RG" | shasum -a 256)
DEPLOYMENT_PREFIX="model-catalogue-$(printf '%.12s' "${deployment_hash%% *}")"

check_group() {
    exists=$(azc group exists --name "$RG") || fail "Cannot inspect the target resource group."
    case "$exists" in
        true)
            group=$(azc group show --name "$RG" -o json)
            printf '%s' "$group" | jq -e '.tags.project=="model-catalogue" and .tags.managedBy=="model-catalogue"' >/dev/null ||
                fail "The existing group is not owned by this project."
            ;;
        false) ;;
        *) fail "Unexpected resource-group existence response.";;
    esac
}

require_state() {
    [ -f "$CONTEXT" ] && [ -f "$FOUNDATION" ] || fail "Run the Azure deployment first."
    check_group
    [ "$exists" = true ] || fail "The recorded resource group no longer exists."
}

foundation_value() { jq -er --arg key "$1" '.[$key] | strings | select(length>0)' "$FOUNDATION"; }

build_parameters() {
    if [ -n "${VAULT_REFERENCE_ID:-}" ]; then
        jq -n --slurpfile context "$CONTEXT" --arg vault "$VAULT_REFERENCE_ID" '{
            parameters: {
                resourceGroupName:{value:$context[0].resourceGroup},
                location:{value:$context[0].location},
                operatorPrincipalId:{value:$context[0].operatorPrincipalId},
                administratorPassword:{reference:{keyVault:{id:$vault},secretName:"postgres-admin"}},
                readerPassword:{reference:{keyVault:{id:$vault},secretName:"postgres-reader"}}
            }
        }' > "$STATE/foundation.parameters.json"
        return
    fi
    jq -n --slurpfile context "$CONTEXT" --slurpfile credentials "$STATE/credentials.json" '{
        parameters: {
            resourceGroupName: {value:$context[0].resourceGroup},
            location: {value:$context[0].location},
            operatorPrincipalId: {value:$context[0].operatorPrincipalId},
            administratorPassword: {value:$credentials[0].administratorPassword},
            readerPassword: {value:$credentials[0].readerPassword}
        }
    }' > "$STATE/foundation.parameters.json"
}

read_vault_secret() {
    secret_vault=$1
    secret_name=$2
    secret_target=$3
    if azc keyvault secret show --vault-name "$secret_vault" --name "$secret_name" -o json \
        > "$secret_target" 2> "$secret_target.error"; then
        rm -f "$secret_target.error"
        jq -e '.value | type=="string" and length>0' "$secret_target" >/dev/null ||
            fail "The existing secret has an invalid value."
        return 0
    fi
    if grep -q '(SecretNotFound)' "$secret_target.error"; then
        rm -f "$secret_target" "$secret_target.error"
        return 1
    fi
    cat "$secret_target.error" >&2
    rm -f "$secret_target" "$secret_target.error"
    return 2
}

prepare_context() {
    check_group
    if [ ! -f "$CONTEXT" ]; then
        principal=$(az ad signed-in-user show --query id -o tsv) || fail "Cannot identify the deployment operator."
        jq -n --arg sub "$SUBSCRIPTION" --arg rg "$RG" --arg region "$LOCATION" \
            --arg principal "$principal" \
            --arg regions "${AZURE_REGIONS:-all}" \
            '{project:"model-catalogue",subscription:$sub,resourceGroup:$rg,location:$region,
              operatorPrincipalId:$principal,modelRegions:$regions}' > "$CONTEXT"
    fi
    jq -e '
        .project=="model-catalogue"
        and (.modelRegions | test("^[a-z0-9]+(,[a-z0-9]+)*$"))
    ' "$CONTEXT" >/dev/null || fail "Invalid cloud context."
    if jq -e 'has("allowedCidr")' "$CONTEXT" >/dev/null; then
        jq 'del(.allowedCidr)' "$CONTEXT" > "$CONTEXT.pending"
        mv "$CONTEXT.pending" "$CONTEXT"
    fi
    vault=
    servers=0
    if [ "$exists" = true ]; then
        vault=$(azc keyvault list -g "$RG" --query "[?tags.project=='model-catalogue'].name | [0]" -o tsv)
        servers=$(azc postgres flexible-server list -g "$RG" --query 'length(@)' -o tsv)
    fi
    if [ -n "$vault" ]; then
        vault_info=$(azc keyvault show -g "$RG" -n "$vault" \
            --query '{id:id,private:properties.publicNetworkAccess,templateAccess:properties.enabledForTemplateDeployment}' -o json)
        if [ "$(printf '%s' "$vault_info" | jq -r '.private')" = Disabled ]; then
            [ "$(printf '%s' "$vault_info" | jq -r '.templateAccess')" = true ] ||
                fail "The private vault needs ARM template access. Run the scoped repair-network action."
            VAULT_REFERENCE_ID=$(printf '%s' "$vault_info" | jq -er '.id')
            complete_secrets=true
            for name in postgres-admin postgres-reader; do
                if azc resource show --ids "$VAULT_REFERENCE_ID/secrets/$name" --api-version 2023-07-01 \
                    --query id -o tsv > "$STATE/secret-metadata" 2> "$STATE/secret-metadata.error"; then
                    :
                elif grep -Eq '\((ResourceNotFound|SecretNotFound)\)' "$STATE/secret-metadata.error" &&
                    [ "$servers" = 0 ] && [ -f "$STATE/credentials.json" ]; then
                    complete_secrets=false
                else
                    cat "$STATE/secret-metadata.error" >&2
                    fail "Private-vault secret metadata is unavailable; no credentials were regenerated."
                fi
            done
            rm -f "$STATE/secret-metadata" "$STATE/secret-metadata.error"
            if [ "$complete_secrets" = false ]; then
                VAULT_REFERENCE_ID=
                jq -e '(.administratorPassword|type=="string" and length>=16) and
                    (.readerPassword|type=="string" and length>=16)' "$STATE/credentials.json" >/dev/null ||
                    fail "Pending bootstrap credentials are invalid."
                build_parameters
                printf 'Completing private-vault bootstrap with preserved credentials; no database exists yet.\n'
                return
            fi
            build_parameters
            printf 'Using existing private Key Vault references; local password values are not used.\n'
            return
        fi
    fi
    if [ ! -f "$STATE/credentials.json" ]; then
        printf '{}' > "$STATE/credentials.pending.json"
        for pair in postgres-admin:administratorPassword postgres-reader:readerPassword; do
            name=${pair%%:*}
            key=${pair#*:}
            restored=false
            if [ -n "$vault" ]; then
                if read_vault_secret "$vault" "$name" "$STATE/restore-secret.json"; then
                    jq --arg key "$key" --slurpfile secret "$STATE/restore-secret.json" \
                        '.[$key]=$secret[0].value' "$STATE/credentials.pending.json" > "$STATE/credentials.next.json"
                    restored=true
                    rm -f "$STATE/restore-secret.json"
                else
                    result=$?
                    [ "$result" -eq 1 ] || fail "Existing secrets are inaccessible; credentials were not regenerated."
                fi
            fi
            if [ "$restored" = false ]; then
                [ "$servers" = 0 ] || fail "A PostgreSQL server exists without a recoverable $name secret."
                generated_password="$(openssl rand -hex 32)Aa1!"
                VALUE="$generated_password" jq --arg key "$key" '.[$key]=env.VALUE' \
                    "$STATE/credentials.pending.json" > "$STATE/credentials.next.json"
                unset generated_password
            fi
            mv "$STATE/credentials.next.json" "$STATE/credentials.pending.json"
        done
        mv "$STATE/credentials.pending.json" "$STATE/credentials.json"
    fi
    jq -e '
        (.administratorPassword | type=="string" and length>=16)
        and (.readerPassword | type=="string" and length>=16)
    ' "$STATE/credentials.json" >/dev/null || fail "Invalid stored cloud credentials."
    if [ -n "$vault" ]; then
        for pair in postgres-admin:administratorPassword postgres-reader:readerPassword; do
            name=${pair%%:*}
            key=${pair#*:}
            if read_vault_secret "$vault" "$name" "$STATE/check-secret.json"; then
                jq -e --arg key "$key" --slurpfile secret "$STATE/check-secret.json" \
                    '.[$key]==$secret[0].value' "$STATE/credentials.json" >/dev/null ||
                    fail "Local cloud credentials differ from Key Vault; refusing implicit rotation."
                rm -f "$STATE/check-secret.json"
            else
                result=$?
                [ "$result" -eq 1 ] && [ "$servers" = 0 ] ||
                    fail "Cannot verify existing credentials; the database or secret access needs attention."
                printf 'Secret %s is not created yet; preserving the pending credential for bootstrap.\n' "$name"
            fi
        done
    fi
    build_parameters
}
