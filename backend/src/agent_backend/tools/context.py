"""Trusted request scope; never populated from model arguments."""
from contextvars import ContextVar

run_context = ContextVar('run_context', default=None)
status_reader = ContextVar('status_reader', default=None)
