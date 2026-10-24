## Study Buddy vs Adaptive Quiz SSE Comparison

### Adaptive Quiz Flow (CORRECT MODEL):
```
1. POST /quizzes/start → Creates session, returns session_uid
2. GET /sse/quiz/start?topic_id=X → SSE connection, server sends first question
3. POST /sse/quiz/{session_uid}/answer → Submit answer via SSE stream
4. Get next question automatically via SSE
5. GET /sse/quiz/{session_uid}/summary → Get summary
```

### Current Study Buddy Flow (OVERCOMPLICATED):
```
1. POST /study-buddy/sessions → Create session
2. GET /study-buddy/sessions/{session_id} → Get session (redundant with #1)
3. POST /study-buddy/sessions/{session_id}/messages → Post message
4. GET /study-buddy/sessions/{session_id}/stream → SSE connection
5. POST /study-buddy/sessions/{session_id}/analytics → Post analytics

PROBLEMS:
- Too many REST endpoints before SSE
- Separation between session creation and message posting is confusing
- Should be unified: create session with first message OR connect to SSE to start
- Analytics endpoint seems like overkill
```

### SIMPLIFIED Study Buddy Flow (SHOULD BE):
```
1. POST /study-buddy/sessions → Create session
   Request: { "mode": "quiz", "context": {...} }
   Response: { "session_id": "...", "sse_url": "/sse/study-buddy/...", ... }

2. GET /sse/study-buddy/{session_id} → SSE connection
   - Takes pending message from request
   - Streams response
   - Receives all events (hint_meta, token, done)

3. POST /sse/study-buddy/{session_id}/message → Post next message
   - Queues message
   - Server responds via existing SSE connection

REMOVES:
- GET /study-buddy/sessions/{session_id} (redundant)
- POST /study-buddy/sessions/{session_id}/analytics (not needed for MVP)
- POST /study-buddy/sessions/{session_id}/messages (move to SSE endpoint)
- GET /study-buddy/sessions/{session_id}/stream (becomes main SSE)
```
