# 🌊 SSE Quiz System - Complete Usage Guide

## 🚨 **CRITICAL BUG FIX APPLIED**

**Problem Found & Fixed:**
- **Before:** SSE endpoint accepted `session_uid` in URL path but then created a NEW session with a DIFFERENT ID, causing events to never reach the client
- **After:** SSE endpoint creates session and returns the ID in the first event - client stores and uses it

---

## 📚 **What is SSE (Server-Sent Events)?**

SSE is a **one-way real-time communication** from server to client over HTTP:
- **Client opens a connection** → Server keeps it open
- **Server pushes events** → Client receives them immediately
- **Simpler than WebSockets** → No two-way protocol needed
- **Works over HTTP** → No special infrastructure required

**Use Case:** Perfect for push notifications, live updates, real-time quiz delivery!

---

## 🎯 **How This Quiz System Uses SSE**

### **Architecture:**
```
┌─────────────┐                    ┌──────────────┐
│   Frontend  │                    │   Backend    │
│   (React)   │                    │  (FastAPI)   │
└──────┬──────┘                    └──────┬───────┘
       │                                  │
       │ 1. GET /sse/quiz/start?topic=X  │
       │────────────────────────────────>│
       │                                  │
       │ 2. SSE Stream Opened             │
       │<════════════════════════════════│ (connection stays open)
       │                                  │
       │ event: session_started           │
       │ data: {session_uid: "abc123"...} │
       │<────────────────────────────────│
       │                                  │
       │ event: question                  │
       │ data: {question_id, body...}     │
       │<────────────────────────────────│
       │                                  │
       │ 3. POST /sse/quiz/abc123/answer  │
       │────────────────────────────────>│
       │                                  │
       │ event: answer_feedback           │
       │ data: {is_correct: true...}      │
       │<────────────────────────────────│
       │                                  │
       │ event: question (next one)       │
       │<────────────────────────────────│
       │                                  │
       │ ... repeat until quiz complete   │
       │                                  │
       │ event: quiz_completed            │
       │ data: {summary, analytics...}    │
       │<────────────────────────────────│
       │                                  │
       │ Connection closed                │
       └──────────────────────────────────┘
```

---

## 🛠️ **How to Use: Frontend Implementation**

### **Step 1: Connect to SSE and Get Session ID**

```javascript
// React example with hooks
import { useState, useEffect } from 'react';

function QuizComponent({ topicId, authToken }) {
  const [sessionId, setSessionId] = useState(null);
  const [currentQuestion, setCurrentQuestion] = useState(null);
  const [eventSource, setEventSource] = useState(null);

  useEffect(() => {
    // Connect to SSE endpoint
    const es = new EventSource(
      `http://localhost:8000/sse/quiz/start?topic_id=${topicId}`,
      {
        headers: {
          'Authorization': `Bearer ${authToken}`
        }
      }
    );

    // Listen for session_started event
    es.addEventListener('session_started', (event) => {
      const data = JSON.parse(event.data);
      console.log('Session started:', data);
      
      // CRITICAL: Store the session_uid for later use!
      setSessionId(data.session_uid);
      
      // First question might be included
      if (data.first_question) {
        setCurrentQuestion(data.first_question);
      }
    });

    // Listen for question events
    es.addEventListener('question', (event) => {
      const data = JSON.parse(event.data);
      console.log('New question:', data);
      setCurrentQuestion(data);
    });

    // Listen for answer feedback
    es.addEventListener('answer_feedback', (event) => {
      const data = JSON.parse(event.data);
      console.log('Answer result:', data);
      // Show feedback UI: correct/incorrect, explanation, stats
    });

    // Listen for quiz completion
    es.addEventListener('quiz_completed', (event) => {
      const data = JSON.parse(event.data);
      console.log('Quiz completed:', data);
      // Show final results, analytics, recommendations
      es.close(); // Close the SSE connection
    });

    // Handle errors
    es.onerror = (error) => {
      console.error('SSE error:', error);
      es.close();
    };

    setEventSource(es);

    // Cleanup on unmount
    return () => {
      es.close();
    };
  }, [topicId, authToken]);

  return (
    <div>
      <h2>Quiz Session: {sessionId}</h2>
      {currentQuestion && (
        <QuestionDisplay 
          question={currentQuestion}
          sessionId={sessionId}
          authToken={authToken}
        />
      )}
    </div>
  );
}
```

### **Step 2: Submit Answers Using the Session ID**

```javascript
function QuestionDisplay({ question, sessionId, authToken }) {
  const [selectedAnswer, setSelectedAnswer] = useState(null);

  const submitAnswer = async (choiceKey) => {
    if (!sessionId) {
      console.error('No session ID available!');
      return;
    }

    const startTime = Date.now();
    
    try {
      const response = await fetch(
        `http://localhost:8000/sse/quiz/${sessionId}/answer`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${authToken}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            question_id: question.id,
            selected_answer: choiceKey,
            elapsed_ms: Date.now() - startTime
          })
        }
      );

      const result = await response.json();
      console.log('Answer submitted:', result);
      
      // No need to fetch next question - it will come via SSE!
    } catch (error) {
      console.error('Error submitting answer:', error);
    }
  };

  return (
    <div>
      <h3>{question.body}</h3>
      <div>
        {Object.entries(question.choices).map(([key, text]) => (
          <button 
            key={key}
            onClick={() => submitAnswer(key)}
          >
            {key}. {text}
          </button>
        ))}
      </div>
    </div>
  );
}
```

---

## 🧪 **How to Test in Postman**

### **Test 1: Open SSE Connection**

1. **Create Request:**
   - Method: `GET`
   - URL: `http://localhost:8000/sse/quiz/start?topic_id=<your-topic-uuid>`
   - Headers:
     ```
     Authorization: Bearer <your-jwt-token>
     Accept: text/event-stream
     ```

2. **Click Send:**
   - Postman will keep connection open
   - You'll see events streaming in:
     ```
     event: session_started
     data: {"session_uid":"01JAB...","status":"started",...}

     event: question
     data: {"id":"...","body":"What is 2+2?",...}
     ```

3. **Copy the `session_uid`** from the first event - you'll need it!

### **Test 2: Submit Answer**

1. **Create New Request:**
   - Method: `POST`
   - URL: `http://localhost:8000/sse/quiz/<session_uid>/answer`
     (replace `<session_uid>` with the value from step 1)
   - Headers:
     ```
     Authorization: Bearer <your-jwt-token>
     Content-Type: application/json
     ```
   - Body (raw JSON):
     ```json
     {
       "question_id": "<question-id-from-sse>",
       "selected_answer": "A",
       "elapsed_ms": 5000
     }
     ```

2. **Click Send:**
   - Response will confirm submission
   - **Go back to the SSE tab** - you'll see new events:
     ```
     event: answer_feedback
     data: {"is_correct":true,...}

     event: question
     data: {"id":"...","body":"Next question...",...}
     ```

### **Test 3: Get Summary**

1. **Create Request:**
   - Method: `GET`
   - URL: `http://localhost:8000/sse/quiz/<session_uid>/summary`
   - Headers:
     ```
     Authorization: Bearer <your-jwt-token>
     ```

2. **Click Send:**
   - Returns comprehensive analytics and results

---

## 📝 **Where to Store Session ID in Frontend**

### **Option 1: React Component State (Simple)**
```javascript
const [sessionId, setSessionId] = useState(null);
```
✅ **Use when:** Single quiz component
❌ **Problem:** Lost on page refresh

### **Option 2: React Context (Medium)**
```javascript
// QuizContext.js
const QuizContext = createContext();

export function QuizProvider({ children }) {
  const [sessionId, setSessionId] = useState(null);
  return (
    <QuizContext.Provider value={{ sessionId, setSessionId }}>
      {children}
    </QuizContext.Provider>
  );
}
```
✅ **Use when:** Multiple components need access
❌ **Problem:** Lost on page refresh

### **Option 3: LocalStorage + State (Recommended for persistence)**
```javascript
const [sessionId, setSessionId] = useState(() => {
  return localStorage.getItem('quizSessionId') || null;
});

// When session starts
const handleSessionStarted = (data) => {
  setSessionId(data.session_uid);
  localStorage.setItem('quizSessionId', data.session_uid);
};

// Cleanup when quiz ends
const handleQuizComplete = () => {
  localStorage.removeItem('quizSessionId');
  setSessionId(null);
};
```
✅ **Use when:** Want to survive page refresh
⚠️ **Remember:** Clear it when quiz completes!

### **Option 4: Redux/Zustand (Large Apps)**
```javascript
// Zustand store
const useQuizStore = create((set) => ({
  sessionId: null,
  setSessionId: (id) => set({ sessionId: id }),
}));
```
✅ **Use when:** Complex state management needed

---

## ❓ **FAQ: Common Questions**

### **Q: Do I need to call `/quizzes/start` before SSE?**
**A:** No! The new SSE endpoint creates the session automatically. Just connect and get the session_uid from the first event.

### **Q: Where is session_uid stored on backend?**
**A:** In the `sessions` table in PostgreSQL. But the frontend must store it too (in memory/localStorage) to use it in subsequent API calls.

### **Q: What if I refresh the page?**
**A:** 
- SSE connection closes
- If you stored session_uid in localStorage, you can reconnect
- Otherwise, start a new quiz session

### **Q: Can I resume a quiz later?**
**A:** Yes! Store the session_uid in localStorage/database. You won't get live SSE events, but you can:
- POST answers to the same session
- GET /sse/quiz/{session_uid}/summary for results

### **Q: Is this standard SSE usage?**
**A:** Yes! This is a common pattern:
1. Client connects to SSE endpoint
2. Server sends initial state/ID
3. Client stores ID for subsequent operations
4. Server pushes updates via SSE

Examples: GitHub notifications, trading apps, live sports scores.

---

## 🚀 **Complete Example: Vanilla JavaScript**

```html
<!DOCTYPE html>
<html>
<head>
  <title>SSE Quiz Test</title>
</head>
<body>
  <h1>Adaptive Quiz</h1>
  <div id="quiz-container"></div>

  <script>
    const topicId = 'your-topic-uuid-here';
    const authToken = 'your-jwt-token-here';
    let sessionId = null;

    // Connect to SSE
    const eventSource = new EventSource(
      `http://localhost:8000/sse/quiz/start?topic_id=${topicId}`
      // Note: Can't set auth headers with EventSource, use cookies or query param auth
    );

    // Handle session started
    eventSource.addEventListener('session_started', (e) => {
      const data = JSON.parse(e.data);
      sessionId = data.session_uid;
      console.log('Session ID:', sessionId);
      
      if (data.first_question) {
        displayQuestion(data.first_question);
      }
    });

    // Handle new questions
    eventSource.addEventListener('question', (e) => {
      const question = JSON.parse(e.data);
      displayQuestion(question);
    });

    // Handle answer feedback
    eventSource.addEventListener('answer_feedback', (e) => {
      const feedback = JSON.parse(e.data);
      alert(feedback.is_correct ? '✅ Correct!' : '❌ Wrong!');
    });

    // Handle quiz complete
    eventSource.addEventListener('quiz_completed', (e) => {
      const summary = JSON.parse(e.data);
      alert(`Quiz Complete! Score: ${summary.performance.accuracy * 100}%`);
      eventSource.close();
    });

    function displayQuestion(question) {
      const container = document.getElementById('quiz-container');
      container.innerHTML = `
        <h2>${question.body}</h2>
        ${Object.entries(question.choices).map(([key, text]) => `
          <button onclick="submitAnswer('${question.id}', '${key}')">
            ${key}. ${text}
          </button>
        `).join('')}
      `;
    }

    async function submitAnswer(questionId, choiceKey) {
      const response = await fetch(
        `http://localhost:8000/sse/quiz/${sessionId}/answer`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${authToken}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            question_id: questionId,
            selected_answer: choiceKey,
            elapsed_ms: 5000
          })
        }
      );
      
      const result = await response.json();
      console.log('Answer result:', result);
    }
  </script>
</body>
</html>
```

---

## ✅ **Summary: The Fixed Flow**

### **Old (Broken) Flow:**
1. ❌ Client provides random session_uid in URL
2. ❌ Server subscribes to that random ID
3. ❌ Server creates NEW session with DIFFERENT ID
4. ❌ Events published to wrong ID → client never receives them

### **New (Fixed) Flow:**
1. ✅ Client connects to `/sse/quiz/start?topic_id=X`
2. ✅ Server creates session, gets DB-generated session_uid
3. ✅ Server subscribes to that REAL session_uid
4. ✅ Server sends session_uid to client in first event
5. ✅ Client stores session_uid
6. ✅ All events work perfectly!

---

## 🎉 **You're Ready!**

The bug is fixed and you now understand:
- ✅ How SSE works
- ✅ Where session_uid comes from (server generates it)
- ✅ Where to store it (frontend state/localStorage)
- ✅ How to use it (in all subsequent API calls)
- ✅ How to test in Postman
- ✅ How to implement in React/JavaScript

**Next steps:**
1. Start your server
2. Try the Postman flow above
3. Implement in your frontend using the examples
4. Enjoy real-time adaptive quizzes! 🚀
