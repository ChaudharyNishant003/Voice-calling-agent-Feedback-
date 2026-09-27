# Production image for the dashboard (Railway). Separate from dashboard.Dockerfile, which is
# dev-only (npm run dev, bind-mounted source) — this does a real `next build` and serves with
# `next start`, which reads $PORT (Railway assigns it dynamically).
#
# NEXT_PUBLIC_* vars are baked in at build time (Next.js inlines them into the client bundle), so
# they must be present as build args here, not just as runtime env vars on the running container.
FROM node:20-slim AS base

WORKDIR /srv

COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install

COPY dashboard/ ./

ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL

RUN npm run build

EXPOSE 3000
CMD ["sh", "-c", "npm run start -- -p ${PORT:-3000}"]
