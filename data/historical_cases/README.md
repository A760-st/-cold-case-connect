# Historical dataset input

Place a rights-cleared CSV, JSON, or JSONL dataset in this directory and set `HISTORICAL_CASE_DATASET_PATH` to `/data/historical_cases/<filename>` when running the API container. The repository intentionally contains no fabricated historical case records.

Expected canonical fields are `title` (required), and any available `summary`, `description`, `date`, `location`, `case_type`, `status`, `external_id` (or `case_id`/`id`), `source_name`, `source_url`, and `metadata`. Missing optional fields remain null. Extra source fields are preserved in metadata.

Phase 4 can also read optional `image_path`/`image_paths`, `image_url`/`image_urls`, or `image`/`images` fields (the latter can contain path/URL objects). Local image files must be paths relative to this dataset directory and remain within it; local files are copied to persistent image storage and indexed if they are valid JPEG, PNG, or WebP. Image URLs are kept as provenance and are never fetched automatically. Do not add synthetic historical images.
