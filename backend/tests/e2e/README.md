# E2E Tests with Playwright

> **注意**：完整的测试指南请参阅 [docs/TESTING.md](../../docs/TESTING.md)

This directory contains end-to-end tests using Playwright for headless browser automation.

## Setup

### Prerequisites

- Python 3.11+
- Playwright and browsers installed

### Local Installation

```bash
# Install dependencies
pip install -r requirements-e2e.txt

# Install Playwright browsers
playwright install chromium --with-deps
```

### Running Tests Locally

```bash
# Run all E2E tests
pytest tests/e2e/ -v

# Run with headed browser (visible)
pytest tests/e2e/ -v --headed

# Run specific test file
pytest tests/e2e/tests/test_bootstrap.py -v

# Run tests matching keyword
pytest tests/e2e/ -v -k "bootstrap"

# Generate HTML report
pytest tests/e2e/ -v --html=report.html --self-contained-html
```

## Docker Usage

### Build Image

```bash
docker build -f deploy/Dockerfile.e2e -t codify-e2e:latest .
```

### Run with Docker Compose

```bash
# Start all services
docker-compose -f deploy/docker-compose.e2e.yml up -d

# Run E2E tests against running services
docker-compose -f deploy/docker-compose.e2e.yml run --rm e2e

# Run specific tests
docker-compose -f deploy/docker-compose.e2e.yml run --rm e2e pytest tests/e2e/ -v -k "bootstrap"
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `E2E_BASE_URL` | `http://nginx` | Frontend URL |
| `E2E_BACKEND_URL` | `http://backend:8000` | Backend API URL |
| `E2E_GITLAB_URL` | `http://gitlab:8080` | GitLab URL |

## Test Structure

```
tests/e2e/
├── conftest.py           # Pytest fixtures and configuration
├── pytest.ini            # Pytest settings
├── requirements-e2e.txt   # Python dependencies
└── tests/
    ├── __init__.py
    ├── test_bootstrap.py  # Bootstrap page tests
    └── test_navigation.py # Navigation tests
```

## Writing Tests

```python
import pytest
from playwright.sync_api import Page, expect

@pytest.mark.bootstrap
class TestBootstrapPage:
    def test_bootstrap_page_has_no_sider(self, page: Page):
        """Verify that the Bootstrap page does not display the sidebar."""
        page.goto("/bootstrap")

        sider = page.locator(".app-shell__sider")
        expect(sider).not_to_be_visible()
```

## CI Integration

For GitLab CI, add a job like:

```yaml
e2e-tests:
  image: codify-e2e:latest
  services:
    - postgres:16-alpine
    - nginx
    - backend
  script:
    - pytest tests/e2e/ -v --html=report.html
  artifacts:
    reports:
      html: report.html
```
