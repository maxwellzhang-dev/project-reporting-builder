"""FastAPI application: the page, a health endpoint, and its static assets."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.errors import envelope
from app.errors import install as install_error_handlers
from app.schemas.ai import ExtractRequest, ExtractResponse
from app.schemas.rendering import RenderRequest, RenderResponse
from app.services import ai_extraction
from app.services.rendering import render_card
from app.templating import render_page

MAX_BODY_BYTES = 64 * 1024

app = FastAPI(title=settings.app_name)


class BodySizeLimit(BaseHTTPMiddleware):
    """Enforce the 64 KiB body limit at the boundary.

    Content-Length is a claim, not a fact, so the body is also measured as it
    arrives (docs/test_plan.md §4).
    """

    async def dispatch(self, request: Request, call_next):
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return envelope(413, "Request body is too large.")
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > MAX_BODY_BYTES:
                return envelope(413, "Request body is too large.")
        return await call_next(request)


app.add_middleware(BodySizeLimit)
install_error_handlers(app)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Basic application availability. Says nothing about Azure OpenAI."""
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    html = render_page(app_name=settings.app_name)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.post("/api/cards/render", response_model=RenderResponse)
def render(payload: RenderRequest) -> JSONResponse:
    preview_html, plain_text, rich_html = render_card(payload.card)
    body = RenderResponse(
        card_id=payload.card.id,
        revision=payload.revision,
        preview_html=preview_html,
        plain_text=plain_text,
        rich_html=rich_html,
    )
    return JSONResponse(body.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


def get_ai_provider() -> ai_extraction.Provider | None:
    """The live provider, or None when AI is disabled.

    Tests override this dependency with a fake, so no test makes a paid call.
    """
    if not settings.ai_enabled:
        return None
    from app.services.azure_provider import AzureOpenAIProvider

    return AzureOpenAIProvider(
        endpoint=settings.azure_openai_endpoint,
        deployment=settings.azure_openai_deployment,
        api_key=settings.azure_openai_api_key,
    )


@app.post("/api/ai/extract-progress", response_model=ExtractResponse)
def extract_progress(
    payload: ExtractRequest,
    provider: ai_extraction.Provider | None = Depends(get_ai_provider),
) -> JSONResponse:
    try:
        result = ai_extraction.extract_progress(payload.source_text, provider)
    except ai_extraction.AIError as error:
        return envelope(error.status, error.message)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
