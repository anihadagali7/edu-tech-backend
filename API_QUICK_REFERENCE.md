# 🎯 Quick API Reference - LLM Job Automation

## For Users (Regular Students)

### Request a New Topic
```http
POST /request-topic
Authorization: Bearer <user_token>
Content-Type: application/json

{
  "topic_name": "Linear Algebra"
}
```
**Result:** Request goes to pending queue, awaits admin approval

---

## For Admins

### 1️⃣ View Pending Topic Requests
```http
GET /admin/pending-requests
Authorization: Bearer <admin_token>
```
**Returns:** List of topics users have requested

---

### 2️⃣ Approve Topic & Auto-Generate Questions
```http
POST /admin/approve-topic
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "topic_name": "Linear Algebra",
  "topic_description": "Vectors, matrices, linear transformations, eigenvalues",
  "params": {
    "batch_size": 15,
    "language": "en",
    "avoid_phrases": []
  }
}
```
**Result:** ✅ Automatically generates 15 questions in background

---

### 3️⃣ Create Topic Directly (Bypass Approval)
```http
POST /admin/create-topic
Authorization: Bearer <admin_token>
Content-Type: application/json

{
  "topic_name": "Calculus",
  "topic_description": "Differential and integral calculus basics",
  "params": {
    "batch_size": 30,
    "language": "en",
    "avoid_phrases": []
  }
}
```
**Result:** ✅ Automatically generates 30 questions in background  
**Note:** Default batch_size is 30 for direct creation

---

### 4️⃣ Monitor Job Status
```http
GET /admin/jobs?status=succeeded&limit=50
Authorization: Bearer <admin_token>
```
**Returns:** List of all jobs with their status

**Possible Statuses:**
- `queued` - Waiting to be processed
- `running` - Currently processing
- `succeeded` - ✅ Completed successfully
- `failed` - ❌ Error occurred

---

### 5️⃣ Reject Topic Request
```http
POST /admin/pending-requests/{request_id}/reject
Authorization: Bearer <admin_token>
```
**Result:** Removes from pending queue

---

## Parameters Explained

### `batch_size`
- Number of questions to generate
- **For approval**: Default 15 (can customize)
- **For direct creation**: Default 30 (can customize)
- Range: 1-100 questions

### `topic_description`
- Provides context to LLM for better questions
- 2-4 sentences recommended
- Examples: "Fundamental concepts including...", "Introduction to..."

### `language`
- ISO language code
- Default: `"en"` (English)
- Supports: `"es"` (Spanish), `"fr"` (French), etc.

### `avoid_phrases`
- Array of phrases to avoid in questions
- Example: `["trick question", "none of the above"]`
- Optional

---

## Automation Details

### ✅ What Happens Automatically:
1. Job created in database
2. Background task triggered immediately
3. OpenAI GPT-4o generates questions
4. Questions validated and stored
5. Job status updated to succeeded/failed
6. Events logged for tracking

### ⏱️ Processing Time:
- 10 questions: ~10-15 seconds
- 30 questions: ~20-30 seconds
- Runs in background - response immediate

### 💰 Cost (Approximate):
- Using GPT-4o: ~$0.015 per 30 questions
- Much higher quality than gpt-4o-mini

---

## Workflow Examples

### Scenario 1: User Request Flow
```
1. User POST /request-topic {"topic_name": "Physics"}
   → Creates pending_topics entry
   
2. Admin GET /admin/pending-requests
   → Sees "Physics" in queue
   
3. Admin POST /admin/approve-topic
   → Auto-generates questions
   
4. Admin GET /admin/jobs
   → Confirms status: "succeeded"
```

### Scenario 2: Admin Direct Creation
```
1. Admin POST /admin/create-topic
   → Immediately starts generation
   
2. (Optional) Admin GET /admin/jobs
   → Monitor progress
   
3. Done! Topic with questions available
```

---

## Error Handling

### Common Errors:

**400 - Topic name too short**
```json
{
  "success": false,
  "error": "Topic name too short"
}
```
**Solution:** Use at least 3 characters

**409 - Topic already requested**
```json
{
  "success": true,
  "data": {
    "message": "This topic has already been requested",
    "status": "already_requested"
  }
}
```
**Solution:** Wait for admin approval or use /admin/create-topic

**500 - Generation failed**
Check `/admin/jobs` for error details in the job record

---

## Testing Tips

### Test the Full Flow:
```bash
# 1. User requests topic
curl -X POST http://localhost:8000/request-topic \
  -H "Authorization: Bearer $USER_TOKEN" \
  -d '{"topic_name":"Chemistry"}'

# 2. Admin views requests
curl http://localhost:8000/admin/pending-requests \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Admin approves (auto-generates)
curl -X POST http://localhost:8000/admin/approve-topic \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "topic_name":"Chemistry",
    "topic_description":"Basic chemistry concepts",
    "params":{"batch_size":10,"language":"en","avoid_phrases":[]}
  }'

# 4. Check status (wait a few seconds)
curl http://localhost:8000/admin/jobs \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 5. Verify in database
SELECT * FROM topics WHERE slug = 'chemistry';
SELECT COUNT(*) FROM questions WHERE topic_id = (SELECT id FROM topics WHERE slug = 'chemistry');
```

---

## 🎉 That's It!

The system is **fully automated**. Just call the endpoints and questions generate automatically in the background.

No manual worker execution needed! ✅
