"""Add provenance-preserving SerpApi research records.

Revision ID: 0005_web_research
Revises: 0004_clip_visual
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005_web_research"
down_revision = "0004_clip_visual"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table("research_runs",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("investigation_id", uuid, nullable=False), sa.Column("objective", sa.String(500), nullable=False),
        sa.Column("trigger", sa.String(32), nullable=False), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("trigger IN ('MANUAL','EVIDENCE_RESEARCH')", name="ck_research_runs_trigger"),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','FAILED')", name="ck_research_runs_status"))
    op.create_index("ix_research_runs_investigation_id", "research_runs", ["investigation_id"])
    op.create_table("research_searches",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("investigation_id", uuid, nullable=False), sa.Column("research_run_id", uuid, nullable=False),
        sa.Column("query", sa.String(500), nullable=False), sa.Column("engine", sa.String(64), nullable=False),
        sa.Column("search_type", sa.String(32), nullable=False), sa.Column("parameters", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("serpapi_search_id", sa.String(120), nullable=True), sa.Column("serpapi_status", sa.String(80), nullable=True),
        sa.Column("search_timestamp", sa.String(120), nullable=True), sa.Column("status", sa.String(32), nullable=False),
        sa.Column("result_count", sa.Integer(), server_default="0", nullable=False), sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.String(500), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("search_type IN ('WEB','NEWS','NEWS_TAB','IMAGE')", name="ck_research_searches_type"),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','FAILED')", name="ck_research_searches_status"))
    op.create_index("ix_research_searches_investigation_id", "research_searches", ["investigation_id"])
    op.create_index("ix_research_searches_research_run_id", "research_searches", ["research_run_id"])
    op.create_table("web_sources",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False), sa.Column("investigation_id", uuid, nullable=False),
        sa.Column("url", sa.Text(), nullable=False), sa.Column("canonical_url", sa.Text(), nullable=False), sa.Column("domain", sa.String(500), nullable=True),
        sa.Column("title", sa.String(1000), nullable=True), sa.Column("source_name", sa.String(500), nullable=True), sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("metadata", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False), sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("investigation_id", "canonical_url", name="uq_web_sources_investigation_canonical_url"))
    op.create_index("ix_web_sources_investigation_id", "web_sources", ["investigation_id"])
    op.create_table("web_search_results",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False), sa.Column("investigation_id", uuid, nullable=False),
        sa.Column("research_run_id", uuid, nullable=False), sa.Column("search_id", uuid, nullable=False), sa.Column("source_id", uuid, nullable=True),
        sa.Column("result_type", sa.String(16), nullable=False), sa.Column("title", sa.String(1000), nullable=True), sa.Column("url", sa.Text(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True), sa.Column("source_name", sa.String(500), nullable=True), sa.Column("displayed_url", sa.String(1000), nullable=True),
        sa.Column("published_at", sa.String(120), nullable=True), sa.Column("thumbnail_url", sa.Text(), nullable=True), sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("metadata", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["search_id"], ["research_searches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["web_sources.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"))
    for column in ("investigation_id", "research_run_id", "search_id", "source_id"):
        op.create_index(f"ix_web_search_results_{column}", "web_search_results", [column])
    op.create_table("research_run_evidence",
        sa.Column("research_run_id", uuid, nullable=False), sa.Column("evidence_id", uuid, nullable=False),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("research_run_id", "evidence_id"))


def downgrade():
    op.drop_table("research_run_evidence")
    for column in ("source_id", "search_id", "research_run_id", "investigation_id"):
        op.drop_index(f"ix_web_search_results_{column}", table_name="web_search_results")
    op.drop_table("web_search_results")
    op.drop_index("ix_web_sources_investigation_id", table_name="web_sources")
    op.drop_table("web_sources")
    op.drop_index("ix_research_searches_research_run_id", table_name="research_searches")
    op.drop_index("ix_research_searches_investigation_id", table_name="research_searches")
    op.drop_table("research_searches")
    op.drop_index("ix_research_runs_investigation_id", table_name="research_runs")
    op.drop_table("research_runs")
