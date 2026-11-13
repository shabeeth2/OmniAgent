import asyncio
import json
from uuid import uuid4
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from ..database import get_db
from ..models import Conversation, Message, AgentRun, ToolTrace
from ..schemas import ChatRequest, ConversationRead, TraceRead
from ..agent.graph import ENGINE_VERSION
from ..utils.traces import preview
from ..utils.history import previous_requests, sync_request
from ..models import RequestRecord
from ..agent.clarification import Answers, validate_answers, answer_summary

router = APIRouter()
ACTIVE_STATUSES = ('running', 'awaiting_approval', 'awaiting_input')

class CallDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tool_call_id: str
    decision: Literal['approve','reject']


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra='forbid')
    decision: Literal['approve','reject'] | None = None
    decisions: list[CallDecision] | None = None

    @model_validator(mode='after')
    def one_format(self):
        if (self.decision is None) == (self.decisions is None):
            raise ValueError('Supply either a legacy decision or batch decisions')
        return self


def event(value):
    return f"data: {json.dumps(value)}\n\n"


def run_stream(agent, run, db, history=None, decision=None):
    async def stream():
        queue = asyncio.Queue()
        task = None

        def record(value):
            trace_id = f"{run.id}:{value['call_id']}"
            row = db.query(ToolTrace).filter_by(id=trace_id).first()
            if row is None:
                row = ToolTrace(id=trace_id, message_id=run.assistant_message_id,
                                call_id=value['call_id'], tool_name=value['tool_name'])
                db.add(row)
            row.status = value['status']
            for key in ('arguments', 'result'):
                if key in value:
                    setattr(row, key, preview(value[key]))
            if 'catalog_version' in value:
                row.catalog_version = value['catalog_version']
            if 'duration_ms' in value:
                row.duration_ms = value['duration_ms']
            db.commit()
            queue.put_nowait({'trace': TraceRead.model_validate(row).model_dump()})

        def finish_traces():
            for row in db.query(ToolTrace).filter_by(message_id=run.assistant_message_id).all():
                if row.status in {'running', 'awaiting_approval'}:
                    record({'call_id': row.call_id, 'tool_name': row.tool_name,
                            'status': 'failed', 'result': 'Execution ended before this step completed.'})

        def _fail_run(message):
            finish_traces()
            run.status = 'failed'
            db.get(Message, run.assistant_message_id).content = message
            sync_request(db, run)
            db.commit()

        async def produce():
            try:
                return await agent.run(history, run_id=run.id, decision=decision, on_trace=record, on_status=lambda: previous_requests(db, run.conversation_id, run.id))
            finally:
                queue.put_nowait(None)

        try:
            yield event({'conversation_id':run.conversation_id})
            task = asyncio.create_task(produce())
            while True:
                value = await queue.get()
                if value is None:
                    break
                yield event(value)
            outcome = await task
            if outcome.status == 'awaiting_input':
                payload = {'run_id': run.id, **outcome.clarification}
                run.status = 'awaiting_input'
                run.approval_id = None
                run.approval_payload = None
                run.clarification_id = payload['clarification_id']
                run.clarification_payload = json.dumps(payload)
                summary = '\n\n'.join(q['q'] for q in payload['questions'])
                db.get(Message, run.assistant_message_id).content = summary
                sync_request(db, run)
                db.commit()
                yield event({'content': summary})
                yield event({'clarification_required': payload})
            elif outcome.status == 'awaiting_approval':
                payload = {'run_id':run.id, **outcome.approval}
                run.status = 'awaiting_approval'
                run.approval_id = payload['approval_id']
                run.approval_payload = json.dumps(payload)
                run.clarification_id = None
                run.clarification_payload = None
                sync_request(db, run)
                db.commit()
                yield event({'approval_required':payload})
            else:
                finish_traces()
                while not queue.empty():
                    yield event(queue.get_nowait())
                run.status = outcome.status
                run.approval_id = None
                run.approval_payload = None
                run.clarification_id = None
                run.clarification_payload = None
                db.get(Message,run.assistant_message_id).content = outcome.content
                sync_request(db, run)
                db.commit()
                yield event({'content':outcome.content})
            yield 'data: [DONE]\n\n'
        except (asyncio.CancelledError, GeneratorExit):
            if task:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
            if run.status == 'running':
                _fail_run('Request interrupted before a complete answer was available.')
            raise
        except Exception:
            db.rollback()
            finish_traces()
            while not queue.empty():
                value = queue.get_nowait()
                if value is not None:
                    yield event(value)
            _fail_run('The request failed. Please try again.')
            yield event({'content': 'The request failed. Please try again.'})
            yield 'data: [DONE]\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


@router.post('/chat')
async def chat_endpoint(request: ChatRequest, http_request: Request, db: Session = Depends(get_db)):
    if getattr(http_request.app.state, 'business_agent', None) is None:
        raise HTTPException(503, 'Configure the LLM and embeddings, then restart the app.')
    manager = getattr(http_request.app.state, 'registry_agent_manager', None)
    try:
        agent = await manager.snapshot() if manager else http_request.app.state.business_agent
    except Exception:
        raise HTTPException(503, 'Tool registry is unavailable. Check enabled connections and retry.') from None
    if request.conversation_id:
        conversation = db.get(Conversation,request.conversation_id)
        if not conversation:
            raise HTTPException(404,'Conversation not found')
    else:
        conversation = Conversation(title=request.message[:50] or 'New Chat')
        db.add(conversation)
        db.flush()
    existing = db.query(AgentRun).filter_by(conversation_id=conversation.id).first()
    run_id = str(uuid4())
    if existing:
        changed = db.query(AgentRun).filter(AgentRun.id == existing.id, AgentRun.status.notin_(ACTIVE_STATUSES)).update({'id':run_id,'status':'running','engine_version':getattr(agent, 'engine_version', ENGINE_VERSION),'approval_id':None,'approval_payload':None,'clarification_id':None,'clarification_payload':None},synchronize_session=False)
        if not changed:
            db.rollback()
            raise HTTPException(409,'Conversation has an active or pending request')
        db.expire(existing)
        run = db.query(AgentRun).filter_by(id=run_id).one()
    else:
        run = AgentRun(id=run_id,conversation_id=conversation.id,assistant_message_id=0,status='running', engine_version=getattr(agent, 'engine_version', ENGINE_VERSION))
        db.add(run)
    db.add(Message(conversation_id=conversation.id,role='user',content=request.message))
    db.flush()
    from langchain_core.messages import HumanMessage, AIMessage
    history = [(HumanMessage if row.role=='user' else AIMessage)(content=row.content)
               for row in db.query(Message).filter_by(conversation_id=conversation.id).order_by(Message.id)
               if row.role in {'user','assistant'} and row.content]
    assistant = Message(conversation_id=conversation.id,role='assistant',content='')
    db.add(assistant)
    db.flush()
    run.assistant_message_id = assistant.id
    sync_request(db, run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Conversation already has an active request') from None
    return run_stream(agent,run,db,history)


@router.get('/conversations/{conversation_id}/pending-approval')
async def pending_approval(conversation_id: int, db: Session = Depends(get_db)):
    if not db.get(Conversation,conversation_id):
        raise HTTPException(404,'Conversation not found')
    run = db.query(AgentRun).filter_by(conversation_id=conversation_id,status='awaiting_approval').first()
    return json.loads(run.approval_payload) if run else None


@router.post('/conversations/{conversation_id}/approvals/{approval_id}')
async def resume_approval(conversation_id: int, approval_id: str, body: ApprovalDecision, http_request: Request, db: Session = Depends(get_db)):
    manager = getattr(http_request.app.state, 'registry_agent_manager', None)
    try:
        agent = await manager.snapshot(fresh=True) if manager else http_request.app.state.business_agent
    except Exception:
        raise HTTPException(503, 'Tool registry is unavailable. Check enabled connections and retry.') from None
    run = db.query(AgentRun).filter_by(conversation_id=conversation_id,approval_id=approval_id,status='awaiting_approval').first()
    if not run:
        raise HTTPException(409,'Approval is stale or already decided')
    if run.engine_version != getattr(agent, 'engine_version', ENGINE_VERSION):
        raise HTTPException(409, 'This pending request used a retired agent engine; its history is preserved.')
    payload = json.loads(run.approval_payload)
    if 'calls' in payload:
        ids = [item.tool_call_id for item in body.decisions or []]
        expected = [item['tool_call_id'] for item in payload['calls']]
        if body.decision is not None:
            # The documented decision endpoint applies one choice to every
            # call in a batch. Per-call decisions remain available when the
            # approver needs different outcomes for individual calls.
            decision = body.decision
        elif len(ids) != len(set(ids)) or set(ids) != set(expected):
            raise HTTPException(422, 'Supply exactly one decision for each pending tool call')
        else:
            decision = {'decisions': [item.model_dump() for item in body.decisions]}
    else:
        if body.decision is None:
            raise HTTPException(422, 'This saved approval requires a single decision')
        decision = body.decision
    changed = db.query(AgentRun).filter_by(id=run.id,approval_id=approval_id,status='awaiting_approval').update({'status':'running'},synchronize_session=False)
    if not changed:
        db.rollback()
        raise HTTPException(409,'Approval is already being processed')
    db.commit()
    db.refresh(run)
    return run_stream(agent,run,db,decision=decision)


@router.get('/conversations/{conversation_id}/pending-clarification')
async def pending_clarification(conversation_id: int, db: Session = Depends(get_db)):
    if not db.get(Conversation, conversation_id):
        raise HTTPException(404, 'Conversation not found')
    run = db.query(AgentRun).filter_by(conversation_id=conversation_id, status='awaiting_input').first()
    return json.loads(run.clarification_payload) if run else None


@router.post('/conversations/{conversation_id}/clarifications/{clarification_id}')
async def resume_clarification(conversation_id: int, clarification_id: str, body: Answers,
                               http_request: Request, db: Session = Depends(get_db)):
    run = db.query(AgentRun).filter_by(conversation_id=conversation_id, clarification_id=clarification_id,
                                     status='awaiting_input').first()
    if not run:
        raise HTTPException(409, 'Clarification is stale or already answered')
    payload = json.loads(run.clarification_payload)
    try:
        answers = validate_answers(payload['questions'], body)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    manager = getattr(http_request.app.state, 'registry_agent_manager', None)
    try:
        agent = await manager.snapshot(fresh=True) if manager else http_request.app.state.business_agent
    except Exception:
        raise HTTPException(503, 'Tool registry is unavailable. Check enabled connections and retry.') from None
    if run.engine_version != getattr(agent, 'engine_version', ENGINE_VERSION):
        raise HTTPException(409, 'This pending request used a retired agent engine; its history is preserved.')
    changed = db.query(AgentRun).filter_by(id=run.id, clarification_id=clarification_id,
                                         status='awaiting_input').update({'status': 'running'}, synchronize_session=False)
    if not changed:
        db.rollback()
        raise HTTPException(409, 'Clarification is already being processed')
    db.refresh(run)
    db.add(Message(conversation_id=conversation_id, role='user', content=answer_summary(answers)))
    db.flush()
    assistant = Message(conversation_id=conversation_id, role='assistant', content='')
    db.add(assistant)
    db.flush()
    run.assistant_message_id = assistant.id
    run.clarification_id = None
    run.clarification_payload = None
    sync_request(db, run)
    db.commit()
    return run_stream(agent, run, db, decision=body.model_dump())


@router.get("/conversations", response_model=list[ConversationRead])
async def list_conversations(db: Session = Depends(get_db)):
    """List all conversations."""
    conversations = db.query(Conversation).order_by(Conversation.updated_at.desc()).all()
    return conversations


@router.get("/conversations/{conversation_id}", response_model=ConversationRead)
async def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Get a conversation with its messages."""
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Delete a conversation."""
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    active = db.query(AgentRun).filter_by(conversation_id=conversation_id).first()
    if active and active.status in ACTIVE_STATUSES:
        raise HTTPException(409, "Conversation has an active request")
    if active:
        db.delete(active)
    db.query(RequestRecord).filter_by(conversation_id=conversation_id).delete()
    db.delete(conversation)
    db.commit()
    return {"message": "Conversation deleted"}
