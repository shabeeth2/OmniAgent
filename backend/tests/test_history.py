import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from agent_backend.models import Base, Conversation, Message
from agent_backend.schemas import ConversationRead

class HistoryTest(unittest.TestCase):
    def test_history_and_delete(self):
        engine = create_engine('sqlite:///:memory:')
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            chat = Conversation(title='hello')
            db.add(chat)
            db.flush()
            db.add(Message(conversation_id=chat.id, role='user', content='hello'))
            db.commit()
            db.expire_all()
            self.assertEqual(ConversationRead.model_validate(chat).messages[0].content, 'hello')
            db.delete(chat)
            db.commit()
            self.assertEqual(db.query(Message).count(), 0)

if __name__ == '__main__':
    unittest.main()
