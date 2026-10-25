import json
from unittest.mock import Mock

import pytest
import requests

from lazybrief.ollama import (
    InvalidEndpointError,
    InvalidModelResponseError,
    ModelNotFoundError,
    OllamaClient,
    OllamaTimeoutError,
    OllamaUnavailableError,
    is_loopback_endpoint,
    validate_endpoint,
)


SOURCE = "Priya will ask two contributors to test the guide."
RESPONSE_JSON = {
    "summary": "The guide will be tested by contributors.",
    "insights": [
        {
            "type": "source_fact",
            "text": "Priya will arrange contributor testing.",
            "evidence_ids": [1],
        }
    ],
}


def make_response(status=200, payload=None):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload or {"response": json.dumps(RESPONSE_JSON)}
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(response=response)
    return response


def test_validate_endpoint_and_loopback():
    assert (
        validate_endpoint("http://localhost:11434/api/generate")
        == "http://localhost:11434/api/generate"
    )
    assert is_loopback_endpoint("http://127.0.0.1:11434/api/generate")
    assert not is_loopback_endpoint("https://example.test/api/generate")


@pytest.mark.parametrize(
    "endpoint",
    ["", "file:///tmp/model", "http://user:password@localhost/api/generate", "https://host/#frag"],
)
def test_validate_endpoint_rejects_invalid_or_credential_urls(endpoint):
    with pytest.raises(InvalidEndpointError):
        validate_endpoint(endpoint)


def test_summarize_posts_structured_request_and_parses_result():
    session = Mock()
    session.post.return_value = make_response()
    client = OllamaClient("http://localhost:11434/api/generate", "gemma3:1b", session=session)

    result = client.summarize(SOURCE, "Medium")

    assert result.action_items[0].task == SOURCE
    call = session.post.call_args
    assert call.args[0] == "http://localhost:11434/api/generate"
    assert call.kwargs["json"]["model"] == "gemma3:1b"
    assert call.kwargs["json"]["stream"] is False
    assert call.kwargs["json"]["format"]["type"] == "object"
    assert "insights" in call.kwargs["json"]["format"]["properties"]


def test_summarize_maps_timeout_to_actionable_error():
    session = Mock()
    session.post.side_effect = requests.Timeout()
    client = OllamaClient("http://localhost:11434/api/generate", "gemma3:1b", session=session)

    with pytest.raises(OllamaTimeoutError, match="shorter document"):
        client.summarize(SOURCE, "Short")


def test_summarize_reports_missing_model():
    session = Mock()
    session.post.return_value = make_response(status=404)
    client = OllamaClient("http://localhost:11434/api/generate", "missing-model", session=session)

    with pytest.raises(ModelNotFoundError, match="ollama pull"):
        client.summarize(SOURCE, "Short")


def test_summarize_reports_malformed_response():
    session = Mock()
    session.post.return_value = make_response(payload={"response": "not json"})
    client = OllamaClient("http://localhost:11434/api/generate", "gemma3:1b", session=session)

    with pytest.raises(InvalidModelResponseError, match="malformed JSON"):
        client.summarize(SOURCE, "Short")


def test_summarize_rejects_redirect_without_forwarding_document():
    session = Mock()
    session.post.return_value = make_response(status=302)
    client = OllamaClient("http://localhost:11434/api/generate", "gemma3:1b", session=session)

    with pytest.raises(OllamaUnavailableError, match="does not follow redirects"):
        client.summarize(SOURCE, "Short")

    assert session.post.call_args.kwargs["allow_redirects"] is False


def test_model_is_available_uses_ollama_tags_endpoint():
    session = Mock()
    session.get.return_value = make_response(
        payload={"models": [{"name": "gemma3:1b"}]}
    )
    client = OllamaClient("http://localhost:11434/api/generate", "gemma3:1b", session=session)

    assert client.model_is_available()
    assert session.get.call_args.args[0] == "http://localhost:11434/api/tags"
    assert session.get.call_args.kwargs["allow_redirects"] is False


def test_model_is_unavailable_when_not_in_tags():
    session = Mock()
    session.get.return_value = make_response(payload={"models": []})
    client = OllamaClient("http://localhost:11434/api/generate", "gemma3:1b", session=session)

    assert not client.model_is_available()


def test_model_check_maps_connection_failure():
    session = Mock()
    session.get.side_effect = requests.ConnectionError()
    client = OllamaClient("http://localhost:11434/api/generate", "gemma3:1b", session=session)

    with pytest.raises(OllamaUnavailableError, match="Cannot reach Ollama"):
        client.model_is_available()
