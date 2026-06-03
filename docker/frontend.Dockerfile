FROM node:22-alpine AS source

ARG REPO_URL=https://github.com/kubiax94/python-rpa-platform.git
ARG REPO_REF=

WORKDIR /src

RUN apk add --no-cache git ca-certificates && \
    git init /src/repo && \
    git -C /src/repo remote add origin "${REPO_URL}" && \
    git -C /src/repo config core.sparseCheckout true && \
    git -C /src/repo sparse-checkout init --cone && \
    git -C /src/repo sparse-checkout set frontend && \
    if [ -n "${REPO_REF}" ]; then git -C /src/repo fetch --depth 1 origin "${REPO_REF}"; else git -C /src/repo fetch --depth 1 origin; fi && \
    git -C /src/repo checkout FETCH_HEAD

FROM node:22-alpine AS deps

WORKDIR /app

COPY --from=source /src/repo/frontend/package.json ./package.json
COPY --from=source /src/repo/frontend/package-lock.json ./package-lock.json

RUN npm ci

FROM node:22-alpine AS builder

ENV NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY --from=source /src/repo/frontend ./

RUN npm run build

FROM node:22-alpine AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

WORKDIR /app

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/package-lock.json ./package-lock.json
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./next.config.ts

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]