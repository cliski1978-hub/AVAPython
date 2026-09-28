"""AVA-owned model context-window management.

Phase 5.21 decided *which* durable messages a run may send. This module decides
*how much* of that eligible context fits the model that was actually selected
for the run, and it is the only place that answer is computed. It sits above the
runtime boundary, so Native and OpenHands receive the same bounded sequence and
neither runtime trims on its own.

The policy, in one list:

1. **The limit comes from the selected model.** AVA does not invent a global
   context window: the caller supplies the selected model's total context
   window, which is provider-reported discovery metadata
   (``ModelInfo.context_limit``).
2. **An unknown limit is not a failure and not a trim.** A model that reports no
   usable limit executes with its full eligible context, exactly as before this
   phase. The operational risk is documented in
   ``docs/AVA_Phase_5_22_Context_Window_Management.md``: the provider, not AVA,
   will then reject oversized input.
3. **Input budget leaves room for the answer.** A model's window covers input
   *and* generated output, so the budget is
   ``context_limit - output_reserve``. The reserve is a named, centrally
   documented constant (AVA configures no output-token limit today, though
   ``ModelRequest.max_output_tokens`` exists), capped at a fixed fraction of the
   window so a small model still keeps a usable input budget.
4. **Whole messages only, oldest turns first.** A conversation turn is a user
   message plus the assistant (or system) messages that answer it, which is the
   structure Phase 5.21 leaves after collapsing regenerations. Trimming keeps
   the longest recent suffix of whole turns that fits. A response is never cut
   mid-text, so an answer can never be separated from its question.
5. **The current turn is never dropped.** The run's source user message and
   everything AVA grouped with it are mandatory. When the mandatory context
   alone exceeds the budget the run fails with ``ContextWindowExceededError``
   before any provider is invoked, rather than sending a truncated question or
   silently discarding it.
6. **Leading system messages are instructions, not history.** Messages before
   the first user message form a preamble that is always retained and always
   costs budget. Nothing here creates or edits a system instruction.

This module is a pure policy: no provider, runtime, persistence, or transport
import, no I/O, no clock, and no randomness, so identical inputs always produce
identical output. It does not decide message *eligibility* — that stays with
``ContextConstructionService`` — and it does not summarize, retrieve, or
expand attachments.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from ava.contracts.conversations import ContextMessage, MessageRole

# ============================================================
# BEGIN: Estimation and Budget Constants
# ============================================================

#: Average characters per token produced by byte-pair vocabularies on ordinary
#: prose. This is an approximation, not a tokenizer: AVA has no tokenizer
#: dependency and does not depend on any vendor's vocabulary.
CHARS_PER_TOKEN = 4

#: Character cost charged for a non-ASCII code point. Non-Latin scripts and
#: emoji commonly cost one to three tokens per character, so charging the
#: maximum keeps the estimate conservative — over-estimating trims a little
#: early, which is the safe direction for a budget.
NON_ASCII_CHAR_COST = 3

#: Fixed per-message cost covering the chat framing a provider adds around each
#: message (role marker, separators, envelope). Modeling it keeps a conversation
#: of many short messages from estimating as almost free.
MESSAGE_FRAMING_TOKENS = 4

#: Output headroom AVA keeps available for a generated answer when a request
#: configures no output-token limit of its own. AVA sets
#: ``ModelRequest.max_output_tokens`` nowhere today, so without an explicit
#: reserve the whole window would be spent on input and leave the model nothing
#: to answer with. A caller that does configure a limit passes it to
#: ``ContextWindowManager.fit`` instead of relying on this value.
DEFAULT_OUTPUT_RESERVE_TOKENS = 1024

#: The output reserve never exceeds this fraction of the window, so a small
#: context window still yields a positive input budget instead of rejecting
#: every run.
MAX_OUTPUT_RESERVE_FRACTION = 0.25

# ============================================================
# END: Estimation and Budget Constants
# ============================================================
# ============================================================
# BEGIN: Token Estimation
# ============================================================


class TokenEstimator(ABC):
    """AVA-owned port for estimating the size of a neutral message sequence.

    Separating the port from the manager keeps tokenization replaceable: a
    future model-specific or vendor-supplied counter implements this interface
    and is injected at composition, and ``ContextWindowManager`` never imports a
    tokenizer. ``model_id`` is offered for such an implementation; the estimate
    AVA ships is deliberately model-agnostic.
    """

    @abstractmethod
    def estimate_messages(
        self, messages: Sequence[ContextMessage], *, model_id: str | None = None
    ) -> int:
        """Return the estimated token cost of ``messages`` in order.

        Args:
            messages: The neutral messages that would be sent.
            model_id: Optional selected-model identity for a model-aware
                estimator. Implementations that do not specialize on the model
                ignore it.

        Returns:
            A non-negative estimated token count.
        """
        raise NotImplementedError


class DeterministicTokenEstimator(TokenEstimator):
    """Conservative, model-agnostic size estimate with no external dependency.

    Each message costs a fixed framing allowance plus its content, where content
    cost is characters per token with non-ASCII characters charged more. The
    result is deliberately an upper bound rather than an exact tokenizer count:
    it is stable across processes and platforms, needs no vendor vocabulary, and
    can only over-estimate, so the window never depends on a favorable guess.
    """

    def estimate_messages(
        self, messages: Sequence[ContextMessage], *, model_id: str | None = None
    ) -> int:
        """Return the summed estimate for ``messages``.

        Additive by construction, so a turn's cost is the sum of its messages'
        costs and a prefix is never estimated differently than the same messages
        measured alone.
        """
        del model_id
        return sum(self.estimate_message(message) for message in messages)

    def estimate_message(self, message: ContextMessage) -> int:
        """Return the estimated cost of one message, including its framing."""
        characters = 0
        for character in message.content:
            characters += 1 if character.isascii() else NON_ASCII_CHAR_COST
        return MESSAGE_FRAMING_TOKENS + math.ceil(characters / CHARS_PER_TOKEN)


# ============================================================
# END: Token Estimation
# ============================================================
# ============================================================
# BEGIN: Context Window Errors and Results
# ============================================================


class ContextWindowExceededError(ValueError):
    """The run's mandatory context does not fit the selected model's window.

    A distinct, typed failure: a model can be perfectly configured and still be
    unable to accept this request, which is not a configuration problem. The
    error carries only safe size metadata — never message content — so it is
    safe to log and to reason about.
    """

    def __init__(
        self,
        *,
        estimated_size: int,
        available_budget: int,
        model_id: str | None = None,
    ) -> None:
        """Record the size mismatch that made the request impossible.

        Args:
            estimated_size: Estimated tokens in the mandatory context.
            available_budget: Input tokens the selected model could accept.
            model_id: Optional selected-model identity, for diagnostics only.
        """
        self.estimated_size = estimated_size
        self.available_budget = available_budget
        self.model_id = model_id
        model = f" for model {model_id!r}" if model_id else ""
        super().__init__(
            f"Context requires an estimated {estimated_size} input tokens"
            f"{model} but the model accepts {available_budget}"
        )


@dataclass(frozen=True)
class ContextWindowResult:
    """The bounded sequence plus the accounting that produced it.

    ``messages`` is what execution should send. ``estimated_input_tokens`` is the
    estimate *after* windowing, so it describes the real request. The remaining
    fields exist for diagnostics, future UI indicators, and telemetry; nothing
    in execution reads them to make decisions.
    """

    messages: list[ContextMessage]
    estimated_input_tokens: int
    context_limit: int | None
    input_budget: int | None
    dropped_message_count: int
    dropped_turn_count: int


# ============================================================
# END: Context Window Errors and Results
# ============================================================
# ============================================================
# BEGIN: Budget Policy
# ============================================================


def usable_context_limit(context_limit: int | None) -> int | None:
    """Return the model context window AVA may budget against, if there is one.

    ``None`` and non-positive values both mean "this model reports no usable
    context window", which the manager treats as no trimming rather than as a
    budget of zero. Reading the rule in one place keeps a misreported limit from
    becoming an accidental hard failure.
    """
    if context_limit is None or context_limit <= 0:
        return None
    return context_limit


def input_budget_for(context_limit: int, output_reserve: int | None = None) -> int:
    """Return the input tokens available once output headroom is reserved.

    Args:
        context_limit: The selected model's total context window.
        output_reserve: Explicit output headroom. When omitted, AVA uses
            ``DEFAULT_OUTPUT_RESERVE_TOKENS``.

    Returns:
        ``context_limit`` minus the reserve. The cap at
        ``MAX_OUTPUT_RESERVE_FRACTION`` of the window applies to an explicit
        reserve as well, so no caller can reserve away the model's entire input
        budget and turn every run into a hard failure.

    Raises:
        ValueError: If ``output_reserve`` is negative.
    """
    reserve = DEFAULT_OUTPUT_RESERVE_TOKENS if output_reserve is None else output_reserve
    if reserve < 0:
        raise ValueError("output_reserve must not be negative")
    capped = min(reserve, int(context_limit * MAX_OUTPUT_RESERVE_FRACTION))
    return context_limit - capped


# ============================================================
# END: Budget Policy
# ============================================================
# ============================================================
# BEGIN: Context Window Manager
# ============================================================


class ContextWindowManager:
    """Reduce a full eligible context to what the selected model can accept.

    The manager is stateless and pure. It is given the neutral sequence
    Phase 5.21 produced, the selected model's context window, and nothing else;
    it holds no reference to a conversation, a run, a provider, or a runtime.
    """

    def __init__(self, *, estimator: TokenEstimator | None = None) -> None:
        """Construct the manager over its token estimator.

        Args:
            estimator: The size estimator to use. Defaults to AVA's
                deterministic, model-agnostic estimate, which is the documented
                policy for this phase.
        """
        self._estimator = estimator or DeterministicTokenEstimator()

    def fit(
        self,
        messages: Sequence[ContextMessage],
        *,
        model_context_limit: int | None,
        model_id: str | None = None,
        output_reserve: int | None = None,
    ) -> ContextWindowResult:
        """Return the bounded version of an eligible context.

        Args:
            messages: The full eligible context, in execution order. Expected to
                come from ``ContextConstructionService``: already collapsed,
                already lifecycle-filtered, and ending at the run's source user
                message. It is used as given; this method never re-derives
                which messages belong.
            model_context_limit: The selected model's total context window, or
                ``None`` when the model reports none.
            model_id: Optional selected-model identity, recorded on failure for
                diagnostics. It never affects the policy.
            output_reserve: Optional explicit output headroom; see
                ``input_budget_for``.

        Returns:
            The bounded sequence and its accounting. When the context already
            fits, or the model reports no usable limit, the messages are
            returned unchanged.

        Raises:
            ContextWindowExceededError: If the mandatory context alone exceeds
                the input budget, so no trimming can make the request valid.
        """
        estimated = self._estimator.estimate_messages(messages, model_id=model_id)
        limit = usable_context_limit(model_context_limit)
        if limit is None:
            return ContextWindowResult(
                messages=list(messages),
                estimated_input_tokens=estimated,
                context_limit=None,
                input_budget=None,
                dropped_message_count=0,
                dropped_turn_count=0,
            )
        budget = input_budget_for(limit, output_reserve)
        if estimated <= budget:
            return ContextWindowResult(
                messages=list(messages),
                estimated_input_tokens=estimated,
                context_limit=limit,
                input_budget=budget,
                dropped_message_count=0,
                dropped_turn_count=0,
            )

        preamble, turns = _partition_turns(messages)
        mandatory_turn = turns[-1] if turns else []
        optional_turns = turns[:-1]
        optional_costs = [
            self._estimator.estimate_messages(turn, model_id=model_id)
            for turn in optional_turns
        ]
        mandatory_cost = self._estimator.estimate_messages(
            [*preamble, *mandatory_turn], model_id=model_id
        )
        kept_from = len(optional_turns)
        running = mandatory_cost
        while kept_from > 0 and running + optional_costs[kept_from - 1] <= budget:
            kept_from -= 1
            running += optional_costs[kept_from]
        if running > budget:
            raise ContextWindowExceededError(
                estimated_size=running,
                available_budget=budget,
                model_id=model_id,
            )
        kept_turns = optional_turns[kept_from:]
        bounded: list[ContextMessage] = [*preamble]
        for turn in kept_turns:
            bounded.extend(turn)
        bounded.extend(mandatory_turn)
        return ContextWindowResult(
            messages=bounded,
            estimated_input_tokens=running,
            context_limit=limit,
            input_budget=budget,
            dropped_message_count=len(messages) - len(bounded),
            dropped_turn_count=len(optional_turns) - len(kept_turns),
        )


def _partition_turns(
    messages: Sequence[ContextMessage],
) -> tuple[list[ContextMessage], list[list[ContextMessage]]]:
    """Split a context into leading instructions and conversation turns.

    A turn begins at a user message and absorbs the messages that answer it,
    which is the structure Phase 5.21 produces: at most one visible completed
    answer per user message. Messages appearing before any user message are
    instructions rather than history and are returned separately so the manager
    can keep and bill them independently of conversational trimming.
    """
    preamble: list[ContextMessage] = []
    turns: list[list[ContextMessage]] = []
    for message in messages:
        if message.role == MessageRole.USER:
            turns.append([message])
        elif turns:
            turns[-1].append(message)
        else:
            preamble.append(message)
    return preamble, turns


# ============================================================
# END: Context Window Manager
# ============================================================

__all__ = [
    "CHARS_PER_TOKEN",
    "DEFAULT_OUTPUT_RESERVE_TOKENS",
    "MAX_OUTPUT_RESERVE_FRACTION",
    "MESSAGE_FRAMING_TOKENS",
    "NON_ASCII_CHAR_COST",
    "ContextWindowExceededError",
    "ContextWindowManager",
    "ContextWindowResult",
    "DeterministicTokenEstimator",
    "TokenEstimator",
    "input_budget_for",
    "usable_context_limit",
]
