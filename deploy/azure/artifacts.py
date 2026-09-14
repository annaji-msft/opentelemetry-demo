# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Keep generated deployment credentials and live configuration outside the checkout."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def private_path(path):
    path = Path(path).resolve()
    if path.is_relative_to(ROOT):
        raise ValueError("Generated configuration must be outside the repository; use private local storage.")
    return path
