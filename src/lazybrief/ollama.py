"""HTTP client for local or explicitly configured Ollama endpoints."""

from __future__ import annotations

import ipaddress
import json
from urllib.parse import urlsplit, urlunsplit

import requests

from lazybrief.prompts import SYSTEM_PROMPT, build_prompt
from lazybrief.results import BriefResult, ResultValidationError, parse_model_response

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "insights": {
            "type": "array",
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["source_fact", "interpretation"]},
                    "text": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["type", "text", "evidence_ids"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "insights"],
    "additionalProperties": False,
}


class OllamaError(Exception):
    """Base class for user-actionable Ollama errors."""


class InvalidEndpointError(OllamaError):
    """The configured URL is not a valid HTTP(S) endpoint."""


class OllamaUnavailableError(OllamaError):
    """The configured Ollama service could not be reached."""


class ModelNotFoundError(OllamaError):
    """The requested model is not installed at the configured endpoint."""


class OllamaTimeoutError(OllamaError):
    """The local model did not respond before the configured timeout."""


class InvalidModelResponseError(OllamaError):
    """Ollama returned a response that could not be used."""


def validate_endpoint(endpoint: str) -> str:
    """Return a normalized HTTP(S) endpoint or raise a clear validation error."""
    try:
        parsed = urlsplit(endpoint.strip())
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname is not None
            and parsed.port != 0
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
        )
    except ValueError as exc:
        raise InvalidEndpointError("Enter a valid HTTP(S) Ollama endpoint URL.") from exc
    if not valid:
        raise InvalidEndpointError(
            "Enter a valid HTTP(S) endpoint without credentials or a URL fragment."
        )
    return urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", parsed.query, "")
    )


def is_loopback_endpoint(endpoint: str) -> bool:
    """Identify localhost and loopback IP URLs for the privacy confirmation."""
    try:
        host = urlsplit(validate_endpoint(endpoint)).hostname
    except InvalidEndpointError:
        return False
    if host is None:
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _tags_url(endpoint: str) -> str:
    parsed = urlsplit(validate_endpoint(endpoint))
    path = parsed.path.rstrip("/")
    if path.endswith("/generate"):
        path = f"{path[:-len('/generate')]}/tags"
    elif path.endswith("/api"):
        path = f"{path}/tags"
    else:
        path = f"{path}/api/tags"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class OllamaClient:
    """Small synchronous client; it never logs prompt or response contents."""

    def __init__(
        self,
        endpoint: str,
        model: str,
        timeout: int = 180,
        session: requests.Session | None = None,
    ) -> None:
        self.endpoint = validate_endpoint(endpoint)
        if not model.strip():
            raise ValueError("Model name cannot be empty.")
        if not 1 <= timeout <= 900:
            raise ValueError("Timeout must be between 1 and 900 seconds.")
        self.model = model.strip()
        self.timeout = timeout
        self.session = session or requests.Session()

    def model_is_available(self) -> bool:
        """Check whether the configured model appears in Ollama's local tags."""
        try:
            response = self.session.get(
                _tags_url(self.endpoint),
                timeout=self.timeout,
                allow_redirects=False,
            )
            self._raise_for_status(response)
            data = response.json()
        except requests.Timeout as exc:
            raise OllamaTimeoutError(
                "Ollama did not respond in time. Check that it is running and increase "
                "the timeout if the model is still loading."
            ) from exc
        except requests.ConnectionError as exc:
            raise OllamaUnavailableError(
                "Cannot reach Ollama. Start Ollama and confirm its local endpoint."
            ) from exc
        except requests.RequestException as exc:
            raise OllamaUnavailableError(
                "Could not check Ollama. Confirm the configured endpoint and try again."
            ) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise InvalidModelResponseError(
                "Ollama returned an unreadable model list."
            ) from exc

        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            raise InvalidModelResponseError("Ollama returned an invalid model list.")
        available = {
            entry.get("name")
            for entry in models
            if isinstance(entry, dict) and isinstance(entry.get("name"), str)
        }
        return self.model in available

    def summarize(self, text: str, detail: str) -> BriefResult:
        """Generate and validate one structured brief from the supplied source."""
        payload = {
            "model": self.model,
            "system": SYSTEM_PROMPT,
            "prompt": build_prompt(text, detail),
            "format": RESULT_SCHEMA,
            "stream": False,
            "options": {"temperature": 0.2},
        }
        try:
            response = self.session.post(
                self.endpoint,
                json=payload,
                timeout=self.timeout,
                allow_redirects=False,
            )
            self._raise_for_status(response)
        except requests.Timeout as exc:
            raise OllamaTimeoutError(
                "The model took too long to respond. Try a shorter document or raise "
                "the timeout in the sidebar."
            ) from exc
        except requests.ConnectionError as exc:
            raise OllamaUnavailableError(
                "Cannot reach Ollama. Start the local service and try again."
            ) from exc
        except requests.RequestException as exc:
            raise OllamaUnavailableError(
                "The request to Ollama failed. Check its endpoint and try again."
            ) from exc

        try:
            data = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise InvalidModelResponseError(
                "Ollama returned malformed response data. Try again."
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("response"), str):
            raise InvalidModelResponseError(
                "Ollama returned an unexpected response. Try again."
            )
        raw = data["response"].strip()
        if not raw:
            raise InvalidModelResponseError("The model returned an empty brief.")
        try:
            return parse_model_response(raw, text)
        except ResultValidationError as exc:
            raise InvalidModelResponseError(str(exc)) from exc

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if 300 <= response.status_code < 400:
            raise OllamaUnavailableError(
                "Ollama redirected the request. Update the configured endpoint to the "
                "final URL; LazyBrief does not follow redirects with document text."
            )
        if response.status_code == 404:
            raise ModelNotFoundError(
                "The requested model is not available. In a terminal, run "
                "`ollama pull gemma3:1b` or change the model name in the sidebar."
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise OllamaUnavailableError(
                f"Ollama returned HTTP {response.status_code}. Check the endpoint and "
                "service logs, then try again."
            ) from exc
