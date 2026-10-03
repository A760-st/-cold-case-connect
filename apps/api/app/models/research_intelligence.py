import enum
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Enum, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base


class ResearchGapType(str, enum.Enum):
    MISSING_DATE="MISSING_DATE"; MISSING_LOCATION="MISSING_LOCATION"; MISSING_EVENT_DETAIL="MISSING_EVENT_DETAIL"; MISSING_SOURCE="MISSING_SOURCE"; MISSING_EVIDENCE="MISSING_EVIDENCE"; MISSING_ENTITY_ATTRIBUTE="MISSING_ENTITY_ATTRIBUTE"; MISSING_TIMELINE_EVENT="MISSING_TIMELINE_EVENT"; MISSING_HISTORICAL_CONTEXT="MISSING_HISTORICAL_CONTEXT"; MISSING_PUBLIC_RECORD="MISSING_PUBLIC_RECORD"; INSUFFICIENT_SOURCE_COVERAGE="INSUFFICIENT_SOURCE_COVERAGE"; CONTRADICTORY_INFORMATION="CONTRADICTORY_INFORMATION"; UNRESOLVED_ENTITY="UNRESOLVED_ENTITY"; UNRESOLVED_LOCATION="UNRESOLVED_LOCATION"; UNRESOLVED_TIMELINE="UNRESOLVED_TIMELINE"; UNDER_RESEARCHED_PERIOD="UNDER_RESEARCHED_PERIOD"; UNDER_RESEARCHED_LOCATION="UNDER_RESEARCHED_LOCATION"; UNDER_RESEARCHED_ENTITY="UNDER_RESEARCHED_ENTITY"; UNANSWERED_QUESTION="UNANSWERED_QUESTION"; LOCATION_PRECISION_GAP="LOCATION_PRECISION_GAP"; UNREVIEWED_CORRELATION="UNREVIEWED_CORRELATION"

class ResearchGapStatus(str, enum.Enum):
    OPEN="OPEN"; RESEARCHING="RESEARCHING"; SUFFICIENTLY_ADDRESSED="SUFFICIENTLY_ADDRESSED"; DISMISSED="DISMISSED"

class InvestigationQuestionStatus(str, enum.Enum):
    OPEN="OPEN"; RESEARCHING="RESEARCHING"; PARTIALLY_ADDRESSED="PARTIALLY_ADDRESSED"; ANSWERED="ANSWERED"; DISMISSED="DISMISSED"

class ResearchGap(Base):
    __tablename__="research_gaps"
    __table_args__=(UniqueConstraint("investigation_id","fingerprint",name="uq_research_gap_fingerprint"),Index("ix_research_gaps_investigation_status","investigation_id","status"))
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid())
    investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True)
    gap_type:Mapped[ResearchGapType]=mapped_column(Enum(ResearchGapType,native_enum=False,length=40),nullable=False,index=True)
    title:Mapped[str]=mapped_column(String(300),nullable=False);description:Mapped[str]=mapped_column(Text,nullable=False)
    priority:Mapped[str]=mapped_column(String(8),nullable=False,default="MEDIUM",server_default="MEDIUM")
    status:Mapped[ResearchGapStatus]=mapped_column(Enum(ResearchGapStatus,native_enum=False,length=24),nullable=False,default=ResearchGapStatus.OPEN,index=True)
    subject_type:Mapped[str|None]=mapped_column(String(40));subject_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True))
    related_evidence_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]");related_source_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    related_timeline_event_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]");related_location_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    related_correlation_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]");related_contradiction_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    suggested_research_actions:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    fingerprint:Mapped[str]=mapped_column(String(64),nullable=False)
    investigator_note:Mapped[str|None]=mapped_column(Text)
    last_agent_run_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("agent_runs.id",ondelete="SET NULL"))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now());updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

class InvestigationQuestion(Base):
    __tablename__="investigation_questions"
    __table_args__=(Index("ix_questions_investigation_status","investigation_id","status"),)
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid())
    investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True)
    question:Mapped[str]=mapped_column(String(1000),nullable=False)
    status:Mapped[InvestigationQuestionStatus]=mapped_column(Enum(InvestigationQuestionStatus,native_enum=False,length=24),nullable=False,default=InvestigationQuestionStatus.OPEN,index=True)
    priority:Mapped[str]=mapped_column(String(8),nullable=False,default="MEDIUM",server_default="MEDIUM")
    related_evidence_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]");related_timeline_event_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    related_location_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]");related_source_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    related_gap_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    last_agent_run_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("agent_runs.id",ondelete="SET NULL"))
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now());updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())
