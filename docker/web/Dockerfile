FROM node:20.18-alpine AS build
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ARG VITE_MAP_STYLE_URL=/basemap/style.json
ENV VITE_API_URL=/ \
    VITE_USE_MOCKS=false \
    VITE_MAP_STYLE_URL=$VITE_MAP_STYLE_URL
RUN npm run build

FROM nginx:1.27-alpine
RUN apk upgrade --no-cache
COPY docker/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
COPY docker/web/basemap /usr/share/nginx/html/basemap
EXPOSE 80
