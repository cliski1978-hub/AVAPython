"""Phase 5.22 context-window policy unit tests.

The manager is a pure function of an eligible context, a model context window,
and a token estimator, so these tests drive it directly with synthetic neutral
messages. They pin the deterministic policy: what fits, what is dropped, in what
order, and the one case that must fail.
"""

from __future__ import annotations

import pytest

from ava.contracts.conversations import ContextMessage, MessageRole
from ava.execution.context_window import (
    CHARS_PER_TOKEN,
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    MAX_OUTPUT_RESERVE_FRACTION,
    MESSAGE_FRAMING_TOKENS,
    ContextWindowExceededError,
    ContextWindowManager,
    DeterministicTokenEstimator,
    TokenEstimator,
    input_budget_for,
    usable_context_limit,
)

# ============================================================
# BEGIN: Helpers
# ============================================================


def _user(content: str) -> ContextMessage:
    return ContextMessage(role=MessageRole.USER, content=content)


def _assistant(content: str) -> ContextMessage:
    return ContextMessage(role=MessageRole.ASSISTANT, content=content)


def _system(content: str) -> ContextMessage:
    return ContextMessage(role=MessageRole.SYSTEM, content=content)


def _turn(number: int, *, size: int = 40) -> list[ContextMessage]:
    """One user message with one visible answer, of a predictable size."""
    return [_user(f"U{number}" + "x" * size), _assistant(f"A{number}" + "y" * size)]


def _conversation(turns: int, *, size: int = 40) -> list[ContextMessage]:
    """``turns`` complete turns followed by the current, unanswered user turn."""
    messages: list[ContextMessage] = []
    for number in range(1, turns + 1):
        messages.extend(_turn(number, size=size))
    messages.append(_user("current"))
    return messages


def _manager() -> ContextWindowManager:
    return ContextWindowManager()


def _contents(messages: list[ContextMessage]) -> list[str]:
    return [message.content for message in messages]


# ============================================================
# END: Helpers
# ============================================================
# ============================================================
# BEGIN: Token Estimator
# ============================================================


def test_estimate_is_deterministic_across_repeated_calls() -> None:
    estimator = DeterministicTokenEstimator()
    messages = _conversation(3)
    assert estimator.estimate_messages(messages) == estimator.estimate_messages(messages)
    assert estimator.estimate_messages(messages) == estimator.estimate_messages(list(messages))


def test_estimate_is_zero_for_no_messages_and_framed_for_empty_content() -> None:
    estimator = DeterministicTokenEstimator()
    assert estimator.estimate_messages([]) == 0
    # An empty message still costs its framing, so a context of them is not free.
    assert estimator.estimate_messages([_user("")]) == MESSAGE_FRAMING_TOKENS


def test_estimate_scales_with_content_length() -> None:
    estimator = DeterministicTokenEstimator()
    short = estimator.estimate_messages([_user("a" * CHARS_PER_TOKEN)])
    long = estimator.estimate_messages([_user("a" * CHARS_PER_TOKEN * 4)])
    assert short == MESSAGE_FRAMING_TOKENS + 1
    assert long == MESSAGE_FRAMING_TOKENS + 4
    assert long > short


def test_estimate_adds_across_messages() -> None:
    estimator = DeterministicTokenEstimator()
    one, two = _user("a" * 20), _assistant("b" * 20)
    assert estimator.estimate_messages([one, two]) == (
        estimator.estimate_messages([one]) + estimator.estimate_messages([two])
    )


def test_non_ascii_content_is_costed_conservatively() -> None:
    """Non-Latin text is charged more per character, never less."""
    estimator = DeterministicTokenEstimator()
    ascii_cost = estimator.estimate_message(_user("a" * 40))
    non_ascii_cost = estimator.estimate_message(_user("漢" * 40))
    assert non_ascii_cost > ascii_cost
    # The same content always costs the same, whatever the platform.
    assert non_ascii_cost == estimator.estimate_message(_user("漢" * 40))


def test_model_id_does_not_change_the_ava_estimate() -> None:
    """The shipped estimator is model-agnostic by design, not accidentally."""
    estimator = DeterministicTokenEstimator()
    messages = _conversation(2)
    assert estimator.estimate_messages(messages, model_id="a") == estimator.estimate_messages(
        messages, model_id="b"
    )


def test_manager_accepts_a_replaced_estimator() -> None:
    """Tokenization is a port, so a different counter needs no manager change."""

    class FixedEstimator(TokenEstimator):
        def estimate_messages(
            self, messages, *, model_id: str | None = None
        ) -> int:
            del messages, model_id
            return 10_000

    manager = ContextWindowManager(estimator=FixedEstimator())
    with pytest.raises(ContextWindowExceededError):
        manager.fit(_conversation(2), model_context_limit=100)


# ============================================================
# END: Token Estimator
# ============================================================
# ============================================================
# BEGIN: Budget Policy
# ============================================================


def test_unknown_or_invalid_limits_mean_no_budget() -> None:
    assert usable_context_limit(None) is None
    assert usable_context_limit(0) is None
    assert usable_context_limit(-1) is None
    assert usable_context_limit(4096) == 4096


def test_input_budget_reserves_output_headroom() -> None:
    limit = 8192
    budget = input_budget_for(limit)
    assert budget == limit - DEFAULT_OUTPUT_RESERVE_TOKENS
    assert budget < limit, "the whole window must not be spent on input"


def test_reserve_is_capped_for_a_small_window() -> None:
    """A tiny model keeps a usable input budget instead of rejecting every run."""
    limit = 2048
    budget = input_budget_for(limit)
    assert budget == limit - int(limit * MAX_OUTPUT_RESERVE_FRACTION)
    assert budget > 0


def test_explicit_reserve_is_honored_and_validated() -> None:
    assert input_budget_for(10_000, output_reserve=1_000) == 9_000
    with pytest.raises(ValueError):
        input_budget_for(10_000, output_reserve=-1)


def test_no_reserve_can_starve_the_input_budget() -> None:
    """Even an explicit reserve leaves input room, so a run is never impossible."""
    assert input_budget_for(10_000, output_reserve=10_000) == int(10_000 * 0.75)
    assert input_budget_for(10_000, output_reserve=0) == 10_000


# ============================================================
# END: Budget Policy
# ============================================================
# ============================================================
# BEGIN: No Trimming Required
# ============================================================


def test_context_within_budget_is_returned_unchanged() -> None:
    messages = _conversation(2)
    result = _manager().fit(messages, model_context_limit=100_000)
    assert _contents(result.messages) == _contents(messages)
    assert result.dropped_message_count == 0
    assert result.dropped_turn_count == 0
    assert result.context_limit == 100_000
    assert result.input_budget == input_budget_for(100_000)


def test_first_turn_that_fits_is_returned_unchanged() -> None:
    messages = [_user("hello")]
    result = _manager().fit(messages, model_context_limit=100_000)
    assert _contents(result.messages) == ["hello"]


def test_unknown_model_limit_never_trims() -> None:
    """Compatibility: a model reporting no limit executes exactly as before."""
    messages = _conversation(20, size=500)
    for limit in (None, 0, -5):
        result = _manager().fit(messages, model_context_limit=limit)
        assert _contents(result.messages) == _contents(messages)
        assert result.context_limit is None
        assert result.input_budget is None
        assert result.dropped_message_count == 0


# ============================================================
# END: No Trimming Required
# ============================================================
# ============================================================
# BEGIN: Exact-Fit Boundary
# ============================================================


def _estimate_all(messages) -> int:
    return DeterministicTokenEstimator().estimate_messages(messages)


def test_exact_budget_fit_is_accepted() -> None:
    """An estimate equal to the budget is in range, with no trimming."""
    messages = _conversation(3)
    estimated = _estimate_all(messages)
    result = _manager().fit(
        messages, model_context_limit=estimated, output_reserve=0
    )
    assert result.input_budget == estimated
    assert result.dropped_message_count == 0
    assert result.dropped_turn_count == 0
    assert _contents(result.messages) == _contents(messages)


def test_one_token_over_budget_trims_the_oldest_turn() -> None:
    """One estimated token past the budget is over budget."""
    messages = _conversation(3)
    estimated = _estimate_all(messages)
    result = _manager().fit(
        messages, model_context_limit=estimated - 1, output_reserve=0
    )
    assert result.input_budget == estimated - 1
    assert result.dropped_turn_count == 1
    assert result.dropped_message_count == 2
    assert _contents(result.messages) == _contents(messages[2:])
    assert result.estimated_input_tokens <= result.input_budget


def test_one_token_under_budget_keeps_everything() -> None:
    messages = _conversation(3)
    estimated = _estimate_all(messages)
    result = _manager().fit(
        messages, model_context_limit=estimated + 1, output_reserve=0
    )
    assert result.dropped_message_count == 0
    assert _contents(result.messages) == _contents(messages)


# ============================================================
# END: Exact-Fit Boundary
# ============================================================
# ============================================================
# BEGIN: Trimming Policy
# ============================================================


def test_long_conversation_keeps_the_recent_suffix_in_order() -> None:
    """A conversation far past the budget keeps the newest turns, in order."""
    messages = _conversation(40, size=200)
    # A suffix that would begin mid-turn (an orphan answer) is not a legal
    # outcome, so the fixture budget is the two most recent whole turns.
    suffix = messages[-5:]
    assert suffix[0].role == MessageRole.USER
    result = _manager().fit(
        messages,
        model_context_limit=_estimate_all(suffix),
        output_reserve=0,
    )
    assert result.dropped_turn_count == 38
    assert result.dropped_message_count == len(messages) - len(suffix)
    assert _contents(result.messages) == _contents(suffix)
    assert result.estimated_input_tokens <= result.input_budget


def test_trimming_drops_whole_oldest_turns_and_never_partial_messages() -> None:
    """No message is ever cut: the kept set is a verbatim recent suffix."""
    messages = _conversation(20, size=200)
    result = _manager().fit(
        messages, model_context_limit=2_000, output_reserve=0
    )
    kept = result.messages
    assert kept, "the fixture must still retain the current turn"
    # The kept messages are the input's own messages, unmodified, in order.
    assert kept == messages[len(messages) - len(kept):]
    # Everything dropped is a whole leading turn: the sequence starts at a user
    # message and the first kept message is a user message too.
    assert kept[0].role == MessageRole.USER
    assert messages.index(kept[0]) % 2 == 0
    assert result.dropped_message_count == len(messages) - len(kept)


def test_current_source_message_is_never_dropped() -> None:
    messages = _conversation(10, size=200)
    result = _manager().fit(messages, model_context_limit=1_000, output_reserve=0)
    assert result.messages[-1].content == "current"
    assert result.messages[-1].role == MessageRole.USER


def test_source_message_appears_exactly_once_after_trimming() -> None:
    messages = _conversation(8, size=150)
    result = _manager().fit(messages, model_context_limit=800, output_reserve=0)
    assert _contents(result.messages).count("current") == 1


def test_answer_is_never_orphaned_from_its_question() -> None:
    """Turn coherence: no ``A3`` survives after its ``U3`` is dropped."""
    messages = _conversation(30, size=200)
    result = _manager().fit(messages, model_context_limit=1_500, output_reserve=0)
    assert result.dropped_turn_count > 0
    roles = [message.role for message in result.messages]
    for index, role in enumerate(roles):
        if role == MessageRole.ASSISTANT:
            assert index > 0 and roles[index - 1] == MessageRole.USER


def test_a_system_prompt_is_kept_and_billed() -> None:
    """System instructions are not conversational history and never trimmed."""
    instructions = _system("You are AVA.")
    messages = [instructions, *_conversation(6, size=200)]
    suffix = [instructions, *messages[-4:]]
    result = _manager().fit(
        messages,
        model_context_limit=_estimate_all(suffix),
        output_reserve=0,
    )
    assert result.dropped_turn_count > 0
    assert result.messages[0].content == "You are AVA."
    assert result.estimated_input_tokens <= result.input_budget


def test_trimming_is_deterministic_across_repeated_calls() -> None:
    messages = _conversation(9, size=90)
    manager = _manager()
    first = manager.fit(messages, model_context_limit=1_400, output_reserve=0)
    second = manager.fit(messages, model_context_limit=1_400, output_reserve=0)
    assert _contents(first.messages) == _contents(second.messages)
    assert first.estimated_input_tokens == second.estimated_input_tokens
    assert first.dropped_turn_count == second.dropped_turn_count


def test_result_does_not_mutate_the_input_sequence() -> None:
    messages = _conversation(6, size=120)
    before = _contents(messages)
    result = _manager().fit(messages, model_context_limit=1_200)
    result.messages.clear()
    assert _contents(messages) == before


# ============================================================
# END: Trimming Policy
# ============================================================
# ============================================================
# BEGIN: Regenerate and Lifecycle Layering
# ============================================================


def test_regenerate_context_keeps_only_the_structurally_visible_answer() -> None:
    """Windowing starts from Phase 5.21's already-collapsed sequence.

    The manager never re-expands a turn, so a context that already holds only
    the structurally visible answer still holds only that answer after
    trimming, and the superseded attempt is never reintroduced.
    """
    superseded = _assistant("A1 first attempt")
    visible = _assistant("A1 second attempt")
    # What Phase 5.21 hands over: the first attempt was already collapsed away.
    eligible = [_user("U1"), visible, _user("current")]
    result = _manager().fit(eligible, model_context_limit=1_500, output_reserve=0)
    assert "A1 second attempt" in _contents(result.messages)
    assert "A1 first attempt" not in _contents(result.messages)
    assert superseded.content not in _contents(result.messages)
    assert result.messages[-1].content == "current"


def test_ineligible_messages_are_never_reintroduced_by_trimming() -> None:
    """The manager does not decode status; it only receives eligible messages.

    A turn whose answer never completed has no eligible assistant message, so
    the manager sees a user message with no answer and treats it as an ordinary
    turn.
    """
    messages = [_user("U1"), _user("current")]
    result = _manager().fit(messages, model_context_limit=100_000)
    assert _contents(result.messages) == ["U1", "current"]


# ============================================================
# END: Regenerate and Lifecycle Layering
# ============================================================
# ============================================================
# BEGIN: Oversized Input
# ============================================================


def test_oversized_current_message_fails_with_a_typed_error() -> None:
    """A current turn too large for the window is never silently trimmed."""
    messages = [_user("q" * 4_000), _user("r" * 4_000)]
    with pytest.raises(ContextWindowExceededError) as raised:
        _manager().fit(messages, model_context_limit=1_024, model_id="small-model")

    error = raised.value
    assert error.model_id == "small-model"
    assert error.estimated_size > error.available_budget


def test_oversized_error_carries_no_message_content() -> None:
    secret = "confidential-question-text"
    with pytest.raises(ContextWindowExceededError) as raised:
        _manager().fit([_user(secret * 400)], model_context_limit=512)
    assert secret not in str(raised.value)
    assert raised.value.estimated_size > 0
    assert raised.value.available_budget > 0


def test_oversized_historical_turn_is_dropped_whole() -> None:
    """An old message too large to fit may be dropped, but never cut."""
    oversized = _user("z" * 8_000)
    messages = [oversized, _assistant("answer to the oversized question"), *_conversation(2)]
    result = _manager().fit(messages, model_context_limit=1_500, output_reserve=0)
    assert oversized not in result.messages
    assert "answer to the oversized question" not in _contents(result.messages)
    assert result.messages[-1].content == "current"


def test_oversized_first_turn_fails_rather_than_dropping_the_question() -> None:
    messages = [_user("q" * 4_000)]
    with pytest.raises(ContextWindowExceededError):
        _manager().fit(messages, model_context_limit=1_024)


def test_context_with_only_a_system_prompt_is_never_dropped() -> None:
    messages = [_system("instructions only")]
    result = _manager().fit(messages, model_context_limit=1_024)
    assert _contents(result.messages) == ["instructions only"]


# ============================================================
# END: Oversized Input
# ============================================================
