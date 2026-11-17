# syntax=docker/dockerfile:1.7
FROM python:3.13-slim-trixie AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip uv

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY uv.lock* ./
COPY noxy ./noxy

RUN --mount=type=cache,id=s/4b6d95d6-86c8-4e71-b014-632b4459ddf6-/root/.cache/uv,target=/root/.cache/uv \
    uv venv /opt/venv \
    && (uv sync --no-dev --active 2>/dev/null \
        || uv pip install --python /opt/venv/bin/python .)

FROM python:3.13-slim-trixie AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONFAULTHANDLER=1 \
    PATH="/opt/venv/bin:$PATH" \
    DENO_INSTALL=/usr/local \
    DENO_NO_UPDATE_CHECK=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        aria2 ca-certificates curl ffmpeg unzip \
    && curl -fsSL https://deno.land/install.sh | sh \
    && test -x /usr/local/bin/deno \
    && apt-get purge -y --auto-remove curl unzip \
    && rm -rf /var/lib/apt/lists/* /root/.cache

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY . .

RUN useradd --create-home --uid 10001 noximusic \
    && mkdir -p downloads cache playback noxy/cookies \
    && chown -R noximusic:noximusic /app

USER noximusic

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
    CMD ffmpeg -version >/dev/null && ffprobe -version >/dev/null && deno --version >/dev/null || exit 1

CMD ["python", "-m", "noxy"]
