# Study Buddy API - Simplified Endpoints

## Overview
Study Buddy uses a **simplified flow** similar to Adaptive Quiz SSE. The key is to create a session first, then connect to SSE to stream responses.

---

## Endpoints (3 main endpoints)

### 1. **Create Study Session**
```http
POST /study-buddy/sessions
```

**Purpose**: Initialize a new study/tutoring session

**Headers**:
```
Authorization: Bearer YOUR_CLERK_JWT
Content-Type: application/json
```

**Request Body**:
```json
{
  "mode": "quiz",  // "quiz" | "reading" | "review" | "planning"
  "goal": "Master fractions",  // Optional
  "context": {  // Optional
    "topic_id": "fractions",
    "learning_material_id": "...",
    "quiz_id": "...",
    "question_id": "..."
  }
}
```

**Response (201 Created)**:
```json
{
  "session_id": "b522a333-aef8-4306-b9c5-7402f6cb6e2a",
  "mode": "quiz",
  "hint": {
    "level": 0,
    "remaining": 3,
    "exhausted": false
  },
  "context": {
    "topic_id": "fractions"
  },
  "latest_tutor_message": null,
  "sse_url": "/sse/study-buddy/b522a333-aef8-4306-b9c5-7402f6cb6e2a"
}
```

---

### 2. **Connect to SSE Stream**
```http
GET /study-buddy/sessions/{session_id}/stream
```

**Purpose**: Real-time streaming of AI tutor responses

**Headers**:
```
Authorization: Bearer YOUR_CLERK_JWT
```

**Response**: Server-Sent Events (text/event-stream)

**Example Events**:
```
id: 1
event: hint_meta
data: {"level":1,"remaining":2,"exhausted":false,"sources":["Math Guide"]}

id: 2
event: token
data: {"index":0,"text":"Let's think about the denominators...","latency_ms":5.0}

id: 3
event: token
data: {"index":1,"text":"What do they need to have in common?","latency_ms":5.0}

id: 4
event: done
data: {"message_id":"...","tokens":2,"sources":["Math Guide"],"backend":"mock"}
```

---

### 3. **Post Message to Chat**
```http
POST /study-buddy/sessions/{session_id}/messages
```

**Purpose**: Send a question/message to the tutor (queues for SSE response)

**Headers**:
```
Authorization: Bearer YOUR_CLERK_JWT
Content-Type: application/json
```

**Request Body**:
```json
{
  "message": "I'm confused about adding fractions with different denominators",
  "mode": "quiz",  // Optional: override session mode
  "context": {  // Optional: update context
    "question_id": "..."
  }
}
```

**Response (202 Accepted)**:
```json
{
  "session_id": "b522a333-aef8-4306-b9c5-7402f6cb6e2a",
  "mode": "quiz",
  "hint": {
    "level": 1,
    "remaining": 2,
    "exhausted": false
  },
  "latest_tutor_message": "Great question! Let's think about...",
  "sse_url": "/sse/study-buddy/b522a333-aef8-4306-b9c5-7402f6cb6e2a"
}
```

**What It Does**:
1. Queues the message for processing
2. Returns immediately (202 Accepted)
3. Response will be streamed via SSE (if still connected)

---

## Complete User Flow

### Frontend Implementation (JavaScript Example)

```javascript
// Step 1: Create session
const sessionRes = await fetch('/study-buddy/sessions', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    mode: 'quiz',
    context: { topic_id: 'fractions' }
  })
});

const session = await sessionRes.json();
const sessionId = session.session_id;

// Step 2: Connect to SSE stream
const eventSource = new EventSource(
  `/study-buddy/sessions/${sessionId}/stream`,
  {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  }
);

let currentMessage = '';

eventSource.addEventListener('hint_meta', (e) => {
  const data = JSON.parse(e.data);
  console.log(`Hint level: ${data.level}, Remaining: ${data.remaining}`);
  updateHintUI(data);
});

eventSource.addEventListener('token', (e) => {
  const data = JSON.parse(e.data);
  currentMessage += ' ' + data.text;
  displayMessageInUI(currentMessage);  // Real-time display
});

eventSource.addEventListener('done', (e) => {
  const data = JSON.parse(e.data);
  console.log('Message complete!');
  saveMessageToHistory(currentMessage);
  currentMessage = '';
});

eventSource.addEventListener('error', (e) => {
  console.error('SSE error:', e);
  eventSource.close();
});

// Step 3: Post user messages
async function sendMessage(message) {
  await fetch(`/study-buddy/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ message })
  });
  
  // Response will stream via SSE
}

// Step 4: User asks question
sendMessage('How do I add 1/2 + 1/4?');
// → SSE events stream in real-time
// → User sees response appear token by token
```

---

## Removed Endpoints (No Longer Needed)

❌ **GET /study-buddy/sessions/{session_id}** 
- Why removed: Redundant - session state is returned from POST /sessions and POST /messages
- Alternative: Check `latest_tutor_message` in responses

❌ **POST /study-buddy/sessions/{session_id}/analytics**
- Why removed: Not needed for MVP
- Future: Can add back if analytics tracking is needed

---

## SSE Event Types

| Event | Payload | Meaning |
|-------|---------|---------|
| `hint_meta` | `{level, remaining, exhausted, sources}` | Hint level and availability |
| `token` | `{index, text, latency_ms}` | Streaming text token |
| `done` | `{message_id, tokens, sources}` | Message complete, ready for next |
| `heartbeat` | `{session_id, timestamp}` | Connection keepalive |
| `error` | `{code, message}` | Error during processing |

---

## Error Handling

**503 Service Unavailable**: Study Buddy feature not enabled
- Solution: Set `ENABLE_STUDY_BUDDY=1` in `.env`

**404 Not Found**: Session not found
- Solution: Verify session_id is correct and session hasn't expired

**SSE Connection Lost**: Network issue or server restart
- Solution: Reconnect to SSE endpoint and create new session if needed

---

## Best Practices

1. **Always connect to SSE before posting messages**
   - Connect first: `GET /study-buddy/sessions/{session_id}/stream`
   - Then post: `POST /study-buddy/sessions/{session_id}/messages`

2. **Handle SSE reconnection**
   - If SSE disconnects, user can reconnect to same session_id
   - Messages posted while disconnected are queued

3. **Display tokens in real-time**
   - Use `token` events to update UI smoothly
   - Don't wait for `done` event

4. **Show hint level**
   - Display remaining hints to user
   - Show when hints are exhausted

5. **Handle errors gracefully**
   - Catch `error` events from SSE
   - Provide user feedback

---

## Comparison: Simplified vs Original

| Aspect | Original | Simplified |
|--------|----------|-----------|
| Endpoints | 5 | 3 |
| Redundancy | High (get_session) | None |
| Clarity | Confusing flow | Clear: create → SSE → post |
| Analytics | Yes | No (can add later) |
| Follows Pattern | No | Yes (matches Adaptive Quiz) |
| Test Pass Rate | 7/7 | 7/7 ✅ |

