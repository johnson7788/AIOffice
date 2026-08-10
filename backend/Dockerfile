# Build the Rust xlsx-sidecar (calamine + ironcalc) that powers /sheets.
FROM rust:1-slim-bookworm AS sidecar
WORKDIR /engine
COPY xlsx-engine/ ./
RUN cargo build --release --locked && cp target/release/xlsx-sidecar /xlsx-sidecar

FROM python:3.13-slim

# uv for fast, reproducible installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock* ./
# ponytail: flaky CI/dev egress drops small wheels on uv's default 30s timeout
ENV UV_HTTP_TIMEOUT=180
RUN uv sync --no-dev

COPY app ./app
COPY --from=sidecar /xlsx-sidecar /usr/local/bin/xlsx-sidecar
ENV XLSX_SIDECAR_BIN=/usr/local/bin/xlsx-sidecar

EXPOSE 8585
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8585"]
