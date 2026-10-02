"""Add bounded investigation agent runs and auditable actions.

Revision ID: 0006_investigation_agent
Revises: 0005_web_research
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_investigation_agent"
down_revision = "0005_web_research"
branch_labels = None
depends_on = None


def upgrade():
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table("agent_runs",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("investigation_id", uuid, nullable=False), sa.Column("objective", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("max_iterations", sa.Integer(), nullable=False),
        sa.Column("max_actions", sa.Integer(), nullable=False), sa.Column("max_serpapi_queries", sa.Integer(), nullable=False),
        sa.Column("actions_completed", sa.Integer(), server_default="0", nullable=False), sa.Column("queries_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("results_collected", sa.Integer(), server_default="0", nullable=False), sa.Column("stop_reason", sa.String(80), nullable=True),
        sa.Column("stop_requested", sa.Boolean(), server_default=sa.text("false"), nullable=False), sa.Column("iteration", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('QUEUED','RUNNING','COMPLETED','STOPPED','FAILED')", name="ck_agent_runs_status"),
        sa.CheckConstraint("max_iterations > 0 AND max_actions > 0 AND max_serpapi_queries >= 0", name="ck_agent_runs_budgets"))
    op.create_index("ix_agent_runs_investigation_id", "agent_runs", ["investigation_id"])
    op.create_index("ix_agent_runs_status", "agent_runs", ["status"])
    op.create_table("agent_actions",
        sa.Column("id", uuid, server_default=sa.text("gen_random_uuid()"), nullable=False), sa.Column("investigation_id", uuid, nullable=False),
        sa.Column("agent_run_id", uuid, nullable=False), sa.Column("research_run_id", uuid, nullable=True), sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False), sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("input_payload", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("output_summary", jsonb, server_default=sa.text("'{}'::jsonb"), nullable=False), sa.Column("reason", sa.String(500), server_default="", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True), sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True), sa.Column("error_message", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_run_id"], ["agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["research_run_id"], ["research_runs.id"], ondelete="SET NULL"), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("action_type IN ('GET_INVESTIGATION','GET_EVIDENCE','GET_RESEARCH_HISTORY','SEARCH_HISTORICAL_TEXT','SEARCH_HISTORICAL_IMAGES','SEARCH_WEB','SEARCH_NEWS','SEARCH_IMAGES','STOP')", name="ck_agent_actions_type"),
        sa.CheckConstraint("status IN ('PENDING','RUNNING','COMPLETED','FAILED','SKIPPED')", name="ck_agent_actions_status"),
        sa.UniqueConstraint("agent_run_id", "sequence_number", name="uq_agent_actions_run_sequence"))
    for col in ("investigation_id", "agent_run_id", "research_run_id"):
        op.create_index(f"ix_agent_actions_{col}", "agent_actions", [col])
    op.add_column("research_runs", sa.Column("agent_run_id", uuid, nullable=True))
    op.create_foreign_key("fk_research_runs_agent_run_id", "research_runs", "agent_runs", ["agent_run_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_research_runs_agent_run_id", "research_runs", ["agent_run_id"])


def downgrade():
    op.drop_index("ix_research_runs_agent_run_id", table_name="research_runs")
    op.drop_constraint("fk_research_runs_agent_run_id", "research_runs", type_="foreignkey")
    op.drop_column("research_runs", "agent_run_id")
    for col in ("research_run_id", "agent_run_id", "investigation_id"):
        op.drop_index(f"ix_agent_actions_{col}", table_name="agent_actions")
    op.drop_table("agent_actions")
    op.drop_index("ix_agent_runs_status", table_name="agent_runs")
    op.drop_index("ix_agent_runs_investigation_id", table_name="agent_runs")
    op.drop_table("agent_runs")
