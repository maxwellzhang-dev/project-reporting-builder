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

# Korea Central, because that is where the Azure OpenAI resource lives: it
# keeps the model call in-region. Note that an Azure for Students subscription
# only permits a subset of regions, and Southeast Asia is not one of them --
# a resource there fails with RequestDisallowedByAzure.
LOCATION="${LOCATION:-koreacentral}"
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
# A missing key returns empty rather than failing: an older .env predates the
# tuning settings, and an empty value passed to the container would be worse
# than a default (AI_MAX_OUTPUT_TOKENS="" fails integer validation at startup).
get() {
  local value=""
  value="$(grep -E "^$1=" .env | head -1 | cut -d= -f2- | tr -d '"'"'"'\r')" || true
  printf '%s' "$value"
}
ENDPOINT="$(get AZURE_OPENAI_ENDPOINT)"
DEPLOYMENT="$(get AZURE_OPENAI_DEPLOYMENT)"
API_VERSION="$(get AZURE_OPENAI_API_VERSION)"
MAX_TOKENS="$(get AI_MAX_OUTPUT_TOKENS)"
EFFORT="$(get AI_REASONING_EFFORT)"
KEY="$(get AZURE_OPENAI_API_KEY)"

# Fall back to the same defaults app/config.py uses, so a short .env deploys
# an application configured exactly like the one that was tested.
API_VERSION="${API_VERSION:-2025-04-01-preview}"
MAX_TOKENS="${MAX_TOKENS:-2000}"
EFFORT="${EFFORT:-low}"

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
# A fresh subscription has none of these registered, and the failure arrives
# later as MissingSubscriptionRegistration from whichever step needs one.
for ns in Microsoft.ContainerRegistry Microsoft.App Microsoft.OperationalInsights; do
  az provider register --namespace "$ns" --wait
done

echo "==> Resource group"
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" -o none

echo "==> Container registry"
# Check first, then create. Swallowing the error instead would hide a real
# failure until a later step tripped over the missing resource.
if ! az acr show --name "$REGISTRY" --resource-group "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az acr create --resource-group "$RESOURCE_GROUP" --name "$REGISTRY" \
    --sku Basic --admin-enabled true -o none
fi

# Tag by commit so a running app can be traced back to its source.
TAG="$(git rev-parse --short HEAD)"
IMAGE="${REGISTRY}.azurecr.io/${IMAGE_NAME}:${TAG}"

# Built locally and pushed, rather than server side with `az acr build`: ACR
# Tasks is not permitted on an Azure for Students subscription, which refuses
# the build with TasksOperationsNotAllowed.
#
# --platform linux/amd64 is not optional. Container Apps runs x86, and an
# image built on Apple Silicon defaults to arm64, which would push and deploy
# without complaint and then fail to start.
echo "==> Building $IMAGE locally for linux/amd64 and pushing"
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker Desktop and run this again." >&2
  exit 1
fi
az acr login --name "$REGISTRY" -o none
docker buildx build --platform linux/amd64 \
  --tag "$IMAGE" \
  --tag "${REGISTRY}.azurecr.io/${IMAGE_NAME}:latest" \
  --push .

echo "==> Container Apps environment"
if ! az containerapp env show --name "$ENVIRONMENT" --resource-group "$RESOURCE_GROUP" \
     -o none 2>/dev/null; then
  az containerapp env create --name "$ENVIRONMENT" --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" -o none
fi

REGISTRY_PASSWORD="$(az acr credential show --name "$REGISTRY" --query 'passwords[0].value' -o tsv)"

echo "==> Deploying"
# Create on the first run, update on every later one. Deciding by existence
# rather than by letting create fail keeps a genuine create error visible.
if az containerapp show --name "$APP" --resource-group "$RESOURCE_GROUP" -o none 2>/dev/null; then
  az containerapp secret set --name "$APP" --resource-group "$RESOURCE_GROUP" \
    --secrets "azure-openai-key=$KEY" -o none
  az containerapp update \
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
else
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
  -o none
fi

URL="https://$(az containerapp show --name "$APP" --resource-group "$RESOURCE_GROUP" \
  --query properties.configuration.ingress.fqdn -o tsv)"

echo
echo "Deployed: $URL"
echo "Health  : $URL/healthz"
echo "Image   : $IMAGE"
