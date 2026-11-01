FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 STATE_DIR=/tmp/emporio
COPY --from=ghcr.io/astral-sh/uv:0.10.0 /uv /bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --no-dev --frozen --no-install-project
COPY src/ ./src/
COPY data/ ./data/
COPY web/ ./web/
COPY reports/ ./reports/
RUN uv sync --no-dev --frozen && addgroup --system app && adduser --system --ingroup app app
ARG APP_VERSION="dev"
ENV APP_VERSION=$APP_VERSION PATH="/app/.venv/bin:$PATH"
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:80/health', timeout=5)" || exit 1
USER app
# One worker on purpose: rate limit and conversation lock live in this process
CMD ["uvicorn", "emporio.app:app", "--host", "0.0.0.0", "--port", "80", "--proxy-headers", "--forwarded-allow-ips", "*"]
