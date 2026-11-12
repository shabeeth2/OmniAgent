"""Request-local trace delivery and bounded, credential-redacted previews."""
import ast
import json
import re
from contextvars import ContextVar

catalog_version = ContextVar('catalog_version', default=None)
trace_callback = ContextVar('trace_callback', default=None)
SENSITIVE = re.compile(r'key|token|secret|password|authorization|header|credential|cookie', re.I)


def redact(value):
    def clean(item, depth=0):
        if depth > 12:
            return '[truncated]'
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
            except (ValueError, RecursionError):
                try:
                    parsed = ast.literal_eval(item)
                except (ValueError, SyntaxError, MemoryError, RecursionError):
                    parsed = None
            if isinstance(parsed, (dict, list)):
                return clean(parsed, depth + 1)
            item = re.sub(r'(?i)((?:bearer|basic)\s+)[\w.+/=\-]+', r'\1[redacted]', item)
            item = re.sub(r'''(?ix)(?<![\w-])((?:[\w-]*(?:api[_-]?key|token|secret|password|authorization|credential|cookie)[\w-]*)["']?\s*[=:]\s*)(?:"[^"\n]*"|'[^'\n]*'|[^\s&,;]+)''', r'\1[redacted]', item)
            item = re.sub(r'(?i)(https?://)[^/@\s]+:[^/@\s]+@', r'\1[redacted]@', item)
            return item
        if isinstance(item, dict):
            return {str(k): '[redacted]' if SENSITIVE.search(str(k)) else clean(v, depth + 1) for k, v in item.items()}
        if isinstance(item, (list, tuple)):
            return [clean(v, depth + 1) for v in item[:100]] + (['[truncated]'] if len(item) > 100 else [])
        return item
    return clean(value)


def preview(value):
    text = json.dumps(redact(value), ensure_ascii=False, default=str, indent=2)
    return text if len(text) <= 12000 else text[:12000] + '\n[truncated]'


def emit(call, status, **details):
    callback = trace_callback.get()
    if callback:
        callback({'call_id': call['id'], 'tool_name': call['name'], 'status': status,
                  'arguments': redact(call['args']), 'catalog_version': catalog_version.get(),
                  **{key: redact(value) for key, value in details.items()}})
