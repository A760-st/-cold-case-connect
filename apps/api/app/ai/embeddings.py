from functools import lru_cache
import logging
from app.config import settings

logger = logging.getLogger("coldsync.embeddings")


class EmbeddingService:
    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or settings.sbert_model_name
        self.requested_device = device or settings.sbert_device
        self._model = None
        self.device = None

    def _load(self):
        if self._model is not None:
            return self._model
        from sentence_transformers import SentenceTransformer
        device = self.requested_device
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        try:
            self._model = SentenceTransformer(self.model_name, device=device)
            self.device = device
        except Exception:
            if device == "cuda":
                logger.warning("CUDA unavailable for SBERT; falling back to CPU")
                self._model = SentenceTransformer(self.model_name, device="cpu")
                self.device = "cpu"
            else:
                raise
        return self._model

    def embed_texts(self, texts: list[str], batch_size: int | None = None) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        vectors = model.encode(texts, batch_size=batch_size or settings.sbert_batch_size, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
        return [[float(component) for component in vector] for vector in vectors]

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text], batch_size=1)[0]


@lru_cache(maxsize=4)
def get_embedding_service(model_name: str | None = None, device: str | None = None) -> EmbeddingService:
    return EmbeddingService(model_name, device)
