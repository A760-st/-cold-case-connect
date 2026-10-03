import enum, uuid
from datetime import datetime
from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.database.session import Base

class ClaimType(str,enum.Enum):
    DATE="DATE"; TIME="TIME"; LOCATION="LOCATION"; PERSON="PERSON"; ORGANIZATION="ORGANIZATION"; VEHICLE="VEHICLE"; OBJECT="OBJECT"; EVENT="EVENT"; DESCRIPTION="DESCRIPTION"; RELATIONSHIP="RELATIONSHIP"; ATTRIBUTE="ATTRIBUTE"; IDENTIFIER="IDENTIFIER"; OTHER="OTHER"
class ClaimStatus(str,enum.Enum):
    SOURCE_REPORTED="SOURCE_REPORTED"; AI_EXTRACTED="AI_EXTRACTED"; INVESTIGATOR_ADDED="INVESTIGATOR_ADDED"; REQUIRES_VERIFICATION="REQUIRES_VERIFICATION"
class SourceRelationshipType(str,enum.Enum):
    INDEPENDENT="INDEPENDENT"; POTENTIAL_DUPLICATE="POTENTIAL_DUPLICATE"; POSSIBLE_SYNDICATION="POSSIBLE_SYNDICATION"; REFERENCES="REFERENCES"; QUOTES="QUOTES"; UNKNOWN_RELATIONSHIP="UNKNOWN_RELATIONSHIP"

class Claim(Base):
    __tablename__="claims"
    __table_args__=(UniqueConstraint("investigation_id","fingerprint",name="uq_claim_investigation_fingerprint"),)
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid())
    investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True)
    claim_type:Mapped[ClaimType]=mapped_column(Enum(ClaimType,native_enum=False,length=24),nullable=False,index=True)
    subject:Mapped[str]=mapped_column(String(500),nullable=False);predicate:Mapped[str]=mapped_column(String(200),nullable=False);object_value:Mapped[str]=mapped_column(Text,nullable=False);normalized_value:Mapped[str|None]=mapped_column(Text);value_type:Mapped[str]=mapped_column(String(24),nullable=False,default="TEXT")
    date_value:Mapped[str|None]=mapped_column(String(40));location_text:Mapped[str|None]=mapped_column(String(1000));location_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("locations.id",ondelete="SET NULL"))
    confidence_label:Mapped[str]=mapped_column(String(16),nullable=False,default="UNKNOWN");extraction_method:Mapped[str]=mapped_column(String(40),nullable=False);source_type:Mapped[str]=mapped_column(String(40),nullable=False);source_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),nullable=False,index=True)
    evidence_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("evidence.id",ondelete="CASCADE"));historical_case_id:Mapped[uuid.UUID|None]=mapped_column(UUID(as_uuid=True),ForeignKey("historical_cases.id",ondelete="CASCADE"));status:Mapped[ClaimStatus]=mapped_column(Enum(ClaimStatus,native_enum=False,length=32),nullable=False,default=ClaimStatus.SOURCE_REPORTED)
    metadata_json:Mapped[dict]=mapped_column("metadata",JSON,nullable=False,default=dict,server_default="{}");fingerprint:Mapped[str]=mapped_column(String(64),nullable=False)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now());updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())

class SourceRelationship(Base):
    __tablename__="source_relationships"
    __table_args__=(UniqueConstraint("investigation_id","source_a_id","source_b_id","relationship_type",name="uq_source_relationship_pair"),CheckConstraint("status IN ('REQUIRES_VERIFICATION','REVIEWED','DISMISSED')",name="ck_source_relationship_status"),CheckConstraint("created_by IN ('INVESTIGATOR','SYSTEM')",name="ck_source_relationship_creator"))
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True)
    source_a_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("web_sources.id",ondelete="CASCADE"),nullable=False);source_b_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("web_sources.id",ondelete="CASCADE"),nullable=False)
    relationship_type:Mapped[SourceRelationshipType]=mapped_column(Enum(SourceRelationshipType,native_enum=False,length=32),nullable=False,default=SourceRelationshipType.UNKNOWN_RELATIONSHIP);explanation:Mapped[str]=mapped_column(Text,nullable=False,default="Requires investigator verification.");created_by:Mapped[str]=mapped_column(String(16),nullable=False,default="INVESTIGATOR");status:Mapped[str]=mapped_column(String(24),nullable=False,default="REQUIRES_VERIFICATION")
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())

class GraphNote(Base):
    __tablename__="graph_notes"
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True);node_type:Mapped[str]=mapped_column(String(40),nullable=False);node_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),nullable=False);note:Mapped[str]=mapped_column(Text,nullable=False);created_by:Mapped[str]=mapped_column(String(120),nullable=False,default="INVESTIGATOR");created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now())
class GraphBookmark(Base):
    __tablename__="graph_bookmarks"
    id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),primary_key=True,default=uuid.uuid4,server_default=func.gen_random_uuid());investigation_id:Mapped[uuid.UUID]=mapped_column(UUID(as_uuid=True),ForeignKey("investigations.id",ondelete="CASCADE"),nullable=False,index=True);name:Mapped[str]=mapped_column(String(200),nullable=False);node_ids:Mapped[list]=mapped_column(JSON,nullable=False,default=list,server_default="[]");filters:Mapped[dict]=mapped_column(JSON,nullable=False,default=dict,server_default="{}");layout:Mapped[str]=mapped_column(String(24),nullable=False,default="force");created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now());updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False,server_default=func.now(),onupdate=func.now())
