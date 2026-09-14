# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

from alert_setup import FAILURE_QUERY, GAP_QUERY, documents, gap_test_query, threshold_test_query


class AlertSetupTests(unittest.TestCase):
    def test_scoped_disabled_no_notifications(self):
        alerts = documents("sub", "group", "demo", "region")
        self.assertEqual(set(alerts), {"request-failures.json", "telemetry-gap.json"})
        for alert in alerts.values():
            props = alert["properties"]
            self.assertFalse(props["enabled"])
            self.assertFalse(props["skipQueryValidation"])
            self.assertEqual(props["severity"], 2)
            self.assertEqual(props["actions"], {"actionGroups": []})
            self.assertEqual(props["scopes"], [
                "/subscriptions/sub/resourceGroups/group/providers/"
                "Microsoft.OperationalInsights/workspaces/demo-logs"
            ])

    def test_predicates_and_query_local_cases(self):
        self.assertIn("FailedRequests >= 3 and FailureRate >= 20.0", FAILURE_QUERY)
        self.assertIn("Success == false", FAILURE_QUERY)
        self.assertIn("ago(10m)", GAP_QUERY)
        self.assertIn("Requests == 0", GAP_QUERY)
        test = threshold_test_query()
        self.assertIn(FAILURE_QUERY.removeprefix("AppRequests").replace(
            "by AppRoleName", "by Case, AppRoleName"), test)
        self.assertIn("'exact',15,3", test)
        self.assertIn("'below-rate',16,3", test)
        self.assertIn("'below-count',2,2", test)
        self.assertIn("Passed=Expected == Actual", test)
        self.assertEqual(gap_test_query().count(GAP_QUERY.removeprefix("AppRequests")), 5)
