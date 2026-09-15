# Native SRE incident investigation

For a new clone, use [the quickstart](QUICKSTART.md), including its argument-safe
Azure CLI wrapper and separate app/agent resource inputs.

This is an explicitly authorized extension to the healthy baseline: Azure Monitor
alerts for **only this application** can start an investigation in the existing
hosted SRE Agent. No separate investigator service, model deployment, action
group, ICM connection or Teams integration is required.

## Scope and permissions

Use the existing agent and identity. The generated custom-investigator
configuration requests only `RunAzCliReadCommands`, no handoffs, skills, system
skills or document retrieval.
Its instructions forbid resource-group/subscription-wide metadata enumeration,
unrelated telemetry, writes, mitigation, elevation and outbound notifications.
Queries must use exact demo environment/telemetry resource IDs and bounded
time/row limits. App membership is established from the exact environment ID,
not a tag or resource-group membership.

This is requested behavioral/tool scoping, **not enforced tool or IAM isolation**.
Runtime inspection of the commissioning incident showed that the native platform
also activated baseline tools, including `RunAzCliWriteCommands`, `Task`,
`read_skill_file`, `SearchMemory` and `SaveReport`, despite the configured tool
list. The observed investigation executed read-only operations, with no terminal
calls, writes or approval requests; that does not prove write tools are
inaccessible. The proven controls are Review mode, investigation instructions and
the observed execution record. Existing inherited roles are unchanged. Review
mode alone does not prohibit external MCP/Teams/email writes; do not add those
integrations. Source access must be reported unavailable unless an actual source
read succeeds in the investigator. A separately verified repo connection is not
proof of that runtime capability.
Also compare the investigator's cached checkout HEAD with the remote branch HEAD
using actual source reads. Updating a same-branch source registration can retain
a stale checkout; a successful PUT/connectivity test is not a refresh guarantee.
Do not assume a sync route exists. If refreshing requires removing/recreating
the registration, obtain separate human approval and preserve the exact alias,
URL, branch and authentication scope. Until then, report the cached source
revision explicitly and treat newer deployment code as unavailable.
`commonTools` is a separate built-in-tool property from `tools`.
The setup
requests `commonTools=[RunAzCliReadCommands]` as well.
After this correction, a repeated native investigation executed four scoped
read commands and obeyed the TEST early-stop guide. This demonstrates observed
behavior, not hard tool or IAM isolation. Full scope restrictions are repeated
in the handler guide because that guide was visibly injected into the incident.

## Commissioning status

The September 14, 2026 deployment exercised real shop checkout, distributed
Azure telemetry and native alert-to-investigation routing. Both permanent
request-failure and telemetry-gap rules are enabled in that demo, scoped to its
dedicated workspace, with no action groups. The native response filter is
enabled in Review mode and excludes TEST; both temporary test rules and the
separate test filter are disabled.

The corrected investigator queried real successful checkout spans and fresh
application signals using scoped Azure reads, without remediation, terminal
execution or approval requests. Synthetic routing tests did not inject faults
or establish outage detection under a real failure. The registered source
checkout remains an older feature-branch snapshot: refresh is pending separate
human approval, not implied by successful telemetry verification. No hard tool
or IAM isolation claim is made.

The generators below intentionally remain disabled-by-default for new
deployments; this recorded activation is not permission to enable another
environment without its own healthy-baseline checks.

Later, daily-cap exhaustion stopped application ingestion. The manual gap query
returned one matching `Requests=0` row, yet no expected gap alert or automatic
incident was observed. Exact-rule Resource Health reported Available with no
historical errors; that did not explain or validate managed evaluator behavior.
The SRE investigation of this condition was manually initiated. Commissioning
proof above is historical, not a claim of presently healthy telemetry or proven
cap-induced absence detection. No quota, threshold, rule or permission was
changed to hide the gap.

Use [the mandatory current preflight](DEMO.md#mandatory-current-observability-preflight)
before an exercise; abort on cap exhaustion or stale data. An ingestion warning
companion monitor is future, operator-reviewed work, not installed here. Azure's
[daily-cap guidance](https://learn.microsoft.com/azure/azure-monitor/logs/daily-cap)
describes a five-minute query using `_LogOperation`, `Category =~ 'Ingestion'`
and `Detail contains 'OverQuota'`. Its schema, managed evaluation and actual
routing must be validated before adoption; do not substitute it speculatively.

## Generate and review configuration

```powershell
python deploy\azure\sre_setup.py --subscription $subscription `
  --resource-group $group --workspace-customer-id $workspaceCustomerId `
  --repository-url $forkUrl --branch $deployedBranch --output $privateConfigDir
```

Generate the separate Azure Monitor rule bodies with
`python deploy\azure\alert_setup.py --subscription <id> --resource-group <group>
--location <region> --output <private-directory>` (one command line).
Both are disabled initially, Sev2, evaluated every minute, scoped to the exact
demo workspace, and have no action groups. Apply using ARM PUT to each explicit
`Microsoft.Insights/scheduledQueryRules/<rule-name>?api-version=2023-12-01`
resource ID after reviewing existing ownership and the body.
The failure rule requires at least three failed request records **and** at least
20% failures per core service in five minutes. Unknown success status is not
counted as a failure. The gap rule means no core request spans for ten minutes;
it assumes the load generator is running and is not proof of an app outage.
`threshold-tests.kql` exercises nine query-local fixture cases against the same
failure predicate without ingesting fake telemetry. Require nine `Passed=true`
rows from the dedicated workspace before enabling the rules. Keep TEST routing
rules separate and disabled after verification. Enable permanent rules only
after the real healthy checkout, load-generator and telemetry gates pass.
`gap-tests.kql` additionally requires five passing query-local cases: empty,
stale, self-only and unattributed data trigger; recent checkout data does not.

Keep generated resource IDs/configuration outside the public repository. The
generator makes no Azure calls. Before applying, inspect the existing agent,
incident filters, custom agent and source registrations and compare intended
changes; do not overwrite an unrelated object using the same name.

The following routes were exercised against the native SRE service. Treat its
data-plane API as version-sensitive and re-read live responses after writes.

| Resource | Request |
| --- | --- |
| Custom investigator | `PUT /api/v2/extendedAgent/agents/astronomy-shop-investigator`, body `agent.json` |
| Permanent incident filter, create | `PUT /api/v1/incidentplayground/filters/astronomy-shop-readonly`, body `filter.json` |
| Permanent incident filter, update | `POST` to the same filter path |
| Handler, create | `PUT /api/v1/incidentplayground/handlers/astronomy-shop-readonly-handler`, body `handler.json` |
| Handler, update | `POST` to the same handler path |
| Fork source | `PUT /api/v2/repos/{existing-source-alias}`, body `source.json`; preserve the live alias and auth |
| Source connectivity | `POST /api/v2/repos/{existing-source-alias}/test` |
| Common health prompt | GET then PUT `/api/v2/extendedAgent/commonprompts/{filter-id}-health`, body `health-prompt.json` |
| Incident platform | ARM `PATCH` existing agent, API `2026-01-01`, body `incident-platform.patch.json` |

The source and extended-agent payloads require a top-level `name`. The filter
accepts PascalCase input and returns camelCase output. The verified working
audience for the tested legacy `incidentplayground` requests was
`59f0a04a-b322-4310-adc9-39ac41e9631e`. Earlier requests using
`https://azuresre.dev` returned HTTP 405 while platform initialization was also
in progress. That is not a controlled comparison proving the audience alone
caused those failures or that the GUID is a universal service requirement.
Never copy an access token into a file, chat or URL. Example invocation shape:

```powershell
az rest --method put --resource 59f0a04a-b322-4310-adc9-39ac41e9631e `
  --url "$agentEndpoint/api/v1/incidentplayground/filters/astronomy-shop-readonly" `
  --body "@$privateConfigDir\filter.json"
```

For repeatable application, GET the filter/handler collections first, confirm
the matching object's purpose/scope, then choose PUT only for a new ID and POST
for an existing ID. Repeated PUT on an existing handler returns HTTP 409 rather
than updating it. Re-read each object and compare the effective values after
the write; the document generator intentionally does not perform these writes.

`requests.json` records these methods and audiences for the chosen object names.
The common prompt envelope includes `name`, `type: CommonPrompt`, `tags` and
`properties.prompt`. GET the exact existing prompt, preserve other envelope and
property fields, replace only the reviewed prompt, then PUT and verify
GET `properties.prompt`. Its tested audience is the same public service GUID
used for legacy incident management above. A text copy is also generated for
inspection or use in the hosted UI.

For agent operations, supply the explicit **agent** subscription and ARM ID;
generated application scope remains the separate app subscription/group.
The Azure Monitor rule resources belong to the app group. Do not confuse them
with the agent's self-telemetry.

After creating the permanent rules disabled and passing the real baseline and
query-local predicate tests, use ARM PATCH with
`{"properties":{"enabled":true}}` on each reviewed scheduled-query-rule ID
(`api-version=2023-12-01`). Read back enabled state, exact workspace scopes,
unchanged predicates and empty action groups. Prefer an `@private-file.json`
body over shell-embedded JSON.
Use each generated alert display name as its Azure rule name as well (URL-escape
it in REST paths). The permanent native title filter expects `Astronomy Shop`;
an arbitrary rule name that lacks that text is not a verified routing setup.

For a temporary native test filter, the tested lifecycle is POST
`/api/v1/incidentplayground/filters/{id}/enable` or `/disable`, **without a body**.
New filters default enabled; explicitly disable a new test filter until ready.
The [demo walkthrough](DEMO.md#separately-approved-synthetic-routing-exercise)
provides the separately approved expiring test and mandatory cleanup procedure.

The ARM patch changes only `incidentManagementConfiguration.type` to `AzMonitor`;
it does not replace the agent or change identities/RBAC. Preserve the existing
Review mode. A documented `ReadOnly` value was rejected by the live ARM API; do
not rely on it as an enforced mode. Re-read the effective custom-agent tool list
and restrictions after applying, and inspect the tools actually activated in a
real incident. Configuration alone is not proof of enforcement.

## Alert-to-investigation verification

The permanent filter accepts Sev2 alerts titled `Astronomy Shop`, targeting the
exact dedicated workspace, excludes `TEST`, and disables incident merging so a
synthetic routing incident cannot absorb a real outage.

A commissioning test used an explicitly labeled, expiring TEST
`Microsoft.Insights/scheduledQueryRules` rule, API `2023-12-01`, on actual
`AppMetrics` records for role `opentelemetry-demo.ad`. Its condition was count
greater than zero, not an error condition. It used a five-minute window,
one-minute evaluation and **no action groups**. The real alert was ingested by
the native scanner and started the configured investigation automatically.
The rule was then disabled. This proves routing, not outage detection or shop
health. No fault flag was activated.

For another routing test, create a separate narrowly titled test filter, an
explicit UTC expiry in both metadata and KQL, and disable the rule immediately
after collecting evidence. Do not weaken the permanent filter's TEST exclusion.
Do not leave a perpetual count-greater-than-zero alert enabled.

For real failure detection, first verify checkout and actual
`AppRequests`/`AppDependencies` schemas and role names. Select a meaningful error
threshold and minimum traffic count from the stable baseline, scope the rule to
the dedicated workspace, and validate its result before enabling it. Lack of
telemetry needs a separate freshness signal: zero request errors with no
requests is not healthy.

Capture the actual alert fire timestamp/ID, target, scanner-created incident,
assigned custom investigator, executed tools and bounded query results privately.
Require evidence that the final investigation stayed within exact app scope.
An earlier commissioning run performed broad resource-group **metadata**
discovery; the instructions were tightened to forbid it. This was not a grant of
additional permissions and must not be represented as strict IAM isolation.

The native incident lifecycle can acknowledge an Azure alert. Disabling a test
rule can leave a retained alert's monitor condition Fired while its alert state
is Acknowledged. The boundary is **no automatic application remediation**, not
a promise of zero incident-metadata writes. The commissioned runtime identity
already held Monitoring Contributor; a Reader-only replacement for the complete
scanner/acknowledgment flow has not been validated. Tighter IAM is a separate
hardening exercise, not an automatic role change in this setup.

Mitigation, fault injection, external notifications and production actions remain
outside this integration. The output is an evidence-backed investigation and
proposed next steps, not autonomous remediation.
