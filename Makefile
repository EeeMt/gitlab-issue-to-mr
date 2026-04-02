# Makefile for GIMR development
# Usage: make build | make up | make logs | make clean

# Enable Docker BuildKit if available
export DOCKER_BUILDKIT ?= 1
export COMPOSE_DOCKER_CLI_BUILD ?= 1

.PHONY: build
build:
	cd deploy && docker-compose build

.PHONY: up
up:
	cd deploy && docker-compose up -d --build

.PHONY: down
down:
	cd deploy && docker-compose down

.PHONY: logs
logs:
	cd deploy && docker-compose logs -f

.PHONY: ps
ps:
	cd deploy && docker-compose ps

.PHONY: clean
clean:
	cd deploy && docker-compose down -v --rmi local

.PHONY: rebuild-%:
rebuild-%:
	cd deploy && docker-compose build --no-cache $(shell echo $$* | sed 's/_/-/g')
	cd deploy && docker-compose up -d $(shell echo $$* | sed 's/_/-/g')

# E2E tests
.PHONY: e2e-up
e2e-up:
	cd deploy && docker-compose -f docker-compose.e2e.yml up -d --build

.PHONY: e2e-test
e2e-test:
	cd deploy && docker-compose -f docker-compose.e2e.yml run --rm e2e

.PHONY: e2e-down
e2e-down:
	cd deploy && docker-compose -f docker-compose.e2e.yml down

.PHONY: e2e-logs
e2e-logs:
	cd deploy && docker-compose -f docker-compose.e2e.yml logs -f
