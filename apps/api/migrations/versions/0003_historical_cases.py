"""Add historical case records and vector index state.

Revision ID: 0003_historical
Revises: 0002_evidence
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003_historical"
down_revision = "0002_evidence"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "historical_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("external_id", sa.String(240), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("location", sa.String(500), nullable=True),
        sa.Column("case_type", sa.String(160), nullable=True),
        sa.Column("status", sa.String(120), nullable=True),
        sa.Column("source_name", sa.String(300), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.String(300), nullable=True),
        sa.Column("embedding_version", sa.String(64), nullable=True),
        sa.Column("embedding_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("external_id", name="uq_historical_cases_external_id"),
        sa.UniqueConstraint("fingerprint", name="uq_historical_cases_fingerprint"),
    )
    op.create_index("ix_historical_cases_external_id", "historical_cases", ["external_id"])
    op.create_table(
        "vector_index_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), server_default="NOT_INITIALIZED", nullable=False),
        sa.Column("collection_name", sa.String(240), server_default="historical_cases", nullable=False),
        sa.Column("embedding_model", sa.String(300), nullable=False),
        sa.Column("database_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_vector_index_state_singleton"),
        sa.CheckConstraint("status IN ('NOT_INITIALIZED','BUILDING','READY','FAILED','INDEX_OUT_OF_SYNC')", name="ck_vector_index_state_status"),
    )

def downgrade():
    op.drop_table("vector_index_state")
    op.drop_index("ix_historical_cases_external_id", table_name="historical_cases")
    op.drop_table("historical_cases")
