# GitLab OIDC Login Setup

This document explains how to enable GitLab OIDC login for the GIMR dashboard.

## Overview

After OIDC is enabled:

- users sign in with their GitLab account
- the backend completes the OIDC callback
- the backend stores a server-side session
- the browser keeps only a secure session cookie
- the backend stores GitLab access and refresh tokens encrypted in the session row when available

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

# Emergency recovery
AUTH_BREAK_GLASS_ENABLED=false
AUTH_BREAK_GLASS_USERNAME=emergency-admin
AUTH_BREAK_GLASS_PASSWORD_HASH=pbkdf2_sha256$600000$<salt_hex>$<digest_hex>
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

### Emergency recovery

- `AUTH_BREAK_GLASS_ENABLED`
  - Enables a dedicated emergency admin login path for OIDC recovery.
  - This is environment-controlled only and is intentionally not manageable from the dashboard.

- `AUTH_BREAK_GLASS_USERNAME`
  - Reserved dashboard username used for emergency login.
  - Choose a username that does not overlap with normal GitLab dashboard users.

- `AUTH_BREAK_GLASS_PASSWORD_HASH`
  - Password hash for emergency login.
  - Supported formats:
    - `sha256$<hex_digest>`
    - `pbkdf2_sha256$<iterations>$<salt_hex>$<digest_hex>` (recommended)
  - Keep this in environment variables only.

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
- break-glass recovery is configured through environment variables, not runtime config

## 5. Validation steps

After deployment, validate in this order.

### Open the configuration page

Visit:

```text
https://your-domain.example.com/configuration
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
- if GitLab returns a refresh token, GIMR stores it encrypted and can refresh GitLab API access automatically

### Review your sessions

Visit:

```text
https://your-domain.example.com/sessions
```

You should be able to:

- see the current browser session
- see whether a refresh token is available for each session
- revoke old or suspicious sessions

### Run OIDC diagnostics

Visit:

```text
https://your-domain.example.com/oidc-diagnostics
```

The diagnostics page shows:

- OIDC discovery reachability
- authorization/token/userinfo endpoint presence from discovery
- redirect URI and cookie policy warnings
- the required GitLab OAuth scopes
- an authorization URL preview built from the current effective settings

### Emergency login

If break-glass recovery is enabled, the login page also shows an emergency admin form.

Use it only when:

- OIDC discovery/token exchange is broken
- admin bootstrap rules locked everyone out
- you need temporary access to repair auth configuration

## 6. Break-glass recovery feature

### Purpose

The break-glass login exists to prevent operator lockout.

It is intended for situations such as:

- the GitLab OIDC issuer, token endpoint, or callback configuration is broken
- all platform admins lost access because bootstrap usernames/groups were changed incorrectly
- you need temporary administrator access to repair auth or configuration issues

It is **not** intended to replace normal GitLab OIDC login.

### Design

Current design principles:

- the feature is controlled only by environment variables
- it is not editable in the runtime Configuration page
- it is hidden unless the backend reports it as enabled
- successful break-glass login creates a normal dashboard session cookie
- the resulting session is a `platform_admin` session
- auth events are recorded in `auth_audit_logs`
- the configured secret is never stored in plaintext in the database

Current backend behavior:

- endpoint: `POST /api/auth/break-glass/login`
- login form appears on `/login` only when break-glass is enabled
- accepted password hash formats:
  - `sha256$<hex_digest>`
  - `pbkdf2_sha256$<iterations>$<salt_hex>$<digest_hex>`

### How to configure it

Example:

```bash
AUTH_BREAK_GLASS_ENABLED=true
AUTH_BREAK_GLASS_USERNAME=emergency-admin
AUTH_BREAK_GLASS_PASSWORD_HASH=pbkdf2_sha256$600000$<salt_hex>$<digest_hex>
```

Recommended practice:

1. keep `AUTH_BREAK_GLASS_ENABLED=false` in normal operation unless you deliberately want the path available
2. use a dedicated username that is never used for GitLab OIDC login
3. use the `pbkdf2_sha256` format instead of plain `sha256`
4. rotate the password hash after any real emergency use

### How to generate the password hash

Recommended `pbkdf2_sha256` example with Python:

```bash
python3 - <<'PY'
import os
from hashlib import pbkdf2_hmac

password = b"replace-with-a-strong-password"
salt = os.urandom(16)
iterations = 600000
digest = pbkdf2_hmac("sha256", password, salt, iterations).hex()
print(f"pbkdf2_sha256${iterations}${salt.hex()}${digest}")
PY
```

Simple `sha256` example if you only need a quick temporary hash:

```bash
python3 - <<'PY'
from hashlib import sha256
password = "replace-with-a-strong-password"
print(f"sha256${sha256(password.encode('utf-8')).hexdigest()}")
PY
```

### How to use it

1. set the three break-glass environment variables
2. rebuild and restart the deployment
3. open `/login`
4. confirm the **Emergency access** form is visible
5. sign in with the configured username and password
6. repair the broken OIDC or admin configuration
7. disable break-glass again by setting `AUTH_BREAK_GLASS_ENABLED=false`
8. rebuild and restart once more

### Audit behavior

The backend records break-glass login activity in `auth_audit_logs`.

Current events recorded:

- successful break-glass login
- failed break-glass login

Each row includes:

- event type
- username
- linked user id when available
- success/failure
- detail message
- request IP
- user agent
- timestamp

### Operational guidance

- treat break-glass access as a temporary recovery tool
- prefer enabling it only during a real incident
- after using it, fix the root cause and disable it again
- rotate the emergency password hash after use
- review `auth_audit_logs` after any emergency login attempt

## 7. Role behavior

Current phase behavior:

- logged-in users can access dashboard data only for GitLab projects they can access
- only platform admins can access admin-only pages such as configuration and monitor-related APIs
- project visibility is resolved from the GitLab OAuth access token and includes GitLab membership projects plus public/internal projects visible to the signed-in user
- emergency break-glass login, when enabled, creates a platform admin session and records an auth audit event
- admins can now manage dashboard users from the dedicated **Access Management** page
- authenticated users can manage their own sessions from the dedicated **Sessions** page

Platform admin is assigned when one of these is true:

- the user already has `platform_admin` in the local database
- the GitLab username is listed in `AUTH_ADMIN_USERNAMES`
- the returned GitLab groups intersect with `AUTH_ADMIN_GITLAB_GROUPS`

### Manual admin management

The dashboard now includes a dedicated **Access Management** page.

It is used for:

- granting or removing `platform_admin` explicitly for a dashboard user
- disabling a user without changing bootstrap config
- revoking all active sessions for a user during incident response

Design notes:

- manual role changes are stored in the database and override bootstrap username/group rules for that user
- disabling a user immediately revokes their active sessions
- users cannot change their own role/state from this screen
- the backend blocks removal of the last active platform admin

Typical usage:

1. open `/config`
2. open `/access-management`
3. change **Role** or **State**
4. click **Save access**
5. if needed, click **Revoke sessions** to force immediate re-authentication

## 8. Session hardening

### What was added

Current session hardening behavior includes:

- GitLab `refresh_token` is stored encrypted at rest when GitLab issues one
- project access checks refresh the GitLab access token automatically when possible
- project access caching is keyed by dashboard session instead of only by user id
- the scheduler automatically removes sessions that have been expired or revoked for more than 30 days
- the login screen now preserves clearer reasons when the previous session expired or lost GitLab access
- authenticated users can review and revoke their own sessions on the **Sessions** page

### Operator notes

- users must sign in again after OIDC changes so new sessions pick up the current auth settings
- some self-managed GitLab instances reject `offline_access`; the default login flow therefore requests the GitLab-compatible scopes `openid profile email read_api`
- sessions without refresh tokens still work, but once the GitLab access token expires the user must log in again
- revoking the current session from `/sessions` immediately signs that browser out

### Session UX

The `/sessions` page shows:

- session id summary
- current/active/expired/revoked status
- creation, last-seen, and expiry timestamps
- whether encrypted GitLab access and refresh tokens exist
- IP and user agent when available

## 9. Diagnostics and operator UX

Current diagnostics behavior includes:

- an admin-only `/oidc-diagnostics` page
- a backend diagnostics snapshot endpoint at `/api/config/oidc/diagnostics`
- richer `Test OIDC connection` output with required scopes and warnings
- warnings for callback path mismatches, cookie security mismatches, long session TTLs, disabled break-glass recovery, and group-based admin bootstrap prerequisites

Recommended use:

1. open `/oidc-diagnostics`
2. confirm **OIDC discovery** is healthy
3. confirm the discovered authorization/token/userinfo endpoints are present
4. verify the required scope string includes `openid profile email read_api`
5. review warnings before enabling or changing OIDC settings

## 10. Troubleshooting

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
- GitLab application scopes include `openid`, `profile`, `email`, and `read_api`

### Browser never keeps the session

Check:

- `COOKIE_SECURE=true` requires HTTPS
- nginx or upstream proxy preserves cookies correctly
- browser devtools show the session cookie being set

### Project access starts failing after login

Check:

- the GitLab OAuth application includes `read_api`
- `/sessions` shows whether the current session has a refresh token
- GitLab refresh token exchange is reachable from the backend container

### Emergency login is not visible

Check:

- `AUTH_BREAK_GLASS_ENABLED=true`
- `AUTH_BREAK_GLASS_USERNAME` is non-empty
- `AUTH_BREAK_GLASS_PASSWORD_HASH` is non-empty
- backend was rebuilt and restarted after env changes

### Emergency login fails

Check:

- the username exactly matches `AUTH_BREAK_GLASS_USERNAME`
- the password hash format is valid
- the deployment really loaded the latest environment values
- the break-glass username does not collide with an existing normal dashboard username

### You get login success but no admin access

Check:

- GitLab username spelling in `AUTH_ADMIN_USERNAMES`
- whether your GitLab OIDC response actually contains group info
- local user record in the `users` table

## 11. Safe rollout suggestion

Recommended order:

1. Deploy auth code with `OIDC_ENABLED=false`
2. Verify existing dashboard behavior is unchanged
3. Fill in all OIDC env vars
4. Enable `OIDC_ENABLED=true`
5. Rebuild and restart services
6. Test login with one admin account first
7. Re-login once after enabling OIDC so new sessions are created with the current auth settings

This avoids locking yourself out during the first rollout.
