# Multi-stage Dockerfile for Notex backend

FROM python:3.12-slim AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy project files (before switching user so root can install)
COPY pyproject.toml .
COPY alembic/ alembic/
COPY app/ app/

# Install dependencies as root (required for system-wide installation)
RUN pip install --no-cache-dir -e .

# Create non-root user and fix permissions
RUN useradd -m -u 1000 notex && chown -R notex:notex /app
USER notex

# Development stage
FROM base AS development

# Expose port
EXPOSE 8000

# Default command (can be overridden by docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Production stage
FROM base AS production

# Expose port
EXPOSE 8000

# Run with gunicorn
CMD ["gunicorn", "app.main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000"]
