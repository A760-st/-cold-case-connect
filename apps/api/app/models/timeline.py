import enum, uuid
from datetime import datetime, date
from sqlalchemy import Date, DateTime, Enum, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base

class TimelineEventType(str, enum.Enum):
    CASE_CREATED="CASE_CREATED"; INCIDENT="INCIDENT"; EVIDENCE_COLLECTED="EVIDENCE_COLLECTED"; PERSON_REPORTED="PERSON_REPORTED"; LOCATION_REPORTED="LOCATION_REPORTED"; SEARCH_RESULT="SEARCH_RESULT"; NEWS_REPORT="NEWS_REPORT"; HISTORICAL_CASE="HISTORICAL_CASE"; PUBLICATION="PUBLICATION"; INVESTIGATOR_NOTE="INVESTIGATOR_NOTE"; OTHER="OTHER"
class TimelineDatePrecision(str, enum.Enum):
    EXACT="EXACT"; DAY="DAY"; MONTH="MONTH"; YEAR="YEAR"; RANGE="RANGE"; APPROXIMATE="APPROXIMATE"; UNKNOWN="UNKNOWN"
class TimelineSourceType(str, enum.Enum):
    EVIDENCE="EVIDENCE"; HISTORICAL_CASE="HISTORICAL_CASE"; WEB_RESULT="WEB_RESULT"; NEWS_RESULT="NEWS_RESULT"; IMAGE_RESULT="IMAGE_RESULT"; SOURCE="SOURCE"; INVESTIGATOR="INVESTIGATOR"
class TimelineStatus(str, enum.Enum):
    AI_EXTRACTED="AI_EXTRACTED"; INVESTIGATOR_ADDED="INVESTIGATOR_ADDED"; REVIEWED="REVIEWED"; DISMISSED="DISMISSED"
class TimelineImportance(str, enum.Enum):
    LOW="LOW"; MEDIUM="MEDIUM"; HIGH="HIGH"
class TimelineEvent(Base):
    __tablename__="timeline_events"
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid())
    investigation_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True)
    title: Mapped[str]=mapped_column(String(500),nullable=False); description: Mapped[str]=mapped_column(Text,nullable=False,default="",server_default="")
    event_type: Mapped[TimelineEventType]=mapped_column(Enum(TimelineEventType,native_enum=False,length=32),nullable=False)
    date_start: Mapped[date|None]=mapped_column(Date); date_end: Mapped[date|None]=mapped_column(Date)
    date_precision: Mapped[TimelineDatePrecision]=mapped_column(Enum(TimelineDatePrecision,native_enum=False,length=16),nullable=False)
    date_text: Mapped[str]=mapped_column(String(500),nullable=False,default="",server_default="")
    publication_date_start: Mapped[date|None]=mapped_column(Date); publication_date_end: Mapped[date|None]=mapped_column(Date)
    location: Mapped[str|None]=mapped_column(String(500)); normalized_location: Mapped[str|None]=mapped_column(String(500))
    source_type: Mapped[TimelineSourceType|None]=mapped_column(Enum(TimelineSourceType,native_enum=False,length=32)); source_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True))
    historical_case_id: Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("historical_cases.id",ondelete="SET NULL"))
    correlation_ids: Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]")
    importance: Mapped[TimelineImportance]=mapped_column(Enum(TimelineImportance,native_enum=False,length=16),nullable=False,default=TimelineImportance.MEDIUM)
    status: Mapped[TimelineStatus]=mapped_column(Enum(TimelineStatus,native_enum=False,length=24),nullable=False,default=TimelineStatus.AI_EXTRACTED)
    created_by: Mapped[str]=mapped_column(String(24),nullable=False,default="AI")
    extraction_hash: Mapped[str|None]=mapped_column(String(64),index=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now()); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

class TimelineEventSource(Base):
    __tablename__="timeline_event_sources"
    __table_args__=(UniqueConstraint("timeline_event_id","source_type","source_id",name="uq_timeline_event_source"),)
    id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid())
    timeline_event_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("timeline_events.id",ondelete="CASCADE"),nullable=False,index=True)
    source_type: Mapped[TimelineSourceType]=mapped_column(Enum(TimelineSourceType,native_enum=False,length=32),nullable=False); source_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),nullable=False)
    relationship_type: Mapped[str]=mapped_column(String(24),nullable=False,default="SUPPORTING_SOURCE")
    content_hash: Mapped[str|None]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
class TimelineEventEvidence(Base):
    __tablename__="timeline_event_evidence"
    timeline_event_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("timeline_events.id",ondelete="CASCADE"),primary_key=True)
    evidence_id: Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("evidence.id",ondelete="CASCADE"),primary_key=True)
    relationship_type: Mapped[str]=mapped_column(String(24),nullable=False,default="SUPPORTING_EVIDENCE")
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
