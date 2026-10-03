import enum
import uuid
from datetime import datetime, date
from sqlalchemy import Date, DateTime, Enum, ForeignKey, Float, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base

class LocationPrecision(str,enum.Enum):
    EXACT_POINT="EXACT_POINT"; STREET="STREET"; NEIGHBORHOOD="NEIGHBORHOOD"; LOCALITY="LOCALITY"; CITY="CITY"; DISTRICT="DISTRICT"; STATE="STATE"; COUNTRY="COUNTRY"; REGION="REGION"; APPROXIMATE="APPROXIMATE"; UNKNOWN="UNKNOWN"
class GeocodingStatus(str,enum.Enum):
    PENDING="PENDING"; GEOCODED="GEOCODED"; PARTIAL="PARTIAL"; FAILED="FAILED"; NOT_FOUND="NOT_FOUND"; NOT_ATTEMPTED="NOT_ATTEMPTED"
class GeoConfidence(str,enum.Enum):
    HIGH="HIGH"; MEDIUM="MEDIUM"; LOW="LOW"; UNKNOWN="UNKNOWN"
class Location(Base):
    __tablename__="locations"
    __table_args__=(UniqueConstraint("investigation_id","normalized_name","raw_text",name="uq_location_investigation_raw_normalized"),)
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid())
    investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True)
    raw_text:Mapped[str]=mapped_column(String(1000),nullable=False); normalized_name:Mapped[str]=mapped_column(String(1000),nullable=False,index=True)
    latitude:Mapped[float|None]=mapped_column(Float); longitude:Mapped[float|None]=mapped_column(Float)
    precision:Mapped[LocationPrecision]=mapped_column(Enum(LocationPrecision,native_enum=False,length=24),nullable=False,default=LocationPrecision.UNKNOWN)
    geocoding_status:Mapped[GeocodingStatus]=mapped_column(Enum(GeocodingStatus,native_enum=False,length=24),nullable=False,default=GeocodingStatus.NOT_ATTEMPTED)
    geocoding_source:Mapped[str|None]=mapped_column(String(120)); geocoding_provider:Mapped[str|None]=mapped_column(String(120)); confidence_label:Mapped[GeoConfidence]=mapped_column(Enum(GeoConfidence,native_enum=False,length=16),nullable=False,default=GeoConfidence.UNKNOWN)
    country:Mapped[str|None]=mapped_column(String(200)); state:Mapped[str|None]=mapped_column(String(200)); district:Mapped[str|None]=mapped_column(String(200)); city:Mapped[str|None]=mapped_column(String(200)); locality:Mapped[str|None]=mapped_column(String(300))
    metadata_json:Mapped[dict]=mapped_column("metadata",JSON,nullable=False,default=dict,server_default="{}")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now());updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

class TimelineEventLocation(Base):
    __tablename__="timeline_event_locations";__table_args__=(UniqueConstraint("timeline_event_id","location_id","relationship_type",name="uq_timeline_location_link"),)
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());timeline_event_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("timeline_events.id",ondelete="CASCADE"),nullable=False,index=True);location_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("locations.id",ondelete="CASCADE"),nullable=False,index=True);relationship_type:Mapped[str]=mapped_column(String(32),nullable=False,default="REPORTED_LOCATION");created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
class EvidenceLocation(Base):
    __tablename__="evidence_locations";__table_args__=(UniqueConstraint("evidence_id","location_id","relationship_type",name="uq_evidence_location_link"),)
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());evidence_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("evidence.id",ondelete="CASCADE"),nullable=False,index=True);location_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("locations.id",ondelete="CASCADE"),nullable=False,index=True);relationship_type:Mapped[str]=mapped_column(String(32),nullable=False,default="REPORTED_LOCATION");created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
class HistoricalCaseLocation(Base):
    __tablename__="historical_case_locations";__table_args__=(UniqueConstraint("historical_case_id","location_id","relationship_type",name="uq_historical_location_link"),)
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());historical_case_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("historical_cases.id",ondelete="CASCADE"),nullable=False,index=True);location_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("locations.id",ondelete="CASCADE"),nullable=False,index=True);relationship_type:Mapped[str]=mapped_column(String(32),nullable=False,default="REPORTED_LOCATION");created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
class SourceLocation(Base):
    __tablename__="source_locations";__table_args__=(UniqueConstraint("source_id","location_id","relationship_type",name="uq_source_location_link"),)
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());source_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("web_sources.id",ondelete="CASCADE"),nullable=False,index=True);location_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("locations.id",ondelete="CASCADE"),nullable=False,index=True);relationship_type:Mapped[str]=mapped_column(String(32),nullable=False,default="REFERENCE_LOCATION");created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())

class ContradictionType(str,enum.Enum):
    DATE_CONFLICT="DATE_CONFLICT";LOCATION_CONFLICT="LOCATION_CONFLICT";TIME_CONFLICT="TIME_CONFLICT";ATTRIBUTE_CONFLICT="ATTRIBUTE_CONFLICT";ENTITY_CONFLICT="ENTITY_CONFLICT";IDENTITY_ATTRIBUTE_CONFLICT="IDENTITY_ATTRIBUTE_CONFLICT";TIMELINE_CONFLICT="TIMELINE_CONFLICT";SOURCE_CONFLICT="SOURCE_CONFLICT";DESCRIPTION_CONFLICT="DESCRIPTION_CONFLICT";NUMERIC_CONFLICT="NUMERIC_CONFLICT";EVENT_CONFLICT="EVENT_CONFLICT";STATUS_CONFLICT="STATUS_CONFLICT"
class ContradictionSeverity(str,enum.Enum):
    LOW="LOW";MEDIUM="MEDIUM";HIGH="HIGH"
class ContradictionStatus(str,enum.Enum):
    OPEN="OPEN";UNDER_REVIEW="UNDER_REVIEW";REQUIRES_VERIFICATION="REQUIRES_VERIFICATION";REVIEWED="REVIEWED";RESOLVED="RESOLVED";DISMISSED="DISMISSED"
class Contradiction(Base):
    __tablename__="contradictions"
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True)
    type:Mapped[ContradictionType]=mapped_column(Enum(ContradictionType,native_enum=False,length=32),nullable=False);severity:Mapped[ContradictionSeverity]=mapped_column(Enum(ContradictionSeverity,native_enum=False,length=16),nullable=False,default=ContradictionSeverity.MEDIUM);description:Mapped[str]=mapped_column(Text,nullable=False)
    subject_type:Mapped[str|None]=mapped_column(String(40));subject_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True));source_a_type:Mapped[str]=mapped_column(String(40),nullable=False);source_a_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),nullable=False);source_b_type:Mapped[str]=mapped_column(String(40),nullable=False);source_b_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),nullable=False)
    value_a:Mapped[str|None]=mapped_column(Text);value_b:Mapped[str|None]=mapped_column(Text);date_a:Mapped[date|None]=mapped_column(Date);date_b:Mapped[date|None]=mapped_column(Date);location_a_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("locations.id",ondelete="SET NULL"));location_b_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("locations.id",ondelete="SET NULL"))
    status:Mapped[ContradictionStatus]=mapped_column(Enum(ContradictionStatus,native_enum=False,length=24),nullable=False,default=ContradictionStatus.OPEN);investigator_note:Mapped[str|None]=mapped_column(Text);metadata_json:Mapped[dict]=mapped_column("metadata",JSON,nullable=False,default=dict,server_default="{}");fingerprint:Mapped[str|None]=mapped_column(String(64),unique=True,index=True);priority:Mapped[str]=mapped_column(String(8),nullable=False,default="MEDIUM",server_default="MEDIUM");date_precision:Mapped[str|None]=mapped_column(String(16));related_event_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("timeline_events.id",ondelete="SET NULL"));created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now());updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())
