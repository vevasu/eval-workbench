FROM python:3.12-slim

WORKDIR /app
COPY backend/requirements.txt backend/requirements-prod.txt backend/
RUN pip install --no-cache-dir -r backend/requirements-prod.txt

COPY backend backend
COPY frontend frontend
COPY data data

# Host the SDK for beta users: they install it straight from this site (no PyPI needed).
COPY sdk/python sdk/python
RUN pip wheel --no-deps sdk/python -w frontend/sdk && rm -rf sdk

ENV EVAL_WORKBENCH_ENV=production PYTHONUNBUFFERED=1
WORKDIR /app/backend
EXPOSE 8000

# Set DATABASE_URL (Postgres), EVAL_WORKBENCH_ADMIN_KEY and TRUST_PROXY=1 in the host's environment settings.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
