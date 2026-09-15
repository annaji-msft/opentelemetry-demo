# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Require real recent application signals and the smoke checkout's distributed trace."""

import argparse
import json
import time

from azure_cli import run


def preflight(subscription, group, workspace_name, workspace):
    result = run([
        "monitor", "log-analytics", "workspace", "show",
        "--subscription", subscription, "--resource-group", group,
        "--workspace-name", workspace_name,
        "--query", "{customerId:customerId,capping:workspaceCapping}",
        "--output", "json", "--only-show-errors",
    ], capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError(result.stderr)
    settings = json.loads(result.stdout)
    if str(settings.get("customerId", "")).lower() != workspace.lower():
        raise RuntimeError("Workspace customer ID does not match the inspected resource; abort the exercise.")
    capping = settings.get("capping") or {}
    print(json.dumps({"workspaceCapping": capping}), flush=True)
    if capping.get("dataIngestionStatus") != "RespectQuota":
        raise RuntimeError(
            f"Ingestion is blocked or unknown; abort the exercise. Cap/status/reset: {capping}. "
            "Wait for reset and reverify, or obtain explicit budget approval; never auto-raise the cap."
        )
    rows = query(subscription, workspace, """
union withsource=Signal AppRequests, AppDependencies, AppTraces, AppMetrics
| where TimeGenerated > ago(5m) and TimeGenerated <= now()
| where AppRoleName startswith 'opentelemetry-demo.'
| where AppRoleName !contains 'otelcol' and AppRoleName !endswith '.otel-collector'
| summarize Records=count(), Latest=max(TimeGenerated) by Signal
""")
    fresh = {row["Signal"] for row in rows if int(row["Records"]) > 0}
    if not {"AppRequests", "AppDependencies", "AppTraces", "AppMetrics"} <= fresh:
        raise RuntimeError(f"Missing/stale application telemetry within five minutes; abort the exercise: {rows}")
    return {"workspaceCapping": capping, "freshSignals": rows,
            "limitation": "Read-only preflight passed; this does not prove managed alert evaluation or routing."}


def query(subscription, workspace, kql):
    result = run([
        "monitor", "log-analytics", "query",
        "--subscription", subscription, "--workspace", workspace,
        "--analytics-query", kql, "--output", "json", "--only-show-errors",
    ], capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def verify(subscription, workspace, trace_id, since, timeout):
    if len(trace_id) != 32 or any(c not in "0123456789abcdef" for c in trace_id):
        raise ValueError("Trace ID must be 32 lowercase hex characters")
    signal_query = f"""
union withsource=Signal AppRequests, AppDependencies, AppTraces, AppMetrics
| where TimeGenerated >= datetime({since})
| where AppRoleName startswith 'opentelemetry-demo.'
| where AppRoleName !contains 'otelcol' and AppRoleName !endswith '.otel-collector'
| summarize Records=count(), Latest=max(TimeGenerated) by Signal, AppRoleName
"""
    trace_query = f"""
union withsource=Signal AppRequests, AppDependencies
| where TimeGenerated >= datetime({since}) and OperationId == '{trace_id}'
| summarize Records=count(), Failures=countif(Success == false),
    Latest=max(TimeGenerated) by Signal, AppRoleName, AppRoleInstance, AppVersion,
    Deployment=tostring(Properties['deployment.id']),
    SourceRevision=tostring(Properties['vcs.ref.head.revision'])
"""
    deadline = time.monotonic() + timeout
    while True:
        signals = query(subscription, workspace, signal_query)
        trace = query(subscription, workspace, trace_query)
        tables = {r["Signal"] for r in signals}
        roles = {r["AppRoleName"] for r in trace}
        if {"AppRequests", "AppDependencies", "AppTraces", "AppMetrics"} <= tables and {
            "opentelemetry-demo.frontend", "opentelemetry-demo.checkout",
            "opentelemetry-demo.payment", "opentelemetry-demo.cart",
        } <= roles:
            if any(int(r["Failures"]) for r in trace):
                raise RuntimeError(f"Smoke trace contains failed spans: {trace}")
            for row in trace:
                service = row["AppRoleName"].removeprefix("opentelemetry-demo.")
                if service in {"frontend", "checkout", "payment", "cart"} and (
                    not row["AppRoleInstance"] or row["AppRoleInstance"].startswith("otel-collector-")
                    or not row["Deployment"] or not row["SourceRevision"] or not row["AppVersion"]
                ):
                    raise RuntimeError(f"Smoke trace has missing or overwritten service metadata: {row}")
            return {"signals": signals, "trace": trace, "traceId": trace_id}
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Missing application telemetry after bounded wait. Signals={signals}; trace={trace}")
        print("Waiting for application telemetry ingestion...", flush=True)
        time.sleep(20)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--trace-id")
    parser.add_argument("--since")
    parser.add_argument("--preflight", action="store_true", help="Read ingestion cap and current signal freshness only")
    parser.add_argument("--resource-group")
    parser.add_argument("--workspace-name")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.preflight:
        if not args.resource_group or not args.workspace_name:
            parser.error("--preflight requires --resource-group and --workspace-name")
        print(json.dumps(preflight(args.subscription, args.resource_group, args.workspace_name, args.workspace), indent=2))
    else:
        if not args.trace_id or not args.since:
            parser.error("Trace verification requires --trace-id and --since")
        print(json.dumps(verify(args.subscription, args.workspace, args.trace_id, args.since, args.timeout), indent=2))
