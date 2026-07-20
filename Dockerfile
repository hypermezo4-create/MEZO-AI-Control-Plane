FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY build-requirements.lock ./
RUN python -m pip install --require-hashes -r build-requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip wheel --no-deps --no-build-isolation --wheel-dir /wheels .

FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 mezo
WORKDIR /app

COPY requirements.lock ./
RUN python -m pip install --require-hashes -r requirements.lock
COPY --from=builder /wheels/*.whl /tmp/
RUN python -m pip install --no-deps /tmp/*.whl && rm -f /tmp/*.whl

COPY alembic.ini ./
COPY alembic ./alembic

USER mezo
EXPOSE 8080
CMD ["mezo-api"]
