# SKELETON: This file contains placeholders and TODOs; no business logic yet.
"""Pydantic models and enums representing Study Buddy API contracts."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StudyMode(str, Enum):
    """Enumerated tutor modes that control hinting rules, prompt flavor, and policy enforcement.

    TODO:
    1. Align enum members with product terminology defined in Attachment B to avoid drift.
    2. Add utility methods for mapping to analytics dimensions or feature flags.
    3. Ensure downstream clients reuse this enum to keep payload values canonical.

    Acceptance:
    - Enum values serialize to lowercase strings for API compatibility.
    - Adding new modes requires minimal changes to service and policy layers.
    - Documentation clearly ties each mode to tutor behavior expectations.
    """

    READING = "reading"
    QUIZ = "quiz"
    REVIEW = "review"
    PLANNING = "planning"


class ContextSnapshot(BaseModel):
    """Snapshot of relevant context identifiers so the tutor can retrieve the right content without repeated client input.

    TODO:
    1. Expand with additional identifiers (course_id, cohort_id) if Attachment B requires them.
    2. Support validation that mutually exclusive fields (e.g., quiz_id vs. question_id) follow domain rules.
    3. Provide helper methods to detect whether the snapshot is quiz- or study-oriented.

    Acceptance:
    - Serializes cleanly in JSON payloads and persists alongside session records.
    - Optional fields remain optional while still validating UUID or slug formats when provided.
    - Works seamlessly with ORM mode once repositories hydrate instances.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    topic_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Primary topic identifier tied to the session focus",
    )
    learning_material_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Reference to a learning material artifact",
    )
    quiz_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Identifier for the active quiz, if in quiz mode",
    )
    session_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Reference to an upstream quiz session when cross-linked",
    )
    question_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Current quiz question identifier, if applicable",
    )
    quiz_attempt_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Identifier for the active quiz attempt when available",
    )


class StartStudySessionRequest(BaseModel):
    """Payload for creating a new study session, including desired mode and optional context snapshot overrides.

    TODO:
    1. Validate that the provided context snapshot aligns with the requested mode (e.g., quiz mode requires question_id).
    2. Enforce feature flag checks for modes that may still be in beta (planning).
    3. Derive default mode from learner state if omitted once backend tracking is in place.

    Acceptance:
    - Required fields validate consistently and provide clear error messages for clients.
    - Optional context snapshot merges with server-side defaults during session creation.
    - Compatible with schema versioning should additional fields be added later.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    mode: StudyMode = Field(description="Selected tutor mode guiding hint policies and prompt templates")
    goal: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Optional learner goal or intent for the session",
    )
    context: Optional[ContextSnapshot] = Field(
        default=None,
        description="Optional context identifiers supplied by the client",
    )


class StudyMessageRequest(BaseModel):
    """User message payload submitted for tutor response, capturing mode overrides and per-message context adjustments.

    TODO:
    1. Accept attachments (images, worksteps) if later required by Attachment B enhancements.
    2. Support client-provided event correlation IDs to link streaming responses with UI interactions.
    3. Validate payload size and sanitize markdown prior to prompt ingestion.

    Acceptance:
    - Required message text is non-empty and within configured size limits.
    - Mode overrides fall back to session defaults when omitted.
    - Supports partial context overrides without breaking session continuity.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    message: str = Field(
        min_length=1,
        max_length=2000,
        description="Learner-authored content for the tutor to process",
    )
    mode: Optional[StudyMode] = Field(
        default=None,
        description="Optional per-message mode override",
    )
    context: Optional[ContextSnapshot] = Field(
        default=None,
        description="Optional context adjustments for this message",
    )
    client_message_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="Optional client generated identifier for deduplication",
    )

    @field_validator("client_message_id")
    @classmethod
    def _validate_client_message_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if not value.strip():
            raise ValueError("client_message_id cannot be blank")
        return value


class HintMeta(BaseModel):
    """Metadata describing tutor hint status, including current level, remaining budget, and escalation cues for the UI.

    TODO:
    1. Extend with frustration metrics or adaptive difficulty signals for front-end usage.
    2. Include timestamps or sequencing to help the client detect stale hint updates.
    3. Provide helper methods for converting to SSE events without extra mapping code.

    Acceptance:
    - Fields map directly to SSE metadata consumed by the frontend.
    - Default values align with policy defaults when hints have not yet been delivered.
    - Remains backward compatible as new hint fields are appended in future releases.
    """

    model_config = ConfigDict(from_attributes=True)

    level: int = Field(
        default=0,
        ge=0,
        description="Current hint escalation level for the session",
    )
    remaining: int = Field(
        default=0,
        ge=0,
        description="Number of hints remaining before escalation caps",
    )
    exhausted: bool = Field(
        default=False,
        description="Whether the learner has exhausted available hints",
    )


class TutorTokenChunk(BaseModel):
    """SSE token payload representing a slice of the tutor's streamed response.

    TODO:
    1. Track token index and latency to facilitate streaming analytics.
    2. Support optional classification labels (e.g., reasoning vs. final answer) if using structured decoding.
    3. Encode as newline-delimited JSON without extra escaping to simplify SSE formatting.

    Acceptance:
    - Stores textual token content and associated metadata necessary for rendering.
    - Works seamlessly with AsyncGenerator pipelines.
    - Maintains ordering guarantees via the index field.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    index: int = Field(
        ge=0,
        description="Monotonic index for streamed tokens",
    )
    text: str = Field(
        min_length=1,
        description="Tokenized text chunk emitted by the tutor",
    )
    latency_ms: Optional[float] = Field(
        default=None,
        ge=0,
        description="Elapsed latency between request and token emission",
    )


class TutorDone(BaseModel):
    """Completion payload emitted when the tutor finishes responding, referencing stored artifacts and analytics metadata.

    TODO:
    1. Include identifiers for persisted tutor messages or summaries for retrieval by other services.
    2. Surface aggregate token counts or costs for analytics dashboards.
    3. Indicate whether follow-up jobs (summaries, knowledge graph updates) were enqueued.

    Acceptance:
    - Signals stream termination clearly to clients.
    - Provides enough metadata for clients to fetch persisted messages if needed.
    - Compatible with worker summary jobs that may append additional fields later.
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    message_id: str = Field(
        min_length=1,
        max_length=128,
        description="Identifier of the stored tutor message",
    )
    tokens: int = Field(
        ge=0,
        description="Total tokens emitted for this reply",
    )
    follow_up_job_id: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Reference to a queued summary or analytics job",
    )


class StudyMessageResponse(BaseModel):
    """Standard response payload returned by Study Buddy endpoints, mixing latest tutor output, hint metadata, and SSE URLs.

    TODO:
    1. Embed SSE URL templates consistent with the router responses for message streaming.
    2. Include recent conversation snippets or message IDs to reduce additional API calls.
    3. Provide structured error fields for policy violations or worker timeouts so clients can react gracefully.

    Acceptance:
    - Works as both synchronous response (session fetch) and asynchronous handshake (message post).
    - Serializes cleanly in OpenAPI docs for client SDK generation.
    - Remains extendable without breaking existing clients (prefer optional fields for new data).
    """

    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    session_id: str = Field(
        min_length=1,
        max_length=128,
        description="Identifier for the active study session",
    )
    mode: StudyMode = Field(description="Effective mode governing tutor behavior")
    hint: HintMeta = Field(description="Metadata about hint usage after the latest operation")
    context: Optional[ContextSnapshot] = Field(
        default=None,
        description="Latest resolved context snapshot for the session",
    )
    latest_tutor_message: Optional[str] = Field(
        default=None,
        max_length=5000,
        description="Most recent tutor response text if available",
    )
    sse_url: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="URL for clients to subscribe to the streaming tutor response",
    )
