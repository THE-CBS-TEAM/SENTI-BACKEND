FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (needed for WeasyPrint and PostgreSQL client)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    libpango-1.0-0 \
    libharfbuzz0b \
    libpangoft2-1.0-0 \
    shared-mime-info

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy ONLY dependency files first (Docker layer caching)
COPY requirements/ /app/requirements/

# Install dependencies — this layer is cached until requirements change
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r /app/requirements/base.txt

# Copy project code (this layer busts cache on every code change, but deps are already installed)
COPY . /app/

# Make entrypoint executable (runs migrations before starting the app)
RUN chmod +x /app/entrypoint.sh

RUN adduser --disabled-password --gecos '' appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["gunicorn", "sentimentri.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "120"]
