from functools import lru_cache
import io
import logging
from pathlib import Path
from PIL import Image, ImageOps, UnidentifiedImageError
from app.config import settings

logger = logging.getLogger("coldsync.clip")
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class InvalidImageError(ValueError):
    pass


def load_valid_image(source: bytes | str | Path | Image.Image) -> Image.Image:
    try:
        image_format = source.format if isinstance(source, Image.Image) else None
        if isinstance(source, Image.Image):
            if source.width < 1 or source.height < 1 or source.width * source.height > MAX_IMAGE_PIXELS:
                raise InvalidImageError("Image dimensions exceed the supported limit.")
            image = source.copy()
        elif isinstance(source, bytes):
            if not source:
                raise InvalidImageError("Image is empty.")
            with Image.open(io.BytesIO(source)) as opened:
                opened.verify()
            with Image.open(io.BytesIO(source)) as opened:
                image_format = opened.format
                if opened.width < 1 or opened.height < 1 or opened.width * opened.height > MAX_IMAGE_PIXELS:
                    raise InvalidImageError("Image dimensions exceed the supported limit.")
                image = ImageOps.exif_transpose(opened).convert("RGB")
        else:
            path = Path(source)
            if not path.is_file() or path.stat().st_size == 0:
                raise InvalidImageError("Image file is unavailable.")
            with Image.open(path) as opened:
                opened.verify()
            with Image.open(path) as opened:
                image_format = opened.format
                if opened.width < 1 or opened.height < 1 or opened.width * opened.height > MAX_IMAGE_PIXELS:
                    raise InvalidImageError("Image dimensions exceed the supported limit.")
                image = ImageOps.exif_transpose(opened).convert("RGB")
        if image_format not in ALLOWED_FORMATS:
            raise InvalidImageError("Only JPEG, PNG, and WebP images are supported.")
        if image.width < 1 or image.height < 1 or image.width * image.height > MAX_IMAGE_PIXELS:
            raise InvalidImageError("Image dimensions exceed the supported limit.")
        return image.convert("RGB")
    except InvalidImageError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise InvalidImageError("Image is corrupted or unsupported.") from None


class ClipEmbeddingService:
    def __init__(self, model_name: str | None = None, device: str | None = None):
        self.model_name = model_name or settings.clip_model_name
        self.requested_device = device or settings.clip_device
        self._model = None
        self._processor = None
        self.device = None

    def _load(self):
        if self._model is not None:
            return self._model, self._processor
        import torch
        from transformers import CLIPModel, CLIPProcessor
        device = self.requested_device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            model = CLIPModel.from_pretrained(self.model_name)
            processor = CLIPProcessor.from_pretrained(self.model_name)
            model.to(device).eval()
        except Exception:
            if device != "cuda":
                raise
            logger.warning("CUDA unavailable for CLIP; falling back to CPU")
            device = "cpu"
            model = CLIPModel.from_pretrained(self.model_name)
            processor = CLIPProcessor.from_pretrained(self.model_name)
            model.to(device).eval()
        self._model, self._processor, self.device = model, processor, device
        return model, processor

    def embed_images(self, images: list[bytes | str | Path | Image.Image], batch_size: int | None = None) -> list[list[float]]:
        if not images:
            return []
        import torch
        model, processor = self._load()
        vectors = []
        effective_batch = batch_size or settings.clip_batch_size
        for start in range(0, len(images), effective_batch):
            batch = [load_valid_image(value) for value in images[start:start + effective_batch]]
            inputs = processor(images=batch, return_tensors="pt")
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with torch.inference_mode():
                outputs = model(pixel_values=inputs["pixel_values"])
                features = outputs.image_embeds
                features = torch.nn.functional.normalize(features, p=2, dim=-1)
            vectors.extend([[float(component) for component in vector] for vector in features.cpu().tolist()])
        return vectors

    def embed_image(self, image: bytes | str | Path | Image.Image) -> list[float]:
        return self.embed_images([image], batch_size=1)[0]


@lru_cache(maxsize=3)
def get_clip_embedding_service(model_name: str | None = None, device: str | None = None) -> ClipEmbeddingService:
    return ClipEmbeddingService(model_name, device)
