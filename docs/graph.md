# Investigation graph

The Phase 11 graph is an interactive React Flow view backed by a bounded projection of PostgreSQL records. It is available from the investigation detail page. It does not maintain a duplicate graph database or change the underlying records.

## Nodes and edge categories

The projection renders investigation, evidence, structured claim, public source, search result, research search/run, agent run/action, historical case/image, timeline event, location, correlation, contradiction, research gap, investigative question, and investigator note/action nodes. Nodes expose concise structured metadata; provider credentials and hidden reasoning are not returned.

- **Provenance:** `BELONGS_TO`, `EXTRACTED_FROM`, `REPORTED_BY`, `FOUND_IN`, `PRODUCED_BY`, `SEARCHED_BY`, `SOURCE_OF`, `DERIVED_FROM`, `OCCURRED_AT`, `LOCATED_AT`.
- **Analysis:** `CORRELATES_WITH`, `SEMANTICALLY_SIMILAR`, `VISUALLY_SIMILAR`, `GEOGRAPHICALLY_OVERLAPS`, `TEMPORALLY_OVERLAPS`, `ENTITY_OVERLAP`, `RELATED_TO`.
- **Conflict:** `CONFLICTS_WITH` and typed conflict records.
- **Research:** `GENERATED`, `ADDRESSES`, `INVESTIGATES`, `DISCOVERED`.
- **Investigator:** source relationship types and `ADDED_BY_INVESTIGATOR` notes.

Solid lines indicate recorded/provenance relationships; dashed purple lines indicate analytical relationships; red lines indicate conflicts; grey lines indicate investigator input. Correlation scores are similarity/relevance signals, never probabilities. Public sources are not automatically assigned truth or reliability labels.

## Exploration

The UI supports graph search, investigation modes, force/hierarchical/timeline layouts, zoom, pan, minimap, fit view, node selection, metadata inspection, neighborhood expansion, provenance-neighborhood focus, investigator notes, and saved bookmarks. Timeline and map links navigate to the existing investigation panels. API filters additionally include node/edge/source/claim types, date range, and location IDs. Responses carry total projected counts and `truncated` so clients can explain partial views.

## Claims and provenance

Claim import reads structured dictionaries already stored under an evidence record's `metadata.claims` and explicit normalized date/location fields on timeline records. Evidence claims require nonempty subject/predicate/value strings; timeline claims preserve the event's structured date or location and source event. Source-reported and investigator-added statuses remain distinct, and each source-backed tuple is fingerprinted for idempotency. It never extracts a claim from arbitrary prose. Claims link to their evidence/timeline/source record and investigation. Source results link to their search and research run; agent actions link to their run. Missing or cross-investigation endpoints are omitted rather than fabricated.

## Limits and scope

The API caps one response at 1,000 nodes and 2,000 edges; defaults are 250/600. Neighborhood expansion is capped at depth 5 and 300 nodes. Underlying projections cap large collections and set `truncated` when a cap is reached; claim import scans up to 500 evidence records, 500 timeline records, 100 structured claims per evidence record, and 5,000 claim candidates per rebuild, and reports `claims_truncated`. A truncated result is an exploration slice, not an exhaustive graph. Rebuild is an on-demand projection and claim importer, not a persisted graph cache or snapshot service. The application currently has no authentication/ownership layer; IDs are scoped to an investigation as in the existing API.
