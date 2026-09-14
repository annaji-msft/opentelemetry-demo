# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Invoke Azure CLI without a Windows command shell or echoed argument strings."""

from pathlib import Path
import shutil
import subprocess
import sys


def command():
    executable = shutil.which("az")
    if executable is None:
        raise RuntimeError("Azure CLI is required; install it and ensure az is on PATH.")
    if sys.platform == "win32" and Path(executable).suffix.lower() in {".cmd", ".bat"}:
        python = Path(executable).parent.parent / "python.exe"
        if not python.is_file():
            raise RuntimeError("Cannot locate Azure CLI's bundled Python; repair the Windows CLI installation.")
        return [str(python), "-IBm", "azure.cli"]
    return [executable]


def run(arguments, **kwargs):
    return subprocess.run([*command(), *arguments], shell=False, **kwargs)


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:], check=False).returncode)
