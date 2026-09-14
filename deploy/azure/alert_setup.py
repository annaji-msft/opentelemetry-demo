# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Generate disabled native Azure Monitor alerts; never applies cloud changes."""

import argparse
import json
from pathlib import Path


CORE_ROLES = tuple("opentelemetry-demo." + name for name in (
    "frontend", "checkout", "cart", "payment", "shipping", "product-catalog",
    "currency", "recommendation", "ad", "quote",
))
ROLE_FILTER = "AppRoleName in (" + ", ".join(repr(role) for role in CORE_ROLES) + ")"
FAILURE_QUERY = (
    "AppRequests | where TimeGenerated > ago(5m) | where " + ROLE_FILTER
    + " | summarize Requests=count(), FailedRequests=countif(Success == false) by AppRoleName"
    " | extend FailureRate=100.0 * FailedRequests / Requests"
    " | where FailedRequests >= 3 and FailureRate >= 20.0"
)
GAP_QUERY = (
    "AppRequests | where TimeGenerated > ago(10m) | where " + ROLE_FILTER
    + " | summarize Requests=count() | where Requests == 0"
)


def documents(subscription, group, prefix, location):
    workspace = (
        f"/subscriptions/{subscription}/resourceGroups/{group}/providers/"
        f"Microsoft.OperationalInsights/workspaces/{prefix}-logs"
    )
    result = {}
    for name, title, description, window, query in (
        ("request-failures", "application request failures",
         "At least 3 observed failed requests and at least 20 percent failure rate per core "
         "service over 5 minutes. Counts are observed records, not unsampled traffic estimates.",
         "PT5M", FAILURE_QUERY),
        ("telemetry-gap", "application telemetry gap",
         "No core request spans for 10 minutes. Assumes load generator is running. "
         "An observability or traffic gap, NOT proof of an application outage.",
         "PT10M", GAP_QUERY),
    ):
        result[name + ".json"] = {
            "location": location, "kind": "LogAlert",
            "tags": {"application": prefix, "purpose": "sre-application-monitoring"},
            "properties": {
                "displayName": "Astronomy Shop - " + title,
                "description": description + " Investigation only; no notification action groups.",
                "severity": 2, "enabled": False, "scopes": [workspace],
                "evaluationFrequency": "PT1M", "windowSize": window,
                "criteria": {"allOf": [{
                    "query": query, "timeAggregation": "Count", "operator": "GreaterThan",
                    "threshold": 0,
                    "failingPeriods": {"numberOfEvaluationPeriods": 1, "minFailingPeriodsToAlert": 1},
                }]},
                "autoMitigate": True, "skipQueryValidation": False,
                "actions": {"actionGroups": []},
            },
        }
    return result


def threshold_test_query():
    """Exercise the actual failure predicate with query-local data, never ingestion."""
    pipeline = FAILURE_QUERY.removeprefix("AppRequests").replace(
        "by AppRoleName", "by Case, AppRoleName"
    )
    return """
let Cases = datatable(Case:string, Total:long, Failed:long, Age:timespan,
                     AppRoleName:string, Unknown:bool, Expected:bool)
[
 'exact',15,3,1m,'opentelemetry-demo.cart',false,true,
 'above',10,4,1m,'opentelemetry-demo.payment',false,true,
 'below-count',2,2,1m,'opentelemetry-demo.cart',false,false,
 'below-rate',16,3,1m,'opentelemetry-demo.cart',false,false,
 'healthy',10,0,1m,'opentelemetry-demo.cart',false,false,
 'wrong-role',10,10,1m,'unrelated',false,false,
 'self-telemetry',10,10,1m,'opentelemetry-demo.otel-collector',false,false,
 'unknown',10,10,1m,'opentelemetry-demo.cart',true,false,
 'expired',10,10,6m,'opentelemetry-demo.cart',false,false
];
let Matched = Cases
| mv-expand Index=range(1, Total, 1) to typeof(long)
| extend TimeGenerated=now()-Age, Success=iff(Unknown, bool(null), Index > Failed)
""" + pipeline + """
| project Case, Actual=true;
Cases | join kind=leftouter Matched on Case
| extend Actual=coalesce(Actual, false)
| project Case, Expected, Actual, Passed=Expected == Actual
"""


def gap_test_query():
    cases = (
        ("empty", True), ("stale", True), ("self-only", True),
        ("unattributed", True), ("recent-checkout", False),
    )
    pipeline = GAP_QUERY.removeprefix("AppRequests")
    branches = [
        "(Cases | where Case == '" + name + "'" + pipeline
        + " | summarize Matched=count() | extend Case='" + name
        + "', Expected=" + str(expected).lower()
        + " | extend Actual=Matched > 0 | project Case, Expected, Actual, Passed=Expected == Actual)"
        for name, expected in cases
    ]
    return """
let Cases = datatable(Case:string, Age:timespan, AppRoleName:string)
[
 'stale',11m,'opentelemetry-demo.checkout',
 'self-only',1m,'opentelemetry-demo.otel-collector',
 'unattributed',1m,'',
 'recent-checkout',1m,'opentelemetry-demo.checkout'
] | extend TimeGenerated=now()-Age;
union
""" + ",\n".join(branches)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--prefix", default="astronomy-demo")
    parser.add_argument("--location", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, document in documents(
        args.subscription, args.resource_group, args.prefix, args.location
    ).items():
        (args.output / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (args.output / "threshold-tests.kql").write_text(threshold_test_query(), encoding="utf-8")
    (args.output / "gap-tests.kql").write_text(gap_test_query(), encoding="utf-8")
    print("Generated two disabled alert documents and query-local predicate tests; no cloud writes.")
