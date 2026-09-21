# Deployment

Azure Container Apps, deployed by `deploy.sh` from a machine signed in with
`az login`. There is no deployment pipeline: this is a POC, and a script that
can be read in one sitting says more about the design than a workflow that
hides it.

```bash
az login              # once, in your own terminal
deploy/deploy.sh      # from the repository root
```

## What it creates

| Resource | Name | Why |
| --- | --- | --- |
| Resource group | `rg-reporting-builder-poc` | Holds only this app, so `teardown.sh` can delete everything at once |
| Container registry | `crreportbuilder<hash>`, Basic | Holds the image. The name is derived from the subscription id, so it is stable across runs and globally unique |
| Container Apps environment | `cae-reporting-builder` | |
| Container app | `ca-reporting-builder` | 0.5 vCPU, 1 GiB, ingress on 8000 |

The Azure OpenAI resource is deliberately **not** in this group. Tearing down
the app must never take the model deployment with it.

The image is built by `az acr build`, which uploads the build context and
builds server side. Nothing is pushed from the local machine, so the deploy
works the same on any network and does not depend on the local Docker daemon.
It is tagged with the commit hash, so a running app can be traced to its source.

## Choices worth defending

**Scale to zero by default.** `min-replicas` is 0, so an idle POC costs
nothing but a cold start of a few seconds. Run `deploy/deploy.sh --wake`
before a demo to keep one replica warm, and set it back afterwards:

```bash
az containerapp update -n ca-reporting-builder -g rg-reporting-builder-poc --min-replicas 0
```

**At most one replica.** The AI rate limiter counts calls in process. With two
replicas the limit would silently double, so the ceiling is 1 and
`docs/test_plan.md` §11 records that as a requirement rather than a detail.

**The key is a Container Apps secret**, referenced as
`AZURE_OPENAI_API_KEY=secretref:azure-openai-key`. It is not baked into the
image, not in any frontend asset, and not in the repository. `deploy.sh` reads
it from the local `.env` and never echoes it.

**Registry admin credentials, not managed identity.** A managed identity with
an `AcrPull` role assignment is the production answer. This uses the registry's
admin user because it needs no role-assignment permission and fails in fewer
ways on a student subscription. It is a POC trade-off, recorded rather than
hidden.

One thing the script cannot avoid: `az` takes the key as a command-line
argument, so it is briefly visible in the process list of the machine running
the deploy. On a shared machine, set the secret from the portal instead.

## Cost

Container Apps bills for what runs. Scaled to zero, the standing cost is the
Basic registry, roughly USD 5 a month. A replica left running at 0.5 vCPU
would add roughly USD 30 a month, which is why it is not the default.

`deploy/teardown.sh` deletes the resource group after asking for the name back.
