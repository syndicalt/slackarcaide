# SlackArcade Engineering Plan

## Current release

The production surface is Chess, Fischer Random Chess, Connect Four, Reversi,
English draughts, 9x9 Go, Pong, Light Cycles, Ultimate Tic-Tac-Toe, Battleship,
Bomberman Duel, and Battle Tetris. The service consists of FastAPI, PostgreSQL,
Redis, hosted/stdio MCP bridges, and a Next.js spectator UI.

Release gates:

1. `uv lock --check` and `npm ci` are reproducible.
2. Ruff, ESLint, TypeScript, backend tests, frontend tests, and production build
   pass non-interactively.
3. Backend statement coverage remains at or above the CI threshold, with direct
   failure/concurrency tests for lifecycle, ratings, replay, realtime, and social
   operations.
4. `npm audit --omit=dev --audit-level=high` reports no high/critical findings.
5. Alembic is at head and the upgrade path is tested on a copy of production.
6. Adversarial probes cover invalid configuration, duplicate actions/finalize,
   concurrent last-seat joins, Redis outage, slow spectators, and large replay.

## Scale roadmap

The current process owns live engines in memory. Running matches do not need to
survive restart, but horizontal API deployment requires explicit match ownership
and routing. Before adding multiple generic workers:

1. Assign each match to a worker identity.
2. Route action/state calls to that owner through ingress affinity or a durable
   command stream.
3. Track event-loop lag, tick duration, active matches, WebSocket queues, Redis
   clients, publish bytes/failures, and database pool saturation.
4. Establish tested concurrency envelopes with k6/Locust and WebSocket load.

## Adding a game

A new game is not enabled by adding a class. One pull request must include:

- An explicit rule/version document and bounded strict configuration model.
- Legal-action, scoring, terminal, winner, reset, and deterministic replay tests.
- Full path-to-terminal tests and adversarial malformed-input tests.
- Renderer contract and frontend tests.
- Load/serialization measurements at maximum supported state size.
- Human review and an intentional registry/catalog addition.

Until all gates pass, experimental engines stay outside the production package.
