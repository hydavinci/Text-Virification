FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml ./
COPY src ./src

RUN python -m pip wheel --wheel-dir /wheels ".[dev]"

FROM python:3.12-slim AS runtime

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        fonts-noto-cjk \
        libreoffice-writer \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system app \
    && useradd --system --gid app --create-home app

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels "text-verification[dev]" \
    && rm -rf /wheels

WORKDIR /app

COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests

RUN mkdir -p /var/lib/text-verification/jobs \
    && chown -R app:app /app /var/lib/text-verification

USER app

EXPOSE 8000

CMD ["uvicorn", "text_verification.main:app", "--host", "0.0.0.0", "--port", "8000"]
