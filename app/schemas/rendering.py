"""Request and response bodies for the render endpoint (architecture §6)."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.cards import Card


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    card: Card


class RenderResponse(BaseModel):
    card_id: UUID
    revision: int
    preview_html: str
    plain_text: str
    rich_html: str | None
