#!/usr/bin/env bash
#
# Delete everything deploy.sh created, so an idle POC stops costing anything.
# It removes the whole resource group, which is why the Azure OpenAI resource
# must live in a different one: this script is not allowed to take the model
# deployment with it.
#
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-rg-reporting-builder-poc}"

if ! az account show >/dev/null 2>&1; then
  echo "Not signed in. Run: az login" >&2
  exit 1
fi

echo "This deletes the resource group '$RESOURCE_GROUP' and everything in it:"
az resource list --resource-group "$RESOURCE_GROUP" \
  --query "[].{name:name, type:type}" -o table 2>/dev/null || {
    echo "  (the group does not exist)"; exit 0;
  }

read -r -p "Type the group name to confirm: " reply
if [[ "$reply" != "$RESOURCE_GROUP" ]]; then
  echo "Not confirmed; nothing deleted."
  exit 1
fi

az group delete --name "$RESOURCE_GROUP" --yes --no-wait
echo "Deletion started. It runs in the background."
