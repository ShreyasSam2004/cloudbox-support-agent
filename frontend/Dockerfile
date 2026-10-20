# syntax=docker/dockerfile:1.7
# Support UI for local/compose use. In Azure the same static build is served from a Storage static
# website behind Front Door (no container needed).

FROM node:26-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# nginx 1.30 stable on Alpine 3.24; OS packages are upgraded at build time so the image does not
# inherit fixed CVEs from a stale base layer (CI blocks on fixable HIGH/CRITICAL findings).
FROM nginxinc/nginx-unprivileged:1.30-alpine AS runtime
USER root
RUN apk upgrade --no-cache
USER 101
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --chmod=0755 docker-entrypoint.d/40-api-proxy.sh /docker-entrypoint.d/40-api-proxy.sh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
