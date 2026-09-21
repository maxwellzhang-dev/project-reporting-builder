"""A content-filter rejection is invalid input, not an upstream outage.

The bodies below are the shapes Azure actually returned during live testing on
2026-09-21, trimmed to the fields the check reads. No call is made here.
"""

import pytest

from app.services.azure_provider import _is_content_filter


class FakeBadRequest(Exception):
    def __init__(self, body=None, code=None):
        super().__init__("400")
        self.body = body
        self.code = code


JAILBREAK_BODY = {
    "error": {
        "message": "The response was filtered due to the prompt triggering ...",
        "type": "invalid_request_error",
        "param": "prompt",
        "code": "content_filter",
        "innererror": {"code": "ContentFiltered"},
    }
}


def test_recognises_the_body_azure_returned():
    assert _is_content_filter(FakeBadRequest(body=JAILBREAK_BODY))


def test_recognises_the_code_on_the_exception():
    assert _is_content_filter(FakeBadRequest(code="content_filter"))


def test_recognises_innererror_alone():
    body = {"error": {"code": None, "innererror": {"code": "ContentFiltered"}}}
    assert _is_content_filter(FakeBadRequest(body=body))


@pytest.mark.parametrize(
    "error",
    [
        FakeBadRequest(),
        FakeBadRequest(body=None, code="invalid_request_error"),
        FakeBadRequest(body={"error": {"code": "DeploymentNotFound"}}),
        # The wording that broke the first live run: a different 400 entirely,
        # which must keep propagating as an upstream failure.
        FakeBadRequest(
            body={
                "error": {
                    "message": "Response input messages must contain the word 'json' ...",
                    "code": None,
                }
            }
        ),
    ],
)
def test_other_bad_requests_are_not_content_filtered(error):
    assert not _is_content_filter(error)


def test_a_non_dict_body_does_not_raise():
    assert not _is_content_filter(FakeBadRequest(body="upstream returned html"))
