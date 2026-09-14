# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest
from unittest.mock import patch

from verify_telemetry import verify


class TelemetryGateTests(unittest.TestCase):
    def test_requires_application_trace_not_collector_metrics(self):
        with patch("verify_telemetry.query", side_effect=[
            [{"Signal": "AppMetrics", "AppRoleName": "opentelemetry-demo.ad"}], [],
        ]):
            with self.assertRaisesRegex(RuntimeError, "Missing application telemetry"):
                verify("subscription", "workspace", "a" * 32, "2026-01-01T00:00:00Z", 0)

    def test_requires_successful_cross_service_smoke_trace(self):
        signals = [{"Signal": signal} for signal in
                   ("AppRequests", "AppDependencies", "AppTraces", "AppMetrics")]
        spans = [{"AppRoleName": f"opentelemetry-demo.{role}", "Failures": "0"}
                 for role in ("frontend", "checkout", "payment", "cart")]
        with patch("verify_telemetry.query", side_effect=[signals, spans]):
            result = verify("subscription", "workspace", "a" * 32, "2026-01-01T00:00:00Z", 0)
            self.assertEqual(result["traceId"], "a" * 32)

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
