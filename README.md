# qhhoj-skill

Agent skill for operating a **qhhoj/online-judge** site (DMOJ/VNOJ fork,
Django 5.1 — https://github.com/qhhoj/online-judge) with only a site domain
and an account: login (incl. TOTP 2FA), create/edit/clone problems, upload
test data, import Polygon packages, create/edit contests, announcements,
register/join, submit solutions, rejudge, and read data via `/api/v2`.

Follows the [Agent Skills spec](https://agentskills.io/specification):
skill directory `qhhoj/` (name matches directory) with `SKILL.md`
(frontmatter: `name`, `description`, `license`, `compatibility`, `metadata`),
`references/` and `scripts/`, progressive disclosure, body < 500 lines.

## Layout

```
qhhoj/
├── SKILL.md                    # entry point: mechanics, quick start
├── references/
│   ├── endpoints.md            # full endpoint reference (exact form fields)
│   ├── workflows.md            # step-by-step recipes
│   └── permissions.md          # permission map, limits, troubleshooting
└── scripts/
    └── qhhoj_client.py         # self-contained requests-based client
```

## Usage

```python
import sys; sys.path.insert(0, 'qhhoj/scripts')
from qhhoj_client import QhhojClient

c = QhhojClient('https://oj.example.com', 'user', 'pass', totp_secret=None)
c.login()
c.create_problem(code='demo', name='Demo', description='Compute $A+B$.')
c.upload_testdata('demo', zip_path='tests.zip',
                  cases=[('1.in', '1.ans', 100)])
pk = c.select2_problem('demo')['id']
c.create_contest(key='demo_cont', name='Demo Contest', problems=[(pk, 100)])
c.submit('demo', 'print(int(input())+int(input()))')
```

CLI probe: `python qhhoj/scripts/qhhoj_client.py <url> <user> <pass> [--totp SEC]`

## Install (this harness)

```bash
ln -s $(pwd)/qhhoj /root/.agent/skills/qhhoj
```

## Validation

Spec compliance via the official Agent Skills reference validator:

```bash
pip install skills-ref && agentskills validate qhhoj   # -> Valid skill
```

## Verification

All live-verified flows were exercised against a from-source deployment
(MariaDB + runserver) of upstream `master`; see `SKILL.md` § Provenance and
the `[V]` / `[C]` markers in `references/endpoints.md`.
