from abc import ABC, abstractmethod
from pathlib import Path
from uuid import UUID


class EvidenceStorage(ABC):
    @abstractmethod
    def save(self, investigation_id: UUID, evidence_id: UUID, filename: str, content: bytes) -> str: ...

    @abstractmethod
    def resolve(self, storage_key: str) -> Path: ...

    @abstractmethod
    def delete(self, storage_key: str | None) -> None: ...

    @abstractmethod
    def stage_delete(self, storage_key: str | None) -> tuple[Path, Path] | None: ...

    @abstractmethod
    def finish_delete(self, staged: tuple[Path, Path] | None) -> None: ...

    @abstractmethod
    def restore_delete(self, staged: tuple[Path, Path] | None) -> None: ...
