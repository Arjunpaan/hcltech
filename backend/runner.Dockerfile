# Locked-down image used when RUNNER_MODE=docker: generated tests run here with --network none.
# Build once:  docker build -f backend/runner.Dockerfile -t sdlc-runner:latest backend
FROM python:3.11-slim
RUN pip install --no-cache-dir fastapi pydantic httpx pytest ruff bandit
RUN useradd -m runner
USER runner
WORKDIR /work
