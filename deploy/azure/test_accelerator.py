# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml

from accelerator import HERE, commands
from artifacts import ROOT


class AcceleratorTests(unittest.TestCase):
    def settings(self, directory):
        settings = json.loads((HERE / "accelerator.example.json").read_text())
        settings["privateDirectory"] = str(Path(directory) / "generated")
        settings["application"].update(
            subscriptionId="00000000-0000-4000-8000-000000000001",
            resourceGroup="example-app-group", location="example-region",
        )
        settings["source"]["repositoryUrl"] = "https://github.com/example/demo"
        settings["sre"].update(
            subscriptionId="00000000-0000-4000-8000-000000000001",
            resourceGroup="separate-agent-group", agentName="example-agent",
            endpoint="https://example.azuresre.ai",
        )
        return settings

    def test_only_local_generator_phases(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(directory)
            prepared = commands(settings, "prepare")
            self.assertEqual([Path(command[1]).name for command in prepared], ["prepare.py"])
            self.assertNotIn("-Apply", prepared[0])
            with self.assertRaises(ValueError):
                commands(settings, "deploy")
            with self.assertRaises(ValueError):
                commands(settings, "sre-config")
            settings["sre"]["mode"] = "provision-new-guided"
            configured = commands(settings, "sre-config", "00000000-0000-4000-8000-000000000002")
            self.assertEqual([Path(command[1]).name for command in configured],
                             ["sre_setup.py", "alert_setup.py"])
            self.assertTrue(all("example-app-group" in command for command in configured))
            self.assertTrue(all("separate-agent-group" not in command for command in configured))

    def test_placeholder_credentials_and_unexpected_settings_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            original = self.settings(directory)
            for kind in ("placeholder", "credential-url", "extra-key", "repo-output"):
                settings = copy.deepcopy(original)
                if kind == "placeholder":
                    settings["application"]["resourceGroup"] = "YOUR_GROUP"
                elif kind == "credential-url":
                    settings["source"]["repositoryUrl"] = "https://user:example-token@github.com/example/demo"
                elif kind == "extra-key":
                    settings["credentials"] = {}
                else:
                    settings["privateDirectory"] = str(ROOT / "generated")
                with self.assertRaises(ValueError):
                    commands(settings, "prepare")

    def test_cli_generates_safe_private_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = self.settings(directory)
            config = Path(directory) / "operator.json"
            config.write_text(json.dumps(settings))
            for phase, extra in (
                ("prepare", []),
                ("sre-config", ["--workspace-customer-id", "00000000-0000-4000-8000-000000000002"]),
            ):
                subprocess.run([sys.executable, str(HERE / "accelerator.py"), "--config", str(config),
                                "--phase", phase, *extra], check=True, capture_output=True, text=True)
            output = Path(settings["privateDirectory"])
            params = json.loads((output / "baseline.parameters.json").read_text())
            self.assertEqual(len(params["parameters"]["apps"]["value"]["services"]), 27)
            for name in ("request-failures.json", "telemetry-gap.json"):
                self.assertFalse(json.loads((output / "sre" / name).read_text())["properties"]["enabled"])
            targets = json.loads((output / "sre/operator-targets.json").read_text())
            self.assertEqual(targets["sre"]["resourceGroup"], "separate-agent-group")

    def test_skill_frontmatter_and_cli_reference(self):
        skill = ROOT / ".github/skills/astronomy-shop-accelerator/SKILL.md"
        text = skill.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        metadata = yaml.safe_load(text.split("---", 2)[1])
        self.assertEqual(metadata["name"], "astronomy-shop-accelerator")
        self.assertIsInstance(metadata["description"], str)
        self.assertIn("accelerator.py", text)
        self.assertIn("provision-new-guided", text)


if __name__ == "__main__":
    unittest.main()
