FROM node:22-alpine AS miniapp-builder

WORKDIR /build/miniapp

COPY miniapp/package*.json ./
RUN npm install

COPY miniapp ./
RUN npm run build


FROM python:3.12-slim AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY bot ./bot

RUN pip install --no-cache-dir .

EXPOSE 8080

CMD ["python", "-m", "bot.app"]
