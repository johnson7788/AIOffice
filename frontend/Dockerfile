# Multi-stage: build both SPAs (npm workspaces) → serve static via nginx.
FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json tsconfig.base.json ./
COPY apps ./apps
COPY packages ./packages
# ponytail: flaky dev egress; npm's default 5min fetch timeout aborts slow CI
ENV npm_config_fetch_timeout=600000 npm_config_fetch_retries=5
RUN npm ci
RUN npm run build --workspace @genoffice/docs
RUN npm run build --workspace @genoffice/slides
RUN npm run build --workspace @genoffice/pdf
RUN npm run build --workspace @genoffice/markdown
RUN npm run build --workspace @genoffice/sheets

FROM nginx:alpine
COPY --from=build /app/apps/docs/src/renderer/dist /usr/share/nginx/html/docs
COPY --from=build /app/apps/slides/src/renderer/dist /usr/share/nginx/html/slides
COPY --from=build /app/apps/pdf/src/renderer/dist /usr/share/nginx/html/pdf
COPY --from=build /app/apps/markdown/src/renderer/dist /usr/share/nginx/html/markdown
COPY --from=build /app/apps/sheets/src/renderer/dist /usr/share/nginx/html/sheets
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
