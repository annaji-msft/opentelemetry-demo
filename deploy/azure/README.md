# Astronomy Shop on Azure Container Apps

This fork adapts the **full** `compose.yaml` + `compose.full.yaml` +
`compose.observability.yaml` model, not a replacement application. The translator
fails if the upstream service inventory changes. It currently deploys all 28
services in 27 Container Apps; flagd and flagd-ui share a replica and flag file.
The optional upstream agent, chatbot, extras and eBPF profiling layers are not
part of these three manifests and are not deployed.

## Architecture and boundaries

| Component | ACA mapping |
| --- | --- |
| Shop gateway | `frontend-proxy`, public HTTPS only, Envoy upstream image with narrowed routes |
| Business services | ad, cart, checkout, currency, email, frontend, payment, product-catalog, quote, recommendation, shipping; internal TCP at upstream ports |
| Async order processing | Kafka, accounting and fraud-detection retained; internal Kafka listener and local controller |
| Data | PostgreSQL 18 catalog/accounting initialization and Valkey cart; internal only |
| Flags | flagd plus flagd-ui sidecar, writable shared replica volume, seeded with all faults off |
| Synthetic traffic | Upstream Locust + browser image, five users, no public control UI |
| OTel | Pinned contrib collector in `telemetry-gateway`, internal OTLP gRPC 4317 and HTTP 4318 |
| Local observability | Jaeger, Prometheus, OpenSearch, Grafana and OpAMP retained internally |
| Documentation | Upstream telemetry-docs service retained internally |
| Azure observability | Separate workspace-based Application Insights and Log Analytics workspace |

ACA is not Compose. Services use environment service names and internal TCP,
preserving gRPC/HTTP2 without terminating it as HTTP/1.1. Dependencies are deployed
in waves, with bounded checks of actual running/ready replicas between waves.
Startup, readiness and liveness TCP probes
are present for listening services. An open port is **not** proof that checkout,
Kafka processing or telemetry works: run the functional verification below.
Internal TCP callers must use service-name discovery; the HTTP ingress FQDN
resolves to the shared HTTP proxy and is not a substitute for a TCP service
address. The collector app is named `telemetry-gateway` rather than
`otel-collector`; its container and OTel identity retain the upstream name.

Separate apps provide independent service revisions, readiness and failure
boundaries for investigation. A single multi-container app would share scaling,
deployment and restart boundaries and require remapping duplicate localhost
ports. It is not a drop-in Compose deployment. Do not assume this aggregate
8.5-vCPU/17-GiB allocation fits one consumption replica; verify current profile
limits before choosing consolidation. A VM/AKS deployment is a different hosting
decision, not a fallback this deployment script makes.

The gateway rejects `/feature`, `/flagservice`, `/loadgen`, `/grafana`, `/jaeger`,
`/opamp`, `/profiles`, `/chatbot`, `/telemetry` and `/otlp-http`. Its header-based
fault filter is removed. Envoy admin binds loopback. No databases, collector
ingress, backend UI or fault-control API is publicly routed. The public shop is
a synthetic demo, not an authenticated production storefront; never enter real
personal information or payment details.

No existing SRE Agent, managed identity, role assignment or existing telemetry
resource is managed by this template. `Deploy.ps1` rejects collisions with
resources not tagged `managedBy=astronomy-aca`, previews resource IDs, rejects
deletions/unexpected changes, and uses incremental deployment. It never changes
the Azure CLI default subscription.

## Prerequisites and repeatable deployment

Use PowerShell 7, Python 3.12+, authenticated Azure CLI and Bicep. No local Docker,
ACR, VM, AKS cluster, PAT, GitHub App or model deployment is required. Provisioning
requires resource-write access only to the selected resource group. Querying
requires access to the dedicated workspace. No RBAC is automatically added.

```powershell
python -m pip install -r deploy\azure\requirements.txt
python -m unittest discover -s deploy\azure -p 'test_*.py' -v
az bicep build --file deploy\azure\main.bicep

# Keep this outside the repository and outside cloud-synced folders.
$params = Join-Path $env:LOCALAPPDATA 'astronomy-demo\baseline.parameters.json'
python deploy\azure\prepare.py --output $params --deployment-id baseline-001

# Supply the intended subscription explicitly; do not use az account set.
.\deploy\azure\Deploy.ps1 -SubscriptionId $subscription -ResourceGroup $group `
  -ParameterFile $params
.\deploy\azure\Deploy.ps1 -SubscriptionId $subscription -ResourceGroup $group `
  -ParameterFile $params -Apply
```

The existing group location is used. Resources are named `astronomy-demo-env`,
`astronomy-demo-logs`, `astronomy-demo-insights`, and the upstream service names
(except `telemetry-gateway` for the collector).
Use a separate group for another complete deployment: changing the prefix alone
does not rename the apps.

`images.lock.json` resolves all upstream tags to Linux/amd64 manifest digests.
Deployments consume digests, never moving `latest` tags. To deliberately update:
run `python deploy\azure\lock_images.py`, review the complete diff and repeat
verification. Many upstream application images do not publish an OCI source
revision label: a null `sourceRevision` is unknown provenance, **not** proof that
an image was built from the fork commit. The checkout revision records the
configuration/source context; the image lock identifies the exact executable
artifacts. Keep these separate in investigation evidence.

The parameter file contains randomly generated database passwords and flag UI
signing material. It is passed through secure ARM object parameters and ACA
secret references. Application Insights' connection string is resolved inside
Bicep and is never output. Do not print, commit, attach or paste parameter files,
connection strings or exported live app configuration. Re-running preparation
with the **same parameter file** retains passwords; use a new deployment ID for
changed configurations. Keep the file in access-controlled local storage.
Preparation appends the first eight characters of the actual configuration-bundle
SHA-256 to the deployment ID. The complete config and image-lock digests are
resource tags, and successful deployment writes a private
`<parameter-file>.event.json` with outcome `provisioned`. This identifies
uncommitted configuration precisely without confusing it with the source SHA.

Configuration files are mounted via ACA secret volumes, not environment-sized
base64 blobs. The upstream SQL schema/data is reused with runtime psql password
variables. The flag file is copied by an init container into a shared EmptyDir;
both flagd and its UI see the same file. No fault is enabled by the deployer.

## State, availability and cost

This is a disposable hackathon baseline, **not production hosting**:

- PostgreSQL, Kafka, Valkey and local observability data are ephemeral. Replica
  replacement can reset orders, carts, Kafka offsets and local telemetry.
  PostgreSQL recreates the upstream catalog on startup. Azure Monitor data is
  independent and survives app replacement.
- Flag edits survive a container restart within the same replica but not replica
  replacement. Redeployment seeds the reviewed all-off file. Do not use the flag
  UI for scheduled scenarios until a later explicitly authorized increment.
- There is one replica per app, no automatic scale-out, backup, HA or durable
  volume. Rolling changes can temporarily mix revisions. Dependency startup
    checks time out with the names of unready apps rather than silently proceeding.
    The deployer waits up to ten minutes for real replica readiness per dependency
    wave; network-wait init containers are not used. The collector starts
    independently of local backend readiness; its
    exporters handle retries so a local dashboard backend cannot block Azure
    Monitor ingestion.
- The consumption allocation is 8.5 vCPU and 17 GiB across main containers.
  Upstream Compose limits sum differently because ACA allocates CPU/memory in
  fixed ratios. Always-on Locust makes much of this active, billable compute.
  Additional charges include requests, log ingestion/retention and outbound
  data. There is no dedicated-node, ACR or managed-database charge.
  As a qualified retail scenario, Sweden Central active CPU at
  $0.000024/vCPU-second and memory at $0.000003/GiB-second totals approximately
  **$0.918/hour or $22.03/day** if this entire allocation stays active, before
  grants/discounts and excluding all other charges and rollout overlap. This is
  not an invoice forecast or a spending cap.
- The workspace uses 30-day retention and a 1 GB/day ingestion cap. The cap is
  a safeguard, not an instantaneous hard spending ceiling; reaching it stops
  observability and invalidates freshness checks. Check actual regional pricing
  and Cost Management before leaving the demo running overnight.

No cleanup is executed automatically. To stop the demo, review an explicit
inventory filtered by the ownership tag and stop only those apps. For permanent
cleanup, delete only the 27 named demo apps and three dedicated resources after
review. **Never delete the shared resource group** or use an RG-wide cleanup
command. Retain the evidence and image lock before deleting the workspace.

## Telemetry and end-to-end verification

The checkout pins contrib **0.159.0**, whose `azure_monitor` exporter supports
traces, logs and metrics at beta stability. This deployer preserves OTLP,
PostgreSQL, Kafka, Valkey, nginx, HTTP health and ad Prometheus receivers, span
metrics, upstream span/log normalization and payment/email redaction. It exports
in parallel to Azure Monitor and local Jaeger/Prometheus/OpenSearch.

Sources:
[exporter configuration and mapping](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/v0.159.0/exporter/azuremonitorexporter),
[ACA storage semantics](https://learn.microsoft.com/azure/container-apps/storage-mounts).

Important gaps:

- Docker socket and host-filesystem metrics cannot be collected in ACA. They are
  removed rather than pretending ACA exposes the host. Use ACA platform metrics
  and console/system logs for infrastructure evidence.
- eBPF/profiles are not exported to Azure Monitor; the optional upstream profiling
  layer is not deployed.
- The public gateway does not expose OTLP. Browser OTLP targets the internal
  collector; public clients cannot resolve/reach it, and browser mixed-content
  policy can prevent export from HTTPS pages. Server-side traces remain the
  primary baseline. Do not claim public browser trace coverage.
- TCP probes do not evaluate upstream gRPC readiness status. The
  `failedReadinessProbe` flag remains available at application level but is not
  an ACA readiness-failure demonstration with these probes.
- The collector does not report effective configuration to OpAMP because it
  could disclose the resolved Application Insights connection string. Existing
  app-level OpAMP connections remain internal.
- Metrics are mapped into `AppMetrics`, not an Azure managed Prometheus workspace.
  Inspect exporter mapping for unsupported data types and histogram fidelity;
  no claim is made that all OTel metric representations survive unchanged.

Run the actual public shop APIs, including a synthetic checkout:

```powershell
python deploy\azure\verify_shop.py $shopUrl
python deploy\azure\verify_telemetry.py --subscription $subscription `
  --workspace $workspaceCustomerId --trace-id $smokeTraceId `
  --since '2026-09-14T00:00:00Z'
```

Use the **actual smoke-start timestamp**, not the illustrative timestamp above.
`verify_shop.py` uses the upstream synthetic card fixture and W3C baggage, checks
catalog/ads/recommendations/cart, requires an order/tracking ID, checks cart
emptying and blocked control paths. `verify_telemetry.py` requires recent
application AppRequests, AppDependencies, AppTraces and AppMetrics (excluding
collector self-telemetry), and a correlated frontend/checkout/payment/cart trace.
It also checks emitting-service instance, version, deployment and source metadata.
The shared collector uses non-overriding resource detection so its own identity
cannot replace the application attributes.
Native SDK-generated instance IDs (including UUIDs) are preserved. The gateway
does not supply its own instance ID as a fallback for emitters that omit one.
Its bounded ingestion wait fails rather than falling back to fixtures.

Also inspect accounting/fraud-detection consumer progress, local backend health,
latest revision health and exporter errors. Initial startup errors must be
reported separately from the post-convergence verification window.

Resource attributes carry service name/namespace/version, deployment environment,
deployment ID, per-service instance identity and source revision. Preserve a
private event conforming to `change-event.schema.json` with a SHA-256 of the
actual config bundle and image lock, deployed resource IDs, UTC timestamp,
outcome and verification trace. A `provisioned` event must not be relabeled
`verified` until functional and telemetry gates pass. Do not commit live resource
IDs, operational log payloads, personal data or deployment credentials.

For a targeted repair, preparation supports `--only <app-name> ...` together
with `--credentials-from <existing-full-parameter-file>`. This preserves existing
database credentials and leaves unselected apps untouched. Always finish with
the complete desired configuration and functional verification; a partial
deployment event is not evidence that every service runs the same revision.

## SRE Agent handoff (read-only, this application only)

Use the existing hosted SRE Agent UI, not a second investigator app. Scope
monitoring to apps whose environment ID equals the new demo environment, the
dedicated workspace/Application Insights, and this fork. Verify an actual repo
read and actual resource-scoped KQL under the agent identity before declaring
integration complete. An ARM resource declaration is not a connectivity test.

Suggested first investigation prompt:

> Check only this Astronomy Shop ACA environment and its dedicated telemetry
> resources. Use the supplied deployment event and verification trace ID. Read
> the fork source and query real records since the supplied UTC verification
> timestamp. Report app revision health, checkout outcome, distributed-trace
> services, Kafka consumer evidence and per-signal freshness. Separate initial
> startup errors from the stable window; report missing evidence as unknown.
> Do not change resources, flags, permissions or code, or invoke external writes.

Use explicit Review mode for any future response plan/task, plus tool-access
restrictions for external writes: Review mode alone is not a blanket approval
gate for Teams/email/MCP actions. Configuration scope is not an IAM isolation
guarantee if the existing agent identity has broader inherited access. Changing
those existing permissions is a separate explicit decision. The baseline
deployer does not configure incident triggers, schedules, automatic remediation
or fault injection. The separately authorized native alert-to-read-only-
investigation extension is documented in [SRE.md](SRE.md); it does not authorize
mitigation or outbound notifications.

## Preserved fault inventory (all off)

The source of truth is `src/flagd/demo.flagd.json`. No scenario was activated
during baseline verification. These definitions and normal service code are
retained, not replaced with simulated errors.

| Flag | Upstream behavior / ACA qualification |
| --- | --- |
| `adFailure` | Fail the ad service |
| `adHighCpu` | High CPU in ad; fixed ACA CPU allocation bounds impact |
| `adManualGc` | Manual garbage collection in ad |
| `cartFailure` | Probabilistic cart errors |
| `emailMemoryLeak` | Email memory leak; ACA eventually restarts an exhausted replica |
| `failedReadinessProbe` | Cart gRPC readiness response; not wired to ACA's TCP probe |
| `imageSlowLoad` | Delay image delivery |
| `intlShippingSlowdown` | Delay international shipping |
| `kafkaQueueProblems` | Queue overload and delayed consumer processing; Kafka retained |
| `loadGeneratorFloodHomepage` | Increased homepage requests from load generator |
| `paymentFailure` | Probabilistic payment errors; upstream `90%` variant is numerically 0.95 |
| `paymentUnreachable` | Simulate an unavailable payment service |
| `productCatalogFailure` | Product-targeted errors; upstream targeting branches are both `off` |
| `productCatalogLockContention` | PostgreSQL catalog lock contention; PostgreSQL retained |
| `recommendationCacheFailure` | Recommendation cache failure |

The upstream quirks noted above are intentionally unchanged. A future scenario
increment must explicitly approve activation, observation window, reset and
expected probe/telemetry effects. CPU/memory fault behavior is not assumed to
match the lower Compose memory limits.

For a later CI deployment, prefer repo/branch-scoped GitHub OIDC and a narrowly
scoped deployment identity. Do not store Azure credentials in GitHub. PR text
requires the repository's human verbatim approval; that is independent of local
CLI deployment and verification.
