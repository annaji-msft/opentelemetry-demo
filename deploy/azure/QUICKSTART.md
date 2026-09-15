# Clean-clone deployment and SRE onboarding

This guide deploys the full demo, not a toy replacement. Read
[architecture/resources](ARCHITECTURE.md) and [cost/state limits](README.md#state-availability-and-cost)
before provisioning. The existing commissioned demo is already monitored;
these commands describe a **new operator-owned environment**, not permission
to recreate or overwrite that deployment.

## Prerequisites

Use PowerShell 7, Git, Python 3.12+, Azure CLI with Bicep and the Container Apps
extension. Node/npm are optional for documentation linting; Azure MCP is not
required because the tooling uses Azure CLI/REST. No local Docker is needed.
Install tools from their official distributions and authenticate interactively;
never paste credentials into generated files or this repository.

Choose an enabled subscription and supported region with sufficient ACA
consumption quota for 8.5 vCPU/17 GiB, plus rollout overlap. The relevant
Microsoft.App, Microsoft.OperationalInsights and Microsoft.Insights providers
must be registered. An authorized subscription operator should handle missing
provider registration or quota; this deployment does not change either.
App deployment needs resource-write permissions in the chosen resource group,
not a broad subscription Contributor grant. Query verification requires access
to the dedicated workspace.

Until a human-approved PR is merged, **main does not contain this adaptation**.
Select the current feature branch explicitly:

```powershell
$forkUrl = 'https://github.com/<owner>/opentelemetry-demo.git'
$branch = 'anganti-microsoft-astronomy-shop-on-azure'
git clone --branch $branch --single-branch $forkUrl astronomy-shop
Set-Location astronomy-shop
$demoRoot = (Get-Location).Path
function az { python (Join-Path $demoRoot 'deploy\azure\azure_cli.py') @args }
git rev-parse HEAD
python -m pip install -r deploy\azure\requirements.txt
python -m unittest discover -s deploy\azure -p 'test_*.py' -v
az bicep build --file deploy\azure\main.bicep
```

Replace `<owner>` with this public fork's owner, or your own fork owner. The
feature branch name is intentionally explicit; after merging, select a reviewed
commit/tag rather than assuming this branch lives forever.
The session-local `az` function forwards argument arrays through the installed
Azure CLI's bundled interpreter on Windows, bypassing `az.cmd` shell parsing.
It preserves ampersands, percent signs, quotes, parentheses and newlines without
echoing a credential-bearing command. It changes no Azure defaults or shell
profile. You can instead invoke `python deploy\azure\azure_cli.py ...` explicitly.

Optional documentation linting:

```powershell
npm ci --ignore-scripts --no-audit --no-fund
$markdown = Get-ChildItem deploy\azure -Filter *.md |
  Select-Object -ExpandProperty FullName
npx --no-install markdownlint @markdown
```

## Optional accelerator entrypoint and skill

[The repository-local skill](../../.github/skills/astronomy-shop-accelerator/SKILL.md)
walks the same phases as this guide. People without Copilot can use the thin
local-only entrypoint or the individual commands below.

Copy `accelerator.example.json` into private storage, fill its nonsecret inputs,
and choose `reuse-existing` or `provision-new-guided` for SRE. Do not add
credentials. The latter mode means official portal/admin onboarding followed
by resuming configuration, not unattended or live-verified agent creation.

```powershell
$operatorConfig = 'YOUR_PRIVATE_ABSOLUTE_CONFIG_PATH'
Copy-Item deploy\azure\accelerator.example.json $operatorConfig
# Edit the copied nonsecret settings before proceeding.
python deploy\azure\accelerator.py --config $operatorConfig --phase prepare
$settings = Get-Content -LiteralPath $operatorConfig -Raw | ConvertFrom-Json
$subscription = $settings.application.subscriptionId
$group = $settings.application.resourceGroup
$location = $settings.application.location
$prefix = $settings.application.prefix
$privateDir = $settings.privateDirectory
$params = Join-Path $privateDir 'baseline.parameters.json'
$forkUrl = $settings.source.repositoryUrl
$branch = $settings.source.branch
```

This delegates `prepare.py`; it does not deploy. Continue through the reviewed
`Deploy.ps1` preview/apply flow below. Keep these configured variables and skip
the alternative placeholder assignments and repeated preparation command below.
Once deployment supplies the real
workspace customer ID and the hosted agent has been onboarded:

```powershell
python deploy\azure\accelerator.py --config $operatorConfig --phase sre-config `
  --workspace-customer-id $workspaceCustomerId
```

This delegates `sre_setup.py` and `alert_setup.py`, creating private request
documents, disabled alerts and `operator-targets.json`. It makes no Azure writes
and does not apply native API requests or grant permissions. The individual CLI
commands remain the authoritative equivalent flow, with explicit approval gates.

## Operator inputs and application deployment

```powershell
$subscription = 'YOUR_SUBSCRIPTION_ID'
$group = 'YOUR_DEDICATED_DEMO_RG'
$location = 'YOUR_SUPPORTED_AZURE_REGION'
$prefix = 'astronomy-demo'
$privateDir = Join-Path $env:LOCALAPPDATA "astronomy-demo-private\$subscription\$group"
New-Item -ItemType Directory -Force $privateDir | Out-Null
$params = Join-Path $privateDir 'baseline.parameters.json'

az account show --subscription $subscription --query '{id:id,state:state}' -o json
# Only if this dedicated group has not already been created and creation is approved:
az group create --subscription $subscription --name $group --location $location

python deploy\azure\prepare.py --output $params --prefix $prefix `
  --location $location --deployment-id baseline-001
.\deploy\azure\Deploy.ps1 -SubscriptionId $subscription -ResourceGroup $group `
  -ParameterFile $params
```

Inspect the resource-ID-only preview. It must touch only the intended 27 apps
and three dedicated resources. Do not bypass a collision/deletion guard.
Once the preview and recurring spend are approved:

```powershell
.\deploy\azure\Deploy.ps1 -SubscriptionId $subscription -ResourceGroup $group `
  -ParameterFile $params -Apply
python deploy\azure\verify_revisions.py --subscription $subscription `
  --resource-group $group --parameters $params
```

Every Azure invocation supplies subscription/scope; do not change shared CLI
defaults with `az account set`. `--location` selects resource location; omitting
it uses the group's location. App names are fixed as documented in the
[inventory](ARCHITECTURE.md#complete-service-mapping). Reusing the parameter file
retains generated passwords. Replacing disposable database replicas can reset
data even when the passwords are retained.

Read non-secret deployment outputs, then exercise real requests:

```powershell
$outputs = az deployment group show --subscription $subscription `
  --resource-group $group --name "$prefix-baseline" `
  --query properties.outputs -o json | ConvertFrom-Json
$shopUrl = $outputs.shopUrl.value
$workspaceCustomerId = $outputs.workspaceCustomerId.value
$workspaceId = $outputs.workspaceId.value
$environmentId = $outputs.environmentId.value
$smokeStart = [DateTime]::UtcNow.ToString('o')
$smoke = python deploy\azure\verify_shop.py $shopUrl | ConvertFrom-Json
python deploy\azure\verify_telemetry.py --subscription $subscription `
  --workspace $workspaceCustomerId --trace-id $smoke.traceId --since $smokeStart
```

Require all four application tables and the successful distributed trace, not
just a provisioning success. Also follow [the demo checks](DEMO.md) for Kafka,
local observability and all-off flags. Keep evidence privately; generated files
are not repository inputs. Their producers reject output paths inside this
checkout, and `.gitignore` provides additional accidental-staging safeguards.

Before an incident exercise, rerun the
[current cap/freshness preflight](DEMO.md#mandatory-current-observability-preflight).
Abort on OverQuota or stale signals; a successful earlier checkout is not proof
of current ingestion or managed telemetry-gap alerting.

## Existing or newly onboarded hosted SRE Agent

The app template deliberately **does not provision an SRE Agent**. A new user
must first onboard one through the supported Azure experience, or use an
existing agent with its owner's authorization. Follow the current
[creation prerequisites and roles](https://learn.microsoft.com/azure/sre-agent/usage),
[identity and permissions guidance](https://learn.microsoft.com/azure/sre-agent/overview),
and [run modes](https://learn.microsoft.com/azure/sre-agent/run-modes).
Agent creation and any identity-role grants are separate administrative actions.
The current creation guide requires a human with
`Microsoft.Authorization/roleAssignments/write`, for example Role Based Access
Control Administrator or User Access Administrator, for its onboarding grants.
That is not a reason to grant this privilege to the application deployer.
Do not assume the agent's system-assigned identity is its configured action or
knowledge identity: inspect the live configuration and verify a query under the
identity actually used.

An authorized administrator should grant only the scoped Azure read/query
permissions needed for the dedicated app resources/workspace, following current
service requirements. This repo does not create roles, change existing grants,
or guarantee enforcement when an existing identity inherits broader access.
The tested agent had pre-existing Monitoring Contributor. A query-only Reader
grant is not a validated substitute for native scanning/acknowledgment behavior;
validate narrower IAM separately before claiming equivalent operation.

A public GitHub source should be read without creating a PAT. For a private
repository, use the service's supported authenticated source setup with the
owner's explicit consent; do not invent a token, install an app or consume OAuth
consent automatically. A successful connectivity check is not a source read or
cache-freshness check.

Generate reviewable, parameterized requests without applying them:

```powershell
$sreDir = Join-Path $privateDir 'sre'
$agentEndpoint = 'https://YOUR_AGENT_HOST'
$agentSubscription = $subscription
$agentGroup = 'YOUR_EXISTING_AGENT_RG'
$agentName = 'YOUR_EXISTING_AGENT_NAME'
$agentResourceId = "/subscriptions/$agentSubscription/resourceGroups/$agentGroup/" +
  "providers/Microsoft.App/agents/$agentName"
python deploy\azure\sre_setup.py --subscription $subscription `
  --resource-group $group --prefix $prefix `
  --workspace-customer-id $workspaceCustomerId --repository-url $forkUrl `
  --branch $branch --output $sreDir
python deploy\azure\alert_setup.py --subscription $subscription `
  --resource-group $group --prefix $prefix --location $location --output $sreDir
```

The agent may be in a different resource group; `$group` always means the
**application** group, while `$agentGroup` hosts the existing agent. These
examples use the same subscription. Cross-subscription identity/tool access was
not exercised and must be validated separately rather than assumed supported.

Optional `--agent-name`, `--filter-id` and `--source-alias` select SRE object
names. Preserve an existing source alias and its authentication; do not replace
unrelated objects that happen to share a name.

Follow [the tested native API contracts](SRE.md#generate-and-review-configuration).
`requests.json` records the exact read-first paths, audiences and create/update
methods; it is a review plan, **not an unattended applier**. Apply after reviewing
ownership and approval boundaries, in this order:

1. Inspect existing agent/identity/run mode and source; preserve unrelated fields.
2. Configure the scoped investigator and reusable common health prompt.
3. Configure the fork branch and prove actual source reads plus cached/remote HEAD.
4. Set native Azure Monitor incident management, then scoped filter and handler.
5. Create the two disabled permanent rules; execute their query-local predicate
   tests and real healthy-baseline gates before enabling them.
6. Verify an actual native health investigation and, separately, an approved
   expiring synthetic routing exercise. Inspect actual executed tools and scope.

The common prompt is generated as both `health-prompt.json` and
`health-prompt.txt`. Supply the real UTC window, trace ID and desired inventory
when running it in the hosted UI. Read [source-cache limitations](SRE.md#scope-and-permissions)
before claiming the agent sees the latest branch commit.

## Validation without a deployment

The clone/install/test/Bicep steps above require no Azure writes. Generators write
private local artifacts only; permanent and synthetic alert payloads default to
disabled. `.github/workflows/aca-baseline.yml` runs secretless tests and Bicep
compilation, not deployment. No CI login or stored cloud token is needed.
Any future deployment workflow needs separately configured scoped GitHub OIDC,
environment approval and its own change preview.

See [operating and troubleshooting guidance](DEMO.md#operating-and-troubleshooting)
for lessons from the actual deployment. No cleanup runs automatically.
