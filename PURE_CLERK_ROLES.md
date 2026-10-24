# Pure Clerk Roles Implementation

## Overview

The adaptive quiz backend now uses **Pure Clerk Roles** - all role management is handled entirely by Clerk with no database-stored roles. This provides a clean, single-source-of-truth approach to authorization.

## Architecture

### Role Sources (Clerk JWT Only)

1. **System Roles**: `claims.get("role")` - Global roles like "admin"
2. **Organization Roles**: `claims.get("org_role")` - Org-specific roles like "admin", "member"
3. **Effective Role**: `global_role or org_role or "user"`

### Role Types

- **`admin`**: System administrator or organization administrator
- **`user`**: Default role for regular users  
- **`member`**: Organization member
- **`billing`**: Organization billing manager
- **`custom`**: Custom organization role

## How It Works

### 1. JWT Claims Processing

```python
# Clerk JWT contains all role information
{
    "sub": "user_123",
    "role": "admin",        # Global role (optional)
    "org_id": "org_456",    # Organization ID (optional)
    "org_role": "admin",    # Organization role (optional)
    "org_slug": "acme-corp" # Organization slug (optional)
}
```

### 2. Role Resolution

```python
# Simple, clean role resolution
global_role = claims.get("role")     # System-wide role
org_role = claims.get("org_role")    # Organization role
effective_role = global_role or org_role or "user"
```

### 3. Authorization Patterns

```python
# System admin (no organization)
{
    "role": "admin",
    "org_id": None
}

# Organization admin
{
    "role": "admin", 
    "org_id": "org_123",
    "org_role": "admin"
}

# Organization member
{
    "role": "member",
    "org_id": "org_123", 
    "org_role": "member"
}
```

## Database Changes

### Removed Fields
- `app_users.role` - No longer needed (all roles from Clerk)
- `app_users.active_org_role` - Redundant with Clerk data

### Kept Fields
- `app_users.active_org_id` - Cached for performance
- `app_users.active_org_slug` - Human-readable org identifier

## API Changes

### Request Context
```python
request.state.user = {
    "id": user_uuid,
    "role": effective_role,    # From Clerk JWT
    "org_id": org_id,          # From Clerk JWT
    "org_slug": org_slug,      # From Clerk JWT
    "clerk_user_id": clerk_id,
    "claims": jwt_claims
}
```

### Authorization Decorators

```python
# Simple role check
@require_role("admin")
async def admin_endpoint():
    pass

# Organization-specific role
@require_org_role("member") 
async def org_endpoint():
    pass

# System or org admin
@require_admin_or_org_admin()
async def admin_features():
    pass
```

## Clerk Configuration

### JWT Template Required

Configure Clerk JWT to include organization claims:

```json
{
    "sub": "{{user.id}}",
    "email": "{{user.email_addresses.0.email_address}}",
    "name": "{{user.full_name}}",
    "role": "{{user.public_metadata.role}}",
    "org_id": "{{org.id}}",
    "org_role": "{{membership.role}}",
    "org_slug": "{{org.slug}}",
    "orgs": "{{user.organizations}}"
}
```

### Role Management

All roles are managed in the Clerk dashboard:
- **User Roles**: Set in user's public metadata
- **Organization Roles**: Set via organization membership

## Benefits

1. **Single Source of Truth**: All roles managed in Clerk
2. **Simplified Architecture**: No role sync between systems
3. **Real-time Updates**: Role changes are immediate
4. **Better Security**: No role data stored in application database
5. **Easier Management**: Admin UI is Clerk dashboard

## Migration

### Database Migration
```bash
alembic upgrade head  # Applies 0009_remove_role_pure_clerk
```

### Clerk Setup
1. Configure JWT template with organization claims
2. Set user roles in Clerk dashboard
3. Configure organization roles as needed

## Testing

### Role Scenarios

```python
# Test system admin
jwt_claims = {"sub": "user_1", "role": "admin"}

# Test org admin  
jwt_claims = {
    "sub": "user_2", 
    "org_id": "org_1",
    "org_role": "admin"
}

# Test org member
jwt_claims = {
    "sub": "user_3",
    "org_id": "org_1", 
    "org_role": "member"
}
```

## Troubleshooting

### Common Issues

1. **Missing Role Claims**: Ensure JWT template includes role fields
2. **Organization Not Found**: Check organization membership in Clerk
3. **Access Denied**: Verify role assignment in Clerk dashboard

### Debug Commands

```python
# Check JWT claims
import jwt
token = request.headers.get("authorization").split(" ")[1]
claims = jwt.decode(token, options={"verify_signature": False})
print(f"Role: {claims.get('role')}")
print(f"Org Role: {claims.get('org_role')}")
```

## Conclusion

The Pure Clerk implementation provides a clean, maintainable approach to role-based access control. All complexity is handled by Clerk, while the application focuses on business logic.