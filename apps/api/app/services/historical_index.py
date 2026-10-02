import logging
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.ai.embeddings import get_embedding_service
from app.config import settings
from app.models.historical_case import HistoricalCase
from app.models.vector_index import VectorIndexState

logger = logging.getLogger("coldsync.historical_index")
BASE_COLLECTION = "historical_cases"


class HistoricalIndexError(Exception):
    pass


class HistoricalIndexService:
    def __init__(self, db: Session):
        self.db = db

    def _state(self, create: bool = True) -> VectorIndexState | None:
        state = self.db.get(VectorIndexState, 1)
        if state is None and create:
            state = VectorIndexState(id=1, status="NOT_INITIALIZED", collection_name=BASE_COLLECTION, embedding_model=settings.sbert_model_name, database_count=0, indexed_count=0)
            self.db.add(state)
            self.db.commit()
            self.db.refresh(state)
        return state

    @staticmethod
    def _client():
        import chromadb
        if settings.chroma_host:
            return chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        return chromadb.PersistentClient(path=settings.chroma_persist_directory)

    def status(self) -> dict:
        db_count = self.db.scalar(select(func.count()).select_from(HistoricalCase)) or 0
        state = self._state(create=False)
        indexed_count = 0
        status = "NOT_INITIALIZED"
        model_name = settings.sbert_model_name
        if state:
            status, model_name = state.status, state.embedding_model
            try:
                indexed_count = self._client().get_collection(state.collection_name).count()
            except Exception:
                indexed_count = 0
                if state.status in {"READY", "BUILDING", "FAILED"}:
                    status = "FAILED"
            if state.status == "READY" and (state.embedding_model != settings.sbert_model_name or db_count != indexed_count):
                status = "INDEX_OUT_OF_SYNC"
        if db_count and state is None:
            status = "NOT_INITIALIZED"
        return {"status": status, "historical_case_count": db_count, "vector_index_count": indexed_count, "embedding_model": model_name}

    def rebuild(self, batch_size: int | None = None, force: bool = False, progress=None) -> dict:
        rows = list(self.db.scalars(select(HistoricalCase).order_by(HistoricalCase.id)))
        state = self._state()
        assert state is not None
        previous_model = state.embedding_model
        previous_collection = state.collection_name
        previous_indexed_count = state.indexed_count
        state.status = "BUILDING"
        state.database_count = len(rows)
        state.embedding_model = settings.sbert_model_name
        state.last_error = None
        self.db.commit()
        logger.info("Historical indexing started: %s records", len(rows))
        client = None
        collection_name = None
        try:
            if not rows:
                client = self._client()
                try:
                    client.delete_collection(state.collection_name)
                except Exception:
                    pass
                state.status = "READY"
                state.indexed_count = 0
                state.database_count = 0
                state.embedding_model = settings.sbert_model_name
                self.db.commit()
                return {"status": "READY", "database_count": 0, "indexed_count": 0}
            embedder = get_embedding_service(settings.sbert_model_name, settings.sbert_device)
            effective_batch = batch_size or settings.sbert_batch_size
            vectors = []
            for start in range(0, len(rows), effective_batch):
                batch = rows[start:start + effective_batch]
                vectors.extend(embedder.embed_texts([row.text_content for row in batch], batch_size=effective_batch))
                if progress:
                    progress(min(start + len(batch), len(rows)), len(rows))
                logger.info("Historical embedding progress: %s/%s", min(start + len(batch), len(rows)), len(rows))
            client = self._client()
            old_model_changed = previous_model != settings.sbert_model_name and previous_indexed_count > 0
            staging = force or old_model_changed
            collection_name = f"historical_cases_build_{uuid4().hex[:12]}" if staging else state.collection_name
            collection = client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})
            for start in range(0, len(rows), effective_batch):
                batch_rows = rows[start:start + effective_batch]
                batch_vectors = vectors[start:start + effective_batch]
                metadata = [self._metadata(row) for row in batch_rows]
                collection.upsert(ids=[str(row.id) for row in batch_rows], documents=[row.text_content for row in batch_rows], embeddings=batch_vectors, metadatas=metadata)
            indexed_count = collection.count()
            if indexed_count != len(rows):
                raise HistoricalIndexError(f"ChromaDB count mismatch: PostgreSQL={len(rows)}, ChromaDB={indexed_count}")
            now = datetime.now(timezone.utc)
            for row in rows:
                row.embedding_model = settings.sbert_model_name
                row.embedding_version = settings.sbert_model_name
                row.embedding_created_at = now
            old_collection = previous_collection
            state.collection_name = collection_name
            state.database_count = len(rows)
            state.indexed_count = indexed_count
            state.embedding_model = settings.sbert_model_name
            state.status = "READY"
            state.last_error = None
            self.db.commit()
            if staging and old_collection != collection_name:
                try:
                    client.delete_collection(old_collection)
                except Exception:
                    logger.warning("Prior historical collection cleanup failed after index swap")
            logger.info("Historical indexing completed: %s records", indexed_count)
            return {"status": "READY", "database_count": len(rows), "indexed_count": indexed_count}
        except Exception as exc:
            self.db.rollback()
            state = self._state()
            assert state is not None
            if client is not None and collection_name and collection_name.startswith("historical_cases_build_") and collection_name != state.collection_name:
                try:
                    client.delete_collection(collection_name)
                except Exception:
                    logger.warning("Failed to remove incomplete staging collection")
            state.status = "FAILED"
            state.database_count = len(rows)
            state.last_error = str(exc)[:500]
            self.db.commit()
            logger.exception("Historical indexing failed")
            raise HistoricalIndexError("Historical vector indexing is unavailable.") from exc

    @staticmethod
    def _metadata(row: HistoricalCase) -> dict:
        metadata = {"historical_case_id": str(row.id), "title": row.title}
        optional = {"external_id": row.external_id, "date": row.case_date.isoformat() if row.case_date else None, "date_ordinal": row.case_date.toordinal() if row.case_date else None, "location": row.location, "case_type": row.case_type, "status": row.status, "source_name": row.source_name, "source_url": row.source_url}
        metadata.update({key: value for key, value in optional.items() if value is not None})
        return metadata
