# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Prepare a disabled, expiring native routing test using real application metrics."""

import argparse
import datetime
import json
from pathlib import Path

from alert_setup import documents as alert_documents
from artifacts import private_path
from sre_setup import documents as sre_documents, request_plan


def documents(subscription, group, prefix, location, workspace_customer_id, repository_url,
              branch, expires_at, *, now=None, agent_name="astronomy-shop-investigator",
              test_id="astronomy-shop-routing-test"):
    now = now or datetime.datetime.now(datetime.timezone.utc)
    expiry = datetime.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    if expiry.tzinfo is None or not datetime.timedelta(0) < expiry - now <= datetime.timedelta(minutes=30):
        raise ValueError("Expiry must include a timezone and be within the next 30 minutes.")
    expiry_text = expiry.astimezone(datetime.timezone.utc).isoformat()
    title = "Astronomy Shop - TEST routing " + expiry.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    config = sre_documents(subscription, group, prefix, workspace_customer_id, repository_url,
                           branch, agent_name=agent_name, filter_id=test_id)
    rule = config["filter.json"]
    rule.update(Name=title, TitleContains=title, TitleNotContains=[])
    handler = config["handler.json"]
    handler["name"] = title
    handler["incidentProcessingGuide"].insert(
        0, f"Synthetic routing test only, expires {expiry_text}. Confirm its actual metric condition "
        "and stop. No outage, customer impact or deployment cause is implied."
    )
    alert = alert_documents(subscription, group, prefix, location)["request-failures.json"]
    alert["tags"]["expiresUtc"] = expiry_text
    alert["properties"].update(
        displayName=title,
        description="Synthetic routing only: actual ad metrics exist. Not an outage test. "
                    f"Disable rule and test filter after verification; expires {expiry_text}.",
    )
    alert["properties"]["criteria"]["allOf"][0]["query"] = (
        "AppMetrics | where TimeGenerated > ago(5m)"
        f" | where now() < datetime({expiry_text})"
        " | where AppRoleName == 'opentelemetry-demo.ad'"
    )
    plan = request_plan({"filter.json": rule, "handler.json": handler})
    for request in plan:
        request["file"] = "test-" + request["file"]
    return {"test-filter.json": rule, "test-handler.json": handler,
            "test-alert.json": alert, "test-requests.json": plan}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for flag in ("subscription", "resource-group", "location", "workspace-customer-id",
                 "repository-url", "branch", "expires-at"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--prefix", default="astronomy-demo")
    parser.add_argument("--agent-name", default="astronomy-shop-investigator")
    parser.add_argument("--test-id", default="astronomy-shop-routing-test")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = private_path(args.output)
    config = documents(args.subscription, args.resource_group, args.prefix, args.location,
                       args.workspace_customer_id, args.repository_url, args.branch, args.expires_at,
                       agent_name=args.agent_name, test_id=args.test_id)
    output.mkdir(parents=True, exist_ok=True)
    for name, document in config.items():
        (output / name).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print("Generated disabled expiring routing test; no cloud writes or fault activation.")
