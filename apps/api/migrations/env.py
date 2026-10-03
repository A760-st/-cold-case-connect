from logging.config import fileConfig
import os
from alembic import context
from sqlalchemy import engine_from_config, pool
from app.database.session import Base
from app.models.investigation import Investigation
from app.models.evidence import Evidence
from app.models.historical_case import HistoricalCase
from app.models.vector_index import VectorIndexState
from app.models.historical_case_image import HistoricalCaseImage
from app.models.image_index import ImageIndexState
from app.models.web_research import ResearchRun, ResearchSearch, WebSource, WebSearchResult, ResearchRunEvidence
from app.models.agent import AgentRun, AgentAction
from app.models.correlation import Correlation, CorrelationReview
from app.models.timeline import TimelineEvent, TimelineEventSource, TimelineEventEvidence
from app.models.geospatial import Location, TimelineEventLocation, EvidenceLocation, HistoricalCaseLocation, SourceLocation, Contradiction
from app.models.research_intelligence import ResearchGap, InvestigationQuestion
from app.models.investigation_graph import Claim, SourceRelationship, GraphNote, GraphBookmark

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL", config.get_main_option("sqlalchemy.url")))
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, dialect_opts={"paramstyle":"named"})
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
