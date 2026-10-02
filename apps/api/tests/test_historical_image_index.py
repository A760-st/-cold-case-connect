from datetime import date
import hashlib
import io
from pathlib import Path
from uuid import uuid4
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database.session import Base
from app.models.historical_case import HistoricalCase
from app.models.historical_case_image import HistoricalCaseImage
from app.models.image_index import ImageIndexState
from app.services.historical_image_index import HistoricalImageIndexService


class Collection:
    def __init__(self): self.data = {}
    def upsert(self, ids, documents, embeddings, metadatas):
        for values in zip(ids, documents, embeddings, metadatas): self.data[values[0]] = values[1:]
    def count(self): return len(self.data)
    def get(self, include=None, limit=None, offset=0):
        ids = list(self.data)[offset:offset + limit if limit else None]
        return {"ids": ids, "metadatas": [self.data[key][2] for key in ids]}


class Client:
    def __init__(self): self.collections = {}
    def get_or_create_collection(self, name, metadata=None): return self.collections.setdefault(name, Collection())
    def get_collection(self, name): return self.collections[name]
    def delete_collection(self, name): self.collections.pop(name, None)


def test_image_index_builds_separate_collection_and_records_provenance(monkeypatch, tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    client = Client()
    class FakeClip:
        calls = 0
        def embed_images(self, images, batch_size=None):
            self.calls += len(images)
            return [[0.2, 0.4] for _ in images]
    fake_clip = FakeClip()
    image_path = tmp_path / "historical.png"
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    image_path.write_bytes(buffer.getvalue())
    checksum = hashlib.sha256(buffer.getvalue()).hexdigest()
    monkeypatch.setattr("app.services.historical_image_index.HistoricalImageIndexService._client", staticmethod(lambda: client))
    monkeypatch.setattr("app.services.historical_image_index.get_clip_embedding_service", lambda *args: fake_clip)
    monkeypatch.setattr("app.services.historical_image_index.resolve_historical_image", lambda key: Path(tmp_path / "historical.png"))
    with Session(engine) as db:
        case_id, image_id = uuid4(), uuid4()
        db.add(HistoricalCase(id=case_id, external_id="HC-1", fingerprint="a" * 64, title="Archive record", summary="Source summary", description=None, case_date=date(2019, 2, 3), location="North", case_type="Missing person", status=None, source_name="Archive", source_url="https://archive.example/case", metadata_json={}, text_content="Archive source text"))
        db.add(HistoricalCaseImage(id=image_id, historical_case_id=case_id, image_url="https://archive.example/image", storage_path="record.webp", source_name="Image archive", source_url="https://archive.example/image-source", mime_type="image/webp", checksum=checksum, metadata_json={}))
        db.commit()
        result = HistoricalImageIndexService(db).rebuild(force=True)
        state = db.get(ImageIndexState, 1)
        row = client.get_collection(state.collection_name).get()
        assert result["status"] == "READY" and result["indexed_count"] == 1
        assert state.collection_name.startswith("historical_case_images_build_")
        assert row["metadatas"][0]["historical_case_id"] == str(case_id)
        assert row["metadatas"][0]["source_name"] == "Image archive"
        again = HistoricalImageIndexService(db).rebuild(force=False)
        assert again["status"] == "READY" and fake_clip.calls == 1
    Base.metadata.drop_all(engine)


def test_empty_image_corpus_does_not_create_or_load_clip():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        status = HistoricalImageIndexService(db).status()
        assert status["status"] == "NO_CORPUS"
        assert status["historical_image_count"] == 0
    Base.metadata.drop_all(engine)
