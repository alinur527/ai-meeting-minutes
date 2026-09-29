FROM node:22.16-bookworm-slim AS build
WORKDIR /source/frontend
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY shared/alem_contract/media.json /source/shared/alem_contract/media.json
ENV VITE_USE_MOCK=false VITE_API_BASE_URL=/api
RUN npm run build
FROM nginx:1.28-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /source/frontend/dist /usr/share/nginx/html
