FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG UI_PORT
ARG VITE_PORT
RUN UI_PORT="$UI_PORT" VITE_PORT="$VITE_PORT" npm run build

FROM nginxinc/nginx-unprivileged:1.31-alpine
USER root
RUN rm /etc/nginx/conf.d/default.conf
COPY --chown=101:101 nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
ENV API_UPSTREAM=http://api:18421 NGINX_ENVSUBST_FILTER=API_UPSTREAM
USER 101
EXPOSE 18420
