ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN python -m pip install uv==0.12.6

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra ocr --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra ocr --no-editable

FROM builder AS development-builder
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra dev --extra ocr --no-editable

FROM ${PYTHON_IMAGE} AS base

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-noto-cjk \
        libgl1 \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app \
    && useradd --system --gid app --create-home app

ENV PATH=/opt/venv/bin:$PATH

WORKDIR /app

COPY alembic.ini ./
COPY alembic ./alembic

RUN mkdir -p /var/lib/text-verification/jobs \
    && chown -R app:app /app /var/lib/text-verification

USER app

EXPOSE 8000

CMD ["uvicorn", "text_verification.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS development
COPY --from=development-builder /opt/venv /opt/venv
WORKDIR /workspace/apps/api
COPY --chown=app:app pyproject.toml uv.lock Dockerfile alembic.ini ./
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app src ./src
COPY --chown=app:app tests ./tests
COPY --chown=app:app scripts ./scripts

# Keep the production runtime last so an unqualified docker build excludes test tooling.
FROM base AS runtime
COPY --from=builder /opt/venv /opt/venv
