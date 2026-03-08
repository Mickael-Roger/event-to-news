FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for better layer caching
COPY pyproject.toml .

# Install dependencies into a virtual environment managed by uv
RUN uv sync --no-dev

# Copy source code
COPY src/ src/

# Data directory will be mounted as a volume
RUN mkdir -p data

# Environment variables with sensible defaults
ENV CONFIG_PATH=/app/config.yml
ENV DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

CMD ["uv", "run", "event-to-news"]
