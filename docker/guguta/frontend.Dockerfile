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
# F20: public subcale. Next inline-uiește valoarea în bundle-ul de client, deci
# se dă la BUILD (nu se poate schimba doar din environment la runtime).
# Gol (implicit) = servit pe rădăcină; pe server: /edu-platform.
ARG GUGUTA_BASE_PATH=""
ENV NEXT_PUBLIC_BASE_PATH=${GUGUTA_BASE_PATH}
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
# `next start` reciteste next.config.ts la pornire, deci basePath trebuie să fie
# prezent ȘI în stagiul de runtime: altfel build-ul are prefixul (active, surse
# de rewrites), iar serverul caută rutele fără el și răspunde 404 la tot.
# ARG nu trece între stagii — se redeclară aici, cu aceeași valoare din build.
ARG GUGUTA_BASE_PATH=""
ENV NEXT_PUBLIC_BASE_PATH=${GUGUTA_BASE_PATH}
ENV GUGUTA_API_URL=http://api:5055
COPY --from=build /app ./
RUN addgroup -S guguta && adduser -S guguta -G guguta
USER guguta
EXPOSE 3001
CMD ["npm", "start"]
