# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Translate this checkout's full Compose model, not a hand-maintained service subset."""

import argparse
import copy
import hashlib
import json
import math
import re
import secrets
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
# Compose substitutions in .env and environment entries, not collector ${env:...}.
VARIABLE = re.compile(r"\$\{([A-Z_][A-Z_0-9]*)\}")


def substitute(value, environment):
    for _ in range(20):
        result = VARIABLE.sub(lambda m: environment[m[1]], value)
        if result == value:
            return result
        value = result
    raise ValueError("Recursive environment substitution")


def model():
    environment = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            environment[key] = value.split("    #", 1)[0]
    environment = {k: substitute(v, environment) for k, v in environment.items()}
    services = {}
    for filename in ("compose.yaml", "compose.full.yaml", "compose.observability.yaml"):
        layer = yaml.safe_load((ROOT / filename).read_text())["services"]
        for name, service in layer.items():
            existing = services.setdefault(name, {})
            for key, value in service.items():
                if key == "environment":
                    env = existing.setdefault(key, {})
                    for item in value:
                        k, _, v = item.partition("=")
                        if "=" not in item and k not in environment:
                            if k == "_JAVA_OPTIONS":
                                continue
                            raise ValueError(f"Unresolved Compose environment variable: {k}")
                        env[k] = substitute(v if "=" in item else environment[k], environment)
                elif key == "depends_on":
                    existing.setdefault(key, {}).update(value)
                else:
                    existing[key] = value
    for service in services.values():
        service["image"] = substitute(service["image"], environment)
    return services, environment


def yaml_text(value):
    return yaml.safe_dump(value, sort_keys=False)


def collector_config():
    config = yaml.safe_load((ROOT / "src/otel-collector/otelcol-config.yml").read_text())
    full = yaml.safe_load((ROOT / "src/otel-collector/otelcol-config-full.yml").read_text())
    observability = yaml.safe_load(
        (ROOT / "src/otel-collector/otelcol-config-observability.yml").read_text()
    )
    for name in ("docker_stats", "host_metrics"):
        del config["receivers"][name]
    config["receivers"].update(full["receivers"])
    config["receivers"]["otlp"]["protocols"]["grpc"]["endpoint"] = "0.0.0.0:4317"
    config["receivers"]["otlp"]["protocols"]["http"]["endpoint"] = "0.0.0.0:4318"
    config["receivers"]["http_check/frontend-proxy"]["targets"][0]["endpoint"] = "https://${env:FRONTEND_PROXY_ADDR}"
    config["processors"]["resource_detection"] = {"detectors": ["env"], "override": False}
    config["processors"]["batch"] = {}
    config["exporters"] = {
        k: v for k, v in observability["exporters"].items() if k != "otlp_grpc/firepit"
    }
    config["exporters"]["azure_monitor"] = {
        "spaneventsenabled": True,
        "sending_queue": {"enabled": True, "queue_size": 256},
    }
    # OpAMP effective-config reporting could disclose the resolved connection string.
    config["extensions"] = {"health_check": {"endpoint": "0.0.0.0:13133"}}
    config["service"]["extensions"] = ["health_check"]
    pipelines = config["service"]["pipelines"]
    del pipelines["profiles"]
    pipelines["metrics"]["receivers"] = list(config["receivers"]) + ["span_metrics"]
    for signal, exporters in {
        "traces": ["otlp_grpc/jaeger", "span_metrics", "azure_monitor"],
        "metrics": ["otlp_http/prometheus", "azure_monitor"],
        "logs": ["azure_monitor"],
    }.items():
        pipelines[signal]["exporters"] = exporters
        pipelines[signal]["processors"].append("batch")
    # Encode literal percent signs before dots so flat keys remain distinct, not object paths.
    config["processors"]["transform/opensearch_keys"] = {
        "error_mode": "propagate",
        "log_statements": [{"context": "log", "statements": [
            'replace_all_patterns(attributes, "key", "%", "%25")',
            'replace_all_patterns(attributes, "key", "[.]", "%2E")',
        ]}],
    }
    pipelines["logs/opensearch"] = copy.deepcopy(pipelines["logs"])
    pipelines["logs/opensearch"]["exporters"] = ["opensearch"]
    pipelines["logs/opensearch"]["processors"].insert(-1, "transform/opensearch_keys")
    config["exporters"]["opensearch"]["logs_index"] = "otel-logs-aca"
    return yaml_text(config)


def proxy_config():
    config = yaml.safe_load((ROOT / "src/frontend-proxy/envoy.tmpl.yaml").read_text())
    manager = config["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0]["typed_config"]
    routes = manager["route_config"]["virtual_hosts"][0]["routes"]
    retained = []
    for route in routes:
        cluster = route.get("route", {}).get("cluster")
        if cluster in ("frontend", "image-provider"):
            retained.append(route)
    # Reject control/backend paths before the shop catch-all, including encoded paths.
    blocked = [
        "/loadgen", "/otlp-http", "/jaeger", "/grafana", "/opamp", "/feature",
        "/flagservice", "/profiles", "/chatbot", "/telemetry",
    ]
    manager["route_config"]["virtual_hosts"][0]["routes"] = [
        {"match": {"prefix": path}, "direct_response": {"status": 404}}
        for path in blocked
    ] + retained
    manager["normalize_path"] = True
    manager["merge_slashes"] = True
    manager["path_with_escaped_slashes_action"] = "REJECT_REQUEST"
    manager["http_filters"] = [
        f for f in manager["http_filters"] if f["name"] != "envoy.filters.http.fault"
    ]
    config["admin"]["address"]["socket_address"]["address"] = "127.0.0.1"
    return yaml_text(config)


PORTS = {
    "ad": [9555, 9465], "cart": [7070], "checkout": [5050], "currency": [7001],
    "email": [6060], "frontend": [8080], "frontend-proxy": [8080],
    "image-provider": [8081], "load-generator": [8089], "payment": [50051],
    "product-catalog": [3550], "quote": [8090], "recommendation": [9001],
    "shipping": [50050], "flagd": [8013, 8015, 8016, 4000], "astronomy-db": [5432],
    "valkey-cart": [6379], "otel-collector": [4317, 4318],
    "kafka": [9092], "jaeger": [4317, 16686], "grafana": [3000],
    "prometheus": [9090], "opensearch": [9200], "opamp-server": [4320, 4321],
    "accounting": [], "fraud-detection": [],
}


def prepare(lock, revision, deployment_id, passwords=None):
    services, defaults = model()
    if set(services) != set(PORTS) | {"flagd-ui", "telemetry-docs"}:
        raise ValueError("Upstream service inventory changed; review the ACA mapping")
    # Telemetry docs has its own service; flagd-ui shares a replica and writable flags.
    ports_by_service = dict(PORTS, **{"telemetry-docs": [8000]})
    if passwords is None:
        passwords = {k: secrets.token_hex(32) for k in ("postgres", "astronomy", "monitoring", "flag-ui")}
    attributes = (
        f"service.namespace=opentelemetry-demo,service.version={defaults['IMAGE_VERSION']},"
        "deployment.environment.name=aca-hackathon"
    )
    result = []
    for name, service in services.items():
        if name == "flagd-ui":
            continue
        if service["image"] not in lock["images"]:
            raise ValueError(f"Missing image lock for {name}")
        container = {
            "name": name, "image": lock["images"][service["image"]]["image"],
            "env": [], "resources": {},
        }
        memory_text = service["deploy"]["resources"]["limits"]["memory"]
        mib = float(memory_text[:-1]) * (1024 if memory_text.endswith("G") else 1)
        cpu = max(0.25, math.ceil(mib / 2048 * 4) / 4)
        container["resources"] = {"cpu": cpu, "memory": f"{cpu * 2:g}Gi"}
        env = copy.deepcopy(service.get("environment", {}))
        env.update(ENV_PLATFORM="azure", OTEL_RESOURCE_ATTRIBUTES=attributes)
        # Keep upstream criticality, replacing only its original namespace/version.
        original = service.get("environment", {}).get("OTEL_RESOURCE_ATTRIBUTES", "")
        if "service.criticality=" in original:
            env["OTEL_RESOURCE_ATTRIBUTES"] += "," + original.split(",")[-1]
        env["OTEL_RESOURCE_ATTRIBUTES"] += (
            f",vcs.ref.head.revision={revision},deployment.id={deployment_id},"
            f"service.instance.id={name}-{deployment_id}"
        )
        env["OTEL_SERVICE_NAME"] = name
        env["FLAGD_UI_HOST"] = "flagd"
        env["GOMEMLIMIT"] = f"{int(cpu * 2048 * .75)}MiB"
        # Browser telemetry is available to in-environment synthetic browsers only.
        if name == "frontend":
            env["PUBLIC_OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = "http://otel-collector:4318/v1/traces"
        if name == "load-generator":
            env["LOCUST_HOST"] = "https://frontend-proxy.__ACA_DOMAIN__"
        if name == "otel-collector":
            env["FRONTEND_PROXY_ADDR"] = "frontend-proxy.__ACA_DOMAIN__:443"
        if name == "kafka":
            env["KAFKA_LISTENERS"] = "PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093"
            env["KAFKA_CONTROLLER_QUORUM_VOTERS"] = "1@localhost:9093"
            env["KAFKA_LOG_RETENTION_HOURS"] = "1"
            env["KAFKA_LOG_RETENTION_BYTES"] = "268435456"
        if name == "jaeger":
            env["JAEGER_HOST"] = "0.0.0.0"
        if name == "opensearch":
            env["node.store.allow_mmap"] = "false"
        if name == "otel-collector":
            env["OTEL_RESOURCE_ATTRIBUTES"] = ",".join(
                attribute for attribute in env["OTEL_RESOURCE_ATTRIBUTES"].split(",")
                if not attribute.startswith("service.instance.id=")
            )
            env["OTEL_COLLECTOR_HOST"] = "0.0.0.0"
            env["APPLICATIONINSIGHTS_CONNECTION_STRING"] = {"secretRef": "app-insights"}
            env["POSTGRES_MONITORING_PASSWORD"] = {"secretRef": "monitoring-password"}
        if name == "astronomy-db":
            env["POSTGRES_PASSWORD"] = {"secretRef": "postgres-password"}
            env["POSTGRES_ASTRONOMY_PASSWORD"] = {"secretRef": "astronomy-password"}
            env["POSTGRES_MONITORING_PASSWORD"] = {"secretRef": "monitoring-password"}
        if name in ("accounting", "product-catalog"):
            env["DB_CONNECTION_STRING"] = {"secretRef": "database-url"}
        app = {
            "name": name, "secrets": [],
            "ingress": None,
            "template": {
                "revisionSuffix": deployment_id, "containers": [container],
                "scale": {"minReplicas": 1, "maxReplicas": 1},
                "volumes": [],
            },
        }
        for key, value in env.items():
            container["env"].append(
                {"name": key, **value} if isinstance(value, dict) else {"name": key, "value": value}
            )
        for kind in ("postgres", "astronomy", "monitoring"):
            if any(e.get("secretRef") == f"{kind}-password" for e in container["env"]):
                app["secrets"].append({"name": f"{kind}-password", "value": passwords[kind]})
        if name in ("accounting", "product-catalog"):
            value = (
                f"Host=astronomy-db;Username=astronomy_user;Password={passwords['astronomy']};Database=astronomy_db"
                if name == "accounting" else
                f"postgres://astronomy_user:{passwords['astronomy']}@astronomy-db/astronomy_db?sslmode=disable"
            )
            app["secrets"].append({"name": "database-url", "value": value})

        def mount(text, target):
            ident = "config-" + hashlib.sha256(target.encode()).hexdigest()[:12]
            filename = target.rsplit("/", 1)[-1]
            app["secrets"].append({"name": ident, "value": text})
            app["template"]["volumes"].append({
                "name": ident, "storageType": "Secret",
                "secrets": [{"secretRef": ident, "path": filename}],
            })
            container.setdefault("volumeMounts", []).append({
                "volumeName": ident, "mountPath": target, "subPath": filename,
            })

        if "command" in service:
            command = service["command"]
            if isinstance(command, str):
                import shlex
                command = shlex.split(command)
            container["args"] = command
        if name == "otel-collector":
            container["args"] = ["--config=/etc/aca/collector.yaml"]
            mount(collector_config(), "/etc/aca/collector.yaml")
        elif name == "frontend-proxy":
            mount(proxy_config(), "/home/envoy/envoy.tmpl.yaml")
        elif name == "flagd":
            flags = (ROOT / "src/flagd/demo.flagd.json").read_text()
            if any(f["defaultVariant"] != "off" for f in json.loads(flags)["flags"].values()):
                raise ValueError("Fault defaults must all be off")
            mount(flags, "/seed/demo.flagd.json")
            app["template"]["volumes"].append({"name": "flags", "storageType": "EmptyDir"})
            container.setdefault("volumeMounts", []).append({"volumeName": "flags", "mountPath": "/etc/flagd"})
            app["template"]["initContainers"] = [{
                "name": "seed-flags", "image": lock["images"]["busybox:1.37.0"]["image"],
                "command": ["sh", "-ec", "cp /seed/demo.flagd.json /flags/demo.flagd.json; chmod 666 /flags/demo.flagd.json"],
                "resources": {"cpu": 0.25, "memory": "0.5Gi"},
                "volumeMounts": [
                    {**container["volumeMounts"][0]},
                    {"volumeName": "flags", "mountPath": "/flags"},
                ],
            }]
            ui = services["flagd-ui"]
            ui_env = dict(ui["environment"])
            ui_env["OTEL_RESOURCE_ATTRIBUTES"] = (
                f"{attributes},vcs.ref.head.revision={revision},deployment.id={deployment_id},"
                f"service.instance.id=flagd-ui-{deployment_id}"
            )
            ui_env.pop("SECRET_KEY_BASE")
            app["secrets"].append({"name": "flag-ui-key", "value": passwords["flag-ui"]})
            app["template"]["containers"].append({
                "name": "flagd-ui", "image": lock["images"][ui["image"]]["image"],
                "resources": {"cpu": 0.25, "memory": "0.5Gi"},
                "env": [{"name": k, "value": v} for k, v in ui_env.items()] + [
                    {"name": "SECRET_KEY_BASE", "secretRef": "flag-ui-key"}
                ],
                "volumeMounts": [{"volumeName": "flags", "mountPath": "/app/data"}],
                "probes": probes(4000),
            })
        else:
            for volume in service.get("volumes", []):
                source, target = volume.split(":", 1)
                source = substitute(source, defaults)
                source_path = ROOT / source
                target = target.removesuffix(":ro")
                files = list(source_path.rglob("*")) if source_path.is_dir() else [source_path]
                for file in files:
                    if not file.is_file():
                        continue
                    destination = target.rstrip("/") + "/" + file.relative_to(source_path).as_posix() if source_path.is_dir() else target
                    text = file.read_text(encoding="utf-8")
                    if name == "astronomy-db":
                        text = (
                            "\\getenv astronomy_password POSTGRES_ASTRONOMY_PASSWORD\n"
                            "\\getenv monitoring_password POSTGRES_MONITORING_PASSWORD\n"
                        ) + text.replace("'astronomy_password'", ":'astronomy_password'").replace(
                            "'monitoring_password'", ":'monitoring_password'"
                        )
                    mount(text, destination)
        ports = ports_by_service[name]
        if ports:
            app["ingress"] = {
                "external": name == "frontend-proxy", "targetPort": ports[0],
                "transport": "auto" if name == "frontend-proxy" else "tcp",
            }
            if name == "frontend-proxy":
                app["ingress"]["allowInsecure"] = False
            else:
                app["ingress"]["exposedPort"] = ports[0]
            if len(ports) > 1:
                app["ingress"]["additionalPortMappings"] = [
                    {"external": False, "targetPort": port, "exposedPort": port} for port in ports[1:]
                ]
            container["probes"] = probes(13133 if name == "otel-collector" else ports[0])
        result.append(app)
    # Internal TCP uses ACA service discovery, not the shared HTTP ingress FQDN.
    hostnames = {name: name for name in ports_by_service}
    hostnames["otel-collector"] = "telemetry-gateway"
    hostnames["frontend-proxy"] = "frontend-proxy.__ACA_DOMAIN__"
    # Match service hosts followed by a numeric port, never YAML keys or attributes.
    host_port = re.compile(r"(?<![A-Za-z0-9_.-])(" + "|".join(map(re.escape, hostnames)) + r")(?=:\d)")
    for app in result:
        if app["name"] == "otel-collector":
            app["name"] = "telemetry-gateway"
        for secret in app["secrets"]:
            secret["value"] = host_port.sub(lambda m: hostnames[m[1]], secret["value"])
            if secret["name"] == "database-url":
                secret["value"] = secret["value"].replace("Host=astronomy-db;", f"Host={hostnames['astronomy-db']};")
                secret["value"] = secret["value"].replace("@astronomy-db/", f"@{hostnames['astronomy-db']}/")
            secret["resolveDomain"] = "__ACA_DOMAIN__" in secret["value"]
        for container in app["template"]["containers"]:
            for item in container["env"]:
                if "value" not in item:
                    continue
                value = host_port.sub(lambda m: hostnames[m[1]], item["value"])
                if item["name"].endswith(("_HOST", "_ADDR")) and value in hostnames:
                    value = hostnames[value]
                item["value"] = value
        source_name = "otel-collector" if app["name"] == "telemetry-gateway" else app["name"]
        dependencies = services[source_name].get("depends_on", {})
        if source_name == "otel-collector":
            dependencies = {}
        app["dependencies"] = []
        for dependency in dependencies:
            dependency = "flagd" if dependency == "flagd-ui" else dependency
            if dependency == app["name"]:
                continue
            app["dependencies"].append("telemetry-gateway" if dependency == "otel-collector" else dependency)
    pending = {app["name"]: app for app in result}
    ordered = []
    while pending:
        ready = [
            name for name in pending
            if not {
                "flagd" if d == "flagd-ui" else "telemetry-gateway" if d == "otel-collector" else d
                for d in services["otel-collector" if name == "telemetry-gateway" else name].get("depends_on", {})
            }.intersection(pending)
        ]
        if not ready:
            raise ValueError(f"Cyclic deployment dependencies: {list(pending)}")
        for name in ready:
            ordered.append(pending.pop(name))
    return ordered


def probes(port):
    return [
        {"type": "Startup", "tcpSocket": {"port": port}, "periodSeconds": 10, "failureThreshold": 60},
        {"type": "Readiness", "tcpSocket": {"port": port}, "periodSeconds": 10, "failureThreshold": 3},
        {"type": "Liveness", "tcpSocket": {"port": port}, "periodSeconds": 30, "failureThreshold": 6},
    ]


def config_digest():
    files = {
        ROOT / ".env", ROOT / "otel-config.yml",
        ROOT / "compose.yaml", ROOT / "compose.full.yaml", ROOT / "compose.observability.yaml",
        HERE / "prepare.py", HERE / "main.bicep", HERE / "service.bicep", HERE / "images.lock.json",
        HERE / "Deploy.ps1", HERE / "verify_revisions.py",
    }
    for directory in ("flagd", "frontend-proxy", "grafana", "jaeger", "otel-collector", "postgresql", "prometheus"):
        files.update(p for p in (ROOT / "src" / directory).rglob("*") if p.is_file())
    digest = hashlib.sha256()
    for file in sorted(files):
        digest.update(file.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(file.read_bytes())
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--prefix", default="astronomy-demo")
    parser.add_argument("--only", nargs="+", help="Deploy only these named apps; does not delete others")
    parser.add_argument("--credentials-from", type=Path, help="Existing full secure parameter file for partial deployment")
    args = parser.parse_args()
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    lock = json.loads((HERE / "images.lock.json").read_text())
    fingerprint = config_digest()
    deployment_id = args.deployment_id + "-" + fingerprint[:8]
    passwords = None
    credential_file = args.credentials_from or args.output
    if credential_file.exists():
        previous = json.loads(credential_file.read_text())["parameters"]["apps"]["value"]["services"]
        stored = {s["name"]: s["value"] for app in previous for s in app["secrets"]}
        passwords = {kind: stored[f"{kind}-password"] for kind in ("postgres", "astronomy", "monitoring")}
        passwords["flag-ui"] = stored["flag-ui-key"]
    apps = prepare(lock, revision, deployment_id, passwords)
    if args.only:
        unknown = set(args.only) - {a["name"] for a in apps}
        if unknown:
            raise ValueError(f"Unknown selected apps: {sorted(unknown)}")
        apps = [app for app in apps if app["name"] in args.only]
    parameters = {
        "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
        "contentVersion": "1.0.0.0",
        "parameters": {key: {"value": value} for key, value in {
            "prefix": args.prefix, "sourceRevision": revision,
            "deploymentId": deployment_id, "apps": {"services": apps},
            "configDigest": fingerprint,
            "imageLockDigest": hashlib.sha256((HERE / "images.lock.json").read_bytes()).hexdigest(),
        }.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(parameters), encoding="utf-8")
    print(f"Prepared {len(apps)} apps at {deployment_id}; parameter file contains secrets: keep outside git.")


if __name__ == "__main__":
    main()
