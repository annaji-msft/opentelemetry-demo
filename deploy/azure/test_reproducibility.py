# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import azure_cli
from artifacts import ROOT, private_path
from routing_test import documents as routing_documents
from sre_setup import documents, request_plan


class ReproducibilityTests(unittest.TestCase):
    def test_native_methods_and_common_prompt_schema(self):
        config = documents("sub", "app-group", "demo", "workspace",
                           "https://github.com/example/demo", "feature",
                           agent_name="demo-investigator", filter_id="demo-filter",
                           source_alias="demo-source")
        plan = {item["file"]: item for item in request_plan(config)}
        for filename in ("filter.json", "handler.json"):
            self.assertEqual(plan[filename]["createMethod"], "PUT")
            self.assertEqual(plan[filename]["updateMethod"], "POST")
            self.assertTrue(plan[filename]["readFirst"])
        prompt = config["health-prompt.json"]
        self.assertEqual(prompt["name"], "demo-filter-health")
        self.assertEqual(prompt["type"], "CommonPrompt")
        self.assertIn("app-group", prompt["properties"]["prompt"])
        self.assertEqual(plan["health-prompt.json"]["readFirst"],
                         plan["health-prompt.json"]["path"])
        self.assertEqual(config["source.json"]["name"], "demo-source")

    def test_routing_is_disabled_scoped_and_expiring(self):
        now = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)
        config = routing_documents("sub", "group", "demo", "region", "workspace",
                                   "https://github.com/example/demo", "feature",
                                   "2030-01-01T00:15:00Z", now=now)
        alert = config["test-alert.json"]
        self.assertFalse(alert["properties"]["enabled"])
        self.assertEqual(alert["properties"]["actions"]["actionGroups"], [])
        query = alert["properties"]["criteria"]["allOf"][0]["query"]
        self.assertIn("now() < datetime(2030-01-01T00:15:00+00:00)", query)
        self.assertIn("opentelemetry-demo.ad", query)
        self.assertIn("TEST", config["test-filter.json"]["TitleContains"])
        self.assertFalse(config["test-filter.json"]["MergeEnabled"])
        self.assertEqual(config["test-filter.json"]["AgentMode"], "review")
        for expiry in ("2029-12-31T23:59:00Z", "2030-01-01T01:00:00Z", "2030-01-01T00:15:00"):
            with self.assertRaises(ValueError):
                routing_documents("sub", "group", "demo", "region", "workspace",
                                  "https://github.com/example/demo", "feature", expiry, now=now)

    def test_artifacts_cannot_be_written_inside_checkout(self):
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            private_path(ROOT / "deploy" / "azure" / "generated" / "secret.json")
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(private_path(directory), Path(directory).resolve())

    def test_prepare_cli_location_and_private_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "demo.parameters.json"
            subprocess.run([sys.executable, str(ROOT / "deploy/azure/prepare.py"),
                            "--output", str(output), "--location", "example-region",
                            "--prefix", "example-demo", "--deployment-id", "test"],
                           check=True, capture_output=True, text=True)
            params = json.loads(output.read_text())["parameters"]
            self.assertEqual(params["location"]["value"], "example-region")
            self.assertEqual(params["prefix"]["value"], "example-demo")
            self.assertEqual(len(params["apps"]["value"]["services"]), 27)

    def test_argument_boundaries_without_shell(self):
        arguments = ["a&b", "keys(@)", '"quoted"', "'single'", "percent%25", "line1\nline2"]
        program = "import json,sys; print(json.dumps(sys.argv[1:]))"
        with patch("azure_cli.command", return_value=[sys.executable, "-c", program]):
            result = azure_cli.run(arguments, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), arguments)

    def test_windows_launcher_uses_bundled_interpreter(self):
        with patch("azure_cli.sys.platform", "win32"), \
             patch("azure_cli.shutil.which", return_value="/cli/wbin/az.cmd"), \
             patch("azure_cli.Path.is_file", return_value=True):
            self.assertEqual(azure_cli.command()[1:], ["-IBm", "azure.cli"])
            self.assertEqual(Path(azure_cli.command()[0]).name, "python.exe")

    def test_ignore_safeguards_do_not_hide_source(self):
        paths = ["private.parameters.json", "private.parameters.json.wave.json",
                 "verified.event.json", "deploy/azure/generated/source.json"]
        result = subprocess.run(["git", "check-ignore", "--no-index", "-z", "--stdin"],
                                cwd=ROOT, input=("\0".join(paths) + "\0").encode(), capture_output=True)
        self.assertEqual(set(result.stdout.decode().split("\0")[:-1]), set(paths))
        result = subprocess.run(["git", "check-ignore", "--no-index",
                                 "deploy/azure/images.lock.json", "deploy/azure/change-event.schema.json"],
                                cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 1)

    def test_document_links_and_script_references_exist(self):
        # Match inline Markdown link destinations and repository-local script paths.
        links = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        scripts = re.compile(r"deploy[\\/]azure[\\/][\w.-]+\.(?:py|ps1|bicep)")
        docs = list((ROOT / "deploy/azure").glob("*.md"))
        skill = ROOT / ".github/skills/astronomy-shop-accelerator/SKILL.md"
        if skill.exists():
            docs.append(skill)
        for path in docs:
            text = path.read_text(encoding="utf-8")
            for target in links.findall(text):
                if "://" not in target and not target.startswith("#"):
                    self.assertTrue((path.parent / target.split("#")[0]).exists(), (path, target))
            for script in scripts.findall(text):
                self.assertTrue((ROOT / script.replace("\\", "/")).exists(), (path, script))


if __name__ == "__main__":
    unittest.main()
