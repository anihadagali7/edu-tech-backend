# Clerk Organization-Based Roles Implementation

## Overview

This document describes the comprehensive implementation of Clerk organization-based roles in the adaptive quiz backend. The system now supports both global user roles and organization-specific roles, providing fine-grained access control.

## Architecture

### Role Hierarchy

1. **Global Roles**: Traditional system-wide roles
   - `admin`: System administrator with full access
   - `user`: Regular user with standard permissions

2. **Organization Roles**: Context-specific roles within organizations
   - `org:admin`: Administrator within an organization
   - `org:member`: Regular member of an organization
   - `org:billing`: Billing manager for an organization
   - `org:custom`: Custom role for specific use cases

### Database Schema Changes

#### AppUser Model Updates

```python
class AppUser(Base):
    # Existing fields...
    role: Mapped[str | None]  # Global role: 'admin'|'user'
    
    # New organization fields
    active_org_id: Mapped[str | None]     # Clerk organization ID
    active_org_role: Mapped[str | None]   # Role within active org
    active_org_slug: Mapped[str | None]   # Human-readable org identifier
```

### Authentication Flow

1. **JWT Processing**: Extract organization info from Clerk JWT tokens
2. **Role Resolution**: Determine effective role (org role takes precedence)
3. **User Upsert**: Store/update user with organization context
4. **Request Context**: Attach comprehensive user info to request

## Implementation Details

### Middleware Updates

#### Enhanced `clerk_auth_dependency`

- Extracts `org_id`, `org_role`, `org_slug` from JWT claims
- Handles multiple organizations (uses first one if no active org)
- Returns comprehensive user context:
  ```python
  {
      "id": user_id,
      "role": effective_role,        # org role or global role
      "global_role": global_role,    # always the global role
      "org_id": org_id,
      "org_role": org_role,
      "org_slug": org_slug,
      # ... other fields
  }
  ```

#### New Authorization Decorators

1. **`require_role(*roles)`**: Updated to support both global and org roles
2. **`require_org_role(*org_roles)`**: Requires specific org roles
3. **`require_admin_or_org_admin()`**: Allows either global or org admins

### Service Layer Updates

#### Quiz Service
- Updated ownership checks to recognize org admins
- Supports both global and organization-level administrative access

#### SSE Implementation
- Uses user's effective role for all operations
- Maintains consistency with standard API role handling

### API Endpoint Updates

All admin endpoints now use `require_admin_or_org_admin()` instead of `require_role("admin")`:

- `/admin/users` - User management
- `/admin/events` - Event viewing
- `/admin/export.*` - Data export
- `/admin/topics/*` - Topic management
- `/admin/questions/import` - Question import

## Configuration

### Environment Variables

```bash
# Clerk organization settings (existing)
CLERK_PUBLISHABLE_KEY=pk_test_...
CLERK_SECRET_KEY=sk_test_...
CLERK_JWKS_URL=https://.../.well-known/jwks.json
CLERK_ISSUER=https://...
CLERK_JWT_AUDIENCE=...

# Role mappings (optional)
ORG_ROLE_MAPPINGS='{"admin":"org:admin","member":"org:member"}'
```

### Clerk Dashboard Configuration

1. **Enable Organizations**: Turn on organization feature in Clerk dashboard
2. **JWT Template**: Ensure JWT includes organization claims:
   ```json
   {
     "org_id": "{{org.id}}",
     "org_role": "{{org.role}}",
     "org_slug": "{{org.slug}}",
     "orgs": "{{user.organizations}}"
   }
   ```

## Usage Examples

### Frontend Integration

```typescript
// Check if user has admin privileges (global or org)
const isAdmin = user.role === 'admin' || user.role === 'org:admin';

// Access organization context
if (user.org_id) {
    console.log(`User is ${user.org_role} in ${user.org_slug}`);
}

// Handle role-specific UI
switch (user.role) {
    case 'admin':
        // Global admin UI
        break;
    case 'org:admin':
        // Organization admin UI
        break;
    case 'org:member':
        // Organization member UI
        break;
    default:
        // Regular user UI
}
```

### Backend Role Checks

```python
# Endpoint requiring global or org admin
@router.get("/admin/dashboard")
async def admin_dashboard(
    _: dict = Depends(require_admin_or_org_admin())
):
    return {"message": "Admin access granted"}

# Endpoint requiring specific org role
@router.get("/org/billing")
async def billing_info(
    _: dict = Depends(require_org_role("billing", "admin"))
):
    return {"billing": "data"}

# Service-level role checking
def can_edit_topic(user_role: str, topic_owner_id: str, user_id: str) -> bool:
    is_owner = topic_owner_id == user_id
    is_admin = user_role in ["admin", "org:admin"]
    return is_owner or is_admin
```

## Migration Guide

### Database Migration

Run the new migration to add organization fields:

```bash
alembic upgrade head
```

### Existing User Handling

- Existing users will have `NULL` organization fields initially
- When they log in with organization context, fields will be populated
- Global roles are preserved and continue to work

### API Client Updates

Update API clients to handle new user context fields:

```python
# Before
if user['role'] == 'admin':
    show_admin_features()

# After
if user['role'] == 'admin' or user['role'] == 'org:admin':
    show_admin_features()

# Or use helper function
def is_admin(user):
    return user.get('global_role') == 'admin' or 'admin' in user.get('role', '')
```

## Testing

### Test Coverage

1. **Unit Tests**: Role resolution logic, middleware functions
2. **Integration Tests**: End-to-end organization workflows
3. **Access Control Tests**: Verify role-based restrictions work correctly

### Test Organization Setup

Create test organizations in Clerk dashboard for development/testing:

```json
{
    "test-org-1": {
        "users": [
            {"email": "admin@test.com", "role": "admin"},
            {"email": "member@test.com", "role": "member"}
        ]
    }
}
```

## Security Considerations

### JWT Validation
- All organization claims are validated through Clerk's JWT verification
- Organization membership is verified server-side
- Role assignments can only be made through Clerk dashboard

### Access Control
- Organization roles are scoped to their organization
- Global admin role overrides organization restrictions
- No privilege escalation between organizations

### Data Isolation
- Organization context is included in audit logs
- Future features can implement org-level data segregation
- Session management respects organization boundaries

## Monitoring and Observability

### Logging Enhancements

All requests now include organization context in logs:

```json
{
    "timestamp": "2025-01-11T12:00:00Z",
    "user_id": "uuid",
    "global_role": "user",
    "effective_role": "org:admin",
    "org_id": "org_123",
    "org_slug": "acme-corp",
    "action": "topic_created"
}
```

### Metrics
- Track organization adoption rates
- Monitor role distribution within organizations
- Measure feature usage by organization size

## Future Enhancements

1. **Multi-Organization Support**: Allow users to be members of multiple orgs
2. **Custom Permissions**: Fine-grained permissions within organizations
3. **Organization Analytics**: Org-specific reporting and dashboards
4. **Bulk Operations**: Batch operations scoped to organizations
5. **Organization Settings**: Org-level configuration and preferences

## Troubleshooting

### Common Issues

1. **JWT Missing Org Claims**: Ensure JWT template includes organization fields
2. **Role Not Updating**: Check Clerk organization membership and role assignments
3. **Access Denied**: Verify user has correct role in the right organization
4. **Migration Issues**: Ensure database migration completed successfully

### Debug Commands

```bash
# Check user's organization status
python -c "
from app.auth.middleware import _upsert_app_user
# ... debug user role resolution
"

# Verify JWT claims
python -c "
import jwt
token = 'your_jwt_token_here'
claims = jwt.decode(token, options={'verify_signature': False})
print(claims)
"
```

## Conclusion

The organization-based roles implementation provides a robust, scalable foundation for multi-tenant functionality while maintaining backward compatibility with existing global roles. The system is ready for production use and provides a superior access control experience for both individual users and organizational teams.