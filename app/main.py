"""FastAPI application: the page, a health endpoint, and its static assets."""

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class BodySizeLimit:
    """Enforce the body limit at the boundary: 64 KiB, or 1.5 MiB on the two AI
    routes that can carry one downscaled image.

    Content-Length is a claim, not a fact, and a chunked request has none, so
    the body is counted as it arrives and reading stops the moment it passes
    the limit (docs/test_plan.md §4). Reading it whole and measuring afterwards,
    as the first version did, let a client stream as much as it liked into
    memory before being refused.

    A plain ASGI middleware rather than BaseHTTPMiddleware, because only this
    level sees the body as it arrives. On overflow it sends the 413 itself and
    tells the route the body has ended; whatever the route then tries to send
    is dropped. Raising instead does not work: FastAPI turns any exception
    during body parsing into a 400.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = MAX_IMAGE_BODY_BYTES if scope["path"] in IMAGE_ROUTES else MAX_BODY_BYTES
        declared = dict(scope["headers"]).get(b"content-length", b"")
        if declared.isdigit() and int(declared) > limit:
            await envelope(413, "Request body is too large.")(scope, receive, send)
            return

        received = 0
        refused = False

        async def counted() -> Message:
            nonlocal received, refused
            if refused:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    refused = True
                    await envelope(413, "Request body is too large.")(scope, receive, send)
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        async def guarded(message: Message) -> None:
            if not refused:
                await send(message)

        await self.app(scope, counted, guarded)


# Sent on every response (docs/architecture.md §12). The CSP allows only this
# origin for scripts, styles and requests: the page has no inline script, no
# CDN and no third party. data: and blob: images are the local image cards and
# the PNG export, which draws the card through an SVG data URL; connect-src
# blob: and data: let the export library read them back. Every browser test
# fails on any CSP violation, so a directive that breaks the page cannot pass.
CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self' data: blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
)
SECURITY_HEADERS = [
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    # Browsers ignore this over plain HTTP, so it is harmless locally; on the
    # deployed HTTPS site it stops a later visit being downgraded.
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
]


class SecurityHeaders:
    """Add SECURITY_HEADERS to every HTTP response, error responses included."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    *((name, value) for name, value in SECURITY_HEADERS if name not in present),
                ]
            await send(message)

        await self.app(scope, receive, with_headers)


app.add_middleware(BodySizeLimit)
# Added last, so it is outermost and also covers the 413 BodySizeLimit sends.
app.add_middleware(SecurityHeaders)
install_error_handlers(app)


class RevalidatedStaticFiles(StaticFiles):
    """Static files the browser must revalidate on every load.

    The ES modules are not fingerprinted, so heuristic caching could pair a
    new page with an old module after a deploy (the Select all button with no
    handler). no-cache keeps the ETag round trip cheap: an unchanged file is a
    304 with no body.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", RevalidatedStaticFiles(directory="app/static"), name="static")


# HEAD as well as GET on the two routes monitors and link checkers probe.
# Starlette before 1.0 added HEAD to every GET route by itself; since the
# upgrade it has to be asked for, and without it a HEAD check reads 405.
@app.api_route("/healthz", methods=["GET", "HEAD"])
def healthz() -> JSONResponse:
    """Basic application availability. Says nothing about Azure OpenAI."""
    return JSONResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
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


def client_id(request: Request) -> str:
    """Who the AI rate limit counts against.

    Behind Azure Container Apps the socket peer is the ingress proxy, and the
    visitor's address is the entry the proxy appended to X-Forwarded-For:
    `trusted_proxy_hops` from the right. Entries to its left are whatever the
    client sent and are ignored, and with no trusted proxy the header is
    ignored entirely, or rotating a forged value would buy a fresh limit.
    """
    hops = settings.trusted_proxy_hops
    if hops > 0:
        forwarded = request.headers.get("x-forwarded-for", "")
        entries = [part.strip() for part in forwarded.split(",") if part.strip()]
        if len(entries) >= hops:
            return entries[-hops]
    return request.client.host if request.client else "unknown"


@app.post(EXTRACT_ROUTE, response_model=ExtractResponse)
def extract_progress(
    request: Request,
    payload: ExtractRequest,
    provider: ai_extraction.Provider | None = Depends(get_ai_provider),
) -> JSONResponse:
    try:
        result = ai_extraction.extract_progress(
            payload.source_text,
            provider,
            image_data_url=payload.image_data_url,
            client=client_id(request),
        )
    except ai_extraction.AIError as error:
        return envelope(error.status, error.message)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@app.post(IMAGE_ROUTE, response_model=DescribeImageResponse)
def describe_image(
    request: Request,
    payload: DescribeImageRequest,
    provider: ai_extraction.Provider | None = Depends(get_ai_provider),
) -> JSONResponse:
    """Draft alt text and a caption for an image the person chose to send.

    The image is used for this one call and not stored or logged: it leaves
    the browser only when the person asks for a description (scope §7).
    """
    try:
        result = ai_extraction.describe_image(
            payload.image_data_url, provider, client=client_id(request)
        )
    except ai_extraction.AIError as error:
        return envelope(error.status, error.message)
    return JSONResponse(result.model_dump(mode="json"), headers={"Cache-Control": "no-store"})
