#!/usr/bin/env python3
"""Safely probe a provider endpoint for three V2 wire protocols.

The key is read only from ``PROBE_API_KEY``. It is never logged, written to a
file, passed as a command-line argument, or included in an exception message.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request


def request(base_url: str, path: str, headers: dict[str, str], body: dict, timeout: int) -> str:
    req = urllib.request.Request(
        urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/")),
        data=json.dumps(body).encode("utf-8"), method="POST", headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response.read(1)
            return f"http_{response.status}"
    except urllib.error.HTTPError as error:
        error.read(1)
        return f"http_{error.code}"
    except (OSError, ValueError, urllib.error.URLError):
        return "transport_error"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="HTTP(S) origin, without credentials or query.")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query:
        parser.error("--base-url must be an http(s) origin without credentials or a query string")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    cases = {
        "anthropic_messages": ("/v1/messages", {"content-type": "application/json", "anthropic-version": "2023-06-01"}, {"model": args.model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}),
        "openai_responses": ("/v1/responses", {"content-type": "application/json"}, {"model": args.model, "input": "ping", "max_output_tokens": 1}),
        "openai_chat_completions": ("/v1/chat/completions", {"content-type": "application/json"}, {"model": args.model, "max_tokens": 1, "messages": [{"role": "user", "content": "ping"}]}),
    }
    if args.dry_run:
        print(json.dumps({"protocols": sorted(cases), "result": "dry_run"}, sort_keys=True))
        return 0
    key = os.environ.get("PROBE_API_KEY")
    if not key:
        print(json.dumps({"error": "missing_probe_api_key"}, sort_keys=True))
        return 2
    results: dict[str, str] = {}
    for protocol, (path, headers, body) in cases.items():
        request_headers = dict(headers)
        if protocol == "anthropic_messages":
            request_headers["x-api-key"] = key
        else:
            request_headers["authorization"] = f"Bearer {key}"
        results[protocol] = request(args.base_url, path, request_headers, body, args.timeout)
    print(json.dumps({"protocols": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
