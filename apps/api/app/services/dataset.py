import csv
import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PureWindowsPath
from typing import Any
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.historical_case import HistoricalCase
from app.config import settings
from app.services.historical_index import HistoricalIndexService, HistoricalIndexError
from app.models.historical_case_image import HistoricalCaseImage
from app.services.historical_image_index import HistoricalImageIndexService, HistoricalImageIndexError
from app.ai.clip_embeddings import load_valid_image
from app.storage.historical_images import store_historical_image, delete_historical_image

logger = logging.getLogger("coldsync.dataset")
NULLS = {"", "null", "none", "n/a", "na", "unknown", "-"}
DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%b-%Y", "%d %B %Y")


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    value = re.sub(r"\s+", " ", value).strip()
    if value.casefold() in NULLS:
        return None
    return value


def normalize_date(value: Any) -> date | None:
    if value is None or normalize_text(value) is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        for format_string in DATE_FORMATS:
            try:
                return datetime.strptime(raw, format_string).date()
            except ValueError:
                continue
    raise ValueError(f"Malformed date: {raw[:80]}")


@dataclass
class NormalizedCase:
    external_id: str | None
    fingerprint: str
    title: str
    summary: str | None
    description: str | None
    case_date: date | None
    location: str | None
    case_type: str | None
    status: str | None
    source_name: str | None
    source_url: str | None
    metadata: dict
    text_content: str
    images: list[dict]


def normalize_record(raw: dict[str, Any]) -> NormalizedCase:
    if not isinstance(raw, dict):
        raise ValueError("Record must be an object")
    if None in raw:
        raise ValueError("CSV row contains unexpected extra columns")
    external_id = next((candidate for key in ("external_id", "case_id", "id") if (candidate := normalize_text(raw.get(key))) is not None), None)
    title = normalize_text(raw.get("title"))
    if not title:
        raise ValueError("Missing required title")
    summary = normalize_text(raw.get("summary"))
    description = normalize_text(raw.get("description"))
    case_date = normalize_date(raw.get("date"))
    location = normalize_text(raw.get("location"))
    case_type = normalize_text(raw.get("case_type"))
    status = normalize_text(raw.get("status"))
    source_name = normalize_text(raw.get("source_name"))
    source_url = normalize_text(raw.get("source_url"))
    image_paths = raw.get("image_paths", raw.get("image_path"))
    image_urls = raw.get("image_urls", raw.get("image_url"))
    image_refs = raw.get("images", raw.get("image"))
    if isinstance(image_paths, str): image_paths = [image_paths]
    if isinstance(image_urls, str): image_urls = [image_urls]
    image_paths = image_paths if isinstance(image_paths, list) else []
    image_urls = image_urls if isinstance(image_urls, list) else []
    if isinstance(image_refs, (str, dict)):
        image_refs = [image_refs]
    image_refs = image_refs if isinstance(image_refs, list) else []
    images = []
    for index, value in enumerate(image_paths):
        if isinstance(value, dict):
            images.append({"path": normalize_text(value.get("path")), "url": normalize_text(value.get("image_url") or value.get("url")), "source_name": normalize_text(value.get("source_name")), "source_url": normalize_text(value.get("source_url"))})
        else:
            images.append({"path": normalize_text(value), "url": None, "source_name": None, "source_url": None})
    for value in image_urls:
        if isinstance(value, str) and normalize_text(value):
            images.append({"path": None, "url": normalize_text(value), "source_name": None, "source_url": None})
    for value in image_refs:
        if isinstance(value, dict):
            images.append({"path": normalize_text(value.get("path") or value.get("image_path")), "url": normalize_text(value.get("image_url") or value.get("url")), "source_name": normalize_text(value.get("source_name")), "source_url": normalize_text(value.get("source_url"))})
        elif isinstance(value, str) and normalize_text(value):
            reference = normalize_text(value)
            if reference.lower().startswith(("https://", "http://")):
                images.append({"path": None, "url": reference, "source_name": None, "source_url": None})
            else:
                images.append({"path": reference, "url": None, "source_name": None, "source_url": None})
    if not any((summary, description, case_date, location, case_type, status, *images)):
        raise ValueError("Case has no descriptive fields beyond its title")
    fields = [("Case Title", title), ("Summary", summary), ("Description", description), ("Date", case_date.isoformat() if case_date else None), ("Location", location), ("Case Type", case_type), ("Status", status)]
    text_content = "\n\n".join(f"{label}:\n{value}" for label, value in fields if value)
    canonical = "|".join((title.casefold(), case_date.isoformat() if case_date else "", (location or "").casefold(), (summary or "").casefold(), (description or "").casefold()))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    metadata = raw.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {"source_metadata_text": metadata}
    if not isinstance(metadata, dict):
        metadata = {}
    known = {"external_id", "case_id", "id", "title", "summary", "description", "date", "location", "case_type", "status", "source_name", "source_url", "metadata", "image_path", "image_paths", "image_url", "image_urls", "image", "images"}
    extra = {str(key): value for key, value in raw.items() if key not in known and key is not None and value not in (None, "")}
    if extra:
        metadata = {**metadata, "source_fields": extra}
    return NormalizedCase(external_id, fingerprint, title, summary, description, case_date, location, case_type, status, source_name, source_url, metadata, text_content, images)


def load_dataset(path: str | Path, format: str = "auto") -> list[tuple[int, dict[str, Any]]]:
    path = Path(path)
    selected = format.lower()
    if selected == "auto":
        suffix = path.suffix.lower()
        selected = {".csv": "csv", ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl"}.get(suffix, "")
    if selected not in {"csv", "json", "jsonl"}:
        raise ValueError("Dataset format must be CSV, JSON, or JSONL")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            if selected == "csv":
                return [(number, row) for number, row in enumerate(csv.DictReader(stream), start=2)]
            if selected == "jsonl":
                rows = []
                for number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    try:
                        rows.append((number, json.loads(line)))
                    except json.JSONDecodeError as exc:
                        rows.append((number, {"__invalid_record__": f"Invalid JSON: {exc.msg}"}))
                return rows
            data = json.load(stream)
    except UnicodeDecodeError as exc:
        raise ValueError(f"Dataset is not valid UTF-8 (byte {exc.start})") from None
    rows = data if isinstance(data, list) else data.get("cases", data.get("records")) if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("JSON dataset must be an array or an object with a cases/records array")
    return [(number, row) for number, row in enumerate(rows, start=1)]


@dataclass
class IngestionReport:
    total_records: int = 0
    valid_records: int = 0
    skipped_records: int = 0
    duplicates: int = 0
    invalid_records: int = 0
    errors: list[dict] = field(default_factory=list)
    index_status: str | None = None
    indexed_count: int = 0
    image_index_status: str | None = None
    image_indexed_count: int = 0

    def as_dict(self):
        return {"total_records": self.total_records, "valid_records": self.valid_records, "skipped_records": self.skipped_records, "duplicates": self.duplicates, "invalid_records": self.invalid_records, "errors": self.errors, "index_status": self.index_status, "indexed_count": self.indexed_count, "image_index_status": self.image_index_status, "image_indexed_count": self.image_indexed_count}


class HistoricalDatasetIngestor:
    def __init__(self, db: Session):
        self.db = db

    def ingest(self, path: str | Path, format: str = "auto", batch_size: int | None = None, rebuild: bool = False, progress=None) -> IngestionReport:
        dataset_path = Path(path).resolve()
        rows = load_dataset(path, format)
        report = IngestionReport(total_records=len(rows))
        seen_ids: set[str] = set()
        seen_fingerprints: set[str] = set()
        seen_external_ids: dict[str, str] = {}
        logger.info("Historical dataset started: %s records", report.total_records)
        for row_number, raw in rows:
            try:
                if isinstance(raw, dict) and "__invalid_record__" in raw:
                    raise ValueError(raw["__invalid_record__"])
                record = normalize_record(raw)
                if record.external_id and record.external_id in seen_external_ids:
                    if seen_external_ids[record.external_id] == record.fingerprint:
                        report.duplicates += 1
                    else:
                        report.invalid_records += 1
                        report.errors.append({"row": row_number, "reason": f"Duplicate external_id conflicts with an earlier row: {record.external_id}"})
                    report.skipped_records += 1
                    continue
                unique_key = f"id:{record.external_id}" if record.external_id else f"fingerprint:{record.fingerprint}"
                if unique_key in seen_ids or record.fingerprint in seen_fingerprints:
                    report.duplicates += 1
                    report.skipped_records += 1
                    continue
                seen_ids.add(unique_key)
                seen_fingerprints.add(record.fingerprint)
                if record.external_id:
                    seen_external_ids[record.external_id] = record.fingerprint
                existing_by_id = self.db.scalar(select(HistoricalCase).where(HistoricalCase.external_id == record.external_id)) if record.external_id else None
                existing_by_fingerprint = self.db.scalar(select(HistoricalCase).where(HistoricalCase.fingerprint == record.fingerprint))
                if existing_by_fingerprint is not None and existing_by_id is not None and existing_by_fingerprint.id != existing_by_id.id:
                    report.duplicates += 1
                    report.skipped_records += 1
                    continue
                if existing_by_fingerprint is not None and existing_by_id is None and record.external_id and existing_by_fingerprint.external_id not in {None, record.external_id}:
                    report.duplicates += 1
                    report.skipped_records += 1
                    continue
                existing = existing_by_id or existing_by_fingerprint
                values = {"external_id": record.external_id, "fingerprint": record.fingerprint, "title": record.title, "summary": record.summary, "description": record.description, "case_date": record.case_date, "location": record.location, "case_type": record.case_type, "status": record.status, "source_name": record.source_name, "source_url": record.source_url, "metadata_json": record.metadata, "text_content": record.text_content}
                if existing:
                    for key, value in values.items():
                        setattr(existing, key, value)
                else:
                    self.db.add(HistoricalCase(**values))
                    self.db.flush()
                    existing = self.db.scalar(select(HistoricalCase).where(HistoricalCase.fingerprint == record.fingerprint))
                for image_ref in record.images:
                    image_url = image_ref.get("url")
                    image_path = image_ref.get("path")
                    image_row = None
                    if image_path:
                        relative_image_path = Path(image_path.replace("\\", "/"))
                        if relative_image_path.is_absolute() or PureWindowsPath(image_path).is_absolute() or PureWindowsPath(image_path).drive:
                            report.errors.append({"row": row_number, "reason": "Historical image paths must be relative to the dataset directory."})
                            continue
                        candidate = (dataset_path.parent / relative_image_path).resolve()
                        if not candidate.is_relative_to(dataset_path.parent):
                            report.errors.append({"row": row_number, "reason": "Historical image path must remain inside the dataset directory."})
                            continue
                        if not candidate.is_file():
                            report.errors.append({"row": row_number, "reason": f"Historical image file is missing: {Path(image_path).name}"})
                            continue
                        if candidate.stat().st_size > settings.max_evidence_file_size_mb * 1024 * 1024:
                            report.errors.append({"row": row_number, "reason": f"Historical image exceeds the configured {settings.max_evidence_file_size_mb} MB limit."})
                            continue
                        content = candidate.read_bytes()
                        try:
                            load_valid_image(content)
                        except ValueError:
                            report.errors.append({"row": row_number, "reason": f"Historical image is corrupted or unsupported: {candidate.name}"})
                            continue
                        checksum = hashlib.sha256(content).hexdigest()
                        image_row = self.db.scalar(select(HistoricalCaseImage).where(HistoricalCaseImage.historical_case_id == existing.id, HistoricalCaseImage.checksum == checksum))
                        if image_row is None:
                            image_id = uuid.uuid4()
                            storage_path, checksum = store_historical_image(existing.id, image_id, candidate.name, content)
                            image_row = HistoricalCaseImage(id=image_id, historical_case_id=existing.id, image_url=image_url, storage_path=storage_path, source_name=image_ref.get("source_name") or record.source_name, source_url=image_ref.get("source_url") or record.source_url, mime_type={".jpg":"image/jpeg", ".png":"image/png", ".webp":"image/webp"}.get(Path(storage_path).suffix.lower()), checksum=checksum, metadata_json={})
                            self.db.add(image_row)
                            try:
                                self.db.flush()
                            except Exception:
                                delete_historical_image(storage_path)
                                raise
                        else:
                            image_row.image_url = image_url or image_row.image_url
                            image_row.source_name = image_ref.get("source_name") or record.source_name or image_row.source_name
                            image_row.source_url = image_ref.get("source_url") or record.source_url or image_row.source_url
                    elif image_url:
                        image_row = self.db.scalar(select(HistoricalCaseImage).where(HistoricalCaseImage.historical_case_id == existing.id, HistoricalCaseImage.image_url == image_url))
                        if image_row is None:
                            image_row = HistoricalCaseImage(historical_case_id=existing.id, image_url=image_url, source_name=image_ref.get("source_name") or record.source_name, source_url=image_ref.get("source_url") or record.source_url, metadata_json={})
                            self.db.add(image_row)
                            self.db.flush()
                report.valid_records += 1
            except Exception as exc:
                report.invalid_records += 1
                report.skipped_records += 1
                report.errors.append({"row": row_number, "reason": str(exc)[:300]})
        self.db.commit()
        logger.info("Historical dataset validated: valid=%s skipped=%s duplicates=%s invalid=%s", report.valid_records, report.skipped_records, report.duplicates, report.invalid_records)
        try:
            index_report = HistoricalIndexService(self.db).rebuild(batch_size=batch_size or settings.sbert_batch_size, force=rebuild, progress=progress)
            report.index_status = index_report["status"]
            report.indexed_count = index_report["indexed_count"]
        except HistoricalIndexError:
            report.index_status = "FAILED"
            report.errors.append({"row": 0, "reason": "PostgreSQL ingestion succeeded, but vector indexing failed; historical search is unavailable until the index is rebuilt."})
        try:
            image_report = HistoricalImageIndexService(self.db).rebuild(batch_size=batch_size or settings.clip_batch_size, force=rebuild, progress=progress)
            report.image_index_status = image_report["status"]
            report.image_indexed_count = image_report["indexed_count"]
        except HistoricalImageIndexError:
            report.image_index_status = "FAILED"
            report.errors.append({"row": 0, "reason": "Historical case ingestion succeeded, but CLIP image indexing failed; image search is unavailable until the index is rebuilt."})
        return report
