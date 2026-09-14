# Copyright The OpenTelemetry Authors
# SPDX-License-Identifier: Apache-2.0

"""Exercise real demo APIs with upstream synthetic payment data; never real cards."""

import argparse
import datetime
import json
import secrets
import urllib.error
import urllib.request
import uuid

from prepare import ROOT


def verify(url):
    trace_id = secrets.token_hex(16)
    user_id = "aca-smoke-" + str(uuid.uuid4())

    def request(path, body=None):
        headers = {
            "Content-Type": "application/json",
            "baggage": "synthetic_request=true",
            "traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01",
        }
        req = urllib.request.Request(
            url.rstrip("/") + path, headers=headers,
            data=None if body is None else json.dumps(body).encode(),
        )
        with urllib.request.urlopen(req, timeout=90) as response:
            data = response.read()
            if response.status != 200:
                raise RuntimeError(f"{path}: HTTP {response.status}")
            return json.loads(data) if "json" in response.headers.get("Content-Type", "") else data

    request("/")
    products = request("/api/products?currencyCode=USD")
    if not products:
        raise RuntimeError("Product catalog is empty")
    product = products[0]
    product_id = product["id"]
    request(f"/api/products/{product_id}?currencyCode=USD")
    request("/api/currency")
    request("/api/data?contextKeys=telescopes")
    request(f"/api/recommendations?productIds={product_id}&currencyCode=USD&sessionId={user_id}")
    cart = request("/api/cart", {"userId": user_id, "item": {"productId": product_id, "quantity": 1}})
    if not cart.get("items"):
        raise RuntimeError("Add-to-cart did not persist an item")
    fixture = json.loads((ROOT / "src/load-generator/people.json").read_text())[0]
    fixture["userId"] = user_id
    order = request("/api/checkout?currencyCode=USD", fixture)
    if not order.get("orderId") or not order.get("shippingTrackingId") or not order.get("items"):
        raise RuntimeError("Checkout lacks an order ID, tracking ID or items")
    cart = request(f"/api/cart?sessionId={user_id}&currencyCode=USD")
    if cart.get("items"):
        raise RuntimeError("Checkout did not empty the cart")
    for path in ("/feature", "/flagservice/", "/grafana", "/jaeger", "/loadgen", "/otlp-http/v1/traces"):
        try:
            request(path)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        else:
            raise RuntimeError(f"Control path is publicly accessible: {path}")
    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "traceId": trace_id, "orderId": order["orderId"],
        "checks": ["homepage", "catalog", "currency", "ads", "recommendations",
                   "cart-write", "checkout", "shipping", "cart-emptied", "control-paths-blocked"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    args = parser.parse_args()
    print(json.dumps(verify(args.url), indent=2))
