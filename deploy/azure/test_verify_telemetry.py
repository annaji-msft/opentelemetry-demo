# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest
from subprocess import CompletedProcess
from unittest.mock import patch

from verify_telemetry import query, verify


class TelemetryGateTests(unittest.TestCase):
    def test_cli_preserves_multiline_query(self):
        with patch("verify_telemetry.run", return_value=CompletedProcess(
            [], 0, '[{"Records":"1"}]', ""
        )) as run:
            self.assertEqual(query("sub", "workspace", "\nAppRequests\n| count\n"),
                             [{"Records": "1"}])
            arguments = run.call_args.args[0]
            self.assertEqual(arguments[arguments.index("--analytics-query") + 1],
                             "\nAppRequests\n| count\n")

    def test_requires_application_trace_not_collector_metrics(self):
        with patch("verify_telemetry.query", side_effect=[
            [{"Signal": "AppMetrics", "AppRoleName": "opentelemetry-demo.ad"}], [],
        ]):
            with self.assertRaisesRegex(RuntimeError, "Missing application telemetry"):
                verify("subscription", "workspace", "a" * 32, "2026-01-01T00:00:00Z", 0)

    def test_requires_successful_cross_service_smoke_trace(self):
        signals = [{"Signal": signal} for signal in
                   ("AppRequests", "AppDependencies", "AppTraces", "AppMetrics")]
        spans = [{"AppRoleName": f"opentelemetry-demo.{role}", "Failures": "0",
                  "AppRoleInstance": f"{role}-baseline-test", "Deployment": "baseline-test",
                  "SourceRevision": "b" * 40, "AppVersion": "3.0.0"}
                 for role in ("frontend", "checkout", "payment", "cart")]
        spans[-1]["AppRoleInstance"] = "11111111-2222-4333-8444-555555555555"
        with patch("verify_telemetry.query", side_effect=[signals, spans]):
            result = verify("subscription", "workspace", "a" * 32, "2026-01-01T00:00:00Z", 0)
            self.assertEqual(result["traceId"], "a" * 32)

    def test_rejects_collector_overwriting_service_identity(self):
        signals = [{"Signal": signal} for signal in
                   ("AppRequests", "AppDependencies", "AppTraces", "AppMetrics")]
        spans = [{"AppRoleName": f"opentelemetry-demo.{role}", "Failures": "0",
                  "AppRoleInstance": "otel-collector-baseline-test", "Deployment": "baseline-test",
                  "SourceRevision": "b" * 40, "AppVersion": "3.0.0"}
                 for role in ("frontend", "checkout", "payment", "cart")]
        with patch("verify_telemetry.query", side_effect=[signals, spans]):
            with self.assertRaisesRegex(RuntimeError, "overwritten service metadata"):
                verify("subscription", "workspace", "a" * 32, "2026-01-01T00:00:00Z", 0)

    def test_failed_span_fails_gate(self):
        signals = [{"Signal": signal} for signal in
                   ("AppRequests", "AppDependencies", "AppTraces", "AppMetrics")]
        spans = [{"AppRoleName": f"opentelemetry-demo.{role}", "Failures": "1"}
                 for role in ("frontend", "checkout", "payment", "cart")]
        with patch("verify_telemetry.query", side_effect=[signals, spans]):
            with self.assertRaisesRegex(RuntimeError, "failed spans"):
                verify("subscription", "workspace", "a" * 32, "2026-01-01T00:00:00Z", 0)

    def test_rejects_invalid_trace_query_input(self):
        with self.assertRaises(ValueError):
            verify("subscription", "workspace", "'; invalid", "2026-01-01T00:00:00Z", 0)


if __name__ == "__main__":
    unittest.main()
