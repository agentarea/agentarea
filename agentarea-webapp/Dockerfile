# syntax=docker.io/docker/dockerfile:1

FROM node:22-alpine AS base

# Install dependencies only when needed
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

# Copy package files
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml* .npmrc* ./
COPY packages/ ./packages/

RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
  corepack prepare pnpm@9.15.4 --activate && \
  corepack enable pnpm && \
  pnpm i --frozen-lockfile


# Rebuild the source code only when needed
FROM base AS builder
WORKDIR /app
ARG APP_VERSION=0.0.0
ENV NEXT_PUBLIC_APP_VERSION=$APP_VERSION
COPY --from=deps /app/node_modules ./node_modules
# Copy packages without their node_modules (we use TypeScript source directly)
COPY --from=deps /app/packages ./packages
COPY . .

RUN --mount=type=cache,id=nextjs-cache,target=/app/.next/cache \
  corepack prepare pnpm@9.15.4 --activate && \
  corepack enable pnpm && \
  pnpm run build

# Production image, copy all the files and run next
FROM base AS runner
WORKDIR /app
ARG APP_VERSION=0.0.0

ENV NODE_ENV=production
ENV NEXT_PUBLIC_APP_VERSION=$APP_VERSION

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY --from=builder /app/public ./public

# Set the correct permission for prerender cache
RUN mkdir .next && chown nextjs:nodejs .next

# Automatically leverage output traces to reduce image size
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
CMD ["node", "server.js"]
