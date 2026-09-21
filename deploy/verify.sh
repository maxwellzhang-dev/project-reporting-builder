#!/usr/bin/env bash
#
# The deployment checks in docs/test_plan.md §11 that can be made from outside
# the cluster. Run after deploy.sh; it prints one line per check and exits
# non-zero if any fail. It makes exactly one real AI call.
#
set -uo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-reporting-builder-poc}"
APP="${APP:-ca-reporting-builder}"

fails=0
check() { # check <name> <condition-result> <detail>
  if [[ "$2" == "0" ]]; then printf '  PASS  %s\n' "$1"
  else printf '  FAIL  %s -- %s\n' "$1" "${3:-}"; fails=$((fails + 1)); fi
}

URL="https://$(az containerapp show -n "$APP" -g "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"
echo "Target: $URL"
echo

# -- Ingress, HTTPS and the health probe ------------------------------------
body="$(curl -fsS --max-time 60 "$URL/healthz" 2>/dev/null)"
check "HTTPS ingress serves /healthz" "$?" "no response"
[[ "$body" == '{"status":"ok"}' ]]
check "health body is {\"status\":\"ok\"}" "$?" "got: $body"

code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "$URL/")"
[[ "$code" == "200" ]]
check "application page loads" "$?" "HTTP $code"

# -- Configuration ----------------------------------------------------------
port="$(az containerapp show -n "$APP" -g "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.targetPort -o tsv)"
[[ "$port" == "8000" ]]
check "ingress targets port 8000" "$?" "targets $port"

max="$(az containerapp show -n "$APP" -g "$RESOURCE_GROUP" \
  --query properties.template.scale.maxReplicas -o tsv)"
[[ "$max" == "1" ]]
check "at most one replica" "$?" "maxReplicas=$max"

# The key must be a secret reference, never a literal value.
keyref="$(az containerapp show -n "$APP" -g "$RESOURCE_GROUP" \
  --query "properties.template.containers[0].env[?name=='AZURE_OPENAI_API_KEY'].secretRef | [0]" -o tsv)"
[[ -n "$keyref" && "$keyref" != "None" ]]
check "API key supplied as a secret reference" "$?" "secretRef=$keyref"

literal="$(az containerapp show -n "$APP" -g "$RESOURCE_GROUP" \
  --query "properties.template.containers[0].env[?name=='AZURE_OPENAI_API_KEY'].value | [0]" -o tsv)"
[[ -z "$literal" || "$literal" == "None" ]]
check "API key is not a literal env value" "$?" "a literal value is set"

# -- The key must not be reachable from the browser -------------------------
page="$(curl -fsS --max-time 60 "$URL/" 2>/dev/null)"
! grep -qiE 'azure_openai_api_key|openai\.azure\.com' <<<"$page"
check "no credential or endpoint in the served page" "$?" "found a reference"

# -- One real AI request in the deployed environment ------------------------
ai="$(curl -fsS --max-time 120 -X POST "$URL/api/ai/extract-progress" \
  -H 'Content-Type: application/json' \
  -d '{"source_text":"Login refactor finished on 9 September. Vendor has not confirmed a date for the credential rotation."}' 2>/dev/null)"
grep -q '"draft"' <<<"$ai"
check "one real AI request succeeds" "$?" "response: ${ai:0:200}"

# The model must not assign a status: the user chooses it (scope §5).
! grep -q '"status"' <<<"$ai"
check "draft carries no model-assigned status" "$?" "a status came back"

# -- Errors must stay controlled --------------------------------------------
err="$(curl -s --max-time 60 -X POST "$URL/api/ai/extract-progress" \
  -H 'Content-Type: application/json' -d '{"source_text":""}')"
grep -q '"error"' <<<"$err" && ! grep -qi 'traceback\|azure_openai_api_key' <<<"$err"
check "invalid input returns the error envelope, no internals" "$?" "$err"

echo
if [[ "$fails" == "0" ]]; then echo "All checks passed."; else echo "$fails check(s) failed."; fi
exit "$fails"
