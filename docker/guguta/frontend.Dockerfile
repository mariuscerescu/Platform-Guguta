# Guguță frontend image (L5/L8): Next.js production build, from a fixed commit.
FROM node:22-alpine AS deps
WORKDIR /app
COPY frontend-guguta/package.json frontend-guguta/package-lock.json* ./
RUN npm install --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY frontend-guguta ./
# The browser talks to the same origin; Next rewrites /guguta-api/* to the API.
ENV GUGUTA_API_URL=http://api:5055
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
RUN addgroup -S guguta && adduser -S guguta -G guguta
USER guguta
EXPOSE 3001
CMD ["npm", "start"]
