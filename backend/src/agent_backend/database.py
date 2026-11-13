from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "app.db"
DB_PATH.parent.mkdir(exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def initialize_schema(target_engine=engine):
    """Only additive changes; never rewrite or drop saved user data."""
    from sqlalchemy import inspect, text
    Base.metadata.create_all(bind=target_engine)
    if 'ui_surfaces_json' not in {column['name'] for column in inspect(target_engine).get_columns('messages')}:
        with target_engine.begin() as connection:
            connection.execute(text('ALTER TABLE messages ADD COLUMN ui_surfaces_json TEXT'))
    if 'catalog_version' not in {column['name'] for column in inspect(target_engine).get_columns('tool_traces')}:
        with target_engine.begin() as connection:
            connection.execute(text('ALTER TABLE tool_traces ADD COLUMN catalog_version VARCHAR(64)'))
    columns = {column['name'] for column in inspect(target_engine).get_columns('agent_runs')}
    with target_engine.begin() as connection:
        if 'engine_version' not in columns:
            connection.execute(text("ALTER TABLE agent_runs ADD COLUMN engine_version VARCHAR(30) NOT NULL DEFAULT 'legacy'"))
        if 'clarification_id' not in columns:
            connection.execute(text('ALTER TABLE agent_runs ADD COLUMN clarification_id VARCHAR(100)'))
        if 'clarification_payload' not in columns:
            connection.execute(text('ALTER TABLE agent_runs ADD COLUMN clarification_payload TEXT'))
    if 'engine_version' not in {column['name'] for column in inspect(target_engine).get_columns('request_records')}:
        with target_engine.begin() as connection:
            connection.execute(text("ALTER TABLE request_records ADD COLUMN engine_version VARCHAR(30) NOT NULL DEFAULT 'legacy'"))
