# Provenance and interpretation rules

ColdSync separates source-reported information, extracted claims, analytical links, contradictions, research gaps, and investigator input. The graph groups these relationships visually and preserves their record IDs and source paths. A line means the application stored or derived that relationship; it does not make the underlying statement true.

## Claim status

Claims retain claim type, subject, predicate, object value, normalized value when supplied, source type/ID, evidence ID when available, extraction method, confidence label, and review status. Current automatic graph import only reads explicit structured `metadata.claims` entries from evidence and labels them `SOURCE_REPORTED`. Nothing is promoted from unstructured text. Investigator claims and public-source claim extraction are not inferred by this phase.

## Source relationships

An investigator may record `INDEPENDENT`, `POTENTIAL_DUPLICATE`, `POSSIBLE_SYNDICATION`, `REFERENCES`, `QUOTES`, or `UNKNOWN_RELATIONSHIP`. These describe the investigator's assessment and are stored with explanation, creator, timestamp, and `REQUIRES_VERIFICATION`; the system does not infer duplication or independence.

## Analytical and conflict edges

Similarity, correlation, geographic overlap, and temporal overlap are analytical signals. They do not state identity, causation, guilt, or probability. Contradictions preserve both compared reports and review state; no preferred report is selected. Research gaps and unanswered questions are prompts for additional coverage, not conclusions.

## Provenance path

For a stored web result, the graph links result → search → research run → investigation, and result → source when a source record exists. Agent actions link to their agent run and, where recorded, their research run. Evidence claims link to the evidence record. Timeline, location, historical, gap, and contradiction links are emitted only when referenced records are present in the same investigation projection.
