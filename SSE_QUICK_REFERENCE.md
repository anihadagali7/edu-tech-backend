# 🎯 SSE Quiz - Quick Reference Card

## 🐛 BUG THAT WAS FIXED
**Problem:** SSE endpoint expected `session_uid` in URL, but server created a different one internally → events never reached client
**Solution:** Server now generates session_uid and sends it in first SSE event → client stores and uses it

---

## 📋 THE CORRECT FLOW (Step-by-Step)

### **Step 1: Open SSE Connection**
```
GET http://localhost:8000/sse/quiz/start?topic_id=<topic-uuid>
Headers:
  - Authorization: Bearer <jwt-token>
  - Accept: text/event-stream
```

**What happens:**
1. Server creates NEW quiz session
2. Server generates session_uid (e.g., "01JAB123...")
3. Server subscribes internally to that session_uid
4. Server sends first event:
   ```
   event: session_started
   data: {"session_uid":"01JAB123...","first_question":{...}}
   ```

### **Step 2: Store the Session ID (Frontend)**
```javascript
let sessionId = null; // CRITICAL: Must store this!

eventSource.addEventListener('session_started', (event) => {
  const data = JSON.parse(event.data);
  sessionId = data.session_uid; // ← SAVE THIS!
  
  // Optional: persist across page refresh
  localStorage.setItem('quizSession', sessionId);
});
```

### **Step 3: Submit Answers**
```
POST http://localhost:8000/sse/quiz/<session-uid>/answer
Headers:
  - Authorization: Bearer <jwt-token>
  - Content-Type: application/json
Body:
{
  "question_id": "<question-uuid>",
  "selected_answer": "A",
  "elapsed_ms": 5000
}
```

**What happens:**
1. Server processes answer
2. Server publishes events to session_uid
3. Your SSE connection receives:
   ```
   event: answer_feedback
   data: {"is_correct":true,...}
   
   event: question
   data: {"id":"...","body":"Next question",...}
   ```

---

## 🎨 FRONTEND: Where to Store session_uid

### **Option A: Component State (Simple)**
```javascript
const [sessionId, setSessionId] = useState(null);
```
✅ Good for: Single page quiz
❌ Lost on: Page refresh

### **Option B: LocalStorage (Persistent)**
```javascript
// Save
localStorage.setItem('quizSessionId', sessionId);

// Load
const sessionId = localStorage.getItem('quizSessionId');

// Clear when done
localStorage.removeItem('quizSessionId');
```
✅ Good for: Resumable quizzes
⚠️ Remember: Clean up when quiz ends!

### **Option C: React Context (Shared)**
```javascript
const { sessionId, setSessionId } = useQuizContext();
```
✅ Good for: Multi-component apps
❌ Lost on: Page refresh

---

## 🧪 POSTMAN TESTING CHEAT SHEET

### **Test 1: Open SSE**
```
Method: GET
URL: http://localhost:8000/sse/quiz/start?topic_id=<your-topic-uuid>
Headers:
  Authorization: Bearer <your-token>
  Accept: text/event-stream
```
→ Look for: `event: session_started` with `session_uid` in data
→ **Copy that session_uid!**

### **Test 2: Submit Answer**
```
Method: POST
URL: http://localhost:8000/sse/quiz/<session-uid-from-test-1>/answer
Headers:
  Authorization: Bearer <your-token>
  Content-Type: application/json
Body:
{
  "question_id": "<from-sse-event>",
  "selected_answer": "A",
  "elapsed_ms": 3000
}
```
→ Check SSE tab: You should see `answer_feedback` and next `question` events!

---

## ❓ FAQ

**Q: Do I call /quizzes/start first?**
A: NO! Just connect to SSE `/sse/quiz/start?topic_id=<topic-uuid>` - it creates the session automatically (include topic_id as query param).

**Q: Where does session_uid come from?**
A: Server generates it (ULID) and stores in database. You get it in first SSE event.

**Q: Must I store it in frontend?**
A: YES! You need it to submit answers. Store in state/localStorage.

**Q: What if I refresh the page?**
A: SSE disconnects. If you saved session_uid in localStorage, you can resume (no live events, but can still submit answers).

**Q: Can I use the same session_uid later?**
A: Yes! As long as the session exists in DB, you can submit answers to it.

---

## 🚀 MINIMAL WORKING EXAMPLE

```html
<!DOCTYPE html>
<html>
<body>
  <h1>Quiz</h1>
  <div id="quiz"></div>
  
  <script>
    const topicId = 'your-topic-uuid';
    let sessionId = null;
    
    // 1. Connect to SSE
    const es = new EventSource(
      `http://localhost:8000/sse/quiz/start?topic_id=${topicId}`
    );
    
    // 2. Get and store session ID
    es.addEventListener('session_started', (e) => {
      const data = JSON.parse(e.data);
      sessionId = data.session_uid;
      console.log('Session:', sessionId);
      if (data.first_question) showQuestion(data.first_question);
    });
    
    // 3. Listen for questions
    es.addEventListener('question', (e) => {
      const q = JSON.parse(e.data);
      showQuestion(q);
    });
    
    // 4. Listen for feedback
    es.addEventListener('answer_feedback', (e) => {
      const f = JSON.parse(e.data);
      alert(f.is_correct ? '✅ Correct!' : '❌ Wrong!');
    });
    
    function showQuestion(q) {
      document.getElementById('quiz').innerHTML = `
        <p>${q.body}</p>
        ${Object.entries(q.choices).map(([k,v]) => 
          `<button onclick="answer('${q.id}','${k}')">${k}. ${v}</button>`
        ).join('')}
      `;
    }
    
    async function answer(qid, choice) {
      await fetch(`http://localhost:8000/sse/quiz/${sessionId}/answer`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          question_id: qid,
          selected_answer: choice,
          elapsed_ms: 5000
        })
      });
    }
  </script>
</body>
</html>
```

---

## ✅ CHECKLIST

Before going live, verify:
- [ ] Server is running
- [ ] You can connect to `/sse/quiz/start?topic_id=X`
- [ ] First event contains `session_uid`
- [ ] Frontend stores `session_uid` in state/localStorage
- [ ] Answer submissions use the stored `session_uid`
- [ ] SSE connection receives `answer_feedback` events
- [ ] SSE connection receives next `question` events
- [ ] Quiz completion sends `quiz_completed` event

---

## 🎉 YOU'RE READY!

**Read full guide:** `SSE_USAGE_GUIDE.md`
**API docs:** http://localhost:8000/docs (when server running)
