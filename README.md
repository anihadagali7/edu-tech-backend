# 🎓 Adaptive Quiz Backend - Complete Guide

> FastAPI-based adaptive learning platform with Clerk authentication, LLM-powered question generation, and real-time SSE quiz delivery.

## 📋 Table of Contents

- [Features](#-features)
- [Tech Stack](#-tech-stack)
- [Quick Start](#-quick-start)
- [Authentication Setup](#-authentication-clerk-setup)
- [API Documentation](#-api-documentation)
- [Worker System](#-worker-system-llm-question-generation)
- [Testing](#-testing)
- [Database](#-database)
- [Deployment](#-deployment)
- [Troubleshooting](#-troubleshooting)

---

## ✨ Features

### Core Functionality
- ✅ **Adaptive Quiz Engine** - Real-time difficulty adjustment based on user performance
- ✅ **Server-Sent Events (SSE)** - Real-time quiz streaming with instant feedback
- ✅ **LLM Question Generation** - OpenAI-powered topic and question creation
- ✅ **Clerk Authentication** - Secure JWT-based auth with role management
- ✅ **Admin Panel** - Direct topic creation and job management
- ✅ **Profile System** - User profiles with learning preferences

### Role System
- **Admin Role**: 
  - Create topics directly (bypasses approval)
  - Manage LLM jobs
  - Add questions to existing topics
  - View all system reports
  
- **User Role** (default):
  - Take adaptive quizzes
  - Track progress
  - Request new topics (pending admin approval)
  - Manage profile

---

## 🛠 Tech Stack

**Backend**
- Python 3.11+
- FastAPI (async web framework)
- SQLAlchemy 2.0 (ORM)
- Alembic (migrations)
- Uvicorn/Gunicorn (ASGI server)

**Database**
- PostgreSQL (Supabase)
- asyncpg (async driver)

**Authentication**
- Clerk (JWT tokens)
- Role-based access control (RBAC)

**AI/ML**
- OpenAI GPT-4
- LangChain (prompt management)

**Background Jobs**
- Systemd timer (cron-style)
- Async worker processing

**Code Quality**
- Ruff (linting)
- Black (formatting)
- MyPy (type checking)
- Pytest (testing)

---

## 🚀 Quick Start

### 1. Prerequisites
```bash
# Python 3.11+ required
python --version

# PostgreSQL database (Supabase recommended)
# Clerk account for authentication
# OpenAI API key for question generation
```

### 2. Installation

```bash
# Clone repository
git clone <your-repo-url>
cd edu-tech-backend

# Create virtual environment
python -m venv edtech
# Windows PowerShell:
.\edtech\Scripts\Activate.ps1
# Linux/Mac:
source edtech/bin/activate

# Install dependencies
pip install -U pip
pip install -r requirements

# Install dev dependencies (optional)
pip install -r requirements-dev
```

### 3. Environment Setup

Create `.env` file:
```env
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname

# Clerk Authentication
CLERK_SECRET_KEY=sk_test_...
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_JWT_AUDIENCE=your-clerk-instance
CLERK_ISSUER=https://clerk-instance.clerk.accounts.dev

# OpenAI
OPENAI_API_KEY=sk-...

# Application
SECRET_KEY=your-secret-key-here
ENVIRONMENT=development

# Feature Flags
ENABLE_STUDY_BUDDY=0
ENABLE_LEARNING_MATERIALS=0

# Study Buddy (optional overrides)
STUDY_BUDDY_POLICY_URL=https://docs.example.com/study-buddy/policies
STUDY_BUDDY_USE_OPENAI=0
STUDY_BUDDY_MODEL=gpt-4o-mini
```

### 4. Database Migration

```bash
# Run migrations
alembic upgrade head
```

### 5. Start Server

```bash
# Development mode (auto-reload)
python -m uvicorn app.main:app --reload --port 8000

# Production mode
gunicorn -k uvicorn.workers.UvicornWorker app.main:app --bind 0.0.0.0:8000 --workers 2
```

Server will be available at: `http://localhost:8000`

API docs: `http://localhost:8000/docs`

### Feature Flag Notes

- Set `ENABLE_STUDY_BUDDY=1` to mount the Study Buddy REST + SSE routers. When disabled, the endpoints stay unmounted and any lingering requests return `503`.
- Set `ENABLE_LEARNING_MATERIALS=1` to expose admin generation + learner retrieval routes for the learning materials service.
- Optional Study Buddy overrides:
  - `STUDY_BUDDY_POLICY_URL` controls the link returned inside hint metadata.
  - `STUDY_BUDDY_USE_OPENAI` and `STUDY_BUDDY_MODEL` toggle real OpenAI streaming instead of the deterministic mock (requires `OPENAI_API_KEY`).

---

## 🔐 Authentication (Clerk Setup)

### Step 1: Disable Organizations (Current Setup)

1. Login to [Clerk Dashboard](https://dashboard.clerk.com)
2. Navigate to: **Configure → Settings**
3. Find "Organizations" section
4. Toggle **OFF**: "Enable Organizations"
5. Click **Save**

### Step 2: Set Admin Role

1. Go to: **Users** → Select your user
2. Click **Metadata** tab
3. Under **Public Metadata**, click **Edit**
4. Add:
```json
{
  "role": "admin"
}
```
5. Click **Save**

### Step 3: Get JWT Token

Use Clerk's frontend SDK or test with their dashboard to get a JWT token for API testing.

### Step 4: Test Authentication

```bash
curl http://localhost:8000/me \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"

# Should return:
{
  "id": "uuid...",
  "clerk_user_id": "user_...",
  "role": "admin",
  "profile_complete": false,
  ...
}
```

---

## 📚 API Documentation

### Health Check

```bash
GET /health
```
Returns server status.

### Authentication

#### Get Current User
```bash
GET /me
Headers: Authorization: Bearer <jwt>

Response:
{
  "id": "uuid",
  "clerk_user_id": "user_xxx",
  "role": "admin" | "user",
  "full_name": "John Doe",
  "profile_complete": boolean,
  "age": number,
  "highest_education_level": "string",
  "subjects_of_interest": {}
}
```

### Topics

#### List Topics
```bash
GET /topics/search
Query params:
  - q: search term (optional)
  - limit: number of results (default: 20)
  - offset: pagination offset (default: 0)

Response:
{
  "data": {
    "topics": [
      {
        "id": "uuid",
        "slug": "algebra-basics",
        "name": "Algebra Basics",
        "description": "...",
        "question_count": 30,
        "avg_difficulty": 3.0
      }
    ],
    "total_count": 10
  }
}
```

#### Get Topic Details
```bash
GET /topics/{topic_id}
Headers: Authorization: Bearer <jwt>

Response:
{
  "data": {
    "topic": {
      "id": "uuid",
      "slug": "string",
      "name": "string",
      "description": "string",
      "tags": [],
      "difficulty_distribution": {
        "1": 6,
        "2": 6,
        "3": 6,
        "4": 6,
        "5": 6
      }
    }
  }
}
```

### Admin Endpoints

#### Create Topic Directly (Admin Only)
```bash
POST /llm/admin/create-topic
Headers: Authorization: Bearer <admin_jwt>
Body:
{
  "topic_name": "Advanced Calculus",
  "topic_description": "Comprehensive study of calculus including limits, derivatives, and integrals.",
  "params": {
    "batch_size": 30,
    "language": "en",
    "avoid_phrases": []
  }
}

Response:
{
  "data": {
    "job_id": "uuid",
    "topic_slug": "advanced-calculus",
    "status": "queued",
    "batch_size": 30,
    "existing_topic": false,
    "message": "Creating new topic 'Advanced Calculus' with 30 questions. Processing automatically in background."
  }
}
```

**🎯 Important**: Worker processes automatically in background - no manual execution needed!

**Note**: If topic already exists, it will ADD more questions:
```json
{
  "existing_topic": true,
  "message": "Adding 30 more questions to existing topic 'Advanced Calculus'. Processing automatically in background."
}
```

#### List LLM Jobs (Admin Only)
```bash
GET /llm/admin/jobs
Headers: Authorization: Bearer <admin_jwt>
Query params:
  - status_filter: "queued" | "processing" | "succeeded" | "failed"
  - limit: number (default: 20)

Response:
{
  "data": {
    "jobs": [
      {
        "id": "uuid",
        "job_type": "generate_topic",
        "status": "succeeded",
        "topic_slug": "algebra-basics",
        "created_count": 30,
        "created_at": "2025-10-21T..."
      }
    ]
  }
}
```

### Quiz (SSE)

#### Start Quiz Session
```bash
GET /sse/quiz/start?topic_id=algebra-basics
Headers: Authorization: Bearer <jwt>

Returns: Server-Sent Events stream
Events:
  - quiz_started: Initial session data
  - question_presented: New question
  - answer_evaluated: Feedback on answer
  - quiz_completed: Final summary
```

#### End Quiz Session
```bash
POST /sse/quiz/{session_uid}/end
Headers: Authorization: Bearer <jwt>

Response:
{
  "data": {
    "session_uid": "uuid",
    "status": "completed",
    "summary": {
      "total_questions": 10,
      "correct_answers": 7,
      "score": 70.0
    }
  }
}
```

### Profile

#### Get My Profile
```bash
GET /profile/me
Headers: Authorization: Bearer <jwt>

Response:
{
  "data": {
    "id": "uuid",
    "profile_complete": boolean,
    "age": number,
    "highest_education_level": "string",
    "subjects_of_interest": []
  }
}
```

#### Update Profile
```bash
PUT /profile/me
Headers: Authorization: Bearer <jwt>
Body:
{
  "age": 25,
  "highest_education_level": "Bachelor's Degree",
  "subjects_of_interest": ["Mathematics", "Physics"]
}

Response:
{
  "data": {
    "profile_complete": true,
    "message": "Profile updated successfully"
  }
}
```

---

## ⚙️ Worker System (LLM Question Generation)

### 🚀 Automatic Processing (No Manual Execution Needed!)

**NEW**: Worker runs automatically in background when admin creates or approves topics!

### How It Works

1. **Admin creates topic** via `POST /llm/admin/create-topic`
2. **Job queued** in `llm_jobs` table with status "queued"
3. **✨ Worker automatically triggered** in background (FastAPI BackgroundTasks)
4. **LLM generates**:
   - Topic description (2-4 sentences)
   - 30 questions with:
     - ~6 difficulty level 1 (basic)
     - ~6 difficulty level 2 (simple)
     - ~6 difficulty level 3 (moderate)
     - ~6 difficulty level 4 (complex)
     - ~6 difficulty level 5 (advanced)
   - Multiple choice options (A, B, C, D)
   - Explanations for each answer
5. **Questions saved** to database
6. **Job marked** as "succeeded"

### When Worker Runs Automatically

The worker is automatically triggered when:
- ✅ Admin creates topic: `POST /llm/admin/create-topic`
- ✅ Admin approves pending request: `POST /llm/admin/approve-topic`

**No need to run `python run_worker.py` manually!**

### Manual Execution (Optional)

If you still want to run worker manually for testing:

```bash
# Run once
python run_worker.py --once

# Process multiple jobs
python run_worker.py --loop

# Watch logs
python run_worker.py --once --verbose
```

### Systemd Timer (Alternative for Production)

If you prefer scheduled execution instead of automatic triggers:

```bash
# Copy service files
sudo cp deploy/systemd/adaptive-worker.service /etc/systemd/system/
sudo cp deploy/systemd/adaptive-worker.timer /etc/systemd/system/

# Enable and start timer (runs every 5 minutes)
sudo systemctl enable adaptive-worker.timer
sudo systemctl start adaptive-worker.timer

# Check status
sudo systemctl status adaptive-worker.timer
sudo journalctl -u adaptive-worker.service -f
```

### Configuration

Worker settings in `.env`:
```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini  # or gpt-4 for better quality
```
- Logging level

---

## 🧪 Testing

### Automated Test Suite

Run comprehensive tests:
```bash
# Set environment variables
export CLERK_TEST_ADMIN_TOKEN="your_admin_jwt"
export CLERK_TEST_USER_TOKEN="your_user_jwt"  # optional

# Run all tests
python test_all_flows.py
```

Tests cover:
1. ✅ Health check
2. ✅ Admin authentication
3. ✅ User authentication
4. ✅ List topics
5. ✅ Admin create topic
6. ✅ User permission restriction (403)
7. ✅ List LLM jobs
8. ✅ Profile endpoint
9. ✅ SSE quiz start

### Manual Testing

#### 1. Test Admin Topic Creation
```bash
curl -X POST http://localhost:8000/llm/admin/create-topic \
  -H "Authorization: Bearer YOUR_ADMIN_JWT" \
  -H "Content-Type: application/json" \
  -d '{
    "topic_name": "Algebra Basics",
    "topic_description": "Learn fundamental algebra including variables, equations, and expressions.",
    "params": {"batch_size": 30}
  }'
```

#### 2. Run Worker
```bash
python run_worker.py
```

Watch for:
- "Generating topic for: Algebra Basics"
- "LLM generated 30 questions"
- "Job succeeded"

#### 3. Verify Database
```sql
-- Check topic created with description
SELECT slug, name, description FROM topics;

-- Check difficulty distribution
SELECT difficulty, COUNT(*) 
FROM questions 
WHERE topic_id = (SELECT id FROM topics WHERE slug = 'algebra-basics')
GROUP BY difficulty
ORDER BY difficulty;
```

Expected: ~6 questions at each difficulty level (1-5)

#### 4. Test SSE Quiz
```bash
# Using curl
curl -N "http://localhost:8000/sse/quiz/start?topic_id=algebra-basics" \
  -H "Authorization: Bearer YOUR_JWT"

# Will stream events:
# event: quiz_started
# event: question_presented
# ...
```

---

## 💾 Database

### Schema Overview

**Core Tables:**
- `app_users` - User authentication and profiles
- `topics` - Learning topics
- `questions` - Quiz questions with difficulty levels
- `sessions` - Quiz sessions
- `session_answers` - User responses
- `llm_jobs` - Background job queue
- `pending_topics` - User topic requests

### Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one version
alembic downgrade -1

# Check current version
alembic current
```

### Database Utilities

```bash
# Check database connection
python check_db.py

# Inspect jobs
python scripts/inspect_jobs.py

# List recent questions
python scripts/list_recent_questions.py
```

---

## 🚀 Deployment

### AWS EC2 Deployment

1. **Setup EC2 Instance**
   - Ubuntu 22.04 LTS
   - Minimum: t3.small (2GB RAM)
   - Security group: Allow 80, 443, 22

2. **Install Dependencies**
```bash
sudo apt update
sudo apt install python3.11 python3.11-venv postgresql-client nginx
```

3. **Setup Application**
```bash
# Clone repo
git clone <repo-url>
cd edu-tech-backend

# Create venv
python3.11 -m venv edtech
source edtech/bin/activate

# Install
pip install -r requirements
```

4. **Configure Systemd Service**
```bash
sudo cp deploy/systemd/adaptive-api.service /etc/systemd/system/
sudo systemctl enable adaptive-api
sudo systemctl start adaptive-api
```

5. **Setup Nginx**
```bash
sudo cp deploy/nginx/adaptive.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/adaptive.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

6. **Setup Worker Timer**
```bash
sudo cp deploy/systemd/adaptive-worker.* /etc/systemd/system/
sudo systemctl enable adaptive-worker.timer
sudo systemctl start adaptive-worker.timer
```

### Environment Variables (Production)

Use systemd environment files:
```bash
# /etc/adaptive/.env
DATABASE_URL=postgresql+asyncpg://...
CLERK_SECRET_KEY=sk_live_...
OPENAI_API_KEY=sk-...
ENVIRONMENT=production
```

---

## 🐛 Troubleshooting

### Common Issues

#### 1. "403 Forbidden" on Admin Endpoints
**Solution**: 
- Check Clerk metadata has `{"role": "admin"}`
- Logout and login again to refresh JWT

#### 2. "Organization prompt on login"
**Solution**:
- Disable Organizations in Clerk Dashboard
- Settings → Organizations → Toggle OFF

#### 3. "Questions all difficulty level 3"
**Solution**:
- This is fixed in latest prompt
- Run worker again for new jobs
- Consider using GPT-4 for better distribution

#### 4. "Topic description is NULL"
**Solution**:
- Check worker logs for LLM response
- Prompt now requires description
- Re-run job to regenerate

#### 5. "Worker not picking up jobs"
**Solution**:
```bash
# Check job status
python scripts/inspect_jobs.py

# Run worker manually with verbose logging
python run_worker.py --verbose

# Check database connection
python check_db.py
```

#### 6. "SSE connection closes immediately"
**Solution**:
- Check topic has questions in database
- Verify JWT token is valid
- Check server logs for errors

### Logs

```bash
# Application logs (systemd)
sudo journalctl -u adaptive-api -f

# Worker logs
sudo journalctl -u adaptive-worker -f

# Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## 📖 Additional Resources

### Development

- **OpenAPI Docs**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **Swagger UI**: `http://localhost:8000/docs`

### External Documentation

- [FastAPI](https://fastapi.tiangolo.com/)
- [Clerk Auth](https://clerk.com/docs)
- [SQLAlchemy 2.0](https://docs.sqlalchemy.org/)
- [Supabase](https://supabase.com/docs)
- [OpenAI API](https://platform.openai.com/docs)

---

## 📝 License

[Add your license here]

---

## 🤝 Contributing

[Add contribution guidelines]

---

## 📧 Contact

[Add contact information]

---

**Built with ❤️ for adaptive learning**
