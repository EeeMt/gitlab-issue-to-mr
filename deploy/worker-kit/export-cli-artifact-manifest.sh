#!/usr/bin/env bash
set -euo pipefail

image="${1:?usage: export-cli-artifact-manifest.sh IMAGE OUTPUT_PATH}"
output_path="${2:?usage: export-cli-artifact-manifest.sh IMAGE OUTPUT_PATH}"

if [ -e "${output_path}" ]; then
    echo "Refusing to overwrite an existing CLI artifact manifest: ${output_path}" >&2
    exit 1
fi
mkdir -p "$(dirname "${output_path}")"
temporary_path="$(mktemp "${output_path}.tmp.XXXXXX")"
cleanup() { rm -f "${temporary_path}"; }
trap cleanup EXIT

docker image inspect "${image}" >/dev/null
docker run --rm --entrypoint cat "${image}" /etc/codify-worker-cli-artifacts.json > "${temporary_path}"
python3 - "${temporary_path}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    document = json.loads(path.read_bytes())
except (OSError, ValueError) as exc:
    raise SystemExit(f"invalid Worker CLI artifact manifest: {exc}") from exc
if document.get("schema") != "codify.worker.cli-artifacts/v1":
    raise SystemExit("unexpected Worker CLI artifact manifest schema")
if not isinstance(document.get("platform"), str) or not document["platform"].startswith("linux/"):
    raise SystemExit("Worker CLI artifact manifest has invalid platform")
artifacts = document.get("artifacts")
if not isinstance(artifacts, dict) or set(artifacts) != {"claude", "codex", "pi", "opencode"}:
    raise SystemExit("Worker CLI artifact manifest must contain exactly four Harnesses")
for key, artifact in artifacts.items():
    if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
        raise SystemExit(f"Worker CLI artifact {key} has no path")
    if not isinstance(artifact.get("version"), str) or not artifact["version"]:
        raise SystemExit(f"Worker CLI artifact {key} has no version")
    digest = artifact.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64 or set(digest) - set("0123456789abcdef"):
        raise SystemExit(f"Worker CLI artifact {key} has invalid SHA-256")
PY
mv "${temporary_path}" "${output_path}"
trap - EXIT
echo "Worker CLI artifact manifest exported: ${output_path}"
