# Historical Cases Dataset

This directory holds the historical case corpus for ColdSync AI. It is intended for rights-cleared, investigator-owned data only. The repository does not include any fabricated historical records.

Use this folder to store a CSV, JSON, or JSONL dataset that can be ingested into the API and indexed for semantic retrieval.

## Purpose

ColdSync uses historical cases to support:

- semantic search over prior records
- visual similarity search for indexed historical images
- investigation context enrichment and correlation analysis
- timeline and geospatial linking against trusted source material

## Supported input formats

Place one dataset file in this folder, for example:

- `cases.csv`
- `cases.json`
- `cases.jsonl`

The API and ingestion scripts expect a dataset path such as:

```bash
HISTORICAL_CASE_DATASET_PATH=/data/historical_cases/cases.csv
```

## Required and optional fields

The canonical record shape is:

```json
{
  "title": "Required case title",
  "summary": "Optional short summary",
  "description": "Optional long description",
  "date": "Optional date string",
  "location": "Optional place name",
  "case_type": "Optional category or classification",
  "status": "Optional status",
  "external_id": "Optional external identifier",
  "source_name": "Optional source name",
  "source_url": "Optional source URL",
  "metadata": {
    "source_fields": "Additional fields are preserved here"
  }
}
```

Accepted identifiers include:

- `external_id`
- `case_id`
- `id`

Required field:

- `title`

Optional fields:

- `summary`
- `description`
- `date`
- `location`
- `case_type`
- `status`
- `external_id` / `case_id` / `id`
- `source_name`
- `source_url`
- `metadata`

If optional values are missing, they remain `null` in the normalized record. Extra source columns are retained in `metadata`.

## Optional image fields

Historical records may also include image references through any of the following fields:

- `image_path` / `image_paths`
- `image_url` / `image_urls`
- `image` / `images`

Rules:

- Local files must be paths relative to this dataset directory.
- Local images must stay inside the dataset folder.
- Valid image types are JPEG, PNG, and WebP.
- Local images are copied into persistent historical image storage and indexed.
- Image URLs are kept as provenance only and are never fetched automatically.
- Do not add synthetic historical images.

## Example CSV row

```csv
title,summary,date,location,case_type,status,source_name,source_url,external_id
"Sample case title","Short summary of the case","2024-02-15","Bengaluru","Public inquiry","OPEN","Example Source","https://example.com/case/123","CASE-123"
```

## Example JSON array

```json
[
  {
    "title": "Sample case title",
    "summary": "Short summary of the case",
    "date": "2024-02-15",
    "location": "Bengaluru",
    "case_type": "Public inquiry",
    "status": "OPEN",
    "source_name": "Example Source",
    "source_url": "https://example.com/case/123",
    "external_id": "CASE-123",
    "metadata": {
      "notes": "Example only"
    }
  }
]
```

## Ingestion workflow

1. Place your dataset file in this directory.
2. Set the environment variable to the actual file path:

```bash
export HISTORICAL_CASE_DATASET_PATH=/data/historical_cases/cases.csv
```

3. Run the API or ingestion command from the project root or API container context.

Example:

```bash
cd apps/api
python -m app.scripts.ingest_historical_cases --file ../../data/historical_cases/cases.csv --format auto --batch-size 32
```

For a full dataset rebuild:

```bash
cd apps/api
python -m app.scripts.rebuild_historical_index --batch-size 32
```

## Local run URLs

When running the project locally with Docker Compose, the app is typically available at:

- Frontend: http://localhost:3000
- API docs: http://localhost:8001/docs

## Data handling rules

- Use only rights-cleared or appropriately authorized historical data.
- Preserve source provenance when available.
- Keep image URL references as provenance; do not auto-download them.
- Do not add fabricated historical records.
- Treat historical matches as research leads requiring investigator verification.

## Notes

This folder is a strict input location and is intentionally separate from generated evidence, persistent storage, and runtime indexes. Ingestion behavior depends on the dataset being valid, deduplicated where appropriate, and stored under the correct directory structure.
