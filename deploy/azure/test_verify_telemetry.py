# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest
import json
from subprocess import CompletedProcess
from unittest.mock import patch

from verify_telemetry import preflight, query, verify


class TelemetryGateTests(unittest.TestCase):
    def workspace_result(self, status="RespectQuota", customer="workspace"):
        return CompletedProcess([], 0, json.dumps({
            "customerId": customer, "capping": {
                "dataIngestionStatus": status, "dailyQuotaGb": 1,
                "quotaNextResetTime": "2030-01-01T08:00:00Z",
            },
        }), "")

    def test_preflight_aborts_overquota_or_unknown_without_query(self):
        for status in ("OverQuota", "Unknown", None):
            with patch("verify_telemetry.run", return_value=self.workspace_result(status)), \
                 patch("verify_telemetry.query") as query_mock:
                with self.assertRaisesRegex(RuntimeError, "never auto-raise"):
                    preflight("sub", "group", "demo-logs", "workspace")
                query_mock.assert_not_called()

    def test_preflight_rejects_mismatched_workspace(self):
        with patch("verify_telemetry.run", return_value=self.workspace_result(customer="different")):
            with self.assertRaisesRegex(RuntimeError, "does not match"):
                preflight("sub", "group", "demo-logs", "workspace")

    def test_preflight_rejects_missing_or_stale_signals(self):
        for rows in ([], [{"Signal": "AppRequests", "Records": "1"}]):
            with patch("verify_telemetry.run", return_value=self.workspace_result()), \
                 patch("verify_telemetry.query", return_value=rows):
                with self.assertRaisesRegex(RuntimeError, "Missing/stale"):
                    preflight("sub", "group", "demo-logs", "workspace")

    def test_preflight_is_read_only_and_requires_all_four_fresh_signals(self):
        rows = [{"Signal": name, "Records": "1"} for name in
                ("AppRequests", "AppDependencies", "AppTraces", "AppMetrics")]
        with patch("verify_telemetry.run", return_value=self.workspace_result()) as run_mock, \
             patch("verify_telemetry.query", return_value=rows) as query_mock:
            result = preflight("sub", "group", "demo-logs", "workspace")
            self.assertEqual(result["workspaceCapping"]["dailyQuotaGb"], 1)
            self.assertIn("does not prove", result["limitation"])
            self.assertEqual(run_mock.call_args.args[0][:4],
                             ["monitor", "log-analytics", "workspace", "show"])
            self.assertIn("ago(5m)", query_mock.call_args.args[2])
            self.assertIn("TimeGenerated <= now()", query_mock.call_args.args[2])

    def test_preflight_surfaces_workspace_read_failure(self):
        with patch("verify_telemetry.run", return_value=CompletedProcess([], 1, "", "Access denied")):
            with self.assertRaisesRegex(RuntimeError, "Access denied"):
                preflight("sub", "group", "demo-logs", "workspace")

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
