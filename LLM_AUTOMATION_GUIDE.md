# 🤖 LLM Job Automation System - Complete Guide

## 📋 Overview

The system automatically processes LLM jobs for question generation using **FastAPI BackgroundTasks**. When a job is created, it's automatically processed in the background without manual worker execution.

---

## 🔄 How It Works

```
User/Admin Request → Create Job → Add to BackgroundTasks → Auto-Worker Processes → Update Status
```

**Key Components:**
1. **Job Creation Endpoints** - Create jobs and trigger automation
2. **Auto-Worker** - Background processor using LLMWorkerRunner
3. **LLMWorkerRunner** - Actual LLM integration and database operations
4. **Background Tasks** - FastAPI's built-in async task queue

---

## 📡 API Endpoints & Usage

### 🟢 **User Endpoint: Request New Topic**

**Endpoint:** `POST /request-topic`  
**Authentication:** Required (any authenticated user)  
**Purpose:** Users request a new topic that needs admin approval

**Request:**
```json
{
  "topic_name": "Linear Algebra"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Topic request submitted for admin review",
    "topic_slug": "linear-algebra",
    "status": "pending_approval"
  }
}
```

**What Happens:**
1. ✅ Creates entry in `pending_topics` table
2. ✅ Status: `"queued"` 
3. ✅ Emits `TOPIC_REQUESTED` event
4. ❌ **Does NOT create LLM job** (waits for admin approval)
5. ❌ **Does NOT trigger auto-worker** (no job yet)

**Next Step:** Admin must approve via `/admin/approve-topic`

---

### 🔵 **Admin Endpoint: Approve Topic Request**

**Endpoint:** `POST /admin/approve-topic`  
**Authentication:** Required (admin only)  
**Purpose:** Approve user's topic request and auto-generate questions

**Request:**
```json
{
  "topic_name": "Linear Algebra",
  "topic_description": "Fundamental concepts of linear algebra including vectors, matrices, and linear transformations",
  "params": {
    "batch_size": 15,
    "language": "en",
    "avoid_phrases": []
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "job_id": "uuid-here",
    "topic_slug": "linear-algebra",
    "topic_name": "Linear Algebra",
    "status": "queued",
    "message": "Topic approved and queued for generation. Worker processing automatically."
  }
}
```

**What Happens:**
1. ✅ Creates `LLMJob` with status `"queued"`
2. ✅ Updates `pending_topics` status to `"approved"`
3. ✅ **Triggers auto-worker via BackgroundTasks**
4. ✅ Worker processes job asynchronously
5. ✅ Updates job status to `"succeeded"` or `"failed"`
6. ✅ Creates topic and questions in database

**Automation:** ✅ **Fully Automated**

---

### 🟣 **Admin Endpoint: Direct Topic Creation**

**Endpoint:** `POST /admin/create-topic`  
**Authentication:** Required (admin only)  
**Purpose:** Directly create/expand topic without approval flow

**Request:**
```json
{
  "topic_name": "Calculus",
  "topic_description": "Differential and integral calculus fundamentals",
  "params": {
    "batch_size": 30,
    "language": "en",
    "avoid_phrases": []
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "job_id": "uuid-here",
    "topic_slug": "calculus",
    "status": "queued",
    "message": "Topic creation job queued. Processing automatically.",
    "exists": false,
    "batch_size": 30
  }
}
```

**What Happens:**
1. ✅ Checks if topic already exists
2. ✅ Creates `LLMJob` with batch_size (default 30 for new topics)
3. ✅ **Triggers auto-worker via BackgroundTasks**
4. ✅ Worker processes job asynchronously
5. ✅ If topic exists: adds more questions
6. ✅ If new: creates topic + initial questions
7. ✅ Updates job status to `"succeeded"` or `"failed"`

**Special Feature:** Can add questions to existing topics!

**Automation:** ✅ **Fully Automated**

---

### 🔴 **Admin Endpoint: Check Job Status**

**Endpoint:** `GET /admin/jobs`  
**Authentication:** Required (admin only)  
**Purpose:** Monitor all LLM job statuses

**Query Parameters:**
- `status`: Filter by status (`queued`, `running`, `succeeded`, `failed`)
- `limit`: Number of results (default 50)

**Response:**
```json
{
  "success": true,
  "data": {
    "jobs": [
      {
        "id": "uuid-here",
        "job_type": "generate_topic",
        "status": "succeeded",
        "topic_slug": "linear-algebra",
        "topic_name": "Linear Algebra",
        "created_count": 15,
        "error": null,
        "created_at": "2025-10-31T10:00:00Z",
        "updated_at": "2025-10-31T10:02:30Z"
      }
    ],
    "total": 1
  }
}
```

**Use Cases:**
- Monitor job progress
- Check for failures
- See which topics are being generated
- Verify automation is working

---

### 🟡 **Admin Endpoint: View Pending Requests**

**Endpoint:** `GET /admin/pending-requests`  
**Authentication:** Required (admin only)  
**Purpose:** See all user topic requests awaiting approval

**Response:**
```json
{
  "success": true,
  "data": {
    "pending_requests": [
      {
        "id": "uuid-here",
        "topic_slug": "quantum-physics",
        "display_name": "Quantum Physics",
        "status": "queued",
        "requested_by": "user-uuid",
        "created_at": "2025-10-31T09:00:00Z"
      }
    ]
  }
}
```

**Use Case:** Admin reviews and approves/rejects user requests

---

## 🔧 Auto-Worker Architecture

### Component: `app/features/llm/auto_worker.py`

```python
class AutoWorker:
    """Automatic background worker that processes LLM jobs."""
    
    async def trigger_job_processing(self, job_id: str = None):
        # 1. Check if already processing (prevent concurrent runs)
        # 2. Initialize LLMWorkerRunner (uses gpt-4o by default)
        # 3. Process single job from queue
        # 4. Log results
        # 5. Job status automatically updated in database
```

**Features:**
- ✅ Singleton pattern (one global instance)
- ✅ Prevents concurrent processing
- ✅ Uses settings from config (gpt-4o, database URL, API keys)
- ✅ Automatic error handling and logging
- ✅ Integrates with worker/runner.py

---

## 🎯 Job Processing Flow

```
1. Admin calls /admin/approve-topic or /admin/create-topic
   ↓
2. Endpoint creates LLMJob in database (status: "queued")
   ↓
3. Endpoint adds trigger_worker_async to BackgroundTasks
   ↓
4. FastAPI processes BackgroundTasks after response sent
   ↓
5. AutoWorker.trigger_job_processing() runs
   ↓
6. LLMWorkerRunner.process_single_job() executes:
   - Claims job (status: "queued" → "running")
   - Calls OpenAI with improved prompt
   - Validates response with Pydantic
   - Creates/updates topic in database
   - Upserts questions with deduplication
   - Updates job status: "running" → "succeeded" or "failed"
   - Emits success/failure events
   ↓
7. Admin checks status via /admin/jobs
```

---

## ⚙️ Configuration

**Environment Variables:**
```bash
# OpenAI Configuration
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o  # Now defaults to gpt-4o for quality

# Database
DATABASE_URL=postgresql+asyncpg://...

# Other settings in app/config.py
```

**Auto-Worker Settings:**
- **Model:** `gpt-4o` (upgraded from gpt-4o-mini)
- **Concurrency:** One job at a time (prevents resource exhaustion)
- **Retry:** Handled by LLMWorkerRunner (1 repair attempt for malformed JSON)
- **Timeout:** Managed by OpenAI client

---

## 🐛 Common Issues & Fixes

### Issue 1: "Auto-worker: no jobs available to process"
**Cause:** No jobs in queue or all jobs already processed  
**Fix:** This is normal! Create a new job via `/admin/create-topic`

### Issue 2: Job stuck in "running" status
**Cause:** Was caused by event emission error (FIXED in this update)  
**Fix:** Applied - now properly sets session_id=None for system events

### Issue 3: Poor quality questions
**Cause:** Using gpt-4o-mini (FIXED in this update)  
**Fix:** Upgraded to gpt-4o + completely rewrote prompt

### Issue 4: "Settings import error"
**Cause:** Was importing `settings` directly instead of `get_settings()` (FIXED)  
**Fix:** Changed to `from app.config import get_settings`

---

## ✅ Verification Steps

### 1. Test User Request Flow
```bash
# User requests topic
curl -X POST http://localhost:8000/request-topic \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"topic_name": "Test Topic"}'

# Check pending requests
curl http://localhost:8000/admin/pending-requests \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

### 2. Test Admin Approval (Automated)
```bash
# Approve and auto-generate
curl -X POST http://localhost:8000/admin/approve-topic \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "topic_name": "Test Topic",
    "topic_description": "A test topic",
    "params": {"batch_size": 10, "language": "en", "avoid_phrases": []}
  }'

# Response should confirm automation:
# "message": "Topic approved and queued for generation. Worker processing automatically."
```

### 3. Test Direct Creation (Automated)
```bash
# Create topic directly
curl -X POST http://localhost:8000/admin/create-topic \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "topic_name": "Physics",
    "topic_description": "Basic physics concepts",
    "params": {"batch_size": 30, "language": "en", "avoid_phrases": []}
  }'
```

### 4. Monitor Job Status
```bash
# Check all jobs
curl http://localhost:8000/admin/jobs \
  -H "Authorization: Bearer ADMIN_TOKEN"

# Filter by status
curl "http://localhost:8000/admin/jobs?status=succeeded" \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

### 5. Verify in Database
```sql
-- Check job statuses
SELECT id, topic_slug, status, created_count, error, updated_at 
FROM llm_jobs 
ORDER BY created_at DESC 
LIMIT 10;

-- Check generated questions
SELECT t.name, COUNT(q.id) as question_count
FROM topics t
LEFT JOIN questions q ON q.topic_id = t.id
GROUP BY t.id, t.name
ORDER BY t.created_at DESC;
```

---

## 📊 Expected Behavior

### After `/admin/approve-topic`:
1. ✅ Response returns immediately with job_id
2. ✅ Background processing starts within seconds
3. ✅ Job status: `queued` → `running` → `succeeded`
4. ✅ Topic and questions created in ~10-30 seconds
5. ✅ Can query `/admin/jobs` to see status

### After `/admin/create-topic`:
1. ✅ Same as approve-topic
2. ✅ Default batch_size: 30 questions
3. ✅ Can add to existing topics
4. ✅ Bypasses approval flow completely

### Logs to Watch:
```
INFO - Auto-triggering worker for job uuid-here
INFO - Processing job uuid-here for topic 'linear-algebra'
INFO - Generating 15 questions for topic 'linear-algebra'
INFO - Successfully parsed artifact with 15 questions
INFO - Job uuid-here completed successfully: 15 questions created, 0 duplicates
INFO - Auto-worker completed job with status: succeeded
INFO - Job uuid-here: 15 questions created
```

---

## 🚀 Summary

**✅ Fully Automated System:**
- User requests → Admin approves → Auto-generates questions
- Admin creates → Auto-generates questions immediately
- No manual worker execution needed
- Background processing via FastAPI

**✅ Fixed Issues:**
- Settings import corrected
- Model upgraded to gpt-4o
- Job status properly updates
- Event emission fixed

**✅ All Endpoints Working:**
- `/request-topic` - User requests
- `/admin/pending-requests` - View requests
- `/admin/approve-topic` - Approve + auto-generate
- `/admin/create-topic` - Direct creation + auto-generate
- `/admin/jobs` - Monitor status

**Ready for production use! 🎉**
