# Safe demo walkthrough and operations

Commands use the quickstart's operator inputs and session-local argument-safe
Azure CLI wrapper. They do not change a shared Azure default subscription.

Use the [quickstart](QUICKSTART.md) first. This walkthrough demonstrates
**healthy checkout -> real telemetry -> scoped investigation** and, separately,
**synthetic alert -> native incident investigation**. It does not activate a
fault or prove outage detection, automatic repair or postmortem publication.

## Healthy application and investigation

### Mandatory current observability preflight

Before any incident exercise, including a separately approved real fault,
inspect the actual workspace cap/status/reset and current application signals:

```powershell
python deploy\azure\verify_telemetry.py --preflight --subscription $subscription `
  --resource-group $group --workspace-name "$prefix-logs" `
  --workspace $workspaceCustomerId
if ($LASTEXITCODE -ne 0) { throw 'Observability preflight failed; do not start an incident exercise.' }
```

This read-only check prints `dailyQuotaGb`, `dataIngestionStatus` and
`quotaNextResetTime`, verifies the workspace customer ID, and requires all four
application tables to contain records from the last five minutes. It aborts on
OverQuota, unknown cap state, stale/missing data or query failure. Successful
checkout or collector readiness alone is insufficient. Rerun immediately before
any approved activation; an earlier commissioning result is not a current gate.
Wait for the reported reset and verify fresh ingestion, or seek explicit human
budget approval for a cap change. Never raise the cap automatically. Keep the
prepare-only accelerator local-only; it does not run this Azure preflight.

### Functional and investigation checks

1. Run `verify_revisions.py` against the private desired parameter file. Require
   all 27 apps' main containers running and ready; flagd-ui is a sidecar.
2. Run `verify_shop.py` and `verify_telemetry.py` with the actual start timestamp
   and returned trace ID, as shown in the quickstart. Require a successful order,
   shipping/tracking, emptied cart and 404 responses on protected routes.
3. Verify Kafka consumption and PostgreSQL persistence, not only checkout's
   producer span. Preserve only counts, timestamps and synthetic order IDs.
4. Open the existing hosted SRE UI and run the configured common health prompt
   with the actual UTC window, trace ID and desired inventory. Require actual
   scoped queries and source-read evidence, not a generic healthy response.
5. Show service identity/version/deployment correlation and distinguish source
   context from image provenance. Label a stale registered checkout explicitly.

Do not enter real names, addresses or cards. The verifier uses the upstream
synthetic payment/person fixture. Preserve evidence privately, never in a PR.

Internal diagnostic examples use only the intended environment:

```powershell
az containerapp exec --subscription $subscription --resource-group $group `
  --name image-provider --command 'wget -qO- http://prometheus:9090/-/ready'
az containerapp exec --subscription $subscription --resource-group $group `
  --name image-provider --command 'wget -qO- http://grafana:3000/api/health'
az containerapp exec --subscription $subscription --resource-group $group `
  --name image-provider --command 'wget -qO- http://jaeger:16686/jaeger/ui/api/services'
az containerapp exec --subscription $subscription --resource-group $group `
  --name flagd --container flagd-ui --command 'sha256sum /app/data/demo.flagd.json'
python -c "import hashlib,pathlib; print(hashlib.sha256(pathlib.Path('src/flagd/demo.flagd.json').read_text().encode()).hexdigest())"
```

The two flag hashes must match the reviewed all-off source. Console execution
can return a successful transport status even when the command itself failed:
inspect its actual response. For OpenSearch, check a fresh application log in
`otel-logs-aca-*`, not just index existence. Inspect exporter errors separately
from commissioning errors. No dashboard/backend is made public for this demo.

## Permanent monitoring

**Observed limitation:** the historically verified synthetic routing tests do
not establish end-to-end absence detection. During a later real daily-cap
exhaustion, ingestion stopped and the gap query returned `Requests=0`, but no
expected Azure gap alert or automatic SRE incident was observed. Exact-rule
Resource Health was Available without reported historical errors. Neither that
status nor successful manual KQL/query-local fixtures certifies the managed
evaluator or alert routing. The cause remains unresolved; do not infer a fix.
The subsequent SRE diagnostic was manually initiated, not automatic detection.
Historical healthy evidence remains as-of its verification timestamps, not a
claim of currently healthy telemetry.

The commissioned deployment has both permanent rules **enabled**. New generated
rules remain disabled until the new environment passes its gates. See
[the native setup contracts](SRE.md). The predicates are:

| Rule | Predicate | Interpretation |
| --- | --- | --- |
| Request failures | At least 3 failed records and at least 20% failures per core service over 5 minutes | Observed requests, not an unsampled traffic estimate |
| Telemetry gap | No core request spans over 10 minutes | Assumes Locust is running; missing traffic/telemetry is not proof of an outage |

Run generated `threshold-tests.kql` and `gap-tests.kql` in the dedicated
workspace. They use query-local fixtures and never ingest fabricated telemetry.
Require nine and five passing cases respectively. On Windows, pass single-line
KQL or use the tested query transport in `verify_telemetry.py`; `az.cmd` can
silently mishandle multiline arguments.

## Separately approved synthetic routing exercise

This exercise creates a **separate**, narrowly named TEST filter/handler and
Azure log alert. Never remove TEST exclusion from the permanent filter. It
uses real ad metrics with count greater than zero; it is not an application
failure. Obtain approval for this exact test and its short duration first.

```powershell
$testId = 'astronomy-shop-routing-test'
$expiry = [DateTime]::UtcNow.AddMinutes(15).ToString('o')
python deploy\azure\routing_test.py --subscription $subscription `
  --resource-group $group --prefix $prefix --location $location `
  --workspace-customer-id $workspaceCustomerId --repository-url $forkUrl `
  --branch $branch --expires-at $expiry --test-id $testId --output $sreDir
```

The generator refuses expired, timezone-less or more-than-30-minute deadlines.
It generates a disabled alert and puts expiry in both its tags and KQL.
KQL expiry stops new triggering matches; it does **not** replace disabling the
rule/filter. The native filter defaults enabled on creation, so disable it
immediately until the test is ready.

Review `test-requests.json`: GET each collection, check the ID's existing
purpose/scope, then use PUT for creation or POST for updating the matching
filter/handler. Preserve unrelated fields. Apply the test alert with ARM PUT
only after checking the exact rule ID for ownership collisions:

```powershell
$sreAudience = '59f0a04a-b322-4310-adc9-39ac41e9631e'
$testFilterUrl = "$agentEndpoint/api/v1/incidentplayground/filters/$testId"
$testTitle = (Get-Content "$sreDir\test-alert.json" -Raw |
  ConvertFrom-Json).properties.displayName
$testRuleName = [Uri]::EscapeDataString($testTitle)
$testRuleId = "/subscriptions/$subscription/resourceGroups/$group/providers/" +
  "Microsoft.Insights/scheduledQueryRules/$testRuleName"
$testRuleUrl = "https://management.azure.com${testRuleId}?api-version=2023-12-01"
az rest --subscription $agentSubscription --method post --resource $sreAudience `
  --url "$testFilterUrl/disable"
az rest --subscription $subscription --method put --url $testRuleUrl `
  --body "@$sreDir\test-alert.json"
```

Read back both objects. Do not execute the next block before the test handler
exists, the filter matches only the generated title/exact workspace, the rule
has no action groups, and expiry remains in the future. Generate patch files
privately to avoid shell quoting errors:

Use the generated title as the Azure rule's actual name, not merely its display
name, so the native title filter matches the alert's rule name. The test filter
ID and Azure rule name are deliberately different identifiers.

```powershell
@{properties=@{enabled=$true}} | ConvertTo-Json |
  Set-Content -LiteralPath "$sreDir\enable.json" -Encoding utf8
@{properties=@{enabled=$false}} | ConvertTo-Json |
  Set-Content -LiteralPath "$sreDir\disable.json" -Encoding utf8
try {
  az rest --subscription $agentSubscription --method post --resource $sreAudience `
    --url "$testFilterUrl/enable"
  if ($LASTEXITCODE -ne 0) { throw 'Could not enable the approved test filter.' }
  az rest --subscription $subscription --method patch --url $testRuleUrl `
    --body "@$sreDir\enable.json"
  if ($LASTEXITCODE -ne 0) { throw 'Could not enable the approved test rule.' }
  Read-Host 'Inspect the native investigation, then press Enter to disable the test'
}
finally {
  try {
    az rest --subscription $subscription --method patch --url $testRuleUrl `
      --body "@$sreDir\disable.json"
    if ($LASTEXITCODE -ne 0) { throw 'Test rule disable failed; operator action required.' }
  }
  finally {
    az rest --subscription $agentSubscription --method post --resource $sreAudience `
      --url "$testFilterUrl/disable"
    if ($LASTEXITCODE -ne 0) { throw 'Test filter disable failed; operator action required.' }
  }
}
```

Read back `properties.enabled=false` on the rule and `isEnabled=false` on the
test filter. A stopped terminal/network failure can interrupt cleanup: check
these values independently. Keep disabled test objects/evidence for review;
do not delete them or incident threads automatically.

Capture actual fire time, alert target/ID, scanner-created investigation,
assigned handler, executed tools, bounded query results and final SYNTHETIC
verdict. No manual prompt should be mistaken for automatic scanner triggering.
The investigator must confirm the metric condition and stop without inventing
customer impact or remediation.

## Actual faults and later increments

The [scenario inventory](README.md#preserved-fault-inventory-all-off)
preserves upstream
flags, including documented quirks and ACA probe qualifications. All defaults
remain off. A real failure exercise needs separate approval of the exact flag,
expected impact, duration, observation predicates, reset method and verification.
Do not turn on faults merely to make the demonstration more dramatic.

ICM, Teams, support data, postmortems, repair items and production remediation
are future work. Review mode is not authorization for external connector writes.

## Operating and troubleshooting

| Symptom | Verified lesson / response |
| --- | --- |
| ARM says succeeded but checkout fails | Inspect actual replica main containers and functional requests |
| Checkout Kafka panic during startup | Preserve dependency waves; do not start consumers/producers before Kafka readiness |
| Internal gRPC/TCP cannot connect | Use app service names, not shared HTTP-ingress FQDNs |
| Collector hostname trouble | Use the tested `telemetry-gateway` app mapping |
| Network-wait init never finishes | Do not reintroduce network init containers; deployer gates waves externally |
| Large ARM expression fails | Resolve endpoint markers per secret, not by serializing giant config arrays |
| All service instances look like collector | Preserve resource attributes with non-overriding detection; do not fabricate missing IDs |
| Local log mapping errors | Use the isolated encoded-key OpenSearch pipeline; retain original Azure attributes |
| Old errors after a rollout | Separate pre-cutover/draining records from the new stable UTC window |
| Native handler PUT returns 409 | GET first; existing filter/handler updates use POST |
| Legacy native API returns misleading 405 | Check the tested service audience and method, not only endpoint reachability |
| Source registration succeeds but code is old | Compare cached and remote HEAD; refresh may require separate approval |
| No recent telemetry | Check Locust, exporter errors, permissions and daily ingestion cap; do not infer health |

Durable **code** is not durable application **state**. PostgreSQL, Valkey, Kafka,
flags and local observability use ephemeral volumes. Replica replacement can
lose data; a rolling deployment can mix service revisions. Keep both deployment
events for scoped repairs. There is one replica per app, no backup/HA guarantee,
and no production-readiness claim.

The all-active retail compute scenario is approximately $22.03/day before
grants/discounts, rollout overlap, requests, ingestion and other charges.
Existing SRE charges are additional. A daily ingestion cap is not an immediate
hard spending ceiling. Review actual regional prices and Cost Management.

To stop spend, obtain approval for an exact inventory, first disable both demo
alerts and its response/test filters, then deactivate only the intended app
revisions. Otherwise an intentional shutdown can fire the telemetry-gap alert.
Alerts and native SRE objects have a separate cleanup inventory from app IaC.
CLI versions
may not provide `containerapp stop`. Stopping stateful replicas can lose data.
For permanent cleanup, review the 27 app IDs, three dedicated resource IDs and
custom alert IDs individually. Never delete a shared RG or the existing SRE
Agent, identity, self-telemetry or unrelated resources. Cleanup is not automated
by these scripts.
