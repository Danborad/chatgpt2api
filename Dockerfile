ARG TARGETARCH

# The console output is architecture-independent, so build it once natively.
FROM --platform=$BUILDPLATFORM node:22-alpine AS web-build

WORKDIR /app/web-vue

COPY web-vue/package.json web-vue/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY VERSION /app/VERSION
COPY CHANGELOG.md /app/CHANGELOG.md
COPY web-vue ./
RUN npm run build


FROM node:22-bookworm-slim AS image-upscale-build

WORKDIR /app/scripts/image_upscale

COPY scripts/image_upscale/package.json scripts/image_upscale/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force


FROM python:3.13-slim AS app

ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    TZ=Asia/Shanghai \
    CHATGPT2API_BUILD_TYPE=release \
    CHATGPT2API_THREAD_TOKENS=120

WORKDIR /opt/chatgpt2api

# 安装系统依赖
# - git: Git 存储后端需要
# - libpq-dev: PostgreSQL 客户端库
# - gcc: 编译 psycopg2-binary 需要
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libpq-dev \
    postgresql-client \
    gcc \
    openssl \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY main.py ./
COPY VERSION ./
COPY api ./api
COPY contracts ./contracts
COPY services ./services
COPY utils ./utils
COPY scripts ./scripts
COPY --from=image-upscale-build /usr/local/bin/node /usr/local/bin/node
COPY --from=image-upscale-build /app/scripts/image_upscale/node_modules ./scripts/image_upscale/node_modules
COPY --from=web-build /app/web-vue/dist ./web_dist
COPY deploy/docker-entrypoint.sh /usr/local/bin/chatgpt2api-entrypoint
RUN chmod 0755 /usr/local/bin/chatgpt2api-entrypoint

WORKDIR /app

EXPOSE 80

ENTRYPOINT ["chatgpt2api-entrypoint"]
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80", "--access-log"]
