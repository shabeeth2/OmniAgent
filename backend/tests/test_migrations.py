import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from agent_backend.database import initialize_schema
from agent_backend.models import AgentRun, RequestRecord
from agent_backend.utils.history import backfill_requests, previous_requests


class MigrationTest(unittest.TestCase):
    def test_additive_question_migration_preserves_pending_approval(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE agent_runs (id TEXT PRIMARY KEY, approval_id TEXT, approval_payload TEXT)'))
            connection.exec_driver_sql("INSERT INTO agent_runs VALUES ('old', 'approval', '{\"keep\":true}')")
        initialize_schema(engine)
        initialize_schema(engine)
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT approval_id,approval_payload,clarification_id,clarification_payload FROM agent_runs')).one(),
                             ('approval', '{"keep":true}', None, None))

    def test_additive_trace_migration_keeps_old_rows(self):
        engine = create_engine('sqlite:///:memory:')
        self.addCleanup(engine.dispose)
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE tool_traces (sequence INTEGER PRIMARY KEY, id TEXT)'))
            connection.execute(text("INSERT INTO tool_traces VALUES (1, 'old-trace')"))
        initialize_schema(engine)
        initialize_schema(engine)
        with engine.connect() as connection:
            self.assertEqual(connection.execute(text('SELECT id,catalog_version FROM tool_traces')).one(), ('old-trace', None))

    def test_backfill_and_history_survive_reopened_database(self):
        with TemporaryDirectory() as directory:
            uri = 'sqlite:///'+str(Path(directory)/'history.db')
            engine = create_engine(uri)
            initialize_schema(engine)
            with Session(engine) as db:
                db.add(AgentRun(id='legacy', conversation_id=1, assistant_message_id=1, status='failed'))
                db.commit()
                backfill_requests(db)
                db.commit()
                backfill_requests(db)
                db.commit()
                self.assertEqual(db.query(RequestRecord).count(), 1)
            engine.dispose()
            engine = create_engine(uri)
            try:
                with Session(engine) as db:
                    self.assertEqual(previous_requests(db, 1, 'current')[0]['status'], 'failed')
                    self.assertEqual(previous_requests(db, 2, 'current'), [])
            finally:
                engine.dispose()
