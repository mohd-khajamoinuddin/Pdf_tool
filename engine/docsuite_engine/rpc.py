"""Method registry and the stdio JSON-RPC loop.

Wire format (one JSON object per line, UTF-8):

    request   {"id": 7, "method": "pdf.info", "params": {"input": "a.pdf"}}
    response  {"id": 7, "result": {...}}
    failure   {"id": 7, "error": {"code": "not_found", "message": "..."}}
    progress  {"id": 7, "event": "progress", "value": 0.4, "message": "page 4/10"}

Requests run on a worker pool so a long conversion never blocks a thumbnail
render. stdout is reserved for the protocol; anything a library prints is
redirected to stderr (see __main__).
"""

from __future__ import annotations

import json
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, IO, Optional


class EngineError(Exception):
    """An expected, user-presentable failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Context:
    """Per-request handle passed to every handler."""

    def __init__(self, emit: Optional[Callable[[dict], None]] = None, request_id: Any = None):
        self._emit = emit
        self._id = request_id

    def progress(self, value: float, message: str = "") -> None:
        if self._emit is not None:
            self._emit(
                {
                    "id": self._id,
                    "event": "progress",
                    "value": max(0.0, min(1.0, float(value))),
                    "message": message,
                }
            )


Handler = Callable[[Dict[str, Any], Context], Any]
_METHODS: Dict[str, Handler] = {}


def method(name: str) -> Callable[[Handler], Handler]:
    """Register ``fn(params, ctx)`` as an RPC method."""

    def deco(fn: Handler) -> Handler:
        if name in _METHODS:
            raise RuntimeError(f"duplicate RPC method: {name}")
        _METHODS[name] = fn
        return fn

    return deco


def methods() -> Dict[str, Handler]:
    return dict(_METHODS)


def call(name: str, params: Optional[Dict[str, Any]] = None, ctx: Optional[Context] = None) -> Any:
    """Invoke a method in-process (used by tests and by batch handlers)."""
    fn = _METHODS.get(name)
    if fn is None:
        raise EngineError("unknown_method", f"Unknown method: {name}")
    return fn(params or {}, ctx or Context())


def _error_payload(exc: BaseException) -> dict:
    if isinstance(exc, EngineError):
        return {"code": exc.code, "message": exc.message}
    if isinstance(exc, FileNotFoundError):
        return {"code": "not_found", "message": f"File not found: {exc.filename or exc}"}
    if isinstance(exc, PermissionError):
        return {"code": "permission_denied", "message": f"Permission denied: {exc.filename or exc}"}
    if isinstance(exc, KeyError):
        return {"code": "bad_params", "message": f"Missing parameter: {exc.args[0]}"}
    return {"code": "internal", "message": f"{type(exc).__name__}: {exc}"}


def serve(stdin: IO[str], stdout: IO[str], workers: int = 4) -> None:
    """Read requests from ``stdin`` until EOF; write responses to ``stdout``."""
    write_lock = threading.Lock()

    def emit(obj: dict) -> None:
        line = json.dumps(obj, ensure_ascii=False, default=str)
        with write_lock:
            stdout.write(line + "\n")
            stdout.flush()

    def run(req: dict) -> None:
        rid = req.get("id")
        try:
            result = call(req.get("method", ""), req.get("params") or {}, Context(emit, rid))
            emit({"id": rid, "result": result})
        except BaseException as exc:  # noqa: BLE001 - must always answer the request
            if not isinstance(exc, (EngineError, OSError, KeyError)):
                traceback.print_exc(file=sys.stderr)
            emit({"id": rid, "error": _error_payload(exc)})

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rpc") as pool:
        emit({"event": "ready", "methods": sorted(_METHODS)})
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
                if not isinstance(req, dict):
                    raise ValueError("request must be a JSON object")
            except ValueError as exc:
                emit({"id": None, "error": {"code": "bad_request", "message": str(exc)}})
                continue
            pool.submit(run, req)
