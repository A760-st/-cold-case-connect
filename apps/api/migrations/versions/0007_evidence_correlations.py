"""Add evidence correlations and investigator reviews."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_evidence_correlations"
down_revision = "0006_investigation_agent"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table("correlations",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("investigation_id", uuid, nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False), sa.Column("source_id", uuid, nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False), sa.Column("target_id", uuid, nullable=False),
        sa.Column("correlation_type", sa.String(40), nullable=False), sa.Column("score", sa.Float(), nullable=True),
        sa.Column("confidence_label", sa.String(16), nullable=True), sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("supporting_attributes", jsonb, server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("evidence_basis", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_by", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("source_type IN ('EVIDENCE','HISTORICAL_CASE','HISTORICAL_IMAGE','WEB_RESULT','NEWS_RESULT','IMAGE_RESULT','SOURCE')", name="ck_correlations_source_type"),
        sa.CheckConstraint("target_type IN ('EVIDENCE','HISTORICAL_CASE','HISTORICAL_IMAGE','WEB_RESULT','NEWS_RESULT','IMAGE_RESULT','SOURCE')", name="ck_correlations_target_type"),
        sa.CheckConstraint("correlation_type IN ('POTENTIAL_CONNECTION','SHARED_ATTRIBUTE','SEMANTIC_SIMILARITY','VISUAL_SIMILARITY','GEOGRAPHIC_OVERLAP','TEMPORAL_OVERLAP','TEMPORAL_PROXIMITY','ENTITY_OVERLAP','SOURCE_REFERENCE','CONTEXTUAL_RELEVANCE')", name="ck_correlations_type"),
        sa.CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="ck_correlations_score_range"),
        sa.CheckConstraint("created_by IN ('AI','INVESTIGATOR')", name="ck_correlations_created_by"),
        sa.UniqueConstraint("investigation_id", "source_type", "source_id", "target_type", "target_id", "correlation_type", name="uq_correlation_pair_type"))
    op.create_index("ix_correlations_investigation_id", "correlations", ["investigation_id"])
    op.create_index("ix_correlations_correlation_type", "correlations", ["correlation_type"])
    op.create_table("correlation_reviews",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("correlation_id", uuid, nullable=False), sa.Column("review_status", sa.String(32), nullable=False),
        sa.Column("note", sa.String(1000), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["correlation_id"], ["correlations.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("review_status IN ('RELEVANT','NOT_RELEVANT','REQUIRES_VERIFICATION')", name="ck_correlation_reviews_status"))
    op.create_index("ix_correlation_reviews_correlation_id", "correlation_reviews", ["correlation_id"])


def downgrade():
    op.drop_index("ix_correlation_reviews_correlation_id", table_name="correlation_reviews")
    op.drop_table("correlation_reviews")
    op.drop_index("ix_correlations_correlation_type", table_name="correlations")
    op.drop_index("ix_correlations_investigation_id", table_name="correlations")
    op.drop_table("correlations")
