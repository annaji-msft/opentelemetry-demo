# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Check actual replica containers, not just successful ARM provisioning."""

import argparse
import concurrent.futures
import json
import shutil
import subprocess
import time
from pathlib import Path


def azure(arguments):
    result = subprocess.run([shutil.which("az"), *arguments, "--output", "json", "--only-show-errors"],
                            capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def verify(subscription, group, parameter_file, timeout):
    parameters = json.loads(parameter_file.read_text(encoding="utf-8-sig"))["parameters"]
    expected = {
        app["name"]: {
            "revision": f"{app['name']}--{app['template']['revisionSuffix']}",
            "containers": {c["name"] for c in app["template"]["containers"]},
        } for app in parameters["apps"]["value"]["services"]
    }
    scope = ["--subscription", subscription, "--resource-group", group]
    deadline = time.monotonic() + timeout

    def inspect(item):
        name, spec = item
        containers = azure([
            "containerapp", "replica", "list", *scope, "--name", name, "--revision", spec["revision"],
            "--query", "[].properties.containers[].{name:name,ready:ready,state:runningState}",
        ])
        actual = {c["name"] for c in containers if c["ready"] and c["state"] == "Running"}
        return name, actual == spec["containers"]

    while True:
        deployed = azure(["containerapp", "list", *scope,
                          "--query", "[].[name,properties.latestReadyRevisionName]"])
        ready = dict(deployed)
        pending = [name for name, spec in expected.items() if ready.get(name) != spec["revision"]]
        candidates = [(name, spec) for name, spec in expected.items() if name not in pending]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            pending.extend(name for name, running in pool.map(inspect, candidates) if not running)
        if not pending:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Expected revisions not ready: {pending}")
        print(f"Waiting for expected revisions: {', '.join(pending)}", flush=True)
        time.sleep(30)

    return [{"app": name, "revision": spec["revision"], "containers": sorted(spec["containers"])}
            for name, spec in expected.items()]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    print(json.dumps(verify(args.subscription, args.resource_group, args.parameters, args.timeout), indent=2))
