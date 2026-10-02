from pathlib import Path
from uuid import UUID, uuid4
from app.storage.base import EvidenceStorage


class LocalEvidenceStorage(EvidenceStorage):
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def save(self, investigation_id: UUID, evidence_id: UUID, filename: str, content: bytes) -> str:
        directory = self.root / "investigations" / str(investigation_id) / "evidence" / str(evidence_id)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / filename
        temporary = directory / f".{filename}.uploading"
        try:
            temporary.write_bytes(content)
            temporary.replace(destination)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        return destination.relative_to(self.root).as_posix()

    def resolve(self, storage_key: str) -> Path:
        candidate = (self.root / storage_key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ValueError("Storage path is outside the evidence root")
        return candidate

    def delete(self, storage_key: str | None) -> None:
        if not storage_key:
            return
        path = self.resolve(storage_key)
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != self.root and parent.is_relative_to(self.root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def stage_delete(self, storage_key: str | None):
        if not storage_key:
            return None
        path = self.resolve(storage_key)
        if not path.exists():
            return None
        tombstone = path.with_name(f".{path.name}.{uuid4().hex}.deleting")
        path.replace(tombstone)
        return path, tombstone

    def finish_delete(self, staged) -> None:
        if not staged:
            return
        original, tombstone = staged
        tombstone.unlink(missing_ok=True)
        parent = original.parent
        while parent != self.root and parent.is_relative_to(self.root):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def restore_delete(self, staged) -> None:
        if not staged:
            return
        original, tombstone = staged
        if tombstone.exists():
            tombstone.replace(original)
