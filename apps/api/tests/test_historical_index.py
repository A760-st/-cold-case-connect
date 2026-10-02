from datetime import date
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
import pytest
from app.database.session import Base
from app.models.historical_case import HistoricalCase
from app.models.vector_index import VectorIndexState
from app.services.historical_index import HistoricalIndexService

class Collection:
    def __init__(self): self.vectors={}
    def upsert(self,ids,documents,embeddings,metadatas):
        for row_id,document,vector,metadata in zip(ids,documents,embeddings,metadatas): self.vectors[row_id]=(document,vector,metadata)
    def count(self): return len(self.vectors)
class Client:
    def __init__(self): self.collections={}
    def get_or_create_collection(self,name,metadata=None): return self.collections.setdefault(name,Collection())
    def get_collection(self,name): return self.collections[name]
    def delete_collection(self,name): self.collections.pop(name,None)

engine=create_engine("sqlite+pysqlite:///:memory:",connect_args={"check_same_thread":False},poolclass=StaticPool)
Base.metadata.create_all(engine)

@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

def test_safe_rebuild_batches_and_verifies_counts(monkeypatch):
    client=Client()
    class FakeEmbedder:
        def embed_texts(self,texts,batch_size=None): return [[0.1,0.2] for _ in texts]
    monkeypatch.setattr("app.services.historical_index.HistoricalIndexService._client",staticmethod(lambda:client))
    monkeypatch.setattr("app.services.historical_index.get_embedding_service",lambda *args:FakeEmbedder())
    with Session(engine) as db:
        case=HistoricalCase(id=uuid4(),external_id="CASE-1",fingerprint="f"*64,title="Source case",summary="Summary",description=None,case_date=date(2020,1,1),location="North",case_type=None,status=None,source_name="Archive",source_url="https://example.org/source",metadata_json={},text_content="Case Title: Source case")
        db.add(case);db.commit()
        report=HistoricalIndexService(db).rebuild(batch_size=1,force=True)
        state=db.get(VectorIndexState,1)
        assert report=={"status":"READY","database_count":1,"indexed_count":1}
        assert state.status=="READY" and state.collection_name.startswith("historical_cases_build_")
        assert client.get_collection(state.collection_name).count()==1
        assert case.embedding_model

def test_count_mismatch_is_visible(monkeypatch):
    class EmptyClient:
        def get_collection(self,name): return Collection()
    monkeypatch.setattr("app.services.historical_index.HistoricalIndexService._client",staticmethod(lambda:EmptyClient()))
    with Session(engine) as db:
        case=HistoricalCase(id=uuid4(),external_id=None,fingerprint=uuid4().hex*2,title="Other case",summary="Details",description=None,case_date=None,location=None,case_type=None,status=None,source_name=None,source_url=None,metadata_json={},text_content="Other case details")
        db.add(case);db.add(VectorIndexState(id=1,status="READY",collection_name="historical_cases",embedding_model="sentence-transformers/all-MiniLM-L6-v2",database_count=1,indexed_count=1));db.commit()
        assert HistoricalIndexService(db).status()["status"]=="INDEX_OUT_OF_SYNC"
