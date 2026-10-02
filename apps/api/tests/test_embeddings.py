import sys
from types import ModuleType
from app.ai.embeddings import EmbeddingService


def test_single_and_batch_embedding_load_model_once(monkeypatch):
    calls={"init":0,"encode":0,"texts":[]}
    class FakeSentenceTransformer:
        def __init__(self,name,device): calls["init"]+=1
        def encode(self,texts,**kwargs):
            calls["encode"]+=1;calls["texts"].extend(texts)
            return [[0.25,0.75] for _ in texts]
    fake=ModuleType("sentence_transformers");fake.SentenceTransformer=FakeSentenceTransformer
    monkeypatch.setitem(sys.modules,"sentence_transformers",fake)
    service=EmbeddingService("local-test","cpu")
    assert service.embed_text("query")==[0.25,0.75]
    assert service.embed_texts(["one","two"],batch_size=2)==[[0.25,0.75],[0.25,0.75]]
    assert calls["init"]==1 and calls["encode"]==2
