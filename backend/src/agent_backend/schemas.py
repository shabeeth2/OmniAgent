from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class TraceRead(BaseModel):
    id: str
    call_id: str
    tool_name: str
    status: str
    arguments: Optional[str] = None
    result: Optional[str] = None
    duration_ms: Optional[int] = None
    catalog_version: Optional[str] = None

    model_config = {'from_attributes': True}


class MessageRead(BaseModel):
    role: str
    content: str
    id: int
    conversation_id: int
    created_at: datetime
    traces: List[TraceRead] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ConversationRead(BaseModel):
    title: Optional[str] = None
    id: int
    created_at: datetime
    updated_at: datetime
    messages: List[MessageRead] = []

    class Config:
        from_attributes = True


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[int] = None
