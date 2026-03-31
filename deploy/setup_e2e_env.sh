#!/bin/bash
# Setup script for E2E testing environment
# This script starts a fresh E2E environment with clean database

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== E2E Testing Environment Setup ==="

# Stop any existing E2E containers
echo "Stopping existing E2E containers..."
docker-compose -f docker-compose.e2e.yml down --remove-orphans 2>/dev/null || true

# Remove any existing volumes to ensure fresh start
echo "Removing existing volumes..."
docker-compose -f docker-compose.e2e.yml down -v --remove-orphans 2>/dev/null || true

# Start the E2E environment
echo "Starting E2E environment..."
docker-compose -f docker-compose.e2e.yml up -d

# Wait for PostgreSQL to be ready
echo "Waiting for PostgreSQL..."
for i in {1..30}; do
    if docker exec gimr-e2e-postgres pg_isready -U gimr -d gimr > /dev/null 2>&1; then
        echo "PostgreSQL is ready!"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: PostgreSQL failed to start"
        exit 1
    fi
    sleep 1
done

# Wait for backend to be healthy
echo "Waiting for backend to be healthy..."
for i in {1..60}; do
    if docker exec gimr-e2e-backend curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "Backend is healthy!"
        break
    fi
    if [ $i -eq 60 ]; then
        echo "ERROR: Backend failed to become healthy"
        docker-compose -f docker-compose.e2e.yml logs backend
        exit 1
    fi
    sleep 2
done

# Wait for nginx to be ready
echo "Waiting for nginx to be ready..."
sleep 5

echo ""
echo "=== E2E Environment Ready ==="
echo "Services:"
echo "  - PostgreSQL: localhost:5432 (gimr/gimr_password)"
echo "  - Backend:   http://localhost:8000"
echo "  - Frontend:   http://localhost:8880"
echo ""
echo "Run tests with:"
echo "  cd $SCRIPT_DIR/.."
echo "  docker exec gimr-e2e-tester pytest tests/e2e/ -v"
echo ""
echo "Or use docker-compose:"
echo "  docker-compose -f docker-compose.e2e.yml exec e2e pytest tests/e2e/ -v"
