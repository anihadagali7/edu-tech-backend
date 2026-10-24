# Adaptive quiz

**In one line:** each quiz serves one question at a time. It moves the difficulty up after 3 right answers in a row and down after 3 wrong ones.

## The rules

All rules live in `app/features/quizzes/service.py` (`QuizService.submit_answer`) and `app/features/quizzes/sse.py` (`QuizSessionManager.submit_answer`).

| Rule | Value |
|---|---|
| Difficulty scale | 1 (easy) to 5 (hard), starting at 3 (or `difficulty_hint`) |
| Level up | 3 correct in a row → +1 (max 5), streak resets |
| Level down | 3 wrong in a row → −1 (min 1), streak resets |
| Mastery | at difficulty 5, 10 correct in a row |
| End of quiz | mastery reached **or** 20 answers |
| No repeats | a question is never shown twice in one session (unique `attempts(session_id, question_id)`) |
| Fallback | if no unseen question is left at the target level, try ±1, then ±2. If there are none at all, send `needs_refill`. |

The session row is locked (`FOR UPDATE`) while an answer is scored. This stops a double-clicked answer from moving the streak twice.

## Endpoints the UI uses

| Call | Purpose |
|---|---|
| `GET /sse/quiz/start?topic_id=<uuid>` | Opens the stream, creates the session, sends the first question |
| `POST /sse/quiz/{session_uid}/answer` `{question_id, selected_answer, elapsed_ms}` | Scores one answer. The feedback and the next question arrive **on the stream**. |
| `POST /sse/quiz/{session_uid}/pause` / `/end` | Pause, or end early (writes `quiz_summaries`) |
| `GET /sse/quiz/{session_uid}/summary` | Final totals |
| `GET /quizzes/sessions?…` | History list with filters (dashboard) |
| `GET /quizzes/{session_uid}/details` | Every question, your answer and the explanation (review page) |

There is also an older plain REST quiz under `/quizzes/start` and `/quizzes/{id}/answer`. The UI does not use it.

## Stream events

| Event | Data |
|---|---|
| `session_started` | `{session_uid, topic_id, …}` |
| `question` | `{id, body, choices{A..D}, difficulty}` |
| `answer_feedback` | `{is_correct, correct_answer, selected_answer, explanation, session_stats}` |
| `quiz_completed` | totals + recommendations |
| `needs_refill` | the topic ran out of questions; an admin should generate more |
| `heartbeat` | every `SSE_HEARTBEAT_SECONDS` |
| `error` | `{message}` |

The UI side is `src/hooks/use-quiz-sse.ts`. It uses `fetch` with a `ReadableStream`, not `EventSource`, because the browser's `EventSource` cannot send an `Authorization` header.

## Limits

- **One process only.** The stream and the answer POST meet in an in-memory dict ([architecture.md §3.2](../architecture.md#32-take-an-adaptive-quiz-live-stream)).
- With 20 questions per generation job, and about 4 per level, a learner sitting at one level runs out quickly. Admins can add more with `POST /llm/admin/create-topic` on an existing slug, or with `POST /admin/questions/import`.
