FROM registry-1.docker.io/library/node:22.23.3-bookworm-slim@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit
COPY frontend ./
RUN npm run build
FROM registry-1.docker.io/library/nginx:stable-alpine@sha256:c36c74649f425d29473146f051ab9a032874a6989942557acb8ab1e215c6c2d8
COPY frontend/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101
EXPOSE 8080
ENTRYPOINT ["nginx","-g","daemon off;"]
