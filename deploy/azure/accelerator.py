# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Local-only accelerator: delegate deterministic generators, never deploy or grant access."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit
import uuid

from artifacts import ROOT, private_path


HERE = Path(__file__).resolve().parent
FIELDS = {
    "application": {"subscriptionId", "resourceGroup", "location", "prefix", "deploymentId"},
    "source": {"repositoryUrl", "branch"},
    "sre": {"mode", "subscriptionId", "resourceGroup", "agentName", "endpoint"},
}


def value(section, key):
    result = section.get(key)
    if not isinstance(result, str) or not result.strip() or "YOUR_" in result or "<" in result:
        raise ValueError(f"Configure a nonempty, non-placeholder value for {key}.")
    return result


def https_url(text):
    url = urlsplit(text)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Use a credential-free HTTPS URL without a query or fragment.")
    return text


def commands(settings, phase, workspace_customer_id=None):
    if not isinstance(settings, dict) or set(settings) != {"privateDirectory", *FIELDS}:
        raise ValueError("Configuration must contain only privateDirectory, application, source and sre.")
    for name, keys in FIELDS.items():
        if not isinstance(settings[name], dict) or set(settings[name]) != keys:
            raise ValueError(f"Unexpected or missing configuration fields in {name}.")
    output = private_path(value(settings, "privateDirectory"))
    if not Path(settings["privateDirectory"]).is_absolute():
        raise ValueError("privateDirectory must be an absolute local path outside the repository.")
    app, source, sre = settings["application"], settings["source"], settings["sre"]
    for section in (app, source):
        for key in section:
            value(section, key)
    uuid.UUID(app["subscriptionId"])
    https_url(source["repositoryUrl"])
    if sre["mode"] not in {"reuse-existing", "provision-new-guided"}:
        raise ValueError("SRE mode must be reuse-existing or provision-new-guided.")
    if phase == "prepare":
        return [[sys.executable, str(HERE / "prepare.py"), "--output",
                 str(output / "baseline.parameters.json"), "--prefix", app["prefix"],
                 "--location", app["location"], "--deployment-id", app["deploymentId"]]]
    if phase != "sre-config":
        raise ValueError("Only local prepare and sre-config phases are supported.")
    if not workspace_customer_id:
        raise ValueError("sre-config requires the actual deployed workspace customer ID.")
    uuid.UUID(workspace_customer_id)
    for key in sre:
        value(sre, key)
    uuid.UUID(sre["subscriptionId"])
    https_url(sre["endpoint"])
    shared = ["--subscription", app["subscriptionId"], "--resource-group", app["resourceGroup"],
              "--prefix", app["prefix"], "--output", str(output / "sre")]
    return [
        [sys.executable, str(HERE / "sre_setup.py"), *shared,
         "--workspace-customer-id", workspace_customer_id,
         "--repository-url", source["repositoryUrl"], "--branch", source["branch"]],
        [sys.executable, str(HERE / "alert_setup.py"), *shared, "--location", app["location"]],
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--phase", choices=("prepare", "sre-config"), default="prepare")
    parser.add_argument("--workspace-customer-id")
    args = parser.parse_args()
    settings = json.loads(private_path(args.config).read_text(encoding="utf-8-sig"))
    for command in commands(settings, args.phase, args.workspace_customer_id):
        subprocess.run(command, cwd=ROOT, check=True)
    if args.phase == "sre-config":
        output = private_path(settings["privateDirectory"]) / "sre"
        (output / "operator-targets.json").write_text(
            json.dumps({"application": settings["application"], "sre": settings["sre"]}, indent=2),
            encoding="utf-8",
        )
    print("Local preparation complete. No Azure deployment, SRE provisioning, permissions or alerts changed.")
    if settings["sre"]["mode"] == "provision-new-guided":
        print("New-agent onboarding requires the official portal/admin approval path; it is not automated here.")


if __name__ == "__main__":
    main()
