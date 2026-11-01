# syntax=docker/dockerfile:1.7

FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt


FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    EMBEDDING_CACHE_DIR=/var/cache/devsafar/fastembed

RUN groupadd --system devsafar \
    && useradd --system --gid devsafar --home-dir /nonexistent --shell /usr/sbin/nologin devsafar \
    && mkdir -p /app /var/cache/devsafar/fastembed \
    && chown -R devsafar:devsafar /app /var/cache/devsafar

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=devsafar:devsafar app ./app
COPY --chown=devsafar:devsafar alembic ./alembic
COPY --chown=devsafar:devsafar alembic.ini ./alembic.ini
COPY --chown=devsafar:devsafar scripts/docker-entrypoint.sh ./scripts/docker-entrypoint.sh

RUN chmod 0555 /app/scripts/docker-entrypoint.sh

USER devsafar

VOLUME ["/var/cache/devsafar/fastembed"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"]

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
