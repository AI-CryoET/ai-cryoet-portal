# syntax=docker/dockerfile:1.7
# TanStack Start SSR app. Build context: frontend/.
#
# `npm run build` produces dist/client (static assets) and dist/server/server.js
# (a fetch handler exported as default). srvx wraps that handler in an HTTP
# server and serves dist/client as static files.

FROM node:24-bookworm-slim AS base
WORKDIR /app
ENV NODE_ENV=production

# All deps (incl. dev) so we can build.
FROM base AS deps
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --include=dev

# Strip dev deps for the runtime image. srvx is transitive of @tanstack/react-start,
# so it survives the prune and is available via `npx srvx`.
FROM base AS production-deps
COPY package.json package-lock.json ./
COPY --from=deps /app/node_modules ./node_modules
RUN npm prune --omit=dev

FROM base AS build
# Shared image version (the `v*.*.*` git tag). Vite inlines VITE_* env vars into
# the client bundle at build time, so the footer can show it.
ARG APP_VERSION
ENV VITE_APP_VERSION=$APP_VERSION

# Fileglancer API base URL. Vite inlines VITE_* at build time. Default is the
# prod host; override only for an allowlisted dev origin. The ARG carries the
# prod default (not left empty) on purpose: the client reads
# `import.meta.env.VITE_FILEGLANCER_URL ?? '<prod>'`, and `??` only falls back on
# null/undefined — a baked empty string would slip through as "" and break the
# client. A defaulted ARG guarantees a non-empty baked value.
ARG FILEGLANCER_URL=https://fileglancer.int.janelia.org
ENV VITE_FILEGLANCER_URL=$FILEGLANCER_URL
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM base AS runtime
COPY --from=production-deps /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY package.json ./

ENV PORT=3000
EXPOSE 3000

CMD ["npm", "run", "start"]
