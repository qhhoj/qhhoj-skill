---
name: qhhoj
description: "Operates a qhhoj/online-judge site (VNOJ-family fork of DMOJ, Django) over HTTP given only a site URL and an account: logs in (TOTP 2FA, or stateless Bearer-token mode that bypasses CSRF), creates/edits/clones problems with PDF statements, materials, editorials and per-language limits, uploads test data zips, imports Codeforces Polygon packages, creates/edits contests with problems, posts announcements, registers/joins contests, submits code and polls per-case verdicts, rejudges/aborts, comments, votes, writes blog posts, opens tickets, tags problems from external judges, uploads into private organizations the account administers, and reads everything via /api/v2. Use when asked to create a contest, upload or fix a problem, submit code, or manage any DMOJ/VNOJ-style online judge site (qhhoj, VNOJ, DMOJ) with credentials."
license: AGPL-3.0
compatibility: "Requires Python 3 with requests (pyotp optional for TOTP 2FA) and network access to the online judge site"
metadata:
  author: qhhoj-skill
  version: "1.3.0"
  argument-hint: "<site_url> <action>"
---

# qhhoj — Online Judge site automation

Drive a **qhhoj/online-judge** deployment (VNOJ-family fork of DMOJ:
`https://github.com/qhhoj/online-judge`) with plain HTTP. Given only
`SITE_URL` + account credentials, this skill performs every operation the
account is allowed to do: problem authoring, test data upload, contest
management, submissions, and read access via the JSON API.

Everything is **session-cookie + CSRF-token form POSTs** — no browser/JS
needed. All field names below were extracted from the code and re-verified
against a live instance (see *Provenance*).

## When to activate

- "Tạo contest / tạo bài / nộp bài / upload test lên <site>" where site runs
  qhhoj/online-judge (check: footer links to `github.com/qhhoj/online-judge`,
  or `/accounts/login/` renders the DMOJ login page).
- Automating any VNOJ-style DMOJ fork — mechanics are identical; endpoint
  differences are called out inline.

## Prerequisites

- Python 3 with `requests` (`pip install requests`); `pyotp` only for TOTP 2FA.
- Credentials: username + password (optionally TOTP secret or a scratch code).

## Quick start

```python
import sys; sys.path.insert(0, '<skill_dir>/scripts')
from qhhoj_client import QhhojClient

c = QhhojClient('https://oj.example.com', 'user', 'pass')   # totp_secret='JBSW...' if 2FA
c.login()                                                     # raises QhhojError with reason

c.create_problem(code='demo_aplusb', name='A + B', description='Compute $A+B$.')
c.upload_testdata('demo_aplusb', zip_path='tests.zip',
                  cases=[('1.in', '1.ans', 50), ('2.in', '2.ans', 50)])
pk = c.select2_problem('demo_aplusb')['id']
c.create_contest(key='demo_contest', name='Demo Contest', problems=[(pk, 100)])
c.announce('demo_contest', 'Round started', 'Good luck!')
sid = c.submit('demo_aplusb', 'print(int(input()) + int(input()))')
```

CLI probe (`python scripts/qhhoj_client.py <url> <user> <pass> [--totp S]`)
logs in and reports whether `/api/v2` is enabled plus visible contests.

## Core mechanics (read once)

1. **CSRF**: `GET <page>` → regex `name=['"]csrfmiddlewaretoken['"] value=['"]([^'"]+)['"]`
   (tokens are single- **or** double-quoted) → include as form field
   `csrfmiddlewaretoken` on POST, send session cookies, set `Referer: <page url>`.
2. **Success signal**: Django form views answer **302** on success and re-render
   **200** with `<ul class="errorlist">` on failure. Parse that list for reasons.
   Never follow redirects when checking (requests: `allow_redirects=False`).
3. **Login**: `POST /accounts/login/` (`username`, `password`, `next=/`).
   - TOTP-enabled accounts: any page then 302s to `/2fa/?next=…`; answer
     `POST /2fa/` with `totp_or_scratch_code` (6-digit TOTP or scratch code).
   - Pwned passwords force a `password_pwned` loop: every request redirects to
     `/password/change/` until `POST /password/change/` (`old_password`,
     `new_password1`, `new_password2`) succeeds. Choose non-breached passwords.
   - Verify session: `GET /edit/profile/` → 200.
4. **Foreign keys in formsets are numeric PKs**, not codes. Resolve codes → PK
   with select2: `GET /judge-select2/problem/?term=<code>` →
   `{"results": [{"id": <pk>, "text": <name>}]}` (same for `contest`,
   `profile`, `organization`).
5. **Permissions are try-and-see**: the site has no "list my permissions"
   endpoint. `PermissionRequiredMixin` views render a 403 page ("You are not
   allowed…"), login-required redirects to `/accounts/login/?next=…`.
   `references/permissions.md` maps action → required permission codename and
   per-role numeric limits.

## Deep references

| File | Contents |
|---|---|
| `references/endpoints.md` | Every endpoint: method, path, exact form fields, options, units, gotchas |
| `references/workflows.md` | Step-by-step recipes (problem → data → contest → announce → submit → rejudge; org variants; API reading) |
| `references/permissions.md` | Permission codenames, limits, troubleshooting matrix |
| `scripts/qhhoj_client.py` | Reusable client implementing all of the above |

## Field units & identifier rules (memorize)

- `time_limit`: **seconds** (float). `memory_limit`: **KB** (`262144` = 256 MB).
- `points`: problem 800–3500 suggested; contest problem points free integer.
- Problem `code` / contest `key`: `^[a-z0-9_]+$`. Organization-scoped ones must
  start with the org slug prefix (`<slug>_`).
- Datetimes: `%Y-%m-%d %H:%M:%S` (site timezone interpretation).

## Provenance

Live-verified on a from-source deployment of qhhoj/online-judge@master
(Django 5.1, MariaDB): login, 2FA, pwned-password loop, problem create/edit/
clone, zip test-data upload (incl. the `zipfile-clear` trap and case-formset
echoing), contest create/edit (row reconciliation + DELETE), announce, join,
submit, select2 lookups, `/api/v2` list/detail incl. pagination. From-code
(behind features not exercisable without extra infrastructure, marked in the
references): Polygon import parsing, rejudge/rescore POST bodies, registration
flow, external/VJudge problems.

## Security

- Credentials and session cookies stay in memory of the running script; never
  log them. Prefer env vars over argv for passwords.
- Only operate sites/accounts you are authorized to; contest manipulation
  during live contests affects real participants.
