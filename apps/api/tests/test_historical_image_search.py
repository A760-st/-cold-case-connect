import io
import pytest
from PIL import Image
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database.session import Base
from app.models.evidence import Evidence, EvidenceType, ProcessingStatus
from app.models.historical_case import HistoricalCase
from app.models.investigation import Investigation, InvestigationStatus
from app.services.historical_image_search import HistoricalImageSearchError, HistoricalImageSearchService

engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)


def test_no_historical_image_corpus_returns_empty_without_loading_clip(monkeypatch):
    monkeypatch.setattr("app.services.historical_image_index.HistoricalImageIndexService.status", lambda self: {"status": "NO_CORPUS", "historical_image_count": 0, "vector_index_count": 0, "embedding_model": "test"})
    monkeypatch.setattr("app.services.historical_image_search.get_clip_embedding_service", lambda *args: (_ for _ in ()).throw(AssertionError("should not load CLIP")))
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    with Session(engine) as db:
        result = HistoricalImageSearchService(db).search_bytes(buffer.getvalue(), 10)
        assert result["index_status"] == "NO_CORPUS"
        assert result["results"] == []


def test_image_evidence_must_exist_belong_to_investigation_and_be_image():
    with Session(engine) as db:
        investigation = Investigation(id=uuid4(), title="Case", description="", status=InvestigationStatus.ACTIVE)
        other = Investigation(id=uuid4(), title="Other", description="", status=InvestigationStatus.ACTIVE)
        db.add_all([investigation, other])
        db.flush()
        text = Evidence(id=uuid4(), investigation_id=investigation.id, type=EvidenceType.TEXT, title="Note", description="", text_content="Details", metadata_json={}, processing_status=ProcessingStatus.READY)
        image = Evidence(id=uuid4(), investigation_id=other.id, type=EvidenceType.IMAGE, title="Photo", description="", storage_path="missing.jpg", metadata_json={}, processing_status=ProcessingStatus.READY)
        db.add_all([text, image])
        db.commit()
        service = HistoricalImageSearchService(db)
        with pytest.raises(HistoricalImageSearchError) as missing:
            service.search_evidence(investigation.id, uuid4())
        assert missing.value.code == "EVIDENCE_NOT_FOUND"
        with pytest.raises(HistoricalImageSearchError) as wrong_type:
            service.search_evidence(investigation.id, text.id)
        assert wrong_type.value.code == "EVIDENCE_NOT_IMAGE"
        with pytest.raises(HistoricalImageSearchError) as mismatch:
            service.search_evidence(investigation.id, image.id)
        assert mismatch.value.code == "EVIDENCE_INVESTIGATION_MISMATCH"
