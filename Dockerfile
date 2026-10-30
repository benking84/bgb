FROM node:22-bookworm-slim AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ENV NEXT_PUBLIC_API_BASE=
RUN npm run build

FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BGB_WEB_ROOT=/app/web/out \
    PORT=8080
RUN useradd --create-home --uid 10001 bgb
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY --from=web /src/web/out ./web/out
USER bgb
EXPOSE 8080
CMD ["python", "-m", "bgb", "serve", "--host", "0.0.0.0", "--port", "8080"]
