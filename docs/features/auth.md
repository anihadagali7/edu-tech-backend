# Auth and roles

**In one line:** Clerk handles sign-in. The UI sends Clerk's JWT to the API. The API checks the JWT itself and reads the role from it.

## Flow

1. The UI wraps the app in `<ClerkProvider>` (`src/components/providers.tsx`). `src/middleware.ts` runs `clerkMiddleware()` on every route.
2. Before each API call, `useBackendApi().makeAuthenticatedRequest` (`src/hooks/use-backend-api.ts`) calls `getToken()` and sets `Authorization: Bearer <jwt>`. A 401 that looks like an expired session signs the user out.
3. The API's `clerk_auth_dependency` (`app/auth/middleware.py`):
   - reads the token's `kid` (key id) and finds the matching public key in Clerk's JWKS (fetched from `CLERK_JWKS_URL`, cached 5 minutes);
   - checks the signature, expiry and `iss` = `CLERK_ISSUER`. The audience is not checked, because Clerk session tokens do not carry one;
   - reads `sub` (the Clerk user id), name and avatar, and upserts `app_users`;
   - reads the role from `claims.role` or `claims.public_metadata.role`, defaulting to `user`;
   - puts `{id, clerk_user_id, role, full_name, …}` on `request.state.user`.
4. Admin routes add `Depends(require_role("admin"))`. A missing or wrong role returns 403.

## Roles

| Role | How you get it | Can do |
|---|---|---|
| `user` | default | browse topics, take quizzes, request topics, edit profile, see own history |
| `admin` | Clerk public metadata `{"role": "admin"}` **plus** the session-token claim ([deployment.md](../deployment.md#2-clerk-auth)) | all of the above, plus create, edit or delete topics, approve or reject requests, import questions, see jobs, users and events |

Roles are **not** stored in the database (migration `0009_remove_role_pure_clerk`). Changing a role in Clerk takes effect at the next token refresh. Signing out and back in forces it.

On the UI side, `src/hooks/use-role.ts` reads `claims.role` from the `/me` response to show or hide admin links. This only controls what is shown. The API's check is the one that counts.

## Profile

- `GET /profile` and `PUT /profile` (`app/features/profile.py`) store age, education level and subjects of interest on `app_users`, and set `profile_complete`.
- The UI's `/profile/create` page fills these in.

## Gotchas

- "403 on admin pages" almost always means the session-token claim is missing. Decode your token at jwt.io and look for `role`.
- `clerk_webhooks.py` is unused and broken (see [revival-plan.md](../revival-plan.md) 2g). Users are created on their first API call instead.
