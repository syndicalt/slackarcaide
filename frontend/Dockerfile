FROM node:24-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=dependencies /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:24-alpine AS runtime
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup --system --gid 10001 arcade && adduser --system --uid 10001 --ingroup arcade arcade
COPY --from=builder --chown=arcade:arcade /app/public ./public
COPY --from=builder --chown=arcade:arcade /app/.next/standalone ./
COPY --from=builder --chown=arcade:arcade /app/.next/static ./.next/static
USER arcade
EXPOSE 3000
CMD ["node", "server.js"]
