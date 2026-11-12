from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio

from .database import engine
from .routers import chat, tool_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .database import initialize_schema
    initialize_schema()
    from .agent.runtime import build_business_agent, RegistryAgentManager
    from .agent.graph import ENGINE_VERSION
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from .database import DB_PATH
    async with AsyncSqliteSaver.from_conn_string(str(DB_PATH.parent / 'agent-checkpoints.db')) as saver:
        await saver.setup()
        app.state.business_agent = await asyncio.to_thread(build_business_agent, saver)
        app.state.registry_agent_manager = RegistryAgentManager(app.state.business_agent)
        # Running requests cannot be safely replayed after an unclean shutdown.
        from .models import AgentRun, ToolTrace, RequestRecord
        from .models import Message
        from .utils.history import backfill_requests
        from .database import SessionLocal
        with SessionLocal() as db:
            backfill_requests(db)
            db.flush()
            db.query(RequestRecord).filter_by(status="running").update({"status": "failed"})
            running_messages = db.query(AgentRun.assistant_message_id).filter(AgentRun.status == 'running')
            db.query(ToolTrace).filter(ToolTrace.message_id.in_(running_messages), ToolTrace.status.in_(['running', 'awaiting_approval'])).update(
                {'status': 'failed', 'result': 'Execution interrupted by server restart.'}, synchronize_session=False)
            db.query(AgentRun).filter(AgentRun.status == 'running').update({'status':'failed'})
            retired = db.query(AgentRun).filter(
                AgentRun.status.in_(['awaiting_approval', 'awaiting_input']),
                AgentRun.engine_version != ENGINE_VERSION,
            ).all()
            for run in retired:
                db.query(RequestRecord).filter_by(id=run.id).update({'status': 'failed'})
                db.query(ToolTrace).filter(ToolTrace.id.startswith(run.id + ':'),
                    ToolTrace.status.in_(['running', 'awaiting_approval'])).update(
                    {'status': 'failed', 'result': 'Pending approval retired after agent engine upgrade.'}, synchronize_session=False)
                message = db.get(Message, run.assistant_message_id)
                if message:
                    notice = 'This pending request ended after an agent engine upgrade. Start a new request to continue.'
                    message.content = f'{message.content}\n\n{notice}' if message.content else notice
                run.status = 'failed'
                run.approval_id = run.approval_payload = None
                run.clarification_id = run.clarification_payload = None
            db.commit()
        yield



app = FastAPI(
    title="Agent Backend",
    description="FastAPI backend with LangChain and LangGraph for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(tool_registry.router, prefix="/api")


@app.get("/")
async def root():
    return {"message": "Agent Backend API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
