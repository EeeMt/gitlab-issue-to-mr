FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Configure git for the mock server
RUN git config --global user.email "mock@codify.test" \
    && git config --global user.name "Mock Server" \
    && git config --global init.defaultBranch main

WORKDIR /app
COPY backend/tests/mock_integration/mock_server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/tests/mock_integration/mock_server/ /app/

RUN mkdir -p /repos

EXPOSE 9000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "9000", "--log-level", "info"]
