from datetime import date
from uuid import UUID, uuid4
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database.session import Base
from app.models.evidence import Evidence, EvidenceType, ProcessingStatus
from app.models.historical_case import HistoricalCase
from app.models.investigation import Investigation, InvestigationStatus
from app.models.vector_index import VectorIndexState
from app.schemas.historical import HistoricalSearchRequest
from app.services.historical_search import HistoricalSearchError, HistoricalSearchService

class FakeCollection:
    def count(self): return 1
    def query(self, **kwargs): return {"ids":[[case_id]],"distances":[[0.23]]}
class FakeClient:
    def get_collection(self, name): return FakeCollection()

engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
Base.metadata.create_all(engine)

def test_search_returns_postgres_records_with_similarity(monkeypatch):
    global case_id
    case_id=str(uuid4())
    with Session(engine) as db:
        record=HistoricalCase(id=UUID(case_id),external_id="PUB-1",fingerprint="a"*64,title="Missing person case",summary="Last seen near a station",description="",case_date=date(2020,1,2),location="Pune",text_content="Case Title: Missing person case")
        state=VectorIndexState(id=1,status="READY",collection_name="historical_cases",embedding_model="test-model",database_count=1,indexed_count=1)
        db.add_all([record,state]);db.commit()
        service=HistoricalSearchService(db)
        monkeypatch.setattr("app.services.historical_search.HistoricalIndexService.status",lambda self:{"status":"READY","historical_case_count":1,"vector_index_count":1,"embedding_model":"test-model"})
        monkeypatch.setattr("app.services.historical_search.HistoricalIndexService._client",staticmethod(lambda:FakeClient()))
        class Embedder:
            def embed_text(self,query): return [0.1,0.2]
        monkeypatch.setattr("app.services.historical_search.get_embedding_service",lambda *args:Embedder())
        result=service.search(HistoricalSearchRequest(query="witness near station",top_k=5))
        assert result["results"][0]["historical_case_id"]==case_id
        assert result["results"][0]["similarity_score"]==0.77
        assert result["results"][0]["requires_verification"] is True

def test_evidence_search_prevents_cross_investigation_and_empty_text():
    with Session(engine) as db:
        first=Investigation(id=uuid4(),title="A",description="",status=InvestigationStatus.ACTIVE)
        second=Investigation(id=uuid4(),title="B",description="",status=InvestigationStatus.ACTIVE)
        item=Evidence(id=uuid4(),investigation_id=second.id,type=EvidenceType.TEXT,title="Statement",description="",text_content="Text",processing_status=ProcessingStatus.READY,metadata_json={})
        db.add_all([first,second,item]);db.commit()
        with pytest.raises(HistoricalSearchError) as mismatch:
            HistoricalSearchService(db).search_evidence(first.id,[item.id],5)
        assert mismatch.value.code=="EVIDENCE_INVESTIGATION_MISMATCH"

def test_missing_and_image_evidence_are_reported():
    with Session(engine) as db:
        inv=Investigation(id=uuid4(),title="C",description="",status=InvestigationStatus.ACTIVE)
        image=Evidence(id=uuid4(),investigation_id=inv.id,type=EvidenceType.IMAGE,title="Image",description="",text_content=None,processing_status=ProcessingStatus.READY,metadata_json={})
        db.add_all([inv,image]);db.commit()
        with pytest.raises(HistoricalSearchError) as missing:
            HistoricalSearchService(db).search_evidence(inv.id,[uuid4()],5)
        assert missing.value.code=="EVIDENCE_NOT_FOUND"
        with pytest.raises(HistoricalSearchError) as no_text:
            HistoricalSearchService(db).search_evidence(inv.id,[image.id],5)
        assert no_text.value.code=="EVIDENCE_TEXT_UNAVAILABLE"

def test_missing_investigation_is_reported():
    with Session(engine) as db:
        with pytest.raises(HistoricalSearchError) as missing:
            HistoricalSearchService(db).search_evidence(uuid4(),[uuid4()],5)
        assert missing.value.code=="INVESTIGATION_NOT_FOUND"
