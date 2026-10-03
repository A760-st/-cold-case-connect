# API additions: Phases 10–11

All routes use the existing `/api/v1` prefix and standard `{ "success": true, "data": ... }` envelope. UUID identifiers are scoped to the investigation wherever an investigation ID appears. Request limits are bounded.

## Phase 10 research intelligence

- `POST /investigations/{id}/contradictions/detect` runs structured comparison and gap detection.
- `GET /investigations/{id}/contradictions` lists contradictions with status, type, priority, and pagination filters.
- `GET /contradictions/{id}` and `PATCH /contradictions/{id}` inspect or review one finding.
- `GET /investigations/{id}/contradictions/summary` returns aggregate counts.
- `POST /investigations/{id}/gaps/detect`, `GET /investigations/{id}/gaps`, and `GET /investigations/{id}/gaps/summary` detect/list/summarize research gaps.
- `GET /gaps/{gap_id}`, `PATCH /gaps/{gap_id}`, and `POST /gaps/{gap_id}/research` support review and bounded follow-up research.
- `POST /investigations/{id}/questions`, `GET /investigations/{id}/questions`, and `PATCH /questions/{question_id}` manage investigator-defined questions.
- `POST /questions/{question_id}/research` queues the bounded agent with question context.

Status changes remain reviewable by an investigator. Completing a search does not automatically resolve a contradiction, question, or gap.

## Phase 11 graph

- `GET /investigations/{id}/graph` returns typed nodes/edges, counts by node and edge type, projection timestamp, and truncation metadata. Supports repeated `node_types`, `edge_types`, `source_types`, `statuses`, `location_ids`, and `claim_types`; `date_from`, `date_to`, `q`; and bounded `limit` (1–1000), `edge_limit` (1–2000), `offset`.
- `GET /investigations/{id}/graph/node/{node_type}/{node_id}` returns one node and connected records.
- `GET /investigations/{id}/graph/neighborhood/{node_type}/{node_id}` supports `depth` (1–5), node/edge filters, and `max_nodes` (1–300).
- `GET /investigations/{id}/graph/summary` returns node and edge counts by type.
- `POST /investigations/{id}/graph/rebuild` refreshes the deterministic projection and imports structured evidence metadata claims plus explicit normalized timeline date/location claims. Response includes `claims_created` and `claims_truncated`; import caps at 500 evidence records, 500 timeline records, 100 structured claim objects per evidence record, and 5,000 total claim candidates. Repeating it does not duplicate claims.
- `POST /investigations/{id}/graph/notes` stores an investigator note on an existing graph node.
- `GET`, `POST`, `PATCH`, and `DELETE /investigations/{id}/graph/bookmarks[/{bookmark_id}]` manage saved view state. Bookmark node IDs must belong to the investigation.
- `POST /investigations/{id}/graph/source-relationships` records a relationship between two in-scope web sources. New relationships are marked `REQUIRES_VERIFICATION`.

Node types include `INVESTIGATION`, `EVIDENCE`, `CLAIM`, `SOURCE`, `SEARCH_RESULT`, `RESEARCH_SEARCH`, `RESEARCH_RUN`, `AGENT_RUN`, `AGENT_ACTION`, `HISTORICAL_CASE`, `HISTORICAL_IMAGE`, `TIMELINE_EVENT`, `LOCATION`, `CORRELATION`, `CONTRADICTION`, `RESEARCH_GAP`, `INVESTIGATIVE_QUESTION`, and `INVESTIGATOR_ACTION`. See [graph.md](graph.md) for relationships and boundaries.

## Health

`GET /api/v1/health` includes graph-related persisted counts and reports graph generation as `ON_DEMAND_RELATIONAL_PROJECTION`; it does not claim an external graph cache is ready.
