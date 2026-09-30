ARG NODE_IMAGE=node:22.23.3-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
COPY --chown=node:node scripts ./scripts
RUN npm ci

# --- local development (hot reload; source is bind-mounted) ---
FROM deps AS dev
COPY --chown=node:node . .
RUN mkdir -p .next
EXPOSE 3000
CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

# --- production build ---
FROM deps AS build
# Rewrites and security headers are resolved at build time in Next.js.
ARG API_INTERNAL_URL=http://api:8000
ARG STORAGE_PUBLIC_ORIGIN
ENV API_INTERNAL_URL=$API_INTERNAL_URL \
    STORAGE_PUBLIC_ORIGIN=$STORAGE_PUBLIC_ORIGIN \
    NEXT_TELEMETRY_DISABLED=1
COPY --chown=node:node . .
RUN node scripts/fetch-mediapipe.mjs && npm run build

FROM ${NODE_IMAGE} AS prod
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
# The server runs `node server.js`; the npm CLI (and its dependency tree) is not needed.
RUN apk upgrade --no-cache && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx /opt/yarn* /usr/local/bin/yarn*
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
