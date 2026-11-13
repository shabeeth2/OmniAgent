"""Character budgets are conservative demo limits, not provider token limits."""
import json
from langchain_core.messages import SystemMessage, HumanMessage, messages_to_dict
from langchain_core.utils.function_calling import convert_to_openai_tool


class ContextBudgetExceeded(ValueError):
    pass


def bounded_messages(prompt, messages, tools, limit):
    schemas = [convert_to_openai_tool(tool) for tool in tools]
    # Human turns contain complete assistant/tool pairs; never slice within a turn.
    starts = [i for i, message in enumerate(messages) if isinstance(message, HumanMessage)]
    start = 0
    while True:
        result = [SystemMessage(content=prompt)] + messages[start:]
        wire = {'messages': messages_to_dict(result), 'tools': schemas}
        if len(json.dumps(wire, ensure_ascii=True, default=str)) <= limit:
            return result
        next_start = next((i for i in starts if i > start), None)
        if next_start is None:
            raise ContextBudgetExceeded('Current request and selected schemas exceed the context budget')
        start = next_start


def bounded_result(value, limit=12000):
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) <= limit:
        return text
    preview = text[:limit]
    while True:
        result = json.dumps({'complete': False, 'truncated': True,
                             'instruction': 'Narrow the query or fetch smaller pages. Do not claim completeness.', 'preview': preview})
        if len(result) <= limit:
            return result
        if not preview:
            raise ValueError('Result budget cannot fit the truncation notice')
        preview = preview[:max(0, len(preview) - (len(result)-limit))]
