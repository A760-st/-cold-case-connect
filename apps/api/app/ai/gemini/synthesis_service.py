import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gemini.client import GeminiClient
from app.ai.gemini.config import PROMPT_VERSION
from app.ai.gemini.context_builder import InvestigationContextBuilder, InvestigationContextProvider
from app.ai.gemini.safety import list_known_refs, validate_synthesis_references
from app.config import settings
from app.models.investigation import Investigation
from app.models.investigation_synthesis import InvestigationSynthesis, InvestigationSynthesisReview, InvestigationSynthesisStatus


class InvestigationSynthesisService:
    def __init__(self, db: Session):
        self.db = db

    def generate(self, investigation_id, force: bool = False):
        investigation = self.db.get(Investigation, investigation_id)
        if investigation is None:
            raise ValueError("INVESTIGATION_NOT_FOUND")

        context_builder = InvestigationContextBuilder(self.db, investigation_id)
        context = context_builder.build()
        context_hash = context_builder.hash_context(context)
        latest = self._latest(investigation_id)
        if not force and latest and latest.context_hash == context_hash and latest.status == InvestigationSynthesisStatus.COMPLETED.value:
            return latest

        version = (latest.version if latest else 0) + 1
        record = InvestigationSynthesis(
            investigation_id=investigation_id,
            version=version,
            status=InvestigationSynthesisStatus.QUEUED.value,
            model_name=settings.gemini_model,
            prompt_version=PROMPT_VERSION,
            context_hash=context_hash,
            generated_at=datetime.now(timezone.utc),
            executive_summary="Preparing investigation context",
            source_count=len(context.get("sources", [])),
            evidence_count=len(context.get("evidence", [])),
            claim_count=len(context.get("claims", [])),
            contradiction_count=len(context.get("contradictions", [])),
            research_gap_count=len(context.get("research_gaps", [])),
            token_usage={},
            metadata={"context_size": len(json.dumps(context, sort_keys=True))},
        )
        self.db.add(record)
        self.db.flush()

        record.status = InvestigationSynthesisStatus.BUILDING_CONTEXT.value
        self.db.flush()
        context["context_hash"] = context_hash
        record.status = InvestigationSynthesisStatus.GENERATING.value
        self.db.flush()

        synthesized = GeminiClient().generate(context)
        synthesized = validate_synthesis_references(synthesized, list_known_refs(context))
        record.status = InvestigationSynthesisStatus.VALIDATING.value
        self.db.flush()

        record.executive_summary = synthesized.get("executive_summary", "")
        record.synthesis_json = synthesized
        record.completed_at = datetime.now(timezone.utc)
        record.status = InvestigationSynthesisStatus.COMPLETED.value
        record.model_name = settings.gemini_model or "mock-model"
        record.token_usage = {
            "prompt_tokens": len(json.dumps(context, sort_keys=True)) // 4,
            "completion_tokens": len(json.dumps(synthesized, sort_keys=True)) // 4,
            "total_tokens": (len(json.dumps(context, sort_keys=True)) + len(json.dumps(synthesized, sort_keys=True))) // 4,
        }
        self.db.flush()

        if latest and latest.status == InvestigationSynthesisStatus.COMPLETED.value:
            latest.status = InvestigationSynthesisStatus.SUPERSEDED.value

        self.db.commit()
        return record

    def _latest(self, investigation_id):
        return self.db.scalar(
            select(InvestigationSynthesis)
            .where(InvestigationSynthesis.investigation_id == investigation_id)
            .order_by(InvestigationSynthesis.version.desc(), InvestigationSynthesis.generated_at.desc())
        )

    def list_versions(self, investigation_id):
        return self.db.scalars(
            select(InvestigationSynthesis)
            .where(InvestigationSynthesis.investigation_id == investigation_id)
            .order_by(InvestigationSynthesis.version.desc(), InvestigationSynthesis.created_at.desc())
        ).all()

    def get_by_id(self, synthesis_id):
        return self.db.get(InvestigationSynthesis, synthesis_id)

    def get_current(self, investigation_id):
        return self._latest(investigation_id)

    def regenerate(self, synthesis_id, force: bool = True):
        synthesis = self.get_by_id(synthesis_id)
        if synthesis is None:
            raise ValueError("SYNTHESIS_NOT_FOUND")
        return self.generate(synthesis.investigation_id, force=True)

    def create_review(self, synthesis_id, investigation_id, section, item_reference, review_status, note):
        review = InvestigationSynthesisReview(
            synthesis_id=synthesis_id,
            investigation_id=investigation_id,
            section=section,
            item_reference=item_reference,
            review_status=review_status,
            note=note,
        )
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    def list_reviews(self, synthesis_id):
        return self.db.scalars(
            select(InvestigationSynthesisReview)
            .where(InvestigationSynthesisReview.synthesis_id == synthesis_id)
            .order_by(InvestigationSynthesisReview.created_at.desc())
        ).all()


class InvestigationContextProvider:
    def __init__(self, db, investigation_id):
        self.db = db
        self.investigation_id = investigation_id

    def get_context(self):
        return InvestigationContextBuilder(self.db, self.investigation_id).build()

    def get_latest_synthesis(self):
        return InvestigationSynthesisService(self.db).get_current(self.investigation_id)
