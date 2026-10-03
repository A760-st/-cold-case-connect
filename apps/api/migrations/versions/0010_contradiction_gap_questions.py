"""Add Phase 10 contradiction intelligence, research gaps, and questions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_contradiction_gap_questions"
down_revision = "0009_geospatial_contradictions"
branch_labels = None
depends_on = None

GAP_TYPES = "'MISSING_DATE','MISSING_LOCATION','MISSING_EVENT_DETAIL','MISSING_SOURCE','MISSING_EVIDENCE','MISSING_ENTITY_ATTRIBUTE','MISSING_TIMELINE_EVENT','MISSING_HISTORICAL_CONTEXT','MISSING_PUBLIC_RECORD','INSUFFICIENT_SOURCE_COVERAGE','CONTRADICTORY_INFORMATION','UNRESOLVED_ENTITY','UNRESOLVED_LOCATION','UNRESOLVED_TIMELINE','UNDER_RESEARCHED_PERIOD','UNDER_RESEARCHED_LOCATION','UNDER_RESEARCHED_ENTITY','UNANSWERED_QUESTION','LOCATION_PRECISION_GAP','UNREVIEWED_CORRELATION'"
CONTRADICTION_TYPES = "'DATE_CONFLICT','LOCATION_CONFLICT','TIME_CONFLICT','TIMELINE_CONFLICT','ATTRIBUTE_CONFLICT','ENTITY_CONFLICT','IDENTITY_ATTRIBUTE_CONFLICT','SOURCE_CONFLICT','DESCRIPTION_CONFLICT','NUMERIC_CONFLICT','EVENT_CONFLICT','STATUS_CONFLICT'"

def upgrade():
    op.drop_constraint("uq_contradiction_source_pair", "contradictions", type_="unique")
    op.drop_constraint("ck_contradiction_type", "contradictions", type_="check")
    op.drop_constraint("ck_contradiction_status", "contradictions", type_="check")
    op.add_column("contradictions", sa.Column("fingerprint", sa.String(64), nullable=True))
    op.add_column("contradictions", sa.Column("priority", sa.String(8), server_default="MEDIUM", nullable=False))
    op.add_column("contradictions", sa.Column("date_precision", sa.String(16), nullable=True))
    op.add_column("contradictions", sa.Column("related_event_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_contradictions_related_event", "contradictions", "timeline_events", ["related_event_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_contradictions_fingerprint", "contradictions", ["fingerprint"], unique=True)
    op.create_check_constraint("ck_contradiction_type", "contradictions", f"type IN ({CONTRADICTION_TYPES})")
    op.create_check_constraint("ck_contradiction_status", "contradictions", "status IN ('OPEN','UNDER_REVIEW','REQUIRES_VERIFICATION','REVIEWED','RESOLVED','DISMISSED')")
    op.create_check_constraint("ck_contradiction_priority", "contradictions", "priority IN ('LOW','MEDIUM','HIGH')")

    u = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table("research_gaps",
        sa.Column("id", u, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("investigation_id", u, nullable=False),
        sa.Column("gap_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False), sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(8), server_default="MEDIUM", nullable=False),
        sa.Column("status", sa.String(24), server_default="OPEN", nullable=False),
        sa.Column("subject_type", sa.String(40)), sa.Column("subject_id", u),
        sa.Column("related_evidence_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_source_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_timeline_event_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_location_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_correlation_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_contradiction_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("last_agent_run_id", u),
        sa.Column("suggested_research_actions", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("investigator_note", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("investigation_id", "fingerprint", name="uq_research_gap_fingerprint"),
        sa.CheckConstraint(f"gap_type IN ({GAP_TYPES})", name="ck_research_gap_type"),
        sa.CheckConstraint("priority IN ('LOW','MEDIUM','HIGH')", name="ck_research_gap_priority"),
        sa.CheckConstraint("status IN ('OPEN','RESEARCHING','SUFFICIENTLY_ADDRESSED','DISMISSED')", name="ck_research_gap_status"))
    op.create_index("ix_research_gaps_investigation_id", "research_gaps", ["investigation_id"])
    op.create_index("ix_research_gaps_gap_type", "research_gaps", ["gap_type"])
    op.create_index("ix_research_gaps_status", "research_gaps", ["status"])
    op.create_index("ix_research_gaps_investigation_status", "research_gaps", ["investigation_id", "status"])

    op.create_table("investigation_questions",
        sa.Column("id", u, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("investigation_id", u, nullable=False), sa.Column("question", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(24), server_default="OPEN", nullable=False),
        sa.Column("priority", sa.String(8), server_default="MEDIUM", nullable=False),
        sa.Column("related_evidence_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_timeline_event_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_location_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_source_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("related_gap_ids", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("last_agent_run_id", u),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_agent_run_id"], ["agent_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('OPEN','RESEARCHING','PARTIALLY_ADDRESSED','ANSWERED','DISMISSED')", name="ck_question_status"),
        sa.CheckConstraint("priority IN ('LOW','MEDIUM','HIGH')", name="ck_question_priority"))
    op.create_index("ix_investigation_questions_investigation_id", "investigation_questions", ["investigation_id"])
    op.create_index("ix_investigation_questions_status", "investigation_questions", ["status"])
    op.create_index("ix_questions_investigation_status", "investigation_questions", ["investigation_id", "status"])

def downgrade():
    op.drop_table("investigation_questions")
    op.drop_table("research_gaps")
    op.drop_constraint("ck_contradiction_priority", "contradictions", type_="check")
    op.drop_constraint("ck_contradiction_status", "contradictions", type_="check")
    op.drop_constraint("ck_contradiction_type", "contradictions", type_="check")
    op.drop_index("ix_contradictions_fingerprint", table_name="contradictions")
    op.drop_constraint("fk_contradictions_related_event", "contradictions", type_="foreignkey")
    op.drop_column("contradictions", "related_event_id")
    op.drop_column("contradictions", "date_precision")
    op.drop_column("contradictions", "priority")
    op.drop_column("contradictions", "fingerprint")
    op.create_check_constraint("ck_contradiction_type", "contradictions", "type IN ('DATE_CONFLICT','LOCATION_CONFLICT','ATTRIBUTE_CONFLICT','ENTITY_CONFLICT','TIMELINE_CONFLICT','SOURCE_CONFLICT')")
    op.create_check_constraint("ck_contradiction_status", "contradictions", "status IN ('OPEN','REQUIRES_VERIFICATION','REVIEWED','RESOLVED','DISMISSED')")
    op.create_unique_constraint("uq_contradiction_source_pair", "contradictions", ["investigation_id","type","source_a_type","source_a_id","source_b_type","source_b_id"])
