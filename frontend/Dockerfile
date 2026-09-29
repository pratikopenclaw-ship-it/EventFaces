FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY scripts ./scripts
RUN npm ci

# --- local development (hot reload; source is bind-mounted) ---
FROM deps AS dev
COPY . .
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
COPY . .
RUN node scripts/fetch-mediapipe.mjs && npm run build

FROM node:22-alpine AS prod
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["node", "server.js"]
