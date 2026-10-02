import logging
import hashlib
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.ai.clip_embeddings import get_clip_embedding_service, InvalidImageError
from app.config import settings
from app.models.historical_case import HistoricalCase
from app.models.historical_case_image import HistoricalCaseImage
from app.models.image_index import ImageIndexState
from app.storage.historical_images import resolve_historical_image

logger = logging.getLogger("coldsync.historical_image_index")
BASE_COLLECTION = "historical_case_images"


class HistoricalImageIndexError(Exception):
    pass


class HistoricalImageIndexService:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _client():
        import chromadb
        if settings.chroma_host:
            return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        return chromadb.PersistentClient(path=settings.chroma_persist_directory)

    def _state(self, create: bool = True):
        state = self.db.get(ImageIndexState, 1)
        if state is None and create:
            state = ImageIndexState(id=1, status="NOT_INITIALIZED", collection_name=BASE_COLLECTION, embedding_model=settings.clip_model_name)
            self.db.add(state)
            self.db.commit()
            self.db.refresh(state)
        return state

    @staticmethod
    def _collection_records(collection) -> dict[str, dict]:
        rows: dict[str, dict] = {}
        offset = 0
        page_size = 500
        while True:
            page = collection.get(include=["metadatas"], limit=page_size, offset=offset)
            ids = page.get("ids", [])
            rows.update(dict(zip(ids, page.get("metadatas", []))))
            if len(ids) < page_size:
                break
            offset += page_size
        return rows

    def status(self) -> dict:
        db_count = self.db.scalar(select(func.count()).select_from(HistoricalCaseImage).where(HistoricalCaseImage.storage_path.is_not(None))) or 0
        state = self._state(create=False)
        if db_count == 0:
            return {"status": "NO_CORPUS", "historical_image_count": 0, "vector_index_count": 0, "embedding_model": settings.clip_model_name}
        if not state:
            return {"status": "NOT_INITIALIZED", "historical_image_count": db_count, "vector_index_count": 0, "embedding_model": settings.clip_model_name}
        status = state.status
        if db_count > 0 and status == "NO_CORPUS":
            status = "NOT_INITIALIZED"
        try:
            indexed_count = self._client().get_collection(state.collection_name).count()
        except Exception:
            indexed_count = 0
            if status in {"READY", "BUILDING", "FAILED"}:
                status = "FAILED"
        if state.status == "READY" and (state.embedding_model != settings.clip_model_name or db_count != indexed_count):
            status = "INDEX_OUT_OF_SYNC"
        return {"status": status, "historical_image_count": db_count, "vector_index_count": indexed_count, "embedding_model": state.embedding_model}

    def rebuild(self, batch_size: int | None = None, force: bool = False, progress=None) -> dict:
        rows = list(self.db.scalars(select(HistoricalCaseImage).where(HistoricalCaseImage.storage_path.is_not(None)).order_by(HistoricalCaseImage.id)))
        state = self._state()
        previous_collection, previous_model = state.collection_name, state.embedding_model
        previous_status, previous_count = state.status, state.indexed_count
        previous_database_count = state.database_count
        state.status = "BUILDING"
        state.embedding_model = settings.clip_model_name
        state.database_count = len(rows)
        state.last_error = None
        self.db.commit()
        client = None
        collection_name = None
        if not rows:
            try:
                client = self._client()
                try:
                    client.delete_collection(previous_collection)
                except Exception:
                    pass
                state.status = "NO_CORPUS"
                state.indexed_count = 0
                state.database_count = 0
                self.db.commit()
                return {"status": "NO_CORPUS", "database_count": 0, "indexed_count": 0}
            except Exception as exc:
                state.status = "FAILED"
                state.last_error = str(exc)[:500]
                self.db.commit()
                raise HistoricalImageIndexError("Historical image index is unavailable.") from exc
        stage = force or previous_model != settings.clip_model_name or previous_status != "READY" or previous_count > len(rows)
        try:
            client = self._client()
            if not stage:
                try:
                    existing_records = self._collection_records(client.get_collection(previous_collection))
                    existing_ids = set(existing_records)
                    if not existing_ids.issubset({str(row.id) for row in rows}):
                        stage = True
                except Exception:
                    stage = True
        except Exception as exc:
            state.status = "FAILED"
            state.last_error = str(exc)[:500]
            self.db.commit()
            raise HistoricalImageIndexError("Historical image index is unavailable.") from exc
        collection_name = f"historical_case_images_build_{uuid4().hex[:12]}" if stage else previous_collection
        errors = []
        try:
            collection = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
            existing_metadata = {}
            if not stage:
                try:
                    existing_metadata = self._collection_records(collection)
                except Exception:
                    existing_metadata = {}
            effective_batch = batch_size or settings.clip_batch_size
            service = get_clip_embedding_service(settings.clip_model_name, settings.clip_device)
            for start in range(0, len(rows), effective_batch):
                batch_rows = rows[start:start + effective_batch]
                images = []
                valid_rows = []
                for row in batch_rows:
                    try:
                        image_path = resolve_historical_image(row.storage_path)
                        if image_path.stat().st_size > settings.max_evidence_file_size_mb * 1024 * 1024:
                            errors.append(f"{row.id}: image exceeds the configured size limit")
                            continue
                        digest = hashlib.sha256()
                        with image_path.open("rb") as source:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                digest.update(chunk)
                        if not row.checksum or digest.hexdigest() != row.checksum:
                            errors.append(f"{row.id}: image checksum validation failed")
                            continue
                    except (OSError, ValueError) as exc:
                        errors.append(f"{row.id}: image file unavailable ({str(exc)[:120]})")
                        continue
                    saved_metadata = existing_metadata.get(str(row.id))
                    if not stage and saved_metadata and saved_metadata.get("checksum") == row.checksum and row.embedding_model == settings.clip_model_name:
                        continue
                    try:
                        images.append(image_path)
                        valid_rows.append(row)
                    except (OSError, ValueError) as exc:
                        errors.append(f"{row.id}: image file unavailable ({str(exc)[:120]})")
                if images:
                    vectors = service.embed_images(images, batch_size=effective_batch)
                    case_ids = {str(case.id): case for case in self.db.scalars(select(HistoricalCase).where(HistoricalCase.id.in_({row.historical_case_id for row in valid_rows})))}
                    collection.upsert(ids=[str(row.id) for row in valid_rows], documents=[case_ids[str(row.historical_case_id)].title for row in valid_rows], embeddings=vectors, metadatas=[self._metadata(row, case_ids[str(row.historical_case_id)]) for row in valid_rows])
                    now = datetime.now(timezone.utc)
                    for row in valid_rows:
                        row.embedding_model = settings.clip_model_name
                        row.embedding_version = settings.clip_model_name[:64]
                        row.embedding_created_at = now
                if progress:
                    progress(min(start + len(batch_rows), len(rows)), len(rows))
                logger.info("CLIP historical image indexing progress: %s/%s", min(start + len(batch_rows), len(rows)), len(rows))
            indexed_count = collection.count()
            if indexed_count != len(rows) or errors:
                raise HistoricalImageIndexError(f"Historical images indexed={indexed_count}, available records={len(rows)}; invalid images={len(errors)}")
            state.collection_name = collection_name
            state.embedding_model = settings.clip_model_name
            state.database_count = len(rows)
            state.indexed_count = indexed_count
            state.status = "READY"
            state.last_error = None
            self.db.commit()
            if stage and previous_collection != collection_name:
                try:
                    client.delete_collection(previous_collection)
                except Exception:
                    logger.warning("Prior historical image collection cleanup failed after index swap")
            logger.info("CLIP historical image index ready: %s records", indexed_count)
            return {"status": "READY", "database_count": len(rows), "indexed_count": indexed_count}
        except Exception as exc:
            self.db.rollback()
            state = self._state()
            restored = False
            if previous_status == "READY" and previous_model == settings.clip_model_name and previous_database_count == len(rows) and client is not None:
                try:
                    active_by_id = self._collection_records(client.get_collection(previous_collection))
                    restored = len(active_by_id) == len(rows) and all(active_by_id.get(str(row.id), {}).get("checksum") == row.checksum for row in rows)
                except Exception:
                    restored = False
            state.collection_name = previous_collection
            state.embedding_model = previous_model
            state.database_count = previous_database_count if restored else len(rows)
            state.indexed_count = previous_count if restored else state.indexed_count
            state.status = "READY" if restored else "FAILED"
            state.last_error = str(exc)[:500]
            self.db.commit()
            if client is not None and collection_name and collection_name.startswith("historical_case_images_build_") and collection_name != state.collection_name:
                try:
                    client.delete_collection(collection_name)
                except Exception:
                    logger.warning("Failed to remove incomplete CLIP staging collection")
            logger.exception("Historical CLIP indexing failed")
            raise HistoricalImageIndexError("Historical image indexing failed. Check the source image records and CLIP configuration.") from exc

    @staticmethod
    def _metadata(image: HistoricalCaseImage, case: HistoricalCase) -> dict:
        optional = {"external_id": case.external_id, "source_name": image.source_name or case.source_name, "source_url": image.source_url or case.source_url, "image_url": image.image_url, "case_type": case.case_type, "location": case.location, "date": case.case_date.isoformat() if case.case_date else None, "checksum": image.checksum}
        metadata = {"historical_case_id": str(case.id), "image_id": str(image.id), "title": case.title, "embedding_model": settings.clip_model_name}
        metadata.update({key: value for key, value in optional.items() if value is not None})
        return metadata
