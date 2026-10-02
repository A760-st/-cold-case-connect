import argparse
import json
import logging
import sys
from app.config import settings
from app.database.session import SessionLocal
from app.services.dataset import HistoricalDatasetIngestor


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and ingest historical case records, then index them for semantic retrieval.")
    parser.add_argument("--file", default=settings.historical_case_dataset_path, help="CSV, JSON, or JSONL dataset path")
    parser.add_argument("--format", choices=("auto", "csv", "json", "jsonl"), default="auto")
    parser.add_argument("--batch-size", type=int, default=settings.sbert_batch_size)
    parser.add_argument("--rebuild", action="store_true", help="Build a replacement Chroma collection and safely switch to it")
    args = parser.parse_args()
    if not args.file:
        parser.error("Pass --file or set HISTORICAL_CASE_DATASET_PATH")
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        with SessionLocal() as db:
            report = HistoricalDatasetIngestor(db).ingest(args.file, args.format, args.batch_size, args.rebuild, progress=lambda done, total: print(f"Embedding progress: {done}/{total}", file=sys.stderr))
        print(json.dumps(report.as_dict(), indent=2))
        return 2 if report.index_status == "FAILED" or report.image_index_status == "FAILED" else 1 if report.invalid_records or report.errors else 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"total_records": 0, "valid_records": 0, "skipped_records": 0, "duplicates": 0, "invalid_records": 1, "errors": [{"row": 0, "reason": str(exc)}], "index_status": None, "indexed_count": 0}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
