# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import unittest

from sre_setup import documents


class SreConfigurationTests(unittest.TestCase):
    def test_restricted_investigator_and_exact_workspace_filter(self):
        config = documents("example-subscription", "example-group", "demo",
                           "workspace-guid", "https://github.com/example/demo", "feature")
        agent = config["agent.json"]["properties"]
        self.assertEqual(agent["tools"], ["RunAzCliReadCommands"])
        self.assertEqual(agent["commonTools"], ["RunAzCliReadCommands"])
        self.assertEqual(agent["handoffs"], [])
        self.assertFalse(agent["enableSkills"])
        self.assertFalse(agent["addSystemSkills"])
        self.assertTrue(agent["disableDocumentRetrieval"])
        rule = config["filter.json"]
        self.assertEqual(rule["TitleNotContains"], ["TEST"])
        self.assertFalse(rule["MergeEnabled"])
        self.assertTrue(rule["TargetResource"].endswith("/workspaces/demo-logs"))
        self.assertEqual(config["incident-platform.patch.json"],
                         {"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}})


if __name__ == "__main__":
    unittest.main()
