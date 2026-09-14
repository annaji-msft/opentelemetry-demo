# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Resolve upstream image references to immutable Linux/amd64 manifest digests."""

import concurrent.futures
import datetime
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from prepare import HERE, model

ACCEPT = ", ".join([
    "application/vnd.oci.image.index.v1+json",
    "application/vnd.oci.image.manifest.v1+json",
    "application/vnd.docker.distribution.manifest.list.v2+json",
    "application/vnd.docker.distribution.manifest.v2+json",
])


def resolve(image):
    parts = image.split("/")
    if len(parts) > 1 and "." in parts[0]:
        host, repository = parts[0], "/".join(parts[1:])
    else:
        host = "registry-1.docker.io"
        repository = image if "/" in image else "library/" + image
    repository, tag = repository.rsplit(":", 1)
    headers = {"Accept": ACCEPT}

    def request(path):
        url = f"https://{host}/v2/{repository}/{path}"
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90)
        except urllib.error.HTTPError as error:
            if error.code != 401:
                raise
            # Extract quoted registry Bearer challenge parameters.
            fields = dict(re.findall(r'(\w+)="([^"]+)"', error.headers["WWW-Authenticate"]))
            token_url = fields.pop("realm") + "?" + urllib.parse.urlencode(fields)
            with urllib.request.urlopen(token_url, timeout=90) as response:
                token = json.load(response)
            headers["Authorization"] = "Bearer " + (token.get("token") or token["access_token"])
            return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90)

    with request("manifests/" + tag) as response:
        raw = response.read()
    manifest = json.loads(raw)
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    if "manifests" in manifest:
        digest = next(m["digest"] for m in manifest["manifests"]
                      if m.get("platform", {}).get("os") == "linux"
                      and m["platform"].get("architecture") == "amd64")
        with request("manifests/" + digest) as response:
            manifest = json.load(response)
    with request("blobs/" + manifest["config"]["digest"]) as response:
        config = json.load(response)
    return image, {
        "image": image.rsplit(":", 1)[0] + "@" + digest,
        "created": config.get("created"),
        "sourceRevision": config.get("config", {}).get("Labels", {}).get("org.opencontainers.image.revision"),
        "compressedBytes": sum(layer["size"] for layer in manifest["layers"]),
    }


if __name__ == "__main__":
    services, _ = model()
    images = sorted({s["image"] for s in services.values()} | {"busybox:1.37.0"})
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        resolved = dict(pool.map(resolve, images))
    (HERE / "images.lock.json").write_text(json.dumps({
        "resolvedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "platform": "linux/amd64", "images": resolved,
    }, indent=2) + "\n", encoding="utf-8")
    print(f"Locked {len(resolved)} public images by immutable manifest digest.")
