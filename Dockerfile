# =========================================================
# STEAM PROTOCOL AUTOMATION NODE - PRODUCTION DOCKERFILE
# =========================================================
FROM node:22-bookworm-slim AS builder

WORKDIR /app

# Install build tools if needed for native modules
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies with legacy peer deps
COPY package*.json ./
RUN npm install --legacy-peer-deps

# Copy application sources and build frontend dashboard
COPY . .
RUN npm run build

# =========================================================
# RUNTIME CONTAINER
# =========================================================
FROM node:22-bookworm-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

ENV NODE_ENV=production
ENV PORT=8000

COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/server.js ./server.js
COPY --from=builder /app/src/server ./src/server

EXPOSE 8000
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["node", "server.js"]
