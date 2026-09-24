"""AI request and draft models (docs/architecture.md §9).

The draft is a proposal: it carries no status and no card id, because the user
supplies the status and confirms before a card exists (scope §5).
"""

from __future__ import annotations

import base64
import binascii
import re
from math import isfinite
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SOURCE_TEXT_MAX = 8_000
DRAFT_LIST_MAX = 8
DRAFT_ITEM_MAX = 300
DRAFT_METRICS_MAX = 6


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


class MetricDraft(BaseModel):
    """A proposed metric card, copied from the text rather than computed.

    `previous` is optional on purpose. Where the source states a current value
    and no baseline, leaving it empty produces an ordinary metric card showing
    only the current figure (scope §4). Filling it would mean deriving a
    number the text does not contain, which is the one thing the model must
    never do: "847 new users, up 23% from last sprint" names one figure, not
    two.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=120)
    current: float
    previous: float | None = None
    unit: Literal["number", "percent", "custom"] = "number"
    unit_label: str = Field(default="", max_length=16)

    # Deliberately the same check MetricCard applies to user input: model
    # output gets no easier ride than a person typing. It runs before
    # coercion, because a bool would otherwise arrive here already turned
    # into 1.0.
    @model_validator(mode="after")
    def _label_only_for_custom(self) -> MetricDraft:
        # The live model tends to fill this in anyway, returning "%" beside
        # unit "percent" and "users" beside "number". Rendering ignores the
        # label unless the unit is custom, so it is harmless on screen but
        # would surface the moment someone switched the unit. Dropping it is
        # normalisation, not rejection: a stray label is no reason to throw
        # away an otherwise good draft.
        if self.unit != "custom":
            object.__setattr__(self, "unit_label", "")
        return self

    @field_validator("current", "previous", mode="before")
    @classmethod
    def _real_finite_numbers(cls, value: Any) -> Any:
        if value is None:
            return value
        if isinstance(value, bool | str):
            raise ValueError("must be a number, not a string or boolean")
        if isinstance(value, float) and not isfinite(value):
            raise ValueError("must be finite")
        return value


class ExtractResponse(BaseModel):
    draft: ProgressDraft
    metrics: list[MetricDraft] = Field(default_factory=list, max_length=DRAFT_METRICS_MAX)
    review_notes: list[str] = Field(default_factory=list, max_length=DRAFT_LIST_MAX)


# ---- image description ----------------------------------------------------

# The browser downscales before sending (longest side 1024 px, JPEG), which
# keeps a typical screenshot well under this. The limit is on the decoded
# image; the data URL is about a third larger.
IMAGE_BYTES_MAX = 1024 * 1024
IMAGE_DATA_URL_MAX = 1_400_000
# Longer than the card's own limits on purpose. The live model has returned
# alt text of about 570 characters when asked for 300; rejecting that would
# throw the whole draft away. The person trims it in review, and the card's
# field validation (alt text 300, caption 1,000) still applies when it is used.
IMAGE_DRAFT_TEXT_MAX = 1_000

_DATA_URL = re.compile(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})")
# The declared type has to match the bytes: a "PNG" that is not one is refused
# here rather than passed to the model.
_SIGNATURES = {
    "png": (b"\x89PNG\r\n\x1a\n",),
    "jpeg": (b"\xff\xd8\xff",),
    "webp": (b"RIFF",),
}


class DescribeImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_data_url: str = Field(max_length=IMAGE_DATA_URL_MAX)

    @field_validator("image_data_url")
    @classmethod
    def _real_image_within_limit(cls, value: str) -> str:
        # Messages name the rule, never the value: the error envelope must not
        # echo the submitted image back (docs/architecture.md §6).
        match = _DATA_URL.fullmatch(value)
        if not match:
            raise ValueError("must be a PNG, JPEG or WebP image as a base64 data URL")
        kind, payload = match.groups()
        try:
            data = base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("is not valid base64") from error
        if len(data) > IMAGE_BYTES_MAX:
            raise ValueError("is larger than 1 MiB after decoding")
        if not data.startswith(_SIGNATURES[kind]) or (kind == "webp" and data[8:12] != b"WEBP"):
            raise ValueError("does not contain the image type it declares")
        return value


class ImageDraft(BaseModel):
    """What the model is allowed to return for an image. Anything else is rejected."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    alt_text: str = Field(min_length=1, max_length=IMAGE_DRAFT_TEXT_MAX)
    caption: str = Field(default="", max_length=IMAGE_DRAFT_TEXT_MAX)


class DescribeImageResponse(BaseModel):
    draft: ImageDraft
    review_notes: list[str] = Field(default_factory=list, max_length=DRAFT_LIST_MAX)
