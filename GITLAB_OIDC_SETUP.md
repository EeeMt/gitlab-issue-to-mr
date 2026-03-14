# GitLab OIDC Login Setup

This document explains how to enable GitLab OIDC login for the GIMR dashboard.

## Overview

After OIDC is enabled:

- users sign in with their GitLab account
- the backend completes the OIDC callback
- the backend stores a server-side session
- the browser keeps only a secure session cookie

Current implementation notes:

- when `OIDC_ENABLED=false`, dashboard auth is bypassed and existing behavior is preserved
- when `OIDC_ENABLED=true`, dashboard APIs require login
- admin-only pages and APIs are controlled by platform admin role
- OIDC settings can now be managed in the dashboard **Configuration** page
- secrets edited in the page are encrypted before being stored in the database
- normal users only see GitLab projects and tasks for projects they can access in GitLab, including public and internal projects

## 1. Create a GitLab OAuth application

Open your GitLab instance and create an OAuth application:

1. Go to **User Settings** -> **Applications**
2. Click **Add new application**
3. Fill in:
   - **Name**: `GIMR Dashboard`
   - **Redirect URI**: `https://your-domain.example.com/api/auth/callback`
   - **Scopes**:
      - `openid`
      - `profile`
      - `email`
      - `read_api`
4. Save the application
5. Copy:
   - **Application ID**
   - **Secret**

If your deployment is behind the bundled nginx, the redirect URI should point to the external dashboard domain, not the internal backend container address.

## 2. Configure backend environment variables

Set the following bootstrap variables in your deployment environment, such as `deploy/.env.test` or your production env file:

```bash
# Required for encrypted page-managed secrets
CONFIG_ENCRYPTION_KEY=replace-with-a-long-random-secret

# Optional bootstrap/fallback values for OIDC
OIDC_ENABLED=false
OIDC_ISSUER_URL=https://gitlab.example.com
OIDC_CLIENT_ID=your_application_id
OIDC_CLIENT_SECRET=your_application_secret
OIDC_REDIRECT_URI=https://your-domain.example.com/api/auth/callback

# Session settings
SESSION_SECRET=replace-with-a-long-random-secret
SESSION_COOKIE_NAME=gimr_session
SESSION_TTL_SECONDS=28800
COOKIE_SECURE=true
COOKIE_SAMESITE=lax

# Initial platform admins
AUTH_ADMIN_USERNAMES=alice,bob
AUTH_ADMIN_GITLAB_GROUPS=platform-team
```

Recommended usage now:

1. keep `OIDC_ENABLED=false` during first deploy
2. deploy the new config UI/API
3. open the dashboard **Configuration** page
4. fill in OIDC settings there
5. run the built-in **Test OIDC connection**
6. enable OIDC in the page only after validation succeeds

## 3. What each variable means

### Required

- `CONFIG_ENCRYPTION_KEY`
  - Used to encrypt page-managed secret config values at rest.
  - Keep this in environment variables, not in the database.

- `OIDC_ENABLED`
  - Enables GitLab login and API protection.
  - This can be managed in the page once the app is deployed.
  - Keep it `false` during bootstrap until the rest of the values are ready.

- `OIDC_ISSUER_URL`
  - Your GitLab base URL.
  - The backend uses `/.well-known/openid-configuration` under this URL for discovery.

- `OIDC_CLIENT_ID`
  - GitLab OAuth application ID.

- `OIDC_CLIENT_SECRET`
  - GitLab OAuth application secret.
  - Can now be entered in the configuration page and will be stored encrypted.

- `OIDC_REDIRECT_URI`
  - Must exactly match the redirect URI configured in GitLab.

- `SESSION_SECRET`
  - Used by the backend for session-related signing and hashing.
  - Use a strong random string.

### Recommended

- `SESSION_COOKIE_NAME`
  - Cookie name used by the dashboard session.
  - Default is `gimr_session`.

- `SESSION_TTL_SECONDS`
  - Session lifetime in seconds.
  - Default is `28800` (8 hours).

- `COOKIE_SECURE`
  - Should be `true` in production HTTPS deployments.
  - If you test over plain HTTP locally, you may need `false`.

- `COOKIE_SAMESITE`
  - Recommended value is `lax`.

### Admin bootstrap

- `AUTH_ADMIN_USERNAMES`
  - Comma-separated GitLab usernames that should become platform admins on login.

- `AUTH_ADMIN_GITLAB_GROUPS`
  - Comma-separated GitLab group names used for admin bootstrap.
  - This depends on GitLab returning group information in OIDC claims or userinfo.
  - If unsure, start with `AUTH_ADMIN_USERNAMES`.

## 4. Deployment example

If you are using the repository's Docker Compose deployment:

1. Update `deploy/.env.test` or your real env file
2. Rebuild and restart:

```bash
cd deploy
docker-compose build backend nginx
docker-compose up -d backend scheduler nginx
```

Notes:

- `backend` and `scheduler` share the same backend image in the current deployment setup
- only `scheduler` runs automatic migrations during deploy
- `CONFIG_ENCRYPTION_KEY` must be present before saving secrets from the page

## 5. Validation steps

After deployment, validate in this order.

### Open the configuration page

Visit:

```text
https://your-domain.example.com/config
```

Fill in the GitLab OIDC fields, save them, and run **Test OIDC connection**.

### Check backend auth state

```bash
curl -s https://your-domain.example.com/api/auth/me
```

Expected before login after OIDC is enabled:

```json
{
  "oidc_enabled": true,
  "authenticated": false,
  "user": null
}
```

### Open the login page

Visit:

```text
https://your-domain.example.com/login
```

You should see the GitLab sign-in page entry.

### Complete login

Click **Continue with GitLab**.

After GitLab sign-in and callback:

- browser is redirected back to the dashboard
- `/api/auth/me` returns the logged-in user
- a session cookie is set in the browser

## 6. Role behavior

Current phase behavior:

- logged-in users can access dashboard data only for GitLab projects they can access
- only platform admins can access admin-only pages such as configuration and monitor-related APIs
- project visibility is resolved from the GitLab OAuth access token and includes GitLab membership projects plus public/internal projects visible to the signed-in user

Platform admin is assigned when one of these is true:

- the user already has `platform_admin` in the local database
- the GitLab username is listed in `AUTH_ADMIN_USERNAMES`
- the returned GitLab groups intersect with `AUTH_ADMIN_GITLAB_GROUPS`

## 7. Troubleshooting

### `/api/auth/login` returns 503

Usually one of these values is missing or invalid:

- `CONFIG_ENCRYPTION_KEY` when trying to save a page-managed secret
- `OIDC_ENABLED`
- `OIDC_ISSUER_URL`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET`
- `OIDC_REDIRECT_URI`

### Login redirects back with auth failure

Check:

- redirect URI matches exactly in GitLab and env
- GitLab is reachable from the backend container
- system clock is correct
- GitLab application scopes include `openid`, `profile`, and `email`

### Browser never keeps the session

Check:

- `COOKIE_SECURE=true` requires HTTPS
- nginx or upstream proxy preserves cookies correctly
- browser devtools show the session cookie being set

### You get login success but no admin access

Check:

- GitLab username spelling in `AUTH_ADMIN_USERNAMES`
- whether your GitLab OIDC response actually contains group info
- local user record in the `users` table

## 8. Safe rollout suggestion

Recommended order:

1. Deploy auth code with `OIDC_ENABLED=false`
2. Verify existing dashboard behavior is unchanged
3. Fill in all OIDC env vars
4. Enable `OIDC_ENABLED=true`
5. Rebuild and restart services
6. Test login with one admin account first

This avoids locking yourself out during the first rollout.
