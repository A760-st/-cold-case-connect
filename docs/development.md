# Development notes for Phases 10–11

## Local services

The standard development stack is Docker Compose: PostgreSQL, ChromaDB, FastAPI, and Next.js. Copy `.env.example` to `.env` and use local-only credentials. `docker compose up --build` runs Alembic migrations before starting the API. The frontend is at `http://localhost:3000`; the API is at `http://localhost:8001`.

## Migrations

The database migration head is `0011_unified_investigation_graph`. Run `alembic upgrade head` from the API container or `apps/api` environment. Migrations 0010 and 0011 should follow the prior 0009 geospatial revision. Do not use `Base.metadata.create_all` as a replacement for a deployed database migration.

## Checks

From `apps/api`, run `python -m pytest`; from `apps/web`, run the repository's package-manager install, then `npm run build`. Add focused tests for gap/question boundaries, claim extraction idempotency, investigation-scoped graph relationships, endpoint limits, notes, and bookmark validation. React Flow CSS is imported by the graph client component.

## Runtime boundaries

The graph is generated from persisted SQL rows on demand. Its API is intentionally bounded, and `truncated` means the graph needs neighborhood exploration for more context. Source and claim signals retain provenance and review requirements; never describe a similarity score as a probability or a conflict as a resolved fact. No authentication layer is introduced by these phases.
