FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH=/app/.venv/bin:$PATH \
    GEOSTART_USE_MOCKS=false \
    GEOSTART_STORAGE=files
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
COPY config ./config
COPY research ./research
RUN uv sync --locked --no-dev
COPY docker/api/entrypoint.sh /usr/local/bin/geostart-entrypoint
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=120s --retries=12 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4)"
ENTRYPOINT ["sh", "/usr/local/bin/geostart-entrypoint"]
