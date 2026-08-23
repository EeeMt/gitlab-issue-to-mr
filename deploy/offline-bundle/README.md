# Codify Offline Deployment Bundle

This folder contains the artifacts needed to deploy the current Codify build into an intranet / offline environment without rebuilding images on the target host.

## Bundle contents

- `docker-compose.yml`: offline deployment compose file using prebuilt images only
- `config/.env.offline.example`: sanitized environment template
- `docs/CONFIGURATION.md`: variable explanations and deployment checklist
- `scripts/load-images.sh`: load exported images into Docker
- `scripts/start.sh`: start the stack
- `scripts/stop.sh`: stop the stack
- `scripts/health-check.sh`: verify backend/frontend health
- `scripts/export-images.sh`: regenerate image archives from an online build machine
- `scripts/package-bundle.sh`: package the whole `offline-bundle/` directory for distribution
- `scripts/verify-worker-runtime.sh`: compatibility wrapper that delegates to the verifier and
  validator protected by the installed Worker Kit archive checksum
- `images/`: Docker image archives and checksum files
- `kits/`: versioned worker-kit archives and checksums

## Release candidate freeze

Before a rollout, freeze the complete multi-harness release candidate:

- Worker Kit archives for every architecture used by the Host matrix, plus archive SHA-256 and
  `manifest.json` SHA-256. Do not reuse an archive across CPU architectures.
- Every runtime image used by enabled Worker Profiles, exported through `config/worker-images.txt`
  and verified by repo digest after loading, not by mutable tag.
- Fixed host binaries (the Codex CLI) shipped in the bundle and recorded in
  `config/worker-binaries.txt` with `harness_key`, host/container paths, version and SHA-256.
- The Task Runtime Bundle manifest digest and each harness Adapter version/digest; the actual
  Adapter comes only from the immutable Runtime Bundle, never from the Kit or host path.

See `docs/runbooks/multi-harness-rollout.md` for the full freeze list, per-Host verification,
direct switch, alerting and rollback procedure, and `docs/runbooks/multi-harness-rollout-evidence.md`
for the evidence template.

## Images exported by default

The bundle exports these image tags without additional configuration:

- `codify-backend:latest`
- `codify-nginx:latest`
- `postgres:16-alpine`

Project runtime images are intentionally not exported by default. Copy
`config/worker-images.txt.example` to `config/worker-images.txt` and list every runtime image
needed by your Worker Profiles. For example, add `codify-worker/java21-maven:2026.07` if that
reference runtime must be available offline.

## Quick start on the offline host

1. Copy this entire `offline-bundle/` directory to the target machine.
2. Before extracting or executing any bundle script, verify the top-level archive sidecar. On Linux run **only**:
   `sha256sum -c codify-offline-bundle.tar.gz.sha256`; on macOS run **only**:
   `shasum -a 256 -c codify-offline-bundle.tar.gz.sha256`.
3. After the checksum succeeds, extract the archive and copy `config/.env.offline.example` to `config/.env.offline`.
4. Edit `config/.env.offline` and fill in your real values.
5. Run `./scripts/load-images.sh`.
6. On every Docker host, install the kit with `./scripts/install-worker-kit.sh kits/<archive>`; that command verifies the Kit archive sidecar before extraction.
7. Verify each runtime image per harness on the Docker host:

   ```bash
   ./scripts/verify-worker-runtime.sh \
     --kit /opt/codify/worker-kits/0.3.10-linux-amd64 \
     --image <runtime-image> \
     --harness-key claude \
     --harness-host-path /usr/bin/claude \
     --harness-container-path /usr/local/bin/claude \
     --smoke 'java -version && mvn -version'

   ./scripts/verify-worker-runtime.sh \
     --kit /opt/codify/worker-kits/0.3.10-linux-amd64 \
     --image <runtime-image> \
     --harness-key codex \
     --harness-host-path /opt/codify/codex/bin/codex \
     --harness-container-path /opt/codify-codex/bin/codex \
     --smoke 'test -x /opt/codify-codex/bin/codex && /opt/codify-codex/bin/codex --version'
   ```

   For a frozen V2 release, pass the persisted Runtime Bundle manifest and verify all four
   Harnesses in one invocation. This works from the extracted offline bundle without a Codify
   checkout or `PYTHONPATH`:

   ```bash
   ./scripts/verify-worker-runtime.sh \
     --kit /opt/codify/worker-kits/0.3.15-linux-amd64 \
     --image <runtime-image> \
     --runtime-manifest /srv/codify/releases/<release>/runtime-bundle.v2.json \
     --all-harnesses \
     --smoke 'java -version && mvn -version'
   ```

   The legacy `--claude-host-path <host-claude-bin>` form is still accepted. Then run
   `/api/worker-profiles/<id>/verify-runtime` through Codify so the immutable image repo digest and
   `verified_at` are persisted on the profile.

> Codex CLI is a fixed host binary (not part of the runtime image). Ship it with the bundle
> under `kits/` or `images/`, record its SHA-256 in `config/worker-binaries.txt` (see the
> `worker-binaries.txt.example`), and mount it read-only at the path declared by the Worker
> Profile `harness_runtimes.codex`. Never rely on online install or a mutable `latest` tag.

The Worker Kit archive checksum protects the verifier and validator at installation time. A
privileged user who later modifies an installed Kit root is outside that archive-integrity
boundary; re-run the checksum against the original archive before trusting the installation.
8. Run `./scripts/start.sh` and then `./scripts/health-check.sh`.
9. Create worker profiles through the API with `runtime_mode=mounted_kit`, the runtime image,
   kit version, and the same absolute kit path installed on that profile's Docker host.

## Quick start on the export machine

If you want one command that builds images and produces a distributable offline bundle:

```bash
make offline-bundle-export
```

This command:

1. Builds the latest backend and nginx images in their pinned Docker build environments.
2. Builds and exports the versioned mounted worker kit.
3. Regenerates `images/codify-offline-images.tar.gz`.
4. Packages the entire `deploy/offline-bundle/` directory as `deploy/codify-offline-bundle.tar.gz`.

## Notes

- The scheduler runs database migrations automatically on startup.
- `backend` and `scheduler` need access to the local Docker socket because worker containers are created dynamically.
- `scripts/load-images.sh` loads the backend, nginx, Postgres, and any explicitly configured runtime images in the archive.
- If you set or change `WORKER_IMAGE` in `config/.env.offline`, include an image with the same tag through `config/worker-images.txt` or load it separately on every worker Docker host.
- Copy `config/worker-images.txt.example` to `config/worker-images.txt` before export and list
  all project runtime images that must be available offline.
- The Kit version defaulted by `make offline-bundle-export` follows `WORKER_KIT_VERSION`; set it to
  the frozen release version (e.g. `WORKER_KIT_VERSION=0.3.10`) so both architecture archives match
  the release candidate.
- If your intranet environment has no outbound internet access, `ANTHROPIC_BASE_URL` must point to an internal Claude-compatible endpoint.
