"""AI request and draft models (docs/architecture.md §9).

The draft is a proposal: it carries no status and no card id, because the user
supplies the status and confirms before a card exists (scope §5).
"""

from pydantic import BaseModel, ConfigDict, Field

SOURCE_TEXT_MAX = 8_000
DRAFT_LIST_MAX = 8
DRAFT_ITEM_MAX = 300


class ExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source_text: str = Field(min_length=1, max_length=SOURCE_TEXT_MAX)


DraftList = list[str]


class ProgressDraft(BaseModel):
    """What the model is allowed to return. Anything else is rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(max_length=120)
    summary: str = Field(max_length=2_000)
    completed_items: DraftList = Field(default_factory=list, max_length=DRAFT_LIST_MAX)
    next_steps: DraftList = Field(default_factory=list, max_length=DRAFT_LIST_MAX)
    risks: DraftList = Field(default_factory=list, max_length=DRAFT_LIST_MAX)


class ExtractResponse(BaseModel):
    draft: ProgressDraft
    review_notes: list[str] = Field(default_factory=list, max_length=DRAFT_LIST_MAX)
