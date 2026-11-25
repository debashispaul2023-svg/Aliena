---
description: "Pre-launch check catalog and area map. Read during the code pass."
---

# Checks

Skip areas that do not apply and say so in one line.

| Area | Website | Web app | Mobile | API |
|------|---------|---------|--------|-----|
| 1 Secrets | YES | YES | YES | YES |
| 2 Login | NO | YES | YES | YES |
| 3 Access | PARTLY | YES | YES | YES |
| 4 Database | PARTLY | YES | YES | YES |
| 5 Input | PARTLY | YES | YES | YES |
| 6 API abuse | PARTLY | YES | YES | YES |
| 7 Payments | PARTLY | PARTLY | PARTLY | PARTLY |
| 8 AI | PARTLY | PARTLY | PARTLY | PARTLY |
| 9 Dependencies | YES | YES | YES | YES |
| 10 Deploy | YES | YES | PARTLY | YES |
| 11 Cost | PARTLY | YES | YES | YES |
| 12 Privacy | YES | YES | YES | PARTLY |
| 13 Mobile | NO | NO | YES | NO |

## 1 Secrets

1.1 No secret keys in frontend or app bundles.
1.2 No secrets in git history. Deleting is not enough; revoke and replace.
1.3 Secrets come from environment variables, never hardcoded.
1.4 No secrets in logs, errors, or analytics.

## 2 Login

2.1 Private routes verify the session on the server.
2.2 Passwords hashed with bcrypt or argon2. No default admin in code.
2.3 Reset links expire, work once, and do not reveal registered emails.
2.4 Rate limits on login, signup, OTP, and reset.
2.5 Tokens are signature-verified, expire, and reject `none`. Cookies are HttpOnly, Secure, SameSite.
2.6 Tokens not in localStorage. Flag Medium. Do not move storage as a fix.
2.7 OAuth redirects are an exact allowlist.

## 3 Access

3.1 Every read/update/delete filters by the logged-in user.
3.2 Request bodies cannot set role, is_admin, plan, credits, or balance.
3.3 Admin checks are server-side.
3.4 Paid limits are enforced on the server.
3.5 Team queries are scoped.
3.6 No public debug or test routes in production.

## 4 Database

4.1 User input never becomes a raw query. Parameterize SQL. Validate types.
4.2 Public IDs are random. Low if 3.1 passes.
4.3 Files are private, served by signed URLs.
4.4 Database is not open to the internet. CAN'T VERIFY if managed.
4.5 Supabase/Firebase: RLS on, no test-mode open rules, service key server-only.

## 5 Input

5.1 Server validates types, lengths, and allowed values.
5.2 No raw HTML from user content.
5.3 Uploads have type and size limits, are renamed, and are never executed.
5.4 User URLs allow only http(s) and reject private addresses.
5.5 Redirect parameters stay on the app's own paths.
5.6 Errors are generic. Multi-step actions roll back.

## 6 API abuse

6.1 Shared rate limits on login, forms, AI, and uploads.
6.2 CORS is an exact origin list. Never `*` with credentials.
6.3 Public forms have bot protection.
6.4 Responses omit secrets and paginate.
6.5 Cookie logins have CSRF protection.
6.6 Webhooks verify signatures and process each event once.

## 7 Payments

7.1 Server looks up the price. Client amount is never trusted.
7.2 Access follows a verified webhook or server payment check.
7.3 Renewals, refunds, and disputes update access.
7.4 Live secret keys stay on the server.
7.5 Credits change in one atomic update.
7.6 Price, renewal, and cancel are visible.

## 8 AI

8.1 Per-user quotas, input size, output tokens, and timeouts.
8.2 Untrusted content cannot trigger tools or reveal data.
8.3 Model output is escaped and never executed.
8.4 System prompts contain no secrets.
8.5 Memory and RAG are isolated per user.

## 9 Dependencies

9.1 Report Critical and High from audit tools. No forced major upgrades.
9.2 Versions are pinned.
9.3 Scan borrowed files for hidden agent instructions.
9.4 Third-party scripts come from official sources.

## 10 Deploy

10.1 Report missing security headers. Do not add CSP as a fix.
10.2 Debug mode is off.
10.3 API docs are off or admin-only in production.
10.4 Sensitive files are not served.
10.5 Failed logins, admin actions, and payments are logged without secrets.

## 11 Cost

11.1 Polling pauses when the screen is hidden.
11.2 No unbounded retries or scheduled AI jobs.
11.3 List unused v1/v2 copies. Remove only after confirmation.

## 12 Privacy

12.1 Privacy policy and terms are linked.
12.2 Tracking waits for consent where required.
12.3 Account deletion removes data.

## 13 Mobile

13.1 Tokens use secure storage.
13.2 HTTPS only.
13.3 Deep links validate parameters.
13.4 WebViews load only trusted URLs.
13.5 Permissions are minimal.
13.6 In-app account deletion exists.
13.7 Release build has no debug menus or private push data.
