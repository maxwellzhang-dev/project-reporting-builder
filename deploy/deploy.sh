#!/usr/bin/env bash
#
# Deploy to Azure Container Apps. Safe to run repeatedly: every step either
# creates the resource or updates it in place.
#
# Reads the Azure OpenAI settings from ../.env and never prints the key. The
# key is stored as a Container Apps secret and referenced by the environment
# variable, so it is in neither the image nor any frontend asset
# (docs/test_plan.md §11).
#
# Usage:
#   az login                 # once, in your own terminal
#   deploy/deploy.sh         # from the repository root
#   deploy/deploy.sh --wake  # same, but keep one replica warm
#
set -euo pipefail

LOCATION="${LOCATION:-southeastasia}"
RESOURCE_GROUP="${RESOURCE_GROUP:-rg-reporting-builder-poc}"
ENVIRONMENT="${ENVIRONMENT:-cae-reporting-builder}"
APP="${APP:-ca-reporting-builder}"
IMAGE_NAME="project-reporting-builder"

# Scale to zero by default: an idle POC should not burn student credit. One
# replica is the ceiling either way, because the rate limiter counts in
# process (docs/test_plan.md §11). Pass --wake before a demo to avoid a cold
# start, and remember to undo it afterwards.
MIN_REPLICAS=0
if [[ "${1:-}" == "--wake" ]]; then MIN_REPLICAS=1; fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$here"

if ! command -v az >/dev/null; then
  echo "The Azure CLI is not installed. brew install azure-cli" >&2
  exit 1
fi

if ! az account show >/dev/null 2>&1; then
  echo "Not signed in. Run: az login" >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "No .env file. Copy .env.example and fill it in." >&2
  exit 1
fi

# Read settings without echoing them, and without exporting the whole file.
get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d '"'"'"'\r'; }
ENDPOINT="$(get AZURE_OPENAI_ENDPOINT)"
DEPLOYMENT="$(get AZURE_OPENAI_DEPLOYMENT)"
API_VERSION="$(get AZURE_OPENAI_API_VERSION)"
MAX_TOKENS="$(get AI_MAX_OUTPUT_TOKENS)"
EFFORT="$(get AI_REASONING_EFFORT)"
KEY="$(get AZURE_OPENAI_API_KEY)"

for name in ENDPOINT DEPLOYMENT KEY; do
  if [[ -z "${!name}" ]]; then
    echo "AZURE_OPENAI_$name is empty in .env" >&2
    exit 1
  fi
done

SUBSCRIPTION="$(az account show --query id -o tsv)"
# A registry name must be globally unique and alphanumeric. Deriving it from
# the subscription keeps it stable across runs without storing state.
SUFFIX="$(printf '%s' "$SUBSCRIPTION" | shasum | cut -c1-10)"
REGISTRY="${REGISTRY:-crreportbuilder${SUFFIX}}"

echo "Subscription : $(az account show --query name -o tsv)"
echo "Region       : $LOCATION"
echo "Registry     : $REGISTRY"
echo "App          : $APP (min replicas: $MIN_REPLICAS, max: 1)"
echo

echo "==> Registering resource providers (no-op once done)"
az provider register --namespace Microsoft.App --wait
az provider register --namespace Microsoft.OperationalInsights --wait

echo "==> Resource group"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none

echo "==> Container registry"
az acr create --resource-group "$RESOURCE_GROUP" --name "$REGISTRY" \
  --sku Basic --admin-enabled true -o none 2>/dev/null || true

# Tag by commit so a running app can be traced back to its source.
TAG="$(git rev-parse --short HEAD)"
IMAGE="${REGISTRY}.azurecr.io/${IMAGE_NAME}:${TAG}"

echo "==> Building $IMAGE in Azure (the Dockerfile is built server side)"
az acr build --registry "$REGISTRY" --image "${IMAGE_NAME}:${TAG}" \
  --image "${IMAGE_NAME}:latest" . -o none

echo "==> Container Apps environment"
az containerapp env create --name "$ENVIRONMENT" --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" -o none 2>/dev/null || true

REGISTRY_PASSWORD="$(az acr credential show --name "$REGISTRY" --query 'passwords[0].value' -o tsv)"

echo "==> Deploying"
# --secrets and --env-vars are idempotent: the second run updates in place.
az containerapp create \
  --name "$APP" \
  --resource-group "$RESOURCE_GROUP" \
  --environment "$ENVIRONMENT" \
  --image "$IMAGE" \
  --registry-server "${REGISTRY}.azurecr.io" \
  --registry-username "$REGISTRY" \
  --registry-password "$REGISTRY_PASSWORD" \
  --target-port 8000 \
  --ingress external \
  --min-replicas "$MIN_REPLICAS" \
  --max-replicas 1 \
  --cpu 0.5 --memory 1.0Gi \
  --secrets "azure-openai-key=$KEY" \
  --env-vars \
    AI_ENABLED=true \
    "AZURE_OPENAI_ENDPOINT=$ENDPOINT" \
    "AZURE_OPENAI_DEPLOYMENT=$DEPLOYMENT" \
    "AZURE_OPENAI_API_VERSION=$API_VERSION" \
    "AI_MAX_OUTPUT_TOKENS=$MAX_TOKENS" \
    "AI_REASONING_EFFORT=$EFFORT" \
    "AZURE_OPENAI_API_KEY=secretref:azure-openai-key" \
  -o none 2>/dev/null \
|| az containerapp update \
  --name "$APP" \
  --resource-group "$RESOURCE_GROUP" \
  --image "$IMAGE" \
  --min-replicas "$MIN_REPLICAS" \
  --max-replicas 1 \
  --set-env-vars \
    AI_ENABLED=true \
    "AZURE_OPENAI_ENDPOINT=$ENDPOINT" \
    "AZURE_OPENAI_DEPLOYMENT=$DEPLOYMENT" \
    "AZURE_OPENAI_API_VERSION=$API_VERSION" \
    "AI_MAX_OUTPUT_TOKENS=$MAX_TOKENS" \
    "AI_REASONING_EFFORT=$EFFORT" \
    "AZURE_OPENAI_API_KEY=secretref:azure-openai-key" \
  -o none

URL="https://$(az containerapp show --name "$APP" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"

echo
echo "Deployed: $URL"
echo "Health  : $URL/healthz"
echo "Image   : $IMAGE"
