"""Streamlit interface for the LazyBrief local AI briefing app."""

from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

from lazybrief.config import AppSettings, MAX_INPUT_BYTES, MAX_INPUT_CHARS
from lazybrief.input_processing import InputValidationError, decode_upload, validate_text
from lazybrief.ollama import (
    ModelNotFoundError,
    OllamaClient,
    OllamaError,
    is_loopback_endpoint,
    validate_endpoint,
)
from lazybrief.prompts import DETAIL_GUIDANCE
from lazybrief.results import BriefResult

st.set_page_config(
    page_title="LazyBrief — Less busywork, more focus",
    page_icon="LB",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {max-width: 1180px; padding-top: 2.2rem; padding-bottom: 3rem;}
    h1 {letter-spacing: -0.04em; font-weight: 650;}
    [data-testid="stMetric"] {background: #eef1ec; padding: 1rem; border-radius: 12px;}
    div[data-testid="stVerticalBlock"] > div:has(> div[data-testid="stButton"]) button {
        border-radius: 9px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _settings() -> AppSettings:
    try:
        return AppSettings.from_environment()
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        raise


def _client(endpoint: str, model: str, timeout: int) -> OllamaClient:
    return OllamaClient(endpoint=endpoint, model=model, timeout=timeout)


def _render_insights(result: BriefResult) -> str:
    if not result.insights:
        return "No key insights were returned."
    lines: list[str] = []
    for insight in result.insights:
        label = "Source-based" if insight.type == "source_fact" else "AI interpretation"
        lines.append(f"- **{label}:** {insight.text}")
        if insight.type == "interpretation":
            for evidence in insight.evidence:
                lines.append(f"  - Context cited by model: “{evidence}”")
    return "\n".join(lines)


def _render_actions(result: BriefResult) -> str:
    if not result.action_items:
        return "- No explicit action items found."
    return "\n".join(f"- [ ] {item.task}" for item in result.action_items)


settings = _settings()
if "brief_result" not in st.session_state:
    st.session_state.brief_result = None
if "source_text" not in st.session_state:
    st.session_state.source_text = ""


def _load_sample() -> None:
    sample_path = Path(__file__).parent / "sample_data" / "meeting_notes.txt"
    st.session_state.source_text = sample_path.read_text(encoding="utf-8")


with st.sidebar:
    st.markdown("## Settings")
    endpoint = st.text_input(
        "Ollama API endpoint",
        value=settings.endpoint,
        key="settings_endpoint",
        help="Defaults to the Ollama service on this computer.",
    )
    model = st.text_input(
        "Model",
        value=settings.model,
        key="settings_model",
    )
    timeout = st.number_input(
        "Request timeout (seconds)",
        min_value=1,
        max_value=900,
        value=settings.timeout,
        step=15,
        key="settings_timeout",
    )
    st.caption(
        "LazyBrief sends the document to this configured Ollama endpoint. "
        "The default is localhost; documents are not logged or saved by LazyBrief."
    )

    is_local = is_loopback_endpoint(endpoint)
    if not is_local:
        try:
            host = urlsplit(validate_endpoint(endpoint)).hostname or "configured host"
        except OllamaError:
            host = "configured host"
        st.warning(
            f"This endpoint is not localhost. Your document will be sent to `{host}`."
        )
        confirmation = st.text_input(
            f"To allow this, type: I understand: {host}",
            key="remote_endpoint_confirmation",
        )
    else:
        confirmation = ""

    if st.button("Check model status", use_container_width=True):
        try:
            available = _client(endpoint, model, int(timeout)).model_is_available()
            if available:
                st.success(f"`{model}` is available.")
            else:
                st.warning(
                    f"`{model}` is not installed. Run `ollama pull {model}` in a "
                    "terminal, then check again."
                )
        except OllamaError as exc:
            st.error(str(exc))

    st.markdown("---")
    st.markdown("### Quick start")
    st.markdown(
        "1. Install [Ollama](https://ollama.com/download).\n"
        "2. Run `ollama pull gemma3:1b`.\n"
        "3. Keep Ollama running and generate a brief."
    )
    st.caption(
        "Input stays in this browser session and is sent only to the endpoint shown "
        "above when you request a brief. LazyBrief does not claim to be fully offline."
    )

st.title("LazyBrief")
st.markdown("### Less reading busywork. More time for what matters.")
st.write(
    "Turn meeting notes, study material, and technical documents into a concise "
    "summary, evidence-backed insights, and a grounded checklist."
)

input_column, output_column = st.columns([1, 1], gap="large")

with input_column:
    st.subheader("Your source")
    st.caption("Paste text or upload a UTF-8 TXT/Markdown file. Nothing is saved to disk.")
    if st.button("Load fictional sample notes", use_container_width=False):
        _load_sample()

    uploaded = st.file_uploader(
        "Upload a text file",
        type=["txt", "md"],
        help=f"UTF-8 .txt or .md only; maximum {MAX_INPUT_BYTES // 1024} KB.",
    )
    if uploaded is not None:
        content = uploaded.getvalue()
        upload_fingerprint = hashlib.sha256(content).hexdigest()
        if upload_fingerprint != st.session_state.get("_loaded_upload_hash"):
            try:
                st.session_state.source_text = decode_upload(uploaded.name, content)
            except InputValidationError as exc:
                st.session_state.source_text = ""
                st.session_state.brief_result = None
                st.error(str(exc))
            st.session_state["_loaded_upload_hash"] = upload_fingerprint

    with st.form("brief_form"):
        source_text = st.text_area(
            "Paste or edit text",
            key="source_text",
            height=330,
            max_chars=MAX_INPUT_CHARS,
            placeholder="Paste notes, an excerpt, or a document here…",
            label_visibility="collapsed",
        )
        detail = st.selectbox(
            "Summary detail",
            options=list(DETAIL_GUIDANCE),
            index=1,
        )
        generate = st.form_submit_button(
            "Generate my brief",
            type="primary",
            use_container_width=True,
        )

    word_count = len(source_text.split())
    character_count = len(source_text)
    count_col1, count_col2 = st.columns(2)
    count_col1.metric("Words", f"{word_count:,}")
    count_col2.metric("Characters", f"{character_count:,}")

    if generate:
        try:
            source = validate_text(source_text)
            normalized_endpoint = validate_endpoint(endpoint)
            expected_confirmation = f"I understand: {urlsplit(normalized_endpoint).hostname}"
            if not is_loopback_endpoint(normalized_endpoint) and confirmation != expected_confirmation:
                st.error(
                    "Confirm the non-local endpoint in the sidebar before sending "
                    "document text."
                )
            else:
                client = _client(normalized_endpoint, model, int(timeout))
                with st.spinner(f"Checking {model} and preparing your brief…"):
                    if not client.model_is_available():
                        raise ModelNotFoundError(
                            f"`{model}` is not installed at this endpoint. Run "
                            f"`ollama pull {model}` in a terminal, then try again."
                        )
                    result = client.summarize(source, detail)
                st.session_state.brief_result = result
                st.session_state.brief_source_fingerprint = hashlib.sha256(
                    source.encode("utf-8")
                ).hexdigest()
                st.session_state.brief_model = model
        except InputValidationError as exc:
            st.error(str(exc))
        except OllamaError as exc:
            st.error(str(exc))
        except ValueError as exc:
            st.error(str(exc))

with output_column:
    st.subheader("Your brief")
    result = st.session_state.brief_result
    if result is None:
        st.info(
            "Your summary, evidence-backed insights, and action checklist will appear "
            "here after you generate a brief."
        )
        st.caption("Try the fictional meeting notes to test the workflow.")
    elif hashlib.sha256(source_text.strip().encode("utf-8")).hexdigest() != st.session_state.get(
        "brief_source_fingerprint"
    ):
        st.info("Your source has changed. Generate a fresh brief to update these results.")
    else:
        st.caption(f"Generated with `{st.session_state.brief_model}`")
        st.markdown("#### Summary")
        st.markdown(result.summary)
        st.download_button(
            "Download summary",
            data=result.summary + "\n",
            file_name="lazybrief-summary.txt",
            mime="text/plain",
            key="download_summary",
        )

        st.markdown("#### Key insights")
        insights_text = _render_insights(result)
        st.markdown(insights_text)
        st.download_button(
            "Download insights",
            data=insights_text + "\n",
            file_name="lazybrief-insights.md",
            mime="text/markdown",
            key="download_insights",
        )

        st.markdown("#### Action items")
        actions_text = _render_actions(result)
        st.markdown(actions_text)
        st.download_button(
            "Download action items",
            data=actions_text + "\n",
            file_name="lazybrief-action-items.md",
            mime="text/markdown",
            key="download_actions",
        )

        st.download_button(
            "Download complete brief",
            data=result.to_markdown(),
            file_name="lazybrief-brief.md",
            mime="text/markdown",
            type="primary",
            key="download_complete",
        )
