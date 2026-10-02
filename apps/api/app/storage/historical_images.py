import hashlib
import io
from pathlib import Path
from uuid import UUID
from app.config import settings
from PIL import Image

ROOT = Path(settings.historical_image_storage_dir).resolve()


def store_historical_image(case_id: UUID, image_id: UUID, filename: str, content: bytes) -> tuple[str, str]:
    checksum = hashlib.sha256(content).hexdigest()
    with Image.open(io.BytesIO(content)) as image:
        suffix = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(image.format)
    if not suffix:
        raise ValueError("Unsupported historical image format")
    safe_name = f"{checksum}{suffix}"
    directory = ROOT / "historical_cases" / str(case_id) / "images" / str(image_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / safe_name
    temporary = directory / f".{safe_name}.uploading"
    try:
        temporary.write_bytes(content)
        temporary.replace(destination)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return destination.relative_to(ROOT).as_posix(), checksum


def resolve_historical_image(storage_key: str) -> Path:
    candidate = (ROOT / storage_key).resolve()
    if not candidate.is_relative_to(ROOT):
        raise ValueError("Historical image path is outside the configured storage root")
    return candidate


def delete_historical_image(storage_key: str) -> None:
    path = resolve_historical_image(storage_key)
    path.unlink(missing_ok=True)
