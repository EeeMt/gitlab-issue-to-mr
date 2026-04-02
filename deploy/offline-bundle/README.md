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
- `images/`: Docker image archives and checksum files

## Required images

The deployment uses these image tags:

- `codify-backend:latest`
- `codify-nginx:latest`
- `codify-worker:latest`
- `postgres:16-alpine`

## Quick start on the offline host

1. Copy this entire `offline-bundle/` directory to the target machine.
2. Copy `config/.env.offline.example` to `config/.env.offline`.
3. Edit `config/.env.offline` and fill in your real values.
4. Run `./scripts/load-images.sh`.
5. Run `./scripts/start.sh`.
6. Run `./scripts/health-check.sh`.
7. Open the dashboard at `FRONTEND_URL`.

## Notes

- The scheduler runs database migrations automatically on startup.
- `backend` and `scheduler` need access to the local Docker socket because worker containers are created dynamically.
- `scripts/load-images.sh` loads all bundled images, including `deploy-backend`, `deploy-nginx`, `codify-worker`, and `postgres`.
- If you change `WORKER_IMAGE` in `config/.env.offline`, load an image with the same tag on the offline host.
- If your intranet environment has no outbound internet access, `ANTHROPIC_BASE_URL` must point to an internal Claude-compatible endpoint.
