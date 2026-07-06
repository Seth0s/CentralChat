# Production Dockerfile — Bun + TanStack Start build final.

FROM docker.io/oven/bun:1

WORKDIR /app

COPY package.json bun.lock ./
RUN bun install --production --frozen-lockfile

COPY . .

RUN bun run build

EXPOSE 5174

CMD ["bun", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5174"]
