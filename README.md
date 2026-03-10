# GitLab Issue to MR Bot (GIMR)

AI-powered code generation from GitLab Issues.

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.11+
- PostgreSQL 16+

### Configuration

1. Copy the environment template:
   ```bash
   cp backend/.env.example backend/.env
   ```

2. Edit `backend/.env` with your configuration:
   - `GITLAB_URL`: Your GitLab instance URL
   - `GITLAB_BOT_TOKEN`: GitLab personal access token with `api` scope
   - `GITLAB_WEBHOOK_SECRET`: Secret token for webhook verification
   - `ANTHROPIC_BASE_URL`: URL for Claude CLI API (e.g., http://localhost:11434/v1)
   - `ANTHROPIC_API_KEY`: API key for Claude
   - `ANTHROPIC_MODEL`: Model name to use

### Start Services

```bash
cd deploy
docker-compose up -d
```

This will start:
- PostgreSQL database
- Backend API server (port 8000)

### Run Database Migrations

```bash
cd backend
alembic upgrade head
```

### Configure GitLab Webhook

See [GitLab Webhook Setup](GITLAB_WEBHOOK_SETUP.md) for instructions.

## Development

### Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### Run Backend Locally

```bash
cd backend
uvicorn app.main:app --reload
```

### Run Tests

```bash
cd backend
pytest
```

## Usage

1. Create a GitLab Issue in your project
2. Add a comment with `@ai-bot <prompt>`
   - Example: `@ai-bot create a hello world function`
3. The bot will:
   - Create a new branch
   - Generate code using Claude CLI
   - Commit and push the code
   - Create a Merge Request
   - Reply to the issue with the MR link

## Project Structure

```
backend/
├── app/
│   ├── api/          # API endpoints
│   │   └── webhook.py
│   ├── core/         # Core functionality
│   │   ├── docker_client.py
│   │   ├── gitlab_client.py
│   │   ├── parser.py
│   │   └── worker.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   └── models.py
├── alembic/          # Database migrations
└── requirements.txt

deploy/
├── Dockerfile.backend
├── Dockerfile.worker
└── docker-compose.yml
```

## License

MIT
