# Deploying the Web App to Vercel

Vercel can host the Next.js frontend in `apps/web`. The FastAPI API, PostgreSQL database, and ChromaDB remain separate services; the current Docker Compose stack is not deployed by Vercel.

## Import the repository

1. Import `https://github.com/A760-st/-cold-case-connect` into Vercel.
2. Set the project root directory to `apps/web`.
3. Keep the detected Next.js framework and default build command (`npm run build`).
4. Add the frontend environment variables below for Production. Add them for Preview only after the API allows the preview origin.

## Frontend environment

Set both URLs to the public FastAPI service. Do not use `localhost` or the Compose-only hostname `backend` on Vercel.

```text
NEXT_PUBLIC_API_URL=https://<public-api-host>/api/v1
API_INTERNAL_URL=https://<public-api-host>
```

`NEXT_PUBLIC_API_URL` is used by browser requests. `API_INTERNAL_URL` is used by the server-rendered homepage health check. Optional UI limits can also be set as `NEXT_PUBLIC_MAX_EVIDENCE_FILE_SIZE_MB` and `NEXT_PUBLIC_MAX_SEARCH_QUERY_LENGTH`.

## API and data services

Before the hosted site can use investigations, deploy the FastAPI service with PostgreSQL and a reachable ChromaDB service on infrastructure that supports persistent database/storage volumes. Configure the API's `DATABASE_URL`, Chroma connection, storage paths, provider keys, and other secrets in that host's secret manager, not in Git.

Set the API's `API_CORS_ORIGINS` to include the exact Vercel production origin, for example `https://<project>.vercel.app`, and any custom domain. The API currently defaults to `http://localhost:3000`, which is only suitable for local development.

After setting environment variables, redeploy the Vercel project. Open the deployed homepage and confirm it reports `API CONNECTED`; then create an investigation to verify browser-to-API CORS and database access.