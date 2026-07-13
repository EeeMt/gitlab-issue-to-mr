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
- `images/`: Docker image archives and checksum files
- `kits/`: versioned worker-kit archives and checksums

## Required images

The deployment uses these image tags:

- `codify-backend:latest`
- `codify-nginx:latest`
- `codify-worker/java21-maven:2026.07`
- `postgres:16-alpine`

## Quick start on the offline host

1. Copy this entire `offline-bundle/` directory to the target machine.
2. Copy `config/.env.offline.example` to `config/.env.offline`.
3. Edit `config/.env.offline` and fill in your real values.
4. Run `./scripts/load-images.sh`.
5. On every Docker host, install the kit with `./scripts/install-worker-kit.sh kits/<archive>`.
6. Verify each runtime image with `./scripts/verify-worker-runtime.sh --kit <installed-path> --claude-host-path <host-claude-bin> --image <runtime-image>`.
7. Run `./scripts/start.sh` and then `./scripts/health-check.sh`.
8. Create worker profiles through the API with `runtime_mode=mounted_kit`, the runtime image,
   kit version, and the same absolute kit path installed on that profile's Docker host.

## Quick start on the export machine

If you want one command that builds images and produces a distributable offline bundle:

```bash
make offline-bundle-export
```

This command:

1. Builds the latest Codify images.
2. Regenerates `images/codify-offline-images.tar.gz`.
3. Builds and exports the versioned mounted worker kit.
4. Packages the entire `deploy/offline-bundle/` directory as `deploy/codify-offline-bundle.tar.gz`.

## Notes

- The scheduler runs database migrations automatically on startup.
- `backend` and `scheduler` need access to the local Docker socket because worker containers are created dynamically.
- `scripts/load-images.sh` loads all bundled images, including `deploy-backend`, `deploy-nginx`, `codify-worker`, and `postgres`.
- If you change `WORKER_IMAGE` in `config/.env.offline`, load an image with the same tag on the offline host.
- Copy `config/worker-images.txt.example` to `config/worker-images.txt` before export and list
  all project runtime images that must be available offline.
- If your intranet environment has no outbound internet access, `ANTHROPIC_BASE_URL` must point to an internal Claude-compatible endpoint.
