# qhhoj endpoint reference

Base `SITE = https://<domain>`. All POSTs need `csrfmiddlewaretoken` (see
SKILL.md mechanics) + session cookies + `Referer` header. Success = 302;
failure = 200 with errorlist (unless noted otherwise).

Legend: **[V]** = live-verified, **[C]** = from code (structure verified,
full behavior needs infra not present in verification env).

## Authentication

| What | Method & path | Fields / notes |
|---|---|---|
| Login form | `GET /accounts/login/` | Parse CSRF (both quote styles). **[V]** |
| Login | `POST /accounts/login/` | `username`, `password`, `next=/` → 302 `/`. **[V]** |
| 2FA | `POST /2fa/` | `totp_or_scratch_code` = 6-digit TOTP (`pyotp.TOTP(secret).now()`) or a scratch code. Session flag `2fa_passed` set. **[V]** |
| Password change (forced) | `POST /password/change/` | `old_password`, `new_password1`, `new_password2`. Forced when password is in breach lists. **[V]** |
| Logout | `GET/POST /logout/` | n/a |
| Register | `POST /accounts/register/` | `username` (`^\w+$`, ≤30), `full_name`?, `email` (unique, no throwaway domains), `password1`, `password2`, `timezone`, `language` (Language pk), `organizations`?, optional newsletter/captcha. Activation email → `GET /accounts/activate/<key>/` (skip if `SEND_ACTIVATION_EMAIL=False`). **[C]** |
| Session probe | `GET /edit/profile/` | 200 = authenticated; 302 login = not. **[V]** |

## Read API (`/api/v2`, only if `VNOJ_ENABLE_API=True` — probe with
`GET /api/v2/contests`; 404 = disabled → fall back to HTML pages)

Envelope: `{"api_version": "2.0", "method": "get", "fetched": "...", "data":
{...}}`; errors: `{"error": {"code": <http>, "message": ...}}` with matching
HTTP status (403 login required / permission, 404 not found, 400 bad filter).

| Endpoint | Returns / filters |
|---|---|
| `GET /api/v2/contests` **[V]** | Visible contests; filters `key`, `tag`, `organization`, `is_rated`; `?page=N` |
| `GET /api/v2/contest/<key>` **[V]** | Detail incl. `problems` [{code,name,points,partial,max_submissions,label}] (only when contest ended / in contest / editor) and `rankings` (permission-gated) |
| `GET /api/v2/problems` **[V]** | Visible problems; filters `code`, `group`, `type`, `organization`, `partial`, `search` (FTS) |
| `GET /api/v2/problem/<code>` | Detail (partial → fields on group/types/points) |
| `GET /api/v2/users` / `user/<username>` | Public profiles (solved counts, rating, organizations) |
| `GET /api/v2/submissions` **[V]** | Public submissions; filters `user`, `problem`, `result`, `language` |
| `GET /api/v2/submission/<id>` | Detail — **requires login** (403 otherwise) |
| `GET /api/v2/participations` | Contest participations; filters `contest` (key), `user`, `is_disqualified`, `virtual_participation_number`; scoreboard permission-gated |
| `GET /api/v2/organizations` / `languages` / `judges` | Lists (languages: pk ↔ key ↔ name) |

Page size: `DMOJ_API_PAGE_SIZE` (default 1000); `data.has_more` /
`data.page_index` for pagination.

## Select2 PK lookups (auth needed) **[V]**

`GET /judge-select2/<kind>/?term=<text>` where kind ∈ `problem`, `contest`,
`profile`, `organization`, `tag`, `taggroup`, `comment` →
`{"results": [{"id": <pk>, "text": <label>}]}`. Only *visible* objects are
searchable.

## Problems

### Create **[V]**
`POST /problems/create` (perm `judge.add_problem`) — multipart if attaching files.

| Field | Value |
|---|---|
| `code` | `^[a-z0-9_]+$`, unique |
| `name` | display name |
| `time_limit` | seconds (float); > site limit (default 5s) needs `judge.high_problem_timelimit` |
| `memory_limit` | KB, default 262144 |
| `points` | int (800–3500 suggested) |
| `partial` | checkbox `on` = partial scoring |
| `group` | ProblemGroup pk — parse options from the GET page (skip the empty first option) |
| `types` | list of ProblemType pks (first non-empty option works) |
| `source` | free text / origin URL |
| `description` | Markdown (MathJax `$…$` OK) |
| `statement_file` | file, PDF statement (perm `judge.upload_file_statement`) |
| `problem_material_file` | file, materials for contestants (perm `judge.upload_problem_material`) |
| `submission_source_visibility_mode` | `F` follow / `A` always / `S` solved |
| `testcase_visibility_mode` | `A` author-only default / others |

Notes: creator becomes **curator**. Global (non-org) create has **no**
`is_public` field — the problem starts private; publishing global problems is
a staff/admin action. Org variant: `POST /organization/<slug>/problem-create`
(perm `judge.create_organization_problem`), adds `is_public` checkbox
("public to org members"), code must start `<orgslug>_`.

### Edit **[V]**
`POST /problem/<code>/edit` — same fields (incl. `statement_file` PDF,
`problem_material_file`), plus **always** send both inline formset management
forms: `language_limits-TOTAL_FORMS/INITIAL_FORMS/MIN_NUM_FORMS/MAX_NUM_FORMS`
and `solution-TOTAL_FORMS/…`. Omitting them fails with
`(Hidden field TOTAL_FORMS) This field is required.`

Verified semantics for the two formsets:

| Intent | `solution-*` (editorial) | `language_limits-*` (per-language TL/ML) |
|---|---|---|
| Leave existing rows untouched | `TOTAL_FORMS=0`, `INITIAL_FORMS=0` | same |
| Create row (none exists yet) | `TOTAL=1/INITIAL=0`, no id | same |
| Update existing row | echo `solution-0-id` (parse from GET) with `INITIAL_FORMS=1`; re-posting as new → *"Solution with this Associated problem already exists."* | echo `language_limits-<i>-id`; re-posting → *"Language-specific resource limit with this Problem and Language already exists."* |
| Delete row | id + `solution-0-DELETE=on` | id + `language_limits-<i>-DELETE=on` |

`solution-0-*` fields **[V]**: `is_public` (checkbox), `publish_on`
(`YYYY-MM-DD`), `authors` (profile PKs — resolve via
`/judge-select2/profile/?term=<user>`), `content` (Markdown).
`language_limits-<i>-*` fields **[V]**: `language` (Language pk), `time_limit`
(**seconds**, float), `memory_limit` (KB).

### Test data **[V]**
`GET /problem/<code>/test_data` (author/curator/superuser) then
`POST` multipart:

| Field | Value |
|---|---|
| `problem-data-zipfile` | zip file (`1.in`, `1.ans`, … at any depth; checker/grader sources allowed) |
| `problem-data-grader` | **required**: `standard` / `interactive` / `signature` / `output_only` |
| `problem-data-checker` | `standard` / `floats` / `floatsabs` / `floatsrel` / `identical` / `bridged` (custom) |
| `problem-data-checker_type` | checker dialect: `default` (DMOJ) / `testlib` / `themis` / `cms` / `coci` / `peg` |
| `problem-data-custom_checker` | file, checker source (when `bridged`) |
| `problem-data-custom_grader`, `problem-data-custom_header`, `problem-data-grader_args` | grader files / JSON args |
| `problem-data-io_method` | `standard` / `file` (+ `io_input_file`, `io_output_file` names) |
| `problem-data-output_limit` | int, blank = default |
| `mirror-test_source` | `local` (uploaded zip) — keep this on plain uploads |
| `external-enabled` | leave empty (Virtual Judge off) |
| `cases-TOTAL_FORMS/-INITIAL_FORMS/-MIN_NUM_FORMS/-MAX_NUM_FORMS` | management form |
| `cases-<i>-id` | existing case pk — **echo when modifying** (parse from GET page) |
| `cases-<i>-order`, `-type` (`C` normal), `-input_file`, `-output_file`, `-points` | case row; file paths are **inside the zip** |
| `cases-<i>-DELETE` | `on` removes an existing (id-carrying) row |

**Traps (all verified):**
1. Never send any `problem-data-zipfile-clear` key — its *presence* (even
   empty) discards the uploaded zip ("Input file for case 1 does not exist").
2. First upload: `INITIAL_FORMS=0`, no ids. Later edits: parse
   `TOTAL_FORMS/INITIAL_FORMS/ids` from the GET page and echo them.
3. > `VNOJ_TESTCASE_HARD_LIMIT` (300) cases needs `judge.create_mass_testcases`;
   > soft limit 50 shows a warning only.
4. Success 302s back to the same page. Generated `init.yml`:
   `GET /problem/<code>/test_data/init`; raw files: `GET /problem/<code>/data/<path>`.

### Polygon import **[V]** (verified end-to-end with a real package)
`POST /problems/import-polygon` (perm `judge.import_polygon_package`) —
easiest full upload: `code`, `package` (zip of a Codeforces Polygon export),
checkboxes `ignore_zero_point_batches`, `ignore_zero_point_cases`,
`append_main_solution_to_tutorial` (default on), `main_tutorial_language`,
hidden `do_update`. **Plus the `statements` formset management form — required
even when empty** (`statements-TOTAL_FORMS/INITIAL_FORMS/MIN_NUM_FORMS/
MAX_NUM_FORMS` = `0/0/0/1000`); without it: `(Hidden field TOTAL_FORMS) This
field is required.` Update an existing problem:
`POST /problem/<code>/update-polygon` (same fields; code fixed).

Minimal package structure accepted (verified):

```
problem.xml            # <testset name="tests"> with time-limit (ms),
                       #   memory-limit (bytes), input-path-pattern/answer-path-pattern
                       #   (e.g. tests/%d.in, tests/%d.ans), <tests>, optional <groups>
                       #   (points-policy each-test|complete-group),
                       #   <checker type="testlib" name="std::hcmp.cpp"/> (std names
                       #   map to built-ins: hcmp/ncmp/wcmp=standard, rcmp4/6/9=floats,
                       #   fcmp=identical; anything else = custom checker source),
                       #   <statement type="application/x-tex" path=… language=…>,
                       #   <solutions><solution tag="main"><source …/></solution>
tests/1.in, tests/1.ans, …
statements/<lang>/problem-properties.json   # legend/input/output/interaction/
                       #   scoring/sampleTests/notes/tutorial
solutions/main.py
```

Server needs **pandoc ≥ 3.0** (else `pandoc not installed` /
`pandoc version must be at least 3.0.0`). Import auto-creates statement,
tests (converted limits), tutorial/editorial, main solution appended as a
spoiler block.

### Images in Markdown **[V]** (broken on current master)
`POST /widgets/martor/upload-image`, multipart field `markdown-image-upload`,
header `X-Requested-With: XMLHttpRequest`, CSRF token taken from any other
page (this endpoint has no GET form). **Crashes with HTTP 500 on current
master** — the view calls `request.is_ajax()`, removed in Django 5.1. Works
only on deployments that patched it. Fallback: host images elsewhere and use
plain `![alt](https://…)` links in `description`/`content` Markdown.
Permission when it works: staff or `judge.can_upload_image` (else it proxies
to Imgur).

### Other problem ops
| Op | Call | Perm / note |
|---|---|---|
| Clone | `POST /problem/<code>/clone` `code=<new>` **[V]** | `judge.clone_problem`; copies data, sets private |
| View YAML | `GET /problem/<code>/test_data/init` **[V]** | author/curator |
| Rejudge | `POST /problem/<code>/manage/submission/rejudge` with `use_range=on&start=&end=`, `language` (multi), `result` (multi) **[C]** | `judge.rejudge_submission_lot` |
| Rejudge preview | `POST …/rejudge/preview` (same fields) → count **[C]** | |
| Rescore all | `GET/POST …/rescore/all` **[C]** | author/curator |

## Contests

### Create **[V]**
`POST /contests/new` (perm `judge.add_contest`):

| Field | Value |
|---|---|
| `key` | `^[a-z0-9_]+$`, unique |
| `name` | display name |
| `start_time`, `end_time` | `%Y-%m-%d %H:%M:%S` |
| `is_visible` | checkbox — unchecked = hidden (draft) |
| `format_name` | `default` / `icpc` / `ioi` / `ioi16` / `atcoder` / `ecoo` / `vnoj` / `final_submission` / `Ultimate` (parse live options) |
| `scoreboard_visibility` | `V` visible / `C` contest only / `P` after participation / `H` hidden |
| `description` | Markdown |
| `is_private`, `private_contestants` | private + user list (PKs via select2 `profile`) |
| `auto_judge` | checkbox (Final-Submission-Only format) |
| `contest_problems-TOTAL_FORMS/-INITIAL_FORMS/-MIN_NUM_FORMS/-MAX_NUM_FORMS` | management form |
| `contest_problems-<i>-problem` / `-points` / `-order` / `-max_submissions` | problem **PK** (select2), points, distinct order, blank = unlimited |

Duration cap: 14 days unless `judge.long_contest_duration` (verified error:
"Contest duration cannot be longer than 14 days"). Creator becomes **author**.

### Edit **[V]**
`POST /contest/<key>/edit` (author/curator) — same fields. Problem-list
reconciliation rules (verified):
- Existing rows must be echoed with `contest_problems-<i>-id` (from GET page).
- Removing without echoing the id → *"Contest problem with this Problem and
  Contest already exists."*
- Delete a row: echo `id` + `contest_problems-<i>-DELETE=on`.
- Add rows: empty id, next indices; orders must stay distinct.

### Other contest ops
| Op | Call | Note |
|---|---|---|
| Announce | `POST /contest/<key>/announce` `title`, `description` (Markdown) **[V]** | author/curator; notifies participants |
| Register | `POST /contest/<key>/register` (empty body; `access_code` if set) **[C]** | before `register_deadline` |
| Join | `POST /contest/<key>/join` (empty body; `access_code` if set) **[V]** | during contest; after end → virtual join |
| Leave | `POST /contest/<key>/leave` **[C]** | |
| Clone | `POST /contest/<key>/clone` `key=<new>` **[C]** | `judge.clone_contest` |
| Ranking | `GET /contest/<key>/ranking/` HTML (or API detail `rankings`) | |
| Disqualify | `POST /contest/<key>/participation/disqualify` **[C]** | organizer tools |

## Submissions

| Op | Call | Note |
|---|---|---|
| Language list | `GET /problem/<code>/submit` → `<select id="id_language" name="language">` options = `<pk>`/`<name>` **[V]** | Options = problem's `usable_languages` (allowed ∩ judges online). No select rendered = "No judge is available" — cannot submit |
| Submit | `POST /problem/<code>/submit` `language=<pk>` `source=<code>` **[V]** | or `submission_file` (file upload; extension must match language) + empty `source`. Redirects to `/submission/<id>` |
| Status | `GET /submission/<id>` HTML; JSON via `/api/v2/submission/<id>` (login required) **[V]** | result codes: `AC` `WA` `TLE` `MLE` `RE` `CE` `IE` …; poll until not `QU`/`P` |
| Status row fragment | `GET /widgets/single_submission?id=<id>&show_problem=1` **[V]** (path) | HTML row incl. verdict; works when API off; also `GET /widgets/submission_testcases?id=<id>` for case results |

Rate limits: per-problem submission throttling applies between submissions —
retry on the throttle page/`ignore` message.

## Pages worth scraping (API-less fallbacks)

- `GET /problems/` (+ `?search=`, page params) — problem list HTML.
- `GET /contests/` — contest list; `GET /contests.ics` — calendar export.
- `GET /submissions/` (+ filters) — public submission feed.
- `GET /user/<username>` — profile (rating history JSON embedded).

## Django admin (staff/superuser only) **[C]**

`/admin/` exposes full CRUD over every model (problems, contests, users,
organizations, judges…). Login flow is the same. Useful for toggles with no
front-end form (e.g. `is_public` of global problems, contest access codes,
banning users). Prefer front-end endpoints where they exist — admin forms
have their own large field sets (out of scope here).

## Organizations (private group content) **[V]**

Access rule (`AdminOrganizationMixin`): the account must be an **admin of the
org** (`org.is_admin(profile)`) or hold `judge.edit_all_organization`. Org
admins are granted capabilities through the Django group **`Org Admin`**
(setting `GROUP_PERMISSION_FOR_ORG_ADMIN`) — the site adds every org admin to
that group whenever the org is saved.

| Op | Call | Notes |
|---|---|---|
| Org problem create | `POST /organization/<slug>/problem-create` | same fields as global create + `is_public` (visible to org members); `code` must start `<orgslug>_`; problem auto org-private, author = you; perm `judge.create_organization_problem` |
| Org Polygon import | `POST /organization/<slug>/import-polygon` | same fields (incl. `statements-*` mgmt); problem auto org-private; perm `judge.import_polygon_package` |
| Org contest create | `POST /organization/<slug>/contest-create` | same fields as contest create; `key` must start `<orgslug>_`; contest auto org-private; perm **`judge.create_private_contest`** (not `create_organization_contest`!) |
| Org blog post | `POST /organization/<slug>/post/new` **[C]** | `title`, `publish_on`, `visible`, `content`; perm `judge.edit_organization_post` |
| Org listings | `GET /organization/<slug>/problems`, `/contests`, `/submissions` | org-scoped lists |
| Discover orgs | `GET /api/v2/organizations`, `/judge-select2/organization/?term=` | then probe `GET /organization/<slug>/problem-create` (200 = you may create) |

Verified probe results as org admin with the `Org Admin` group: all three
create endpoints answer 200; creating yields `is_organization_private: true`
via `/api/v2/problem/<code>`.
