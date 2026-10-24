# Organization & Role Management Plan

## Current Status Analysis

### ✅ What's Already Implemented
1. **Clerk Integration**: JWT authentication with org support
2. **Basic Middleware**: Extracts org_id, org_role, org_slug from JWT
3. **Database**: Has `role` column (colleague's schema) but NOT using Pure Clerk approach yet
4. **Migrations**: Has org support migrations (0008, 0009) but NOT applied to production DB

### ❌ What's NOT Working / Needs Fixing
1. **Database Schema Mismatch**: 
   - Code has `role` column (colleague's 0008_add_profile_fields)
   - Migrations have 0009_remove_role_pure_clerk but NOT applied
   - Conflicting migration histories
2. **Role Logic Confusion**: Mixing DB roles with Clerk roles
3. **No Organization Enforcement**: Anyone can log in without org context
4. **No Admin Types Separation**: System admin vs Org admin not distinguished
5. **No Job Limits**: No quota/limit system for org admins

---

## Proposed Architecture

### Two-Tier Role System

#### 1. **SUPER ADMIN** (System Administrator)
- **Cl
in"` in Clerk
- **No Organization Required**: Can access system without org context
- **Full API Access**: All endpoints including:
  - Run unlimited LLM jobs
  - Manage all topics globally
  - View all organizations
  - System configuration
- **Identification**: `claims.get("role") == "super_admin"`

#### 2. **ORGANIZATION ADMIN** (Teacher/Class Admin)
- **Clerk Setup**: Member of an organization with `org_role: "admin"`
- **Organization Required**: MUST be in an organization context
- **Limited Access**:
  - Create topics for THEIR organization only
  - Run LIMITED LLM jobs (e.g., 10/month quota)
  - Add/remove students (org members)
  - View org-specific analytics
- **Identification**: `claims.get("org_role") == "admin"`

#### 3. **ORGANIZATION MEMBER** (Student)
- **Clerk Setup**: Member of organization with `org_role: "member"`
- **Organization Required**: MUST be in an organization
- **Student Access**:
  - Take quizzes from their org's topics
  - View their own progress
  - Cannot create topics or jobs
- **Identification**: `claims.get("org_role") == "member"`

---

## Implementation Plan

### Phase 1: Database & Schema Cleanup ⚠️ CRITICAL

**Problem**: Migration conflict between colleague's schema and Pure Clerk
**Solution**: 
1. Check actual production DB schema (`SELECT * FROM app_users LIMIT 1`)
2. Create a reconciliation migration that:
   - Keeps `role` column if it exists (colleague's work)
   - BUT changes logic to prioritize Clerk roles
   - Adds `job_quota_used` and `job_quota_limit` columns
3. Update `AppUser` model to match reality

**Decision Needed**: Do we:
- A) Keep `role` in DB for backwards compatibility (read-only, Clerk is source of truth)
- B) Remove `role` and go Pure Clerk (may break colleague's work)
- **RECOMMENDED**: Option A - keep column, ignore it, use Clerk

### Phase 2: Clerk Configuration 🔧

**In Clerk Dashboard**:

1. **Create Custom JWT Template** with these claims:
```json
{
  "sub": "{{user.id}}",
  "email": "{{user.primary_email_address}}",
  "role": "{{user.public_metadata.system_role}}",  // "super_admin" or null
  "org_id": "{{org.id}}",
  "org_role": "{{membership.role}}",  // "admin" or "member"
  "org_slug": "{{org.slug}}"
}
```

2. **Set System Role** (in user public metadata):
   - For super admins: `user.publicMetadata.system_role = "super_admin"`
   - For regular users: leave empty

3. **Organization Setup**:
   - Create organizations for each class (e.g., "Math Grade 10")
   - Set organization slug (e.g., "math-grade-10")
   - Add teachers as org admins (`org_role: "admin"`)
   - Add students as org members (`org_role: "member"`)

4. **Disable Force Organization Prompt**:
   - In Clerk settings → Organizations → **Uncheck "Force users to select organization"**
   - This allows super admins to log in without org context
   - Students/teachers will be prompted to select org (if they're in multiple)

### Phase 3: Middleware Updates 🔐

**Update `app/auth/middleware.py`**:

```python
# Priority order for role resolution:
# 1. System role (super_admin) - highest priority
# 2. Organization role (admin, member) - if in org context
# 3. Default "user" - fallback

system_role = claims.get("role")  # "super_admin" or None
org_role = claims.get("org_role")  # "admin", "member", or None
org_id = claims.get("org_id")

# Calculate effective role
if system_role == "super_admin":
    effective_role = "super_admin"
    requires_org = False
elif org_id and org_role:
    effective_role = f"org_{org_role}"  # "org_admin" or "org_member"
    requires_org = True
else:
    effective_role = "user"
    requires_org = False
```

### Phase 4: Authorization Decorators 🛡️

**Create role-checking decorators**:

```python
# For super admin only
@require_super_admin
async def manage_system():
    pass

# For org admin (requires org context)
@require_org_admin
async def create_topic():
    # Check quota before allowing
    pass

# For org member (requires org context)
@require_org_member
async def take_quiz():
    pass
```

### Phase 5: Job Quota System 📊

**Add to AppUser model**:
```python
job_quota_limit: Mapped[int] = mapped_column(sa.Integer, default=10)
job_quota_used: Mapped[int] = mapped_column(sa.Integer, default=0)
quota_reset_at: Mapped[datetime | None]
```

**Logic**:
- Super admin: unlimited (quota check skipped)
- Org admin: check `job_quota_used < job_quota_limit`
- Reset monthly or on-demand

### Phase 6: Session Close Endpoint 🔌

**Add to `app/features/quizzes/sse.py`**:
```python
@router.post("/quiz/{session_uid}/end")
async def end_session(session_uid: str, ...):
    # Mark session completed
    # Publish quiz_completed event
    # Return success
```

---

## User Flows

### Flow 1: Super Admin Login
1. User logs in via Clerk
2. Clerk JWT includes `"role": "super_admin"`
3. Middleware sets `effective_role = "super_admin"`
4. User accesses ALL APIs without org context
5. Can run unlimited jobs

### Flow 2: Teacher (Org Admin) Login
1. Teacher logs in via Clerk
2. If in multiple orgs: Clerk prompts to select one
3. JWT includes `"org_role": "admin"`, `"org_id": "org_123"`
4. Middleware sets `effective_role = "org_admin"`
5. Can create topics for org_123
6. Job creation checks quota (10/month limit)

### Flow 3: Student (Org Member) Login
1. Student logs in via Clerk
2. If in multiple orgs: prompted to select
3. JWT includes `"org_role": "member"`, `"org_id": "org_123"`
4. Middleware sets `effective_role = "org_member"`
5. Can only take quizzes from org_123 topics
6. Cannot create topics or jobs

---

## Configuration Guide

### Clerk Dashboard Setup Steps

#### Step 1: JWT Template
1. Go to Clerk Dashboard → JWT Templates
2. Create new template "adaptive-quiz"
3. Add claims:
   - `role`: `{{user.public_metadata.system_role}}`
   - `org_id`: `{{org.id}}`
   - `org_role`: `{{membership.role}}`
   - `org_slug`: `{{org.slug}}`

#### Step 2: Create Super Admin
1. Users → Select admin user
2. Public Metadata → Add:
   ```json
   {
     "system_role": "super_admin"
   }
   ```

#### Step 3: Organization Settings
1. Organizations → Enable Organizations
2. **IMPORTANT**: Settings → Uncheck "Force organization selection"
3. This allows super admins to use the app without org context

#### Step 4: Create Organizations (Classes)
1. Organizations → Create Organization
2. Name: "Math Grade 10"
3. Slug: "math-grade-10"
4. Add teachers as admins
5. Add students as members

---

## API Endpoints by Role

### Super Admin (`role: "super_admin"`)
```
POST /admin/topics           ✅ Unlimited
POST /admin/llm/jobs         ✅ Unlimited
GET  /admin/organizations    ✅ All orgs
DELETE /admin/topics/:id     ✅ Any topic
```

### Org Admin (`org_role: "admin"`)
```
POST /topics                 ✅ For their org only (quota: 10/month)
POST /llm/jobs               ✅ For their org (quota: 10/month)
GET  /topics                 ✅ Their org topics only
POST /org/members            ✅ Add students to their org
```

### Org Member (`org_role: "member"`)
```
GET  /topics                 ✅ Their org topics only
POST /sse/quiz/start         ✅ Take quizzes
POST /sse/quiz/:id/answer    ✅ Submit answers
GET  /sessions               ✅ Their sessions only
```

---

## Questions for You

Before I implement, please confirm:

1. **Database Migration Strategy**:
   - [ ] Keep `role` column (backwards compatible)
   - [ ] Remove `role` column (Pure Clerk, may break colleague's work)

2. **Org Selection Behavior**:
   - [ ] Force org selection for all users EXCEPT super admins
   - [ ] Allow users to switch orgs mid-session
   - [ ] Lock users to one org per login

3. **Job Quota**:
   - [ ] 10 jobs per month for org admins? (configurable?)
   - [ ] Track by user or by organization?
   - [ ] Auto-reset monthly or manual reset?

4. **Super Admin Creation**:
   - [ ] Manual via Clerk dashboard metadata
   - [ ] Special signup endpoint
   - [ ] Hardcoded list in environment variables

5. **Immediate Implementation Priority**:
   - [ ] Fix session close endpoint first (quick win)
   - [ ] Fix org/role system first (bigger impact)
   - [ ] Do both together

---

## Next Steps

**Once you approve this plan**:
1. I'll create the database migration
2. Update middleware with role logic
3. Add authorization decorators
4. Implement job quota system
5. Add session close endpoint
6. Create Postman collection for testing
7. Update all documentation

**Estimated Changes**:
- 1 migration file
- 3 files updated (middleware, models, sse.py)
- 2 new files (decorators, quota logic)
- Full test suite

Please review and let me know:
- Do you agree with this architecture?
- Which database strategy? (keep or remove `role`)
- What should job quotas be?
- Any other requirements I missed?
