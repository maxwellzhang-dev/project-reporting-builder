"""One error envelope for the whole API (docs/architecture.md §6).

FastAPI's default 422 body echoes the offending input back to the caller. The
document forbids exposing raw Pydantic input, so validation errors are
reshaped here into paths and messages only.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

CODES = {
    400: "bad_request",
    404: "not_found",
    413: "request_too_large",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "unavailable",
    504: "upstream_timeout",
}


def envelope(status: int, message: str, fields: list[dict] | None = None) -> JSONResponse:
    error: dict = {"code": CODES.get(status, "error"), "message": message}
    if fields:
        error["fields"] = fields
    return JSONResponse({"error": error}, status_code=status, headers={"Cache-Control": "no-store"})


def _path(location: tuple) -> str:
    # Drop the leading "body"; keep the caller-meaningful path.
    parts = [str(part) for part in location if part != "body"]
    return ".".join(parts) or "body"


def install(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [{"path": _path(error["loc"]), "message": error["msg"]} for error in exc.errors()]
        return envelope(422, "Review the highlighted fields.", fields)

    @app.exception_handler(HTTPException)
    async def _http(_: Request, exc: HTTPException) -> JSONResponse:
        return envelope(exc.status_code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Never leak the exception text or a traceback (architecture §6).
        return envelope(500, "Something went wrong. Please try again.")
