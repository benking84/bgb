FROM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ENV NEXT_PUBLIC_API_BASE=
RUN npm run build

# Builds the virtualenv from uv.lock so the image uses the versions the PR tested. This uv image
# is based on python:3.12-slim-bookworm, the same Python as the runtime stage, so the venv's
# interpreter path matches. --locked fails if uv.lock disagrees with pyproject.toml.
FROM ghcr.io/astral-sh/uv:0.13.6-python3.12-bookworm-slim AS pybuild
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BGB_WEB_ROOT=/app/web/out \
    PORT=8080 \
    PATH=/app/.venv/bin:$PATH
RUN useradd --create-home --uid 10001 bgb
COPY --from=pybuild /app/.venv /app/.venv
COPY --from=web /src/web/out ./web/out
USER bgb
EXPOSE 8080
CMD ["python", "-m", "bgb", "serve", "--host", "0.0.0.0", "--port", "8080"]
