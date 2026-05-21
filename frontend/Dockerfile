FROM node:22-alpine AS builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
COPY ["core/workflows/improvement-cycle/retrospective.workflow.yaml", "core/workflows/improvement-cycle/metrics-review.workflow.yaml", "../core/workflows/improvement-cycle/"]
RUN npm run build

FROM nginx:1.27-alpine

ENV API_BASE_URL=http://localhost:8000

COPY --from=builder /app/frontend/dist /usr/share/nginx/html
COPY --from=builder /app/frontend/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/frontend/docker/40-runtime-config.sh /docker-entrypoint.d/40-runtime-config.sh
RUN sed -i 's/\r$//' /docker-entrypoint.d/40-runtime-config.sh && chmod +x /docker-entrypoint.d/40-runtime-config.sh

EXPOSE 80
