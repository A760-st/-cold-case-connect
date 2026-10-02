"""Add CLIP evidence cache and historical image corpus/index state.

Revision ID: 0004_clip_visual
Revises: 0003_historical
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_clip_visual"
down_revision = "0003_historical"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evidence", sa.Column("clip_embedding", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("evidence", sa.Column("clip_embedding_model", sa.String(300), nullable=True))
    op.add_column("evidence", sa.Column("clip_embedding_version", sa.String(64), nullable=True))
    op.add_column("evidence", sa.Column("clip_embedding_checksum", sa.String(64), nullable=True))
    op.add_column("evidence", sa.Column("clip_embedding_created_at", sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        "historical_case_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("historical_case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("source_name", sa.String(300), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(120), nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("embedding_model", sa.String(300), nullable=True),
        sa.Column("embedding_version", sa.String(64), nullable=True),
        sa.Column("embedding_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["historical_case_id"], ["historical_cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("historical_case_id", "checksum", name="uq_historical_case_image_checksum"),
    )
    op.create_index("ix_historical_case_images_historical_case_id", "historical_case_images", ["historical_case_id"])
    op.create_index("ix_historical_case_images_checksum", "historical_case_images", ["checksum"])
    op.create_table(
        "historical_image_index_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), server_default="NOT_INITIALIZED", nullable=False),
        sa.Column("collection_name", sa.String(240), server_default="historical_case_images", nullable=False),
        sa.Column("embedding_model", sa.String(300), nullable=False),
        sa.Column("database_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("indexed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_historical_image_index_singleton"),
        sa.CheckConstraint("status IN ('NOT_INITIALIZED','NO_CORPUS','BUILDING','READY','FAILED','INDEX_OUT_OF_SYNC')", name="ck_historical_image_index_status"),
    )


def downgrade():
    op.drop_table("historical_image_index_state")
    op.drop_index("ix_historical_case_images_checksum", table_name="historical_case_images")
    op.drop_index("ix_historical_case_images_historical_case_id", table_name="historical_case_images")
    op.drop_table("historical_case_images")
    op.drop_column("evidence", "clip_embedding_created_at")
    op.drop_column("evidence", "clip_embedding_version")
    op.drop_column("evidence", "clip_embedding_checksum")
    op.drop_column("evidence", "clip_embedding_model")
    op.drop_column("evidence", "clip_embedding")
