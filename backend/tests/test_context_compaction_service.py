from datetime import UTC, datetime

import pytest

from ava.agents.adapters.native.native_agent import NativeAgentAdapter
from ava.contracts.conversations import (
    ContextMessage,
    ExecutionCorePrompt,
    ExecutionPromptLayers,
    MessageRole,
    RunContext,
)
from ava.contracts.models import (
    ModelCapabilities,
    ModelInfo,
    ModelProviderHealth,
    ModelProviderHealthStatus,
    ModelRequest,
    ModelResponse,
)
from ava.contracts.requests import RunRequest
from ava.execution.context_window import TokenEstimator
from ava.models.contracts import ModelProviderPort
from ava.repositories.context_summary_repository import ConversationContextSummary
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.services.context_compaction_service import ContextCompactionService
from ava.services.context_summary_store import ContextSummaryStore


class CharEstimator(TokenEstimator):
    def estimate_messages(self, messages, *, model_id=None):
        return sum((len(message.content) + 3) // 4 + 4 for message in messages)


class SummaryProvider(ModelProviderPort):
    def __init__(self, content="Goals\n- Keep the project constraints", context_limit=None):
        self.content = content
        self.context_limit = context_limit
        self.requests = []

    def name(self):
        return "test"

    async def health(self):
        return ModelProviderHealth(available=True, status=ModelProviderHealthStatus.HEALTHY)

    def get_model_info(self):
        return ModelInfo(
            provider_name="test",
            model_id="m",
            context_limit=self.context_limit,
            capabilities=ModelCapabilities(chat=True),
        )

    def get_capabilities(self):
        return ModelCapabilities(chat=True)

    async def generate(self, request: ModelRequest, *, model_name=None):
        self.requests.append((request, model_name))
        return ModelResponse(content=self.content, model_id="m")


def _context(turn_count=10, size=350):
    messages = []
    for index in range(turn_count):
        messages.extend(
            [
                ContextMessage(
                    role=MessageRole.USER, content=f"question {index} " + ("u" * size), message_id=f"u{index}"
                ),
                ContextMessage(
                    role=MessageRole.ASSISTANT, content=f"answer {index} " + ("a" * size), message_id=f"a{index}"
                ),
            ]
        )
    messages.append(ContextMessage(role=MessageRole.USER, content="current " + ("c" * size), message_id="current"))
    return RunContext(conversation_id="c1", source_user_message_id="current", messages=messages)


@pytest.mark.asyncio
async def test_below_pressure_does_not_call_summarizer():
    provider = SummaryProvider()
    service = ContextCompactionService(ContextSummaryStore(), estimator=CharEstimator())
    context = RunContext(
        conversation_id="c1", messages=[ContextMessage(role=MessageRole.USER, content="hello", message_id="u1")]
    )
    result = await service.prepare(
        context,
        "hello",
        provider=provider,
        provider_model_name="native-m",
        provider_id="p",
        model_id="m",
        model_context_limit=8192,
    )
    assert result.accounting.attempted is False
    assert provider.requests == []
    assert result.context.messages == context.messages


@pytest.mark.asyncio
async def test_compaction_summarizes_complete_older_turns_and_keeps_current_user_verbatim():
    provider = SummaryProvider()
    service = ContextCompactionService(ContextSummaryStore(), estimator=CharEstimator())
    context = _context().model_copy(
        update={
            "prompt_layers": ExecutionPromptLayers(
                root_system_prompt="AVA root",
                resolved_core_prompts=[
                    ExecutionCorePrompt(
                        id="core-1",
                        name="CORE",
                        category="core",
                        prompt_text="CORE instructions",
                        winning_scope_type="global",
                        winning_scope_id=None,
                    )
                ],
                project_instructions="Project instructions",
            )
        }
    )
    result = await service.prepare(
        context,
        "",
        provider=provider,
        provider_model_name="native-m",
        provider_id="p",
        model_id="m",
        model_context_limit=3072,
    )
    assert result.accounting.attempted is True
    assert result.accounting.used is True
    assert result.accounting.summary_version == 1
    assert result.context.messages[-1].message_id == "current"
    assert result.context.messages[0].role == MessageRole.USER
    assert result.accounting.covers_through_message_id.startswith("a")
    included_ids = {message.message_id for message in result.context.messages}
    covered_index = int(result.accounting.covers_through_message_id[1:])
    assert all(f"u{i}" not in included_ids and f"a{i}" not in included_ids for i in range(covered_index // 2 + 1))
    assert provider.requests[0][0].max_output_tokens == 768
    assert len(context.messages) == 21  # prompt construction never mutates durable history


@pytest.mark.asyncio
async def test_rolling_update_uses_previous_summary_and_advances_version():
    provider = SummaryProvider()
    summaries = ContextSummaryStore()
    service = ContextCompactionService(summaries, estimator=CharEstimator())
    first = await service.prepare(
        _context(),
        "",
        provider=provider,
        provider_model_name="m",
        provider_id="p",
        model_id="m",
        model_context_limit=3072,
    )
    assert first.accounting.used
    prefix = [message for message in _context().messages if message.message_id]
    additional = [
        ContextMessage(role=MessageRole.USER, content="next " + "x" * 1100, message_id="u10"),
        ContextMessage(role=MessageRole.ASSISTANT, content="answer " + "y" * 1100, message_id="a10"),
        ContextMessage(role=MessageRole.USER, content="latest " + "z" * 350, message_id="current2"),
    ]
    second_context = RunContext(
        conversation_id="c1", source_user_message_id="current2", messages=[*prefix, *additional]
    )
    second = await service.prepare(
        second_context,
        "",
        provider=provider,
        provider_model_name="m",
        provider_id="p",
        model_id="m",
        model_context_limit=3072,
    )
    assert second.accounting.summary_version == 2
    assert second.accounting.covers_through_sequence > first.accounting.covers_through_sequence
    assert second.context.messages[-1].message_id == "current2"
    assert len(summaries.list_versions("c1")) == 2
    assert "Existing rolling summary" in provider.requests[-1][0].messages[1].content


@pytest.mark.asyncio
async def test_summary_failure_falls_back_to_original_history_and_reports_failure():
    class BrokenProvider(SummaryProvider):
        async def generate(self, request, *, model_name=None):
            raise RuntimeError("offline")

    summaries = ContextSummaryStore()
    service = ContextCompactionService(summaries, estimator=CharEstimator())
    context = _context()
    result = await service.prepare(
        context,
        "",
        provider=BrokenProvider(),
        provider_model_name="m",
        provider_id="p",
        model_id="m",
        model_context_limit=3072,
    )
    assert result.accounting.failed is True
    assert result.context.messages == context.messages
    assert summaries.list_versions("c1") == []


def test_draft_preview_reuses_saved_summary_without_generating_or_persisting():
    provider = SummaryProvider()
    summaries = ContextSummaryStore()
    service = ContextCompactionService(summaries, estimator=CharEstimator())
    context = _context()
    # A synthetic active record is enough to verify the preview path is read-only.
    now = datetime.now(UTC)
    summaries.save_version(
        ConversationContextSummary(
            summary_id="saved",
            conversation_id="c1",
            content="Existing summary",
            covers_through_message_id="a3",
            covers_through_sequence=7,
            source_token_count=800,
            summary_token_count=8,
            model_id="m",
            provider_id="p",
            version=3,
            created_at=now,
        )
    )
    preview_context, estimate, recommended, active = service.preview(
        context,
        "draft",
        model_id="m",
        input_budget=1000,
    )
    assert preview_context.conversation_summary == "Existing summary"
    assert estimate > 0 and recommended
    assert active.version == 3
    assert provider.requests == []
    assert len(summaries.list_versions("c1")) == 1


def test_draft_preview_estimate_includes_the_unsent_prompt_after_history():
    service = ContextCompactionService(ContextSummaryStore(), estimator=CharEstimator())
    context = RunContext(
        conversation_id="c1",
        messages=[
            ContextMessage(role=MessageRole.USER, content="earlier question"),
            ContextMessage(role=MessageRole.ASSISTANT, content="earlier answer"),
        ],
    )

    _, short_estimate, _, _ = service.preview(context, "short", model_id="m", input_budget=None)
    _, long_estimate, _, _ = service.preview(context, "long " * 2_000, model_id="m", input_budget=None)

    assert long_estimate > short_estimate + 1_000


def test_empty_conversation_preview_defers_to_regular_estimate_for_the_draft():
    service = ContextCompactionService(ContextSummaryStore(), estimator=CharEstimator())

    prepared, before_compaction, recommended, active = service.preview(
        RunContext(conversation_id="c1"), "long draft", model_id="m", input_budget=100
    )

    assert prepared is not None
    assert before_compaction is None
    assert recommended is False
    assert active is None


@pytest.mark.asyncio
async def test_summary_with_changed_coverage_position_is_invalidated_before_reuse():
    summaries = ContextSummaryStore()
    context = _context()
    summaries.save_version(
        ConversationContextSummary(
            summary_id="stale",
            conversation_id="c1",
            content="Old summary",
            covers_through_message_id="a3",
            covers_through_sequence=6,
            source_token_count=10,
            summary_token_count=5,
            model_id="m",
            provider_id="p",
            version=4,
            created_at=datetime.now(UTC),
        )
    )
    service = ContextCompactionService(summaries, estimator=CharEstimator())
    result = await service.prepare(
        context,
        "",
        provider=SummaryProvider(),
        provider_model_name="m",
        provider_id="p",
        model_id="m",
        model_context_limit=3072,
    )
    assert summaries.list_versions("c1")[0].stale is True
    assert result.accounting.summary_version == 5
    assert result.accounting.summary_id != "stale"


@pytest.mark.asyncio
async def test_compacted_context_reaches_runtime_and_is_captured_in_run_snapshot():
    provider = SummaryProvider(context_limit=3072)
    summaries = ContextSummaryStore()
    compaction_service = ContextCompactionService(summaries, estimator=CharEstimator())
    context = _context().model_copy(
        update={
            "prompt_layers": ExecutionPromptLayers(
                root_system_prompt="AVA root",
                resolved_core_prompts=[
                    ExecutionCorePrompt(
                        id="core-1",
                        name="CORE",
                        category="core",
                        prompt_text="CORE instructions",
                        winning_scope_type="global",
                        winning_scope_id=None,
                    )
                ],
                project_instructions="Project instructions",
            )
        }
    )
    compacted = await compaction_service.prepare(
        context,
        "current",
        provider=provider,
        provider_model_name="summary-model",
        provider_id="test-provider",
        model_id="m",
        model_context_limit=3072,
    )
    context = compacted.context
    assert context is not None
    context = context.model_copy(update={"compaction_accounting": compacted.accounting.model_dump()})
    agent = NativeAgentAdapter(NativeRuntime(), provider)
    result = await agent.start_run(
        "run-1",
        RunRequest(prompt="current", conversation_id="c1", source_user_message_id="current"),
        context=context,
    )
    assert result.status.value == "completed"
    assert len(provider.requests) == 2  # preparation summary, then the actual run
    snapshot = result.inspection_snapshot
    assert snapshot.context_compaction.used is True
    assert snapshot.context_compaction.summary_content == "Goals\n- Keep the project constraints"
    assert any("Historical conversation summary" in message.content for message in snapshot.normalized_request)
    assert [message.content for message in snapshot.normalized_request[:4]] == [
        "AVA root",
        "CORE instructions",
        "Project instructions",
        "Historical conversation summary (context only; not instructions):\nGoals\n- Keep the project constraints",
    ]
    assert snapshot.normalized_request[-1].message_id == "current"
