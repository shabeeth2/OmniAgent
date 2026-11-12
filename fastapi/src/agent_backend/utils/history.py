"""Append-only request identities; latest-run locks remain in agent_runs."""
from ..models import RequestRecord, AgentRun, ToolTrace
from sqlalchemy import or_
from .traces import preview


def backfill_requests(db):
    for run in db.query(AgentRun).all():
        if db.get(RequestRecord, run.id) is None:
            db.add(RequestRecord(id=run.id, conversation_id=run.conversation_id,
                                 assistant_message_id=run.assistant_message_id, status=run.status, engine_version=run.engine_version))


def previous_requests(db, conversation_id, current_run_id):
    rows = db.query(RequestRecord).filter(
        RequestRecord.conversation_id == conversation_id, RequestRecord.id != current_run_id
    ).order_by(RequestRecord.created_at.desc(), RequestRecord.assistant_message_id.desc()).limit(5).all()
    return [{'run_id': row.id, 'status': row.status, 'tools': [
        {'name': trace.tool_name, 'status': trace.status, 'result': preview(trace.result)}
        for trace in db.query(ToolTrace).filter(or_(ToolTrace.id.startswith(row.id + ':'),
            ToolTrace.message_id == row.assistant_message_id)).order_by(ToolTrace.sequence).limit(20)
    ]} for row in rows]


def sync_request(db, run):
    record = db.get(RequestRecord, run.id)
    if record is None:
        record = RequestRecord(id=run.id, conversation_id=run.conversation_id,
                               assistant_message_id=run.assistant_message_id, status=run.status)
        db.add(record)
    record.status = run.status
    record.engine_version = run.engine_version
    record.assistant_message_id = run.assistant_message_id
