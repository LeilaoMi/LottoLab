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
# 注意：这里刻意**不写**镜像级健康检查指令。
#
# 2026-09-30 试加过一条打 /api/v1/health 的检查，结果把 CI 的 container job 弄红了：
# worker 服务与 api 共用同一镜像（compose.yaml 里 worker 只写 image: lottolab:local，
# 没有 build:），而 worker 跑的是 `python -m lottolab.worker` —— 长驻进程、容器内没有
# 8000 端口的服务。于是那条检查对 worker 永远失败，`docker compose up --wait` 判定
# `lottolab-ci-worker-1 is unhealthy`，第 6 步 exit 1。
#
# 裸 `docker run` 想看健康状态，请用 compose（compose.yaml 里三个服务各有自己的
# healthcheck）；或直接 GET /api/v1/health。要加镜像级健康检查，必须先让 worker 有
# 自己的可探测端点，否则会重现上面这个回归。
CMD ["uvicorn", "lottolab.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
