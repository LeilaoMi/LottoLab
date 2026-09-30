FROM node:24-alpine AS web
WORKDIR /build/frontend
RUN npm install -g pnpm@11.19.0
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml requirements.lock ./
COPY backend/ backend/
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-deps .
COPY alembic.ini ./
COPY migrations/ migrations/
COPY --from=web /build/frontend/dist frontend/dist/
RUN useradd --create-home --uid 10001 lottolab && mkdir /data && chown -R lottolab:lottolab /app /data
USER lottolab
EXPOSE 8000
# 2026-09-30 补：此前健康检查只存在于 compose.yaml，裸 `docker run` 拿不到 ——
# 于是本地裸起容器时「应用起没起来」只能靠人盯日志。
# compose.yaml 里的 healthcheck 会覆盖这一条，两个端口探的是同一个 /api/v1/health。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=4).status==200 else 1)"
CMD ["uvicorn", "lottolab.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
