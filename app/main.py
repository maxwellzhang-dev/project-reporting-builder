"""FastAPI application: the page, a health endpoint, and its static assets."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.errors import envelope
from app.errors import install as install_error_handlers
from app.schemas.ai import (
    DescribeImageRequest,
    DescribeImageResponse,
    ExtractRequest,
    ExtractResponse,
)
from app.schemas.rendering import RenderRequest, RenderResponse
from app.services import ai_extraction
from app.services.rendering import render_card
from app.templating import render_page

MAX_BODY_BYTES = 64 * 1024
# The routes that can carry an image. Everything else keeps the 64 KiB limit.
IMAGE_ROUTE = "/api/ai/describe-image"
EXTRACT_ROUTE = "/api/ai/extract-progress"
IMAGE_ROUTES = frozenset({IMAGE_ROUTE, EXTRACT_ROUTE})
MAX_IMAGE_BODY_BYTES = 1536 * 1024

app = FastAPI(title=settings.app_name)


class BodySizeLimit(BaseHTTPMiddleware):
    """Enforce the body limit at the boundary: 64 KiB, or 1.5 MiB on the two AI
    routes that can carry one downscaled image.

    Content-Length is a claim, not a fact, so the body is also measured as it
    arrives (docs/test_plan.md §4).
    """

    async def dispatch(self, request: Request, call_next):
        limit = MAX_IMAGE_BODY_BYTES if request.url.path in IMAGE_ROUTES else MAX_BODY_BYTES
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            return envelope(413, "Request body is too large.")
        if request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > limit:
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


@app.post(EXTRACT_ROUTE, response_model=ExtractResponse)
def extract_progress(
    payload: ExtractRequest,
    provider: ai_extraction.Provider | None = Depends(get_ai_provider),
) -> JSONResponse:
    try:
        result = ai_extraction.extract_progress(
            payload.source_text, provider, image_data_url=payload.image_data_url
        )
    except ai_extraction.AIError as error:
        return envelope(error.status, error.message)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@app.post(IMAGE_ROUTE, response_model=DescribeImageResponse)
def describe_image(
    payload: DescribeImageRequest,
    provider: ai_extraction.Provider | None = Depends(get_ai_provider),
) -> JSONResponse:
    """Draft alt text and a caption for an image the person chose to send.

    The image is used for this one call and not stored or logged: it leaves
    the browser only when the person asks for a description (scope §7).
    """
    try:
        result = ai_extraction.describe_image(payload.image_data_url, provider)
    except ai_extraction.AIError as error:
        return envelope(error.status, error.message)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
