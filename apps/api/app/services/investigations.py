from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.investigation import Investigation, InvestigationStatus
from app.schemas.investigation import InvestigationCreate, InvestigationUpdate
from app.models.evidence import Evidence
from app.storage import LocalEvidenceStorage
from app.config import settings
import logging

logger = logging.getLogger("coldsync.investigations")


class InvestigationService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, payload: InvestigationCreate) -> Investigation:
        item = Investigation(title=payload.title.strip(), description=payload.description.strip(), status=InvestigationStatus.ACTIVE)
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)
        return item

    def list(self) -> list[Investigation]:
        return list(self.db.scalars(select(Investigation).order_by(Investigation.updated_at.desc())))

    def get(self, investigation_id: UUID) -> Investigation | None:
        return self.db.get(Investigation, investigation_id)

    def update(self, investigation_id: UUID, payload: InvestigationUpdate) -> Investigation | None:
        item = self.get(investigation_id)
        if item is None:
            return None
        for key, value in payload.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(item, key, value.strip() if isinstance(value, str) and key in {"title", "description"} else value)
        self.db.commit()
        self.db.refresh(item)
        return item

    def delete(self, investigation_id: UUID) -> bool:
        item = self.get(investigation_id)
        if item is None:
            return False
        evidence = list(self.db.scalars(select(Evidence).where(Evidence.investigation_id == investigation_id)))
        storage = LocalEvidenceStorage(settings.evidence_storage_dir)
        staged = []
        try:
            for record in evidence:
                staged.append(storage.stage_delete(record.storage_path))
            self.db.delete(item)
            self.db.commit()
        except Exception:
            self.db.rollback()
            for entry in reversed(staged):
                storage.restore_delete(entry)
            raise
        for entry in staged:
            try:
                storage.finish_delete(entry)
            except OSError:
                logger.exception("Evidence file cleanup failed after investigation deletion")
        return True
