# Deployment

Azure Container Apps, deployed by `deploy.sh` from a machine signed in with
`az login`. There is no deployment pipeline: this is a POC, and a script that
can be read in one sitting says more about the design than a workflow that
hides it.

```bash
az login              # once, in your own terminal
deploy/deploy.sh      # from the repository root
deploy/verify.sh      # the §11 checks against the deployed URL
```

`verify.sh` prints one line per check in `docs/test_plan.md` §11 that can be
made from outside the cluster, and exits non-zero if any fail. It makes exactly
one real AI call, and it checks the negative cases too: that the key is a
secret reference rather than a literal value, and that neither the key nor the
Azure endpoint appears in the page served to the browser.

## What it creates

| Resource | Name | Why |
| --- | --- | --- |
| Resource group | `rg-reporting-builder-poc` | Holds only this app, so `teardown.sh` can delete everything at once |
| Container registry | `crreportbuilder<hash>`, Basic | Holds the image. The name is derived from the subscription id, so it is stable across runs and globally unique |
| Container Apps environment | `cae-reporting-builder` | |
| Container app | `ca-reporting-builder` | 0.5 vCPU, 1 GiB, ingress on 8000 |

The Azure OpenAI resource is deliberately **not** in this group. Tearing down
the app must never take the model deployment with it.

**Region.** Everything is deployed to `koreacentral`, where the Azure OpenAI
resource already lives, so the model call stays in-region. This is not only a
latency preference: an Azure for Students subscription is restricted to a
subset of regions by policy, and a resource in Southeast Asia is refused with
`RequestDisallowedByAzure`. Set `LOCATION` to override, but check the target
region is permitted first.

The image is built locally and pushed, tagged with the commit hash so a running
app can be traced to its source. `az acr build` would be the nicer option, as
it builds server side and needs no local Docker, but ACR Tasks is not permitted
on an Azure for Students subscription: it refuses with
`TasksOperationsNotAllowed`.

The build is pinned to `--platform linux/amd64`. Container Apps runs x86, and
a build on Apple Silicon would otherwise produce an arm64 image that pushes and
deploys without complaint and then fails to start.

## Choices worth defending

**Scale to zero by default.** `min-replicas` is 0, so an idle POC costs
nothing. Measured on this deployment: it scales to zero after roughly seven
minutes idle, and the first request after that takes 2.33 s against 0.23 s
warm. Two seconds is short enough that a demo does not need to prepare for it.

`deploy/deploy.sh --wake` keeps one replica warm anyway if you would rather not
spend them, and this sets it back:

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

## What a first deployment trips over

Both of these came up deploying this subscription for the first time, and both
are now handled by the script rather than left as folklore:

- **Resource providers.** A new subscription has `Microsoft.ContainerRegistry`,
  `Microsoft.App` and `Microsoft.OperationalInsights` unregistered. The failure
  surfaces as `MissingSubscriptionRegistration` from whichever step needs one,
  not from a step named after the provider.
- **Region policy.** `RequestDisallowedByAzure` means the region is not on the
  subscription's permitted list, not that the name or quota is wrong.

The script checks whether each resource exists and then creates it, rather than
running create and ignoring the error. The earlier version swallowed the
registry failure and the run died two steps later complaining that the registry
did not exist, which pointed at the wrong thing entirely.

## Cost

Container Apps bills for what runs. Scaled to zero, the standing cost is the
Basic registry, roughly USD 5 a month. A replica left running at 0.5 vCPU
would add roughly USD 30 a month, which is why it is not the default.

`deploy/teardown.sh` deletes the resource group after asking for the name back.
