# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Require real recent application signals and the smoke checkout's distributed trace."""

import argparse
import json
import shutil
import subprocess
import time


def query(subscription, workspace, kql):
    # Windows az.cmd does not reliably forward multiline argument values.
    kql = " ".join(kql.splitlines()).strip()
    result = subprocess.run([
        shutil.which("az"), "monitor", "log-analytics", "query",
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
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    print(json.dumps(verify(args.subscription, args.workspace, args.trace_id, args.since, args.timeout), indent=2))
