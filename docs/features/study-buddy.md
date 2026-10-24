# Study Buddy chatbot

**In one line:** a tutor chat that gives hints instead of answers. It is behind `ENABLE_STUDY_BUDDY=1`. The UI uses it in one place: `HintChat` (`edu-tech-ui/src/components/quiz-hint-chat.tsx`), a "need a hint?" panel on the quiz page. It runs in `quiz` mode and sends `topic_id`, the quiz `session_uid` and the current `question_id` as context.

This page describes what exists. [learning/04-chatbot.md](../learning/04-chatbot.md) explains how it works line by line, and how to make it good.

## Modes

| Mode | Persona | Max hint level | Extra rule |
|---|---|---|---|
| `quiz` | quiz coach | 2 | must not reveal the answer: `enforce_quiz_no_answer` plus `LeakClassifier` regexes |
| `reading` | study tutor | 3 | |
| `review` | study tutor | 3 | |
| `planning` | planning mentor | 1 | |

Defined in `app/features/study_buddy/service.py` (`DEFAULT_POLICIES`) and `prompts.py` (personas).

## API

| Call | Purpose |
|---|---|
| `POST /study-buddy/sessions` `{mode, context}` | Create a session (`study_sessions` row). Returns `session_id` and `sse_url`. |
| `POST /study-buddy/sessions/{id}/messages` `{message, mode?, context?}` | Save the learner message and queue it **in memory**. Returns 202. |
| `GET /sse/study-buddy/{id}` | Run the tutor on the queued message and stream the reply |
| `GET /study-buddy/sessions/{id}/stream` | Same, using sse-starlette |

Stream events: `hint_meta {level, remaining, exhausted, sources}`, then `token {index, text}` several times, then `done {message_id, tokens, sources}`, then `heartbeat`. On failure, `error`.

`context` (`ContextSnapshot`) can carry `topic_id`, `question_id`, `learning_material_id` and quiz state, so the tutor knows what the learner is looking at.

## What happens on one message

1. Pick a hint level from the mode's policy (`policies.select_next_hint_level`).
2. `resolve_context`: load the session row and the last 5 messages. If `context.question_id` is set, it also loads that question's text and choices (not the answer) as `question_stem`.
3. `retrieve_documents`: **mock**. It returns made-up "snippets" that echo the query back.
4. Build the system prompt (persona, template and guardrails) and the user prompt (template, learner message, snippets, and the last messages as a Python list printed into the text).
5. Call the LLM **once and wait for the whole reply**. With no API key, it returns a canned mock reply.
6. In quiz mode, check for answer leaks.
7. Cut the reply into 60-character pieces and send each one as a `token` event.
8. Save the assistant message and an analytics row.

## Known weak spots

| # | Weak spot | Effect |
|---|---|---|
| 1 | Fake streaming (step 7) | The learner waits for the whole reply, then it all appears at once |
| 2 | Mock retrieval (step 3) | The prompt contains junk "snippets". The real question is loaded when `question_id` is passed, but there are no topic notes. |
| 3 | History is printed into text, last 5 only | Weak memory; the model cannot tell turns apart cleanly |
| 4 | Pending message lives in a process dict | A restart between the POST and the GET loses the message |
| 5 | The template appears in both the system and the user prompt | Wasted tokens, mixed signals |
| 6 | Only a quiz-mode UI | Reading, review and planning modes exist in the API but nothing in the UI uses them |

Tests: `tests/test_study_buddy_*.py`, `tests/test_policies.py`, `tests/test_leak_classifier.py` (all run against the mock LLM).
