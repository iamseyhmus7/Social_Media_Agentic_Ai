ARG API_BASE_IMAGE=python:3.12-slim
ARG MEDIA_BASE_IMAGE=runtime
FROM node:22-bookworm-slim AS node-runtime
FROM ${API_BASE_IMAGE} AS runtime
USER root
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN if ! command -v ffmpeg >/dev/null; then apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core libsndfile1 && rm -rf /var/lib/apt/lists/*; fi
WORKDIR /app
COPY backend/requirements.txt backend/requirements-media.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
RUN (id -u sahne >/dev/null 2>&1 || useradd --create-home --uid 10001 sahne) && mkdir -p /app/data && chown sahne:sahne /app/data

FROM runtime AS base
COPY backend backend
COPY shared shared
USER sahne
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM ${MEDIA_BASE_IMAGE} AS media-dependencies
USER root
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements-media.txt backend/
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir torch --index-url ${TORCH_INDEX_URL} && pip install --no-cache-dir -r backend/requirements.txt -r backend/requirements-media.txt
RUN (id -u sahne >/dev/null 2>&1 || useradd --create-home --uid 10001 sahne) && mkdir -p /app/data && chown sahne:sahne /app/data

FROM media-dependencies AS media
USER root
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && if ! command -v chromium >/dev/null; then apt-get update && apt-get install -y --no-install-recommends chromium && rm -rf /var/lib/apt/lists/*; fi
COPY remotion/production/package*.json /app/remotion/production/
RUN cd /app/remotion/production && npm ci --omit=dev --no-audit --no-fund && mkdir -p node_modules/.cache && chown -R sahne:sahne node_modules/.cache
RUN cd /app/remotion/production && node --input-type=module -e "import {ensureBrowser} from '@remotion/renderer'; await ensureBrowser({chromeMode:'headless-shell',logLevel:'error'});" && chown -R sahne:sahne node_modules/.remotion
COPY remotion/production/*.jsx remotion/production/*.mjs /app/remotion/production/
COPY remotion/production/licenses /app/remotion/production/licenses
COPY backend backend
COPY shared shared
RUN mkdir -p /app/remotion-code-cache && chown sahne:sahne /app/remotion-code-cache
ENV REMOTION_ROOT=/app/remotion REMOTION_BROWSER_EXECUTABLE="" REMOTION_BUNDLE_CACHE=/app/remotion-code-cache
USER sahne

