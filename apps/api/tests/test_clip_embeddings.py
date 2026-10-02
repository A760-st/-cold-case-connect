import io
import contextlib
import sys
from types import ModuleType, SimpleNamespace
import pytest
from PIL import Image
from app.ai.clip_embeddings import ClipEmbeddingService, InvalidImageError, load_valid_image


def image_bytes(format="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), color=(20, 80, 120)).save(buffer, format=format)
    return buffer.getvalue()


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP"])
def test_supported_images_are_normalized_to_rgb(format):
    image = load_valid_image(image_bytes(format))
    assert image.mode == "RGB"
    assert image.size == (12, 8)


def test_corrupt_and_unsupported_images_are_rejected():
    with pytest.raises(InvalidImageError):
        load_valid_image(b"not an image")
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="GIF")
    with pytest.raises(InvalidImageError):
        load_valid_image(buffer.getvalue())


def test_clip_batches_images_and_normalizes_embeddings(monkeypatch):
    class Tensor:
        def __init__(self, count=1): self.count = count
        def to(self, device): return self
        def cpu(self): return self
        def tolist(self): return [[0.6, 0.8] for _ in range(self.count)]
    class Model:
        def __call__(self, pixel_values): return SimpleNamespace(image_embeds=Tensor(pixel_values.count))
    class Processor:
        def __init__(self): self.batch_sizes = []
        def __call__(self, images, return_tensors):
            self.batch_sizes.append(len(images))
            return {"pixel_values": Tensor(len(images))}
    processor = Processor()
    service = ClipEmbeddingService("test-clip", "cpu")
    monkeypatch.setattr(service, "_load", lambda: (Model(), processor))
    torch = ModuleType("torch")
    torch.inference_mode = contextlib.nullcontext
    torch.nn = SimpleNamespace(functional=SimpleNamespace(normalize=lambda values, p, dim: values))
    monkeypatch.setitem(sys.modules, "torch", torch)
    result = service.embed_images([image_bytes(), image_bytes()], batch_size=1)
    assert processor.batch_sizes == [1, 1]
    assert result == [[0.6, 0.8], [0.6, 0.8]]


def test_clip_cuda_failure_falls_back_to_cpu(monkeypatch):
    loaded_on = []
    class Model:
        @classmethod
        def from_pretrained(cls, name): return cls()
        def to(self, device):
            loaded_on.append(device)
            if device == "cuda": raise RuntimeError("CUDA unavailable")
            return self
        def eval(self): return self
    class Processor:
        @classmethod
        def from_pretrained(cls, name): return cls()
    transformers = ModuleType("transformers")
    transformers.CLIPModel = Model
    transformers.CLIPProcessor = Processor
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    service = ClipEmbeddingService("test-clip", "cuda")
    model, processor = service._load()
    assert loaded_on == ["cuda", "cpu"]
    assert service.device == "cpu"
    assert service._load() == (model, processor)
