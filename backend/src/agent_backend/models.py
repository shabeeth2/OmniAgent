from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from .database import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    messages = relationship("Message", primaryjoin="Conversation.id == foreign(Message.conversation_id)", cascade="all, delete-orphan", order_by="Message.id")
    title = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    role = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    traces = relationship('ToolTrace', primaryjoin='Message.id == foreign(ToolTrace.message_id)', cascade='all, delete-orphan', order_by='ToolTrace.sequence')


class ToolTrace(Base):
    __tablename__ = 'tool_traces'
    sequence = Column(Integer, primary_key=True)
    id = Column(String(200), nullable=False, unique=True)
    message_id = Column(Integer, nullable=False, index=True)
    call_id = Column(String(150), nullable=False)
    tool_name = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False)
    arguments = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    catalog_version = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AgentRun(Base):
    __tablename__ = 'agent_runs'
    id = Column(String(36), primary_key=True)
    conversation_id = Column(Integer, nullable=False, unique=True, index=True)
    assistant_message_id = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False)
    engine_version = Column(String(30), nullable=False, default='legacy')
    approval_id = Column(String(100), nullable=True)
    approval_payload = Column(Text, nullable=True)
    clarification_id = Column(String(100), nullable=True)
    clarification_payload = Column(Text, nullable=True)


class RequestRecord(Base):
    __tablename__ = 'request_records'
    id = Column(String(36), primary_key=True)
    conversation_id = Column(Integer, nullable=False, index=True)
    assistant_message_id = Column(Integer, nullable=False)
    status = Column(String(30), nullable=False)
    engine_version = Column(String(30), nullable=False, default='legacy')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
