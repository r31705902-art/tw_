# syntax=docker/dockerfile:1
FROM node:20-slim

# curl for the healthcheck, python3 in case a task needs it
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV NODE_ENV=production

COPY package*.json ./
RUN npm install --omit=optional --no-audit --no-fund

COPY . .

# keep the node heap well inside the 1 GB container
ENV NODE_OPTIONS=--max-old-space-size=384
ENV PORT=8080

EXPOSE 8080
CMD ["npm", "start"]