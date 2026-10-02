import argparse
import json
import logging
from app.database.session import SessionLocal
from app.services.historical_index import HistoricalIndexService, HistoricalIndexError


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely rebuild the persistent historical case vector index.")
    parser.add_argument("--batch-size", type=int, default=None)
    args = parser.parse_args()
    if args.batch_size is not None and args.batch_size < 1:
        parser.error("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        with SessionLocal() as db:
            result = HistoricalIndexService(db).rebuild(batch_size=args.batch_size, force=True, progress=lambda done, total: print(f"Embedding progress: {done}/{total}"))
        print(json.dumps(result, indent=2))
        return 0
    except HistoricalIndexError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
