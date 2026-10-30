# 화면을 빌드한 뒤, API 서버가 같은 주소에서 내보낸다. 사전 DB는 Turso에서 읽는다(JANGDAN_DB_SOURCE=turso).
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
COPY requirements.txt .
RUN grep -v '^pytest' requirements.txt > /tmp/requirements.txt && pip install --no-cache-dir -r /tmp/requirements.txt
COPY api/ api/
COPY core/ core/
COPY prep/ prep/
COPY --from=web /web/dist web/dist
CMD exec uvicorn api.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8080}
