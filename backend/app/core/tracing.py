from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from langsmith import Client, tracing_context

from app.core.config import Settings

ChatMode = Literal["saved", "temporary"]


@dataclass(frozen=True, slots=True)
class TracePolicy:
    enabled: bool
    tags: list[str]
    metadata: dict[str, str]


def trace_policy(
    settings: Settings, *, chat_mode: ChatMode, conversation_id: UUID | None
) -> TracePolicy:
    has_key = bool(
        settings.langsmith_api_key is not None
        and settings.langsmith_api_key.get_secret_value().strip()
    )
    enabled = settings.langsmith_tracing and chat_mode == "saved" and has_key
    return TracePolicy(
        enabled=enabled,
        tags=["saved_chat"] if chat_mode == "saved" else ["temporary_chat"],
        metadata=(
            {"conversation_id": str(conversation_id)}
            if chat_mode == "saved" and conversation_id is not None
            else {}
        ),
    )


def temporary_chat_tracing_enabled(settings: Settings) -> Literal[False]:
    policy = trace_policy(settings, chat_mode="temporary", conversation_id=None)
    if policy.enabled:
        raise AssertionError("Temporary chat tracing must never be enabled")
    return False


def _mask_trace_payload(_value: dict[str, Any]) -> dict[str, bool]:
    return {"masked": True}


@contextmanager
def graph_tracing_context(
    settings: Settings, *, chat_mode: ChatMode, conversation_id: UUID | None
) -> Generator[TracePolicy]:
    policy = trace_policy(
        settings, chat_mode=chat_mode, conversation_id=conversation_id
    )
    client: Client | None = None
    if policy.enabled:
        assert settings.langsmith_api_key is not None
        client = Client(
            api_url=settings.langsmith_endpoint,
            api_key=settings.langsmith_api_key.get_secret_value(),
            hide_inputs=_mask_trace_payload,
            hide_outputs=_mask_trace_payload,
            hide_metadata=False,
        )
    with tracing_context(
        enabled=policy.enabled,
        project_name=settings.langsmith_project,
        tags=policy.tags,
        metadata=policy.metadata,
        client=client,
    ):
        yield policy
