import json

import pytest

from lazybrief.results import ResultValidationError, parse_model_response


SOURCE = "Leo will update the Windows installation section by Friday."
VALID_RESPONSE = {
    "summary": "The team plans to improve the setup guide.",
    "insights": [
        {
            "type": "source_fact",
            "text": "Leo owns the Windows installation update.",
            "evidence_ids": [1],
        },
        {
            "type": "interpretation",
            "text": "The team is prioritizing onboarding clarity.",
            "evidence_ids": [],
        },
    ],
}


def test_parse_valid_result_and_format_markdown():
    result = parse_model_response(json.dumps(VALID_RESPONSE), SOURCE)
    markdown = result.to_markdown()
    assert result.summary == VALID_RESPONSE["summary"]
    assert "**Source-based:**" in markdown
    assert "**AI interpretation:**" in markdown
    assert f"- [ ] {SOURCE}" in markdown


def test_parse_empty_action_items():
    result = parse_model_response(json.dumps(VALID_RESPONSE), "The team had a discussion.")
    assert result.action_items == []
    assert "No explicit action items found" in result.to_markdown()


@pytest.mark.parametrize(
    "raw",
    [
        "not JSON",
        "[]",
        json.dumps({**VALID_RESPONSE, "summary": ""}),
        json.dumps({**VALID_RESPONSE, "insights": "not a list"}),
        json.dumps(
            {
                **VALID_RESPONSE,
                "unknown": "field",
            }
        ),
        json.dumps(
            {
                **VALID_RESPONSE,
                "insights": [
                    {
                        "type": "source_fact",
                        "text": "unsupported",
                        "evidence_ids": [2],
                    }
                ],
            }
        ),
    ],
)
def test_parse_rejects_malformed_or_ungrounded_results(raw):
    with pytest.raises(ResultValidationError):
        parse_model_response(raw, SOURCE)


def test_parse_maps_ids_to_original_source_text():
    result = parse_model_response(json.dumps(VALID_RESPONSE), SOURCE)
    assert result.insights[0].evidence == [SOURCE]
    assert result.insights[0].text == SOURCE
    assert result.action_items[0].evidence == [SOURCE]
    assert result.action_items[0].task == SOURCE


def test_parse_deduplicates_source_facts():
    payload = {
        **VALID_RESPONSE,
        "insights": [
            VALID_RESPONSE["insights"][0],
            VALID_RESPONSE["insights"][0],
        ],
    }
    result = parse_model_response(json.dumps(payload), SOURCE)
    assert len(result.insights) == 1


def test_parse_extracts_only_explicit_tasks_verbatim():
    source = (
        "We discussed the guide. Maya will revise the setup steps by Friday. "
        "The team likes the result."
    )
    result = parse_model_response(json.dumps(VALID_RESPONSE), source)
    assert [item.task for item in result.action_items] == [
        "Maya will revise the setup steps by Friday."
    ]


def test_parse_extracts_explicit_action_from_imperative():
    source = "Please review the onboarding guide."
    result = parse_model_response(json.dumps(VALID_RESPONSE), source)
    assert [item.task for item in result.action_items] == [source]


def test_parse_does_not_treat_a_scheduled_event_as_an_action():
    source = "The meeting will be Friday."
    result = parse_model_response(json.dumps(VALID_RESPONSE), source)
    assert result.action_items == []
