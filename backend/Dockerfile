# Backend + test engine in one container (the container itself isolates generated code).
FROM python:3.11-slim
WORKDIR /srv/backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV GENERATED_DIR=/srv/generated_projects DB_PATH=/srv/data/sdlc.db RUNNER_MODE=local
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
