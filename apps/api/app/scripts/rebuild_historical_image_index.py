import argparse
import json
import logging
from app.config import settings
from app.database.session import SessionLocal
from app.services.historical_image_index import HistoricalImageIndexService, HistoricalImageIndexError


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely rebuild the persistent CLIP historical image index.")
    parser.add_argument("--batch-size", type=int, default=settings.clip_batch_size)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        with SessionLocal() as db:
            result = HistoricalImageIndexService(db).rebuild(batch_size=args.batch_size, force=True, progress=lambda done, total: print(f"CLIP image embedding progress: {done}/{total}"))
        print(json.dumps(result, indent=2))
        return 0
    except HistoricalImageIndexError as exc:
        print(json.dumps({"status": "FAILED", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
