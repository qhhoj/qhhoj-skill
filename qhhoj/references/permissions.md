# qhhoj permissions, limits & troubleshooting

## How permissions work

Django per-object + role model. Three tiers:

1. **Global permissions** (auth groups / superuser) — codenames below.
2. **Object roles** — problem *curators*/authors (`is_editable_by`),
   contest *authors*/curators; set automatically on create.
3. **Organization roles** — org admins manage org content.

Enforcement: `PermissionRequiredMixin` (403 page), `LoginRequiredMixin`
(302 → login), or object checks (`is_editable_by` → 403/redirect).

## Action → permission map

| Action | Required |
|---|---|
| `POST /problems/create` | `judge.add_problem` |
| Suggest problem (`/problems/suggest`) | `judge.suggest_new_problem` |
| `POST /problems/import-polygon` & `/problem/<c>/update-polygon` | `judge.import_polygon_package` |
| Clone problem | `judge.clone_problem` |
| Clone contest | `judge.clone_contest` |
| Edit problem/test data | curator of problem (auto on create) or staff |
| `POST /contests/new` | `judge.add_contest` |
| Edit contest / announce | author/curator of contest (auto on create) |
| Rejudge lots | `judge.rejudge_submission_lot` |
| See private problems/contests | `judge.see_private_problem` / `judge.see_private_contest` |
| Edit all problems / contests | `judge.edit_all_problem` / `judge.edit_all_contest` |
| Org problem create (`/organization/<s>/problem-create`) | org admin + `judge.create_organization_problem` |
| Org Polygon import (`/organization/<s>/import-polygon`) | org admin + `judge.import_polygon_package` |
| Org contest create (`/organization/<s>/contest-create`) | org admin + **`judge.create_private_contest`** (not `create_organization_contest`) |
| Org blog post | org admin + `judge.edit_organization_post` |
| Upload PDF statement / materials | `judge.upload_file_statement` / `judge.upload_problem_material` |
| Markdown image upload | staff or `judge.can_upload_image` (endpoint broken on master — see endpoints.md) |
| Edit any organization | `judge.edit_all_organization` |
| Spam-rejudge submission | `judge.rejudge_submission` |
| Abort others' submissions | `judge.abort_any_submission` (own queued ones always) |
| Create tag problems | `profile.allow_tagging` + (`judge.add_tagproblem` or rating ≥ `VNOJ_TAG_PROBLEM_MIN_RATING` = 1900) |
| Global/pinned blog posts | `judge.mark_global_post` / `judge.pin_post` |
| Ban users | `judge.ban_user` (never superusers) |
| Edit any comment / hide | `judge.change_comment` |

Superuser implicitly holds everything. Typical site roles: "Problem Setter"
group gets add/edit-own problem perms; "Contest Organizer" gets add/edit-own
contest perms; **org admins are auto-added to the `Org Admin` group** (site
does this when the org is saved) which is where their create permissions come
from.

## Numeric limits (defaults; per-site overridable)

| Limit | Value | Bypass permission |
|---|---|---|
| Problem time limit | 5 s | `judge.high_problem_timelimit` |
| Contest duration | 14 days | `judge.long_contest_duration` |
| Test cases per problem | 300 hard / 50 warn | `judge.create_mass_testcases` |
| PDF statement size | `PDF_STATEMENT_MAX_FILE_SIZE` | — |
| Problem points | suggested 800–3500 | — |
| Submission source | 64 KB (`source` field) | use file upload |

Verified error texts (safe to match): "Contest duration cannot be longer than
14 days", "Input file for case 1 does not exist", "(Hidden field TOTAL_FORMS)
This field is required.", "Contest problem with this Problem and Contest
already exists.", "Solution with this Associated problem already exists.",
"Language-specific resource limit with this Problem and Language already
exists.", "pandoc version must be at least 3.0.0", "You need to have solved
at least 5 problems before your voice can be heard.", "You cannot vote your
own blog", "You cannot vote twice.", "You are not allowed to tag problem.",
"Your part is silent, little toad." (banned/muted).

## Troubleshooting matrix

| Symptom | Cause | Fix |
|---|---|---|
| Every request 302 → `/accounts/login/?next=…` | not authenticated (CSRF failure also re-renders login) | redo login; ensure `csrfmiddlewaretoken` + cookies + `Referer` on POST |
| Every page 302 → `/password/change/` | password in breach list (`password_pwned`) | complete a password change, re-login |
| Redirected to `/2fa/` | TOTP/WebAuthn enabled | supply TOTP secret (or scratch code) — client does this automatically |
| 403 "You are not allowed…" | missing permission | different account / request role; check map above |
| Form 200 with `(Hidden field TOTAL_FORMS) This field is required.` | missing formset management form | problem edit needs `language_limits-*` **and** `solution-*`; data page needs `cases-*`; contest needs `contest_problems-*` |
| "Input file for case N does not exist" | zip discarded (`…-clear` key present) or wrong inner path | never send `problem-data-zipfile-clear`; use paths exactly as in the zip |
| "Contest problem … already exists" | edit dropped row ids | echo `contest_problems-<i>-id`, use `-DELETE=on` for removals |
| No `<select id="id_language">` on submit page | no judge online serving the problem | wait for a judge; site-side admins must connect judge servers |
| Submission stuck `QU`/`P` | judge queue busy/offline | poll longer; check `GET /api/v2/judges` |
| "Solution/Language-specific … already exists" | re-posted an existing editorial/lang-limit row as new | echo the row's `id` with correct `INITIAL_FORMS`, or send `TOTAL_FORMS=0` to leave untouched |
| Org create page 403 | not an admin of that org (or missing `Org Admin` group perms) | org admin must add you; superusers bypass |
| Polygon import 500 / `pandoc not installed` | server lacks pandoc ≥ 3.0 | site-side: `apt install pandoc`; use manual upload path meanwhile |
| Image upload 500 (`is_ajax` AttributeError) | known bug on current master (Django 5.1) | host images externally; embed via Markdown URL |
| API returns 404 | `VNOJ_ENABLE_API=False` | use HTML fallbacks (workflows §9) |
| Select2 finds nothing for a code | problem not visible to you (private/organization) | different account, or get added as tester/curator |

## Operational cautions

- Contests are live systems: changing problems/scoring mid-contest affects
  participants; prefer clone-then-edit for reruns.
- `rejudge`/`rescore` requeue every matching submission — load spike on judges.
- Uploading a new zip replaces the old archive; keep tests versioned locally.
- The account password is used by automation — prefer a dedicated setter
  account with only the roles it needs.
