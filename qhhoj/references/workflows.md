# qhhoj workflow recipes

Each recipe lists the client call (`scripts/qhhoj_client.py`) and the raw HTTP
equivalent. Assume `c = QhhojClient(SITE, USER, PASS, totp_secret=…)` and
`c.login()` succeeded.

## 0. Connect & probe an unknown site

```python
c.login()                                  # raises on: bad creds, forced pw change, 2FA w/o secret
api = c.api('contests')                    # None => /api/v2 disabled on this deployment
print(c.logged_in(), 'api:', api is not None)
```

Raw: `GET /accounts/login/` (200 + DMOJ markup = right software), then
`POST /accounts/login/`, then `GET /edit/profile/` (200 = auth OK), then
`GET /api/v2/contests` (404 = API off).

2FA accounts: `QhhojClient(..., totp_secret='<base32>')` — the client detects
the `/2fa/` redirect and answers automatically. With only a scratch code,
`POST /2fa/` once with `totp_or_scratch_code=<code>` manually.

## 1. Capability discovery (what may this account do?)

No permission-list endpoint exists. Probe (cheap → expensive):

| Probe | 200/302 means |
|---|---|
| `GET /problems/create` | `judge.add_problem` (302→login = anonymous) |
| `GET /problems/import-polygon` | `judge.import_polygon_package` |
| `GET /contests/new` | `judge.add_contest` |
| `GET /problem/<code>/edit` for own/other problems | curator/author of it, or staff |
| `GET /contest/<key>/edit` | author/curator of it |
| `GET /organization/<slug>/problem-create` | org admin (`judge.create_organization_problem`) |
| `GET /admin/` | staff/superuser |

Permission-denied renders a friendly 403 page — distinguishable from 302
login redirect. Limits by permission: see `permissions.md`.

## 2. Full problem upload (statement + tests) — general path

```python
c.create_problem(code='voi25_ab', name='VOI25 - A cộng B',
                 time_limit_s=1.0, memory_limit_kb=262144, points=800,
                 partial=True, description='## Đề bài\nCompute $A + B$.\n\n## Input\n...\n')
c.make_zip({'1.in': '1 2\n', '1.ans': '3\n',
            '2.in': '4 5\n', '2.ans': '9\n'}, '/tmp/tests.zip')
c.upload_testdata('voi25_ab', zip_path='/tmp/tests.zip',
                  cases=[('1.in', '1.ans', 50), ('2.in', '2.ans', 50)])
```

Raw essentials for the data POST (multipart): `problem-data-zipfile`,
`problem-data-grader=standard`, `problem-data-checker=standard`,
`problem-data-checker_type=default`, `problem-data-io_method=standard`,
`mirror-test_source=local`, `external-enabled=` (empty),
`cases-TOTAL_FORMS=2`, `cases-INITIAL_FORMS=0`, `cases-MAX_NUM_FORMS=1000`,
and per case `cases-<i>-order/type=C/input_file/output_file/points`.
**Never** include `problem-data-zipfile-clear`.

Optional extras at create/edit time: `statement_file` (PDF), `problem_material_file`
(zip of materials) — both permission-gated.

### Custom checker
`problem-data-checker=bridged` + `problem-data-custom_checker` (the checker
source file, must be inside the zip or uploaded) + `problem-data-checker_type`
(dialect). Float checkers: `floats`/`floatsabs`/`floatsrel` with
`problem-data-checker_args` JSON, e.g. `{"precision": 6}`.

### Modify existing tests
`GET` the page first; echo `cases-<i>-id` for kept rows, add
`cases-<i>-DELETE=on` for removed ones, append new rows with empty id
(client's `upload_testdata` keeps existing rows and appends — call with only
new `cases`; extend it for deletions).

## 3. Upload from Codeforces Polygon package — one-shot path

```python
c.import_polygon('/tmp/problem.zip', code='cf_1234a')
```
Creates statement, tests, checker, solutions/tutorial automatically. For an
existing problem: `POST /problem/<code>/update-polygon` (client: reuse
`import_polygon` path swap). Requires Polygon package zip with `problem.xml`.

## 4. Clone a problem (reuse tests)

```python
c.clone_problem('old_prob', 'new_prob')   # perm judge.clone_problem
```

## 5. Create a contest with problems

```python
pks = [(c.select2_problem(code)['id'], 100) for code in ['voi25_ab', 'voi25_cd']]
c.create_contest(key='voi25', name='VOI 2025 — Day 1',
                 duration_days=1.5, problems=pks,
                 format_name='ioi', scoreboard_visibility='C',
                 description='Regulations…', visible=True)
```

Raw: fields per `endpoints.md`; remember duration ≤ 14 days, distinct
`order`, `problem` = PK.

## 6. Edit a running contest / swap its problems

```python
keep = c.select2_problem('voi25_ab')['id']
add  = c.select2_problem('voi25_cd')['id']
c.edit_contest('voi25', problems=[(keep, 100), (add, 100)])
```
Client performs row reconciliation (echo ids; DELETE dropped rows; append new).
Also `c.announce('voi25', 'Clarification', '<markdown>')`.

## 7. Register / join a contest as a participant

```python
c.join_contest('voi25')                 # POST /contest/voi25/join
c.join_contest('secret_contest', access_code='XYZ')   # access-code contests
```
Join works while ongoing; after `end_time` it creates a **virtual**
participation (unless `disallow_virtual`).

## 8. Submit solutions & poll verdict

```python
langs = c.languages('voi25_ab')            # [] => no judge online for it
sid = c.submit('voi25_ab', 'print(int(input())+int(input()))')
# or file: c.submit('voi25_ab', source='', file_path='sol.cpp', language_id=<id>)
import time
while True:
    d = c.api('submission/%d' % sid)       # needs login; None if API off
    st = d and d['object']['status']
    print(st)
    if st not in (None, 'QU', 'P', 'G'):   # queued/processing/grading
        break
    time.sleep(2)
```
API-less fallback: `GET /submission/<id>` HTML (status badge), or the row
fragment `GET /widgets/single_submission?id=<id>` returning the status table
row HTML (auth needed; works when `/api/v2` is disabled).

## 9. Read site data (problems/contests/users/rankings)

```python
for obj in c.api('problems', params={'search': 'voi'})['objects']: ...
detail = c.api('contest/voi25')['object']   # problems[] + rankings[] (if allowed)
```
If `c.api(...)` returns None (feature flag off), scrape the HTML list pages
(`/problems/`, `/contests/`, `/submissions/`, `/user/<name>/`).

## 10. Organization-scoped work (org-private content) **[V]**

Who can: **org admins** (auto-added to the `Org Admin` group carrying the
create permissions) or holders of `judge.edit_all_organization`.

```python
# discover orgs, then confirm create rights (200 = allowed, 403 = no)
for org in c.api('organizations')['objects']:
    r = c.get('/organization/%s/problem-create' % org['key'])  # slug
    if r.status_code == 200: print('can upload to', org['key'])

c.create_problem(code='myorg_p1', name='P1', org_slug='myorg',
                 statement_pdf='statement.pdf',   # PDF statement (perm-gated)
                 material='materials.zip',        # contestant materials
                 description='## Đề\n...')        # code auto-required prefix myorg_
c.import_polygon('polygon.zip', 'myorg_p2', org_slug='myorg')  # org-private, one shot
c.create_contest(key='myorg_cont', name='Cont', org_slug='myorg',
                 problems=[(c.select2_problem('myorg_p1')['id'], 100)])
```

Org content is born **org-private** (`is_organization_private=true`) even with
`is_public` on — "public" means visible to org members. Org listings:
`GET /organization/<slug>/problems|contests|submissions`.

Editorial (lời giải) and per-language limits on any problem you curate:

```python
c.edit_problem('myorg_p1',
               editorial={'content': '## Lời giải\n...'})         # creates/updates
c.edit_problem('myorg_p1', language_limits=[(cpp_pk, 3, 131072)])  # (lang, s, KB)
# omit both → existing rows untouched (TOTAL=0 semantics, verified)
```

Images inside statements: the built-in uploader
(`/widgets/martor/upload-image`) 500s on current master (Django 5.1 removed
`request.is_ajax()`), so host images externally and embed with
`![alt](https://…)`.

## 11. Rejudge / rescore after fixing tests (author tools) **[C]**

```
POST /problem/<code>/manage/submission/rejudge
    use_range=on&start=1&end=999&language=<pk>&result=AC   # any subset
POST /problem/<code>/manage/submission/rescore/all         # recompute points
```
Both spawn async tasks — follow `/tasks/status/<id>` (HTML autorefresh).

## 12. Register a new account **[C]**

`POST /accounts/register/` with `username, full_name?, email, password1,
password2, timezone, language` (+ org list, newsletter, captcha when
configured) → activation email if `SEND_ACTIVATION_EMAIL` →
`GET /accounts/activate/<key>/`. Then login as usual.

## 13. Stateless mode: Bearer token **[V]**

For long agent sessions prefer a token over session+CSRF juggling:

```python
c.login()
c.api_token()          # POST /accounts/api/token/generate/ (once)
# from now on every c.get()/c.post() sends Authorization: Bearer <token>;
# CSRF tokens and 2FA are bypassed by the site middleware
```

Notes: `/admin/` is unreachable with the header (site policy); invalid or
revoked tokens → 401 (re-login and regenerate). Votes/AJAX endpoints answer
HTTP 200 `success` (not 302).

## 14. Social: comments, blog, tickets, tags **[V]**

```python
c.comment('/problem/demoprob', 'Bài hay, cảm ơn tác giả!')   # POST the page itself
c.comment('/problem/demoprob', 'Phụ lục…', parent=<cid>)     # reply
c.vote_comment(cid); c.edit_comment(cid, 'Nội dung mới.')

loc = c.blog_post('Thông báo kỳ tập luyện', 'Nội dung **bài viết**.', global_post=True)
c.edit_blog_post(loc, 'Tiêu đề (sửa)', 'Nội dung mới.')
c.vote_blog(<post_id>)           # not your own post!

c.ticket('demoprob', 'Sai đề bài', 'Chi tiết…')               # feedback to authors

tags = c.tag_from_url('https://codeforces.com/problemset/problem/4/A')  # '/tag/CF_4_A'
c.assign_tags(tags, ['math', 'greedy'])
```

Gates (site-wide): commenting/voting needs ≥ 5 solved problems
(`VNOJ_INTERACT_MIN_PROBLEM_COUNT`); tagging needs `allow_tagging` on the
profile plus perm or rating ≥ 1900. Markdown can be dry-run with
`c.preview_markdown('…', 'problem')` before saving anywhere.

## 15. Inspecting & managing submissions **[V]**

```python
print(c.submission_source(sid))          # GET /src/<id>/raw
html = c.submission_testcases(sid)       # per-case verdicts
c.rejudge_submission(sid)                # needs judge.rejudge_submission
c.abort_submission(sid)                  # while queued/grading only
# verdicts without /api/v2:
#   GET /widgets/single_submission?id=<sid>   (status row HTML)
#   d = c.api('submission/%d' % sid)          (JSON, needs auth)
```
