# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import json
import unittest

import yaml

from prepare import HERE, ROOT, collector_config, model, prepare, proxy_config


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads((HERE / "images.lock.json").read_text())
        cls.apps = prepare(cls.lock, "a" * 40, "baseline-test")

    def test_full_service_inventory(self):
        services, _ = model()
        containers = {c["name"] for a in self.apps for c in a["template"]["containers"]}
        self.assertEqual(containers, set(services))
        self.assertEqual(len(self.apps), 27)

    def test_only_shop_is_public(self):
        self.assertEqual(
            [a["name"] for a in self.apps if a["ingress"] and a["ingress"]["external"]],
            ["frontend-proxy"],
        )
        for app in self.apps:
            for port in (app["ingress"] or {}).get("additionalPortMappings", []):
                self.assertFalse(port["external"])

    def test_immutable_images_and_probes(self):
        for app in self.apps:
            for container in app["template"]["containers"]:
                self.assertIn("@sha256:", container["image"])
                if app["ingress"]:
                    self.assertEqual({p["type"] for p in container["probes"]},
                                     {"Startup", "Readiness", "Liveness"})
            self.assertEqual(app["template"]["scale"], {"minReplicas": 1, "maxReplicas": 1})

    def test_flags_shared_and_off(self):
        flagd = next(a for a in self.apps if a["name"] == "flagd")
        for container in flagd["template"]["containers"]:
            self.assertIn("flags", [m["volumeName"] for m in container["volumeMounts"]])
        flags = json.loads((ROOT / "src/flagd/demo.flagd.json").read_text())
        self.assertTrue(all(f["defaultVariant"] == "off" for f in flags["flags"].values()))

    def test_credentials_are_referenced(self):
        for app in self.apps:
            declared = {s["name"] for s in app["secrets"]}
            if app["name"] == "telemetry-gateway":
                declared.add("app-insights")
            for container in app["template"]["containers"]:
                for env in container["env"]:
                    if env["name"] in {"DB_CONNECTION_STRING", "POSTGRES_PASSWORD",
                                       "POSTGRES_ASTRONOMY_PASSWORD", "POSTGRES_MONITORING_PASSWORD",
                                       "SECRET_KEY_BASE", "APPLICATIONINSIGHTS_CONNECTION_STRING"}:
                        self.assertIn(env["secretRef"], declared)
                        self.assertNotIn("value", env)

    def test_collector_preserves_business_receivers_and_redaction(self):
        config = yaml.safe_load(collector_config())
        receivers = config["receivers"]
        self.assertNotIn("docker_stats", receivers)
        self.assertNotIn("host_metrics", receivers)
        self.assertTrue({"kafkametrics", "postgresql", "redis", "prometheus/ad", "nginx"} <= set(receivers))
        self.assertEqual(set(config["service"]["pipelines"]), {"traces", "metrics", "logs"})
        for pipeline in config["service"]["pipelines"].values():
            self.assertIn("azure_monitor", pipeline["exporters"])
        self.assertIn("transform/redact_sensitive_data", config["service"]["pipelines"]["traces"]["processors"])
        self.assertNotIn("opamp", config["service"]["extensions"])
        self.assertNotIn("InstrumentationKey=", collector_config())
        self.assertFalse(config["processors"]["resource_detection"]["override"])

    def test_gateway_has_no_admin_routes_or_fault_filter(self):
        config = yaml.safe_load(proxy_config())
        manager = config["static_resources"]["listeners"][0]["filter_chains"][0]["filters"][0]["typed_config"]
        routes = manager["route_config"]["virtual_hosts"][0]["routes"]
        self.assertEqual({r["route"]["cluster"] for r in routes if "route" in r},
                         {"frontend", "image-provider"})
        self.assertTrue(all(r["direct_response"]["status"] == 404 for r in routes if "direct_response" in r))
        self.assertEqual(manager["path_with_escaped_slashes_action"], "REJECT_REQUEST")
        self.assertNotIn("envoy.filters.http.fault", [f["name"] for f in manager["http_filters"]])

    def test_dependency_order_and_bounded_waits(self):
        names = [app["name"] for app in self.apps]
        self.assertLess(names.index("kafka"), names.index("checkout"))
        self.assertLess(names.index("astronomy-db"), names.index("product-catalog"))
        self.assertLess(names.index("telemetry-gateway"), names.index("ad"))
        self.assertLess(names.index("cart"), names.index("checkout"))
        self.assertLess(names.index("valkey-cart"), names.index("cart"))
        self.assertLess(names.index("frontend"), names.index("frontend-proxy"))
        checkout = next(app for app in self.apps if app["name"] == "checkout")
        self.assertIn("kafka", checkout["dependencies"])
        self.assertIn("cart", checkout["dependencies"])
        self.assertNotIn("initContainers", checkout["template"])
        collector = next(a for a in self.apps if a["name"] == "telemetry-gateway")
        self.assertNotIn("initContainers", collector["template"])
        collector_env = {e["name"]: e.get("value") for e in collector["template"]["containers"][0]["env"]}
        self.assertNotIn("service.instance.id=", collector_env["OTEL_RESOURCE_ATTRIBUTES"])

    def test_explicit_collector_dns_and_flag_sync_port(self):
        for app in self.apps:
            for container in app["template"]["containers"]:
                env = {e["name"]: e.get("value") for e in container["env"]}
                if "OTEL_EXPORTER_OTLP_ENDPOINT" in env:
                    self.assertIn("telemetry-gateway", env["OTEL_EXPORTER_OTLP_ENDPOINT"])
        flagd = next(a for a in self.apps if a["name"] == "flagd")
        self.assertIn(8015, [p["targetPort"] for p in flagd["ingress"]["additionalPortMappings"]])


if __name__ == "__main__":
    unittest.main()
