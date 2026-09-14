# Native SRE incident investigation

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
`commonTools` is a separate built-in-tool property from `tools`.
The setup
requests `commonTools=[RunAzCliReadCommands]` as well.
Its accepted readback is not
yet proof of effective runtime isolation. Full scope restrictions are repeated
in the handler guide because that guide was visibly injected into the incident.

## Generate and review configuration

```powershell
python deploy\azure\sre_setup.py --subscription $subscription `
  --resource-group $group --workspace-customer-id $workspaceCustomerId `
  --repository-url $forkUrl --branch $deployedBranch --output $privateConfigDir
```

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
| Incident platform | ARM `PATCH` existing agent, API `2026-01-01`, body `incident-platform.patch.json` |

The source and extended-agent payloads require a top-level `name`. The filter
accepts PascalCase input and returns camelCase output. On the exercised service,
legacy `incidentplayground` writes required the Azure CLI token audience
`59f0a04a-b322-4310-adc9-39ac41e9631e`; the `https://azuresre.dev` audience worked
for other APIs but produced misleading HTTP 405 responses on these legacy writes.
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

Mitigation, fault injection, external notifications and production actions remain
outside this integration. The output is an evidence-backed investigation and
proposed next steps, not autonomous remediation.
