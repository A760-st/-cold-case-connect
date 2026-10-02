import io
import os
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.session import Base, get_db
from app.main import app
from app.storage.local import LocalEvidenceStorage
from app.services import evidence as evidence_service

engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread":False}, poolclass=StaticPool)
@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(connection, _):
    connection.execute("PRAGMA foreign_keys=ON")
TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

@pytest.fixture(autouse=True)
def reset_db():
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(evidence_service, "storage", LocalEvidenceStorage(tmp_path / "evidence"))
    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()

def make_investigation(client, title="Case"):
    response = client.post("/api/v1/investigations", json={"title":title})
    assert response.status_code == 201
    return response.json()["data"]["id"]

def make_png():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), color="green").save(buffer, format="PNG")
    return buffer.getvalue()

def test_text_evidence_crud_and_filter(client):
    investigation_id = make_investigation(client)
    created = client.post(f"/api/v1/investigations/{investigation_id}/evidence", json={"title":"Witness statement", "description":"Collected note", "text_content":"Line one\r\nLine two"})
    assert created.status_code == 201
    evidence = created.json()["data"]
    assert evidence["type"] == "TEXT" and evidence["processing_status"] == "READY"
    assert evidence["text_content"] == "Line one\nLine two"
    assert len(evidence["checksum"]) == 64
    assert client.get(f"/api/v1/investigations/{investigation_id}/evidence?type=TEXT").json()["data"][0]["id"] == evidence["id"]
    assert client.get(f"/api/v1/evidence/{evidence['id']}").json()["data"]["text_content"] == "Line one\nLine two"
    assert client.patch(f"/api/v1/evidence/{evidence['id']}", json={"title":"Verified statement","metadata":{"review":"pending"}}).json()["data"]["title"] == "Verified statement"
    assert client.get(f"/api/v1/evidence/{evidence['id']}/content").json()["data"]["text_content"] == "Line one\nLine two"
    assert client.delete(f"/api/v1/evidence/{evidence['id']}").status_code == 204
    assert client.get(f"/api/v1/evidence/{evidence['id']}").json()["error"]["code"] == "EVIDENCE_NOT_FOUND"

def test_image_upload_checksum_metadata_content_and_delete(client, tmp_path):
    investigation_id = make_investigation(client)
    payload = make_png()
    created = client.post(f"/api/v1/investigations/{investigation_id}/evidence/upload", data={"title":"Scene image"}, files={"file":("scene.png", payload, "image/png")})
    assert created.status_code == 201
    record = created.json()["data"]
    assert record["type"] == "IMAGE" and record["file_size"] == len(payload)
    assert record["metadata"]["width"] == 4 and record["metadata"]["height"] == 3
    assert record["checksum"]
    content = client.get(f"/api/v1/evidence/{record['id']}/content")
    assert content.content == payload and content.headers["x-content-type-options"] == "nosniff"
    assert client.delete(f"/api/v1/evidence/{record['id']}").status_code == 204
    assert not list((tmp_path / "evidence").rglob("scene.png"))

def test_invalid_type_too_large_and_missing_investigation(client, monkeypatch):
    investigation_id = make_investigation(client)
    bad = client.post(f"/api/v1/investigations/{investigation_id}/evidence/upload", files={"file":("photo.png", b"not an image", "image/png")})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_FILE_TYPE"
    monkeypatch.setattr(evidence_service, "MAX_BYTES", 5)
    oversized = client.post(f"/api/v1/investigations/{investigation_id}/evidence/upload", files={"file":("photo.png", make_png(), "image/png")})
    assert oversized.status_code == 413 and oversized.json()["error"]["code"] == "FILE_TOO_LARGE"
    missing = client.post("/api/v1/investigations/00000000-0000-0000-0000-000000000001/evidence", json={"title":"Statement", "text_content":"Text"})
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "INVESTIGATION_NOT_FOUND"

def test_video_metadata_other_text_file_and_filename_safety(client, tmp_path):
    investigation_id = make_investigation(client)
    video = client.post(f"/api/v1/investigations/{investigation_id}/evidence", json={"type":"VIDEO_METADATA", "title":"Camera reference", "description":"Video retained externally", "metadata":{"duration_seconds":42}})
    assert video.status_code == 201
    assert video.json()["data"]["type"] == "VIDEO_METADATA"
    assert video.json()["data"]["text_content"] is None
    assert video.json()["data"]["metadata"]["source"] == "investigator_entered"
    text_file = client.post(f"/api/v1/investigations/{investigation_id}/evidence/upload", files={"file":("../../notes.txt", b"safe text", "text/plain")})
    assert text_file.status_code == 201
    assert text_file.json()["data"]["original_filename"] == "notes.txt"
    assert text_file.json()["data"]["type"] == "DOCUMENT"

def test_deleting_investigation_removes_file(client, tmp_path):
    investigation_id = make_investigation(client)
    uploaded = client.post(f"/api/v1/investigations/{investigation_id}/evidence/upload", files={"file":("scene.png", make_png(), "image/png")})
    assert uploaded.status_code == 201
    image_files = list((tmp_path / "evidence").rglob("scene.png"))
    assert len(image_files) == 1
    # Point the investigation cascade cleanup at the same test storage root.
    from app.config import settings
    original_storage_dir = settings.evidence_storage_dir
    settings.evidence_storage_dir = str(tmp_path / "evidence")
    try:
        assert client.delete(f"/api/v1/investigations/{investigation_id}").status_code == 204
        assert not image_files[0].exists()
    finally:
        settings.evidence_storage_dir = original_storage_dir

def test_cross_investigation_isolation_and_path_traversal(client, tmp_path):
    first, second = make_investigation(client, "A"), make_investigation(client, "B")
    created = client.post(f"/api/v1/investigations/{first}/evidence", json={"title":"Private note", "text_content":"Only for A"}).json()["data"]
    assert client.get(f"/api/v1/investigations/{second}/evidence").json()["data"] == []
    storage = LocalEvidenceStorage(tmp_path / "root")
    with pytest.raises(ValueError):
        storage.resolve("../../outside.txt")
    assert client.get(f"/api/v1/evidence/{created['id']}").json()["data"]["investigation_id"] == first
