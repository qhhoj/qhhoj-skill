#!/usr/bin/env python3
"""qhhoj (DMOJ/VNOJ fork) site client — session-based HTTP automation.

Self-contained: stdlib + `requests` (pyotp only for TOTP 2FA login).
Every field name and flow below was verified against a live deployment of
https://github.com/qhhoj/online-judge (Django 5.1).

Usage:
    from qhhoj_client import QhhojClient
    c = QhhojClient('https://oj.example.com', 'user', 'pass')  # or totp_secret='...'
    c.login()
    c.create_problem(code='demo_aplusb', name='A + B')
    c.upload_testdata('demo_aplusb', zip_path='tests.zip',
                      cases=[('1.in', '1.ans', 100), ('2.in', '2.ans', 100)])
    pk = c.select2_problem('demo_aplusb')['id']
    c.create_contest(key='demo', name='Demo Contest', problems=[(pk, 100)])
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta
from typing import Optional

import requests

CSRF_RE = re.compile(
    r"name=['\"]csrfmiddlewaretoken['\"] value=['\"]([^'\"]+)['\"]")


class QhhojError(Exception):
    pass


class QhhojClient:
    def __init__(self, base_url: str, username: str, password: str,
                 totp_secret: Optional[str] = None, timeout: int = 30):
        self.base = base_url.rstrip('/')
        self.username = username
        self.password = password
        self.totp_secret = totp_secret
        self.timeout = timeout
        self.s = requests.Session()
        self.api_enabled: Optional[bool] = None

    # ---------------- low-level helpers ----------------

    def url(self, path: str) -> str:
        return self.base + path

    def get(self, path: str, **kw):
        r = self.s.get(self.url(path), headers={'Referer': self.url(path)},
                       timeout=self.timeout, **kw)
        return r

    def _csrf(self, html: str) -> str:
        m = CSRF_RE.search(html)
        if not m:
            raise QhhojError('csrfmiddlewaretoken not found on page')
        return m.group(1)

    def post(self, path: str, data: dict, files: Optional[dict] = None):
        """GET page for a fresh CSRF token, then POST without following redirects.

        Returns the raw 30x response on success (check .status_code in (301, 302)).
        A 200 response means the form re-rendered with validation errors.
        """
        page = self.get(path)
        payload = dict(data)
        payload['csrfmiddlewaretoken'] = self._csrf(page.text)
        return self.s.post(self.url(path), data=payload, files=files,
                           allow_redirects=False,
                           headers={'Referer': self.url(path)},
                           timeout=self.timeout)

    @staticmethod
    def form_errors(html: str) -> list:
        errs = []
        for m in re.finditer(r'<ul class="errorlist[^"]*">(.*?)</ul>', html, re.S):
            errs.append(' '.join(re.sub(r'<[^>]+>', ' ', m.group(1)).split()))
        return [e for e in errs if e]

    @staticmethod
    def select_values(html: str, name: str) -> list:
        """All option values of <select name=...>; first value may be '' (placeholder)."""
        m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % name, html, re.S)
        return re.findall(r'<option value="([^"]*)"', m.group(1)) if m else []

    @staticmethod
    def select_selected(html: str, name: str) -> Optional[str]:
        m = re.search(r'<select[^>]*name="%s"[^>]*>(.*?)</select>' % name, html, re.S)
        if not m:
            return None
        m2 = re.search(r'<option value="([^"]*)"[^>]*\bselected', m.group(1))
        return m2.group(1) if m2 else next(
            (v for v in re.findall(r'<option value="([^"]*)"', m.group(1)) if v), None)

    @staticmethod
    def management_form(html: str, prefix: str) -> dict:
        """Parse TOTAL_FORMS / INITIAL_FORMS (+ row ids) of a Django formset."""
        def val(k):
            m = re.search(r'name="%s-%s"[^>]*value="(\d+)"' % (prefix, k), html)
            return m.group(1) if m else '0'
        ids = dict(re.findall(r'name="%s-(\d+)-id"[^>]*value="(\d+)"' % prefix, html))
        return {'TOTAL_FORMS': val('TOTAL_FORMS'),
                'INITIAL_FORMS': val('INITIAL_FORMS'),
                'MIN_NUM_FORMS': val('MIN_NUM_FORMS'),
                'MAX_NUM_FORMS': val('MAX_NUM_FORMS'),
                'ids': ids}

    # ---------------- auth ----------------

    def login(self) -> None:
        """Password login (+ TOTP if needed). Raises with reason on failure."""
        page = self.s.get(self.url('/accounts/login/'), timeout=self.timeout)
        r = self.s.post(self.url('/accounts/login/'), data={
            'csrfmiddlewaretoken': self._csrf(page.text),
            'username': self.username,
            'password': self.password,
            'next': '/',
        }, allow_redirects=False, headers={'Referer': self.url('/accounts/login/')},
            timeout=self.timeout)
        if r.status_code != 302:
            raise QhhojError('login failed (bad credentials?): %s'
                             % (self.form_errors(page.text) or r.status_code))
        # Forced password change: pwned-password detection in DMOJLoginMiddleware.
        probe = self.get('/edit/profile/')
        if probe.status_code == 302 and '/password/change' in probe.headers.get('Location', ''):
            raise QhhojError(
                'password appears in breach lists; site forces a password change '
                'before any other action (POST /password/change/ first)')
        if self.totp_secret and '/2fa/' in probe.headers.get('Location', ''):
            self._login_2fa()

    def _login_2fa(self) -> None:
        try:
            import pyotp
        except ImportError:
            raise QhhojError('pyotp required for TOTP 2FA login')
        page = self.get('/2fa/')
        r = self.s.post(self.url('/2fa/'), data={
            'csrfmiddlewaretoken': self._csrf(page.text),
            'totp_or_scratch_code': pyotp.TOTP(self.totp_secret).now(),
            'next': '/',
        }, allow_redirects=False, headers={'Referer': self.url('/2fa/')},
            timeout=self.timeout)
        if r.status_code != 302 or self.get('/edit/profile/').status_code != 200:
            raise QhhojError('2FA verification failed (bad code or clock skew)')

    def logged_in(self) -> bool:
        return self.get('/edit/profile/').status_code == 200

    # ---------------- read API (may be disabled: VNOJ_ENABLE_API) ----------------

    def api(self, path: str, params: dict = None) -> Optional[dict]:
        """GET /api/v2/<path>. Returns None (and remembers) if API is disabled."""
        if self.api_enabled is False:
            return None
        r = self.get('/api/v2/' + path.lstrip('/'), params=params)
        if r.status_code == 404:
            self.api_enabled = False
            return None
        r.raise_for_status()
        self.api_enabled = True
        body = r.json()
        if 'error' in body:
            raise QhhojError('API error: %s' % body['error'])
        return body['data']

    # ---------------- select2 lookups (id for formset FK fields) ----------------

    def select2(self, kind: str, term: str) -> list:
        """kind: problem | contest | profile | organization. Returns [{id, text}]."""
        r = self.get('/judge-select2/%s/' % kind, params={'term': term})
        r.raise_for_status()
        return r.json()['results']

    def select2_problem(self, code: str) -> dict:
        for row in self.select2('problem', code):
            return row
        raise QhhojError('problem not visible/found: %s' % code)

    # ---------------- problems ----------------

    def create_problem(self, code: str, name: str, time_limit_s: float = 1.0,
                       memory_limit_kb: int = 262144, points: int = 800,
                       partial: bool = True, description: str = '',
                       source: str = '', statement_pdf: str = None,
                       org_path: str = '') -> None:
        """POST /problems/create (needs judge.add_problem) or
        /organization/<slug>/problem-create (judge.create_organization_problem).

        time_limit seconds; memory_limit KB; global (non-org) problems are always
        created private; org problems get an is_public checkbox (org members).
        Codes: ^[a-z0-9_]+$; org problems must start with <orgslug>_ prefix.
        """
        path = (org_path or '') + '/problems/create'
        page = self.get(path)
        if page.status_code != 200:
            raise QhhojError('no access to %s (%s)' % (path, page.status_code))
        group = next(v for v in self.select_values(page.text, 'group') if v)
        types = [v for v in self.select_values(page.text, 'types') if v][:1]
        data = {
            'code': code, 'name': name,
            'time_limit': str(time_limit_s),
            'memory_limit': str(memory_limit_kb),
            'points': str(points),
            'partial': 'on' if partial else '',
            'group': group, 'types': types,
            'source': source, 'description': description,
            'submission_source_visibility_mode': 'F',
            'testcase_visibility_mode': 'A',
        }
        if org_path:
            data['is_public'] = ''
        files = None
        if statement_pdf:
            files = {'statement_file': (statement_pdf.split('/')[-1],
                                        open(statement_pdf, 'rb'), 'application/pdf')}
        r = self.post(path, data, files)
        if r.status_code not in (301, 302):
            raise QhhojError('create_problem failed: %s' % self.form_errors(
                self.get(path).text if r.status_code == 200 else r.text))
        if self.get('/problem/%s/edit' % code).status_code != 200:
            raise QhhojError('problem %s not editable after create' % code)

    def edit_problem(self, code: str, **fields) -> None:
        """POST /problem/<code>/edit. Only changed fields needed but the two inline
        formset management forms (language_limits, solution) are always required."""
        page = self.get('/problem/%s/edit' % code)
        if page.status_code != 200:
            raise QhhojError('cannot edit %s (not author/curator/staff)' % code)
        data = {
            'code': code,
            'name': fields.get('name') or re.search(
                r'name="name"[^>]*value="([^"]*)"', page.text).group(1),
            'time_limit': str(fields.get('time_limit_s') or self.select_selected(
                page.text, 'time_limit') or re.search(
                r'name="time_limit"[^>]*value="([\d.]+)"', page.text).group(1)),
            'memory_limit': str(fields.get('memory_limit_kb') or 262144),
            'points': str(fields.get('points') or 800),
            'partial': '' if fields.get('partial') is False else 'on',
            'group': self.select_selected(page.text, 'group'),
            'types': [self.select_selected(page.text, 'types')],
            'source': fields.get('source', ''),
            'description': fields.get('description', ''),
            'submission_source_visibility_mode': 'F',
            'testcase_visibility_mode': 'A',
            'language_limits-TOTAL_FORMS': '0', 'language_limits-INITIAL_FORMS': '0',
            'language_limits-MIN_NUM_FORMS': '0', 'language_limits-MAX_NUM_FORMS': '1000',
            'solution-TOTAL_FORMS': '0', 'solution-INITIAL_FORMS': '0',
            'solution-MIN_NUM_FORMS': '0', 'solution-MAX_NUM_FORMS': '1000',
        }
        r = self.post('/problem/%s/edit' % code, data)
        if r.status_code not in (301, 302):
            raise QhhojError('edit_problem failed: %s' % self.form_errors(r.text))

    def upload_testdata(self, code: str, zip_path: str = None,
                        cases: list = None, checker: str = 'standard',
                        grader: str = 'standard') -> None:
        """POST /problem/<code>/test_data (multipart).

        cases: [(input_file, output_file, points)] — paths *inside the zip*.
        grader: standard | interactive | signature | output_only
        checker: standard | floats | floatsabs | floatsrel | identical | bridged

        Gotchas verified on the live site:
        * NEVER include a `problem-data-zipfile-clear` key — its mere presence
          (even empty) makes the server drop all zip contents.
        * `problem-data-grader` is required (no blank option).
        * To modify existing cases, first GET the page: INITIAL_FORMS and every
          `cases-<i>-id` must be echoed back.
        """
        path = '/problem/%s/test_data' % code
        page = self.get(path)
        if page.status_code != 200:
            raise QhhojError('no access to test data of %s' % code)
        mg = self.management_form(page.text, 'cases')
        cases = cases or []
        total = str(max(int(mg['INITIAL_FORMS']) + len(cases), int(mg['TOTAL_FORMS'])))
        data = {
            'cases-TOTAL_FORMS': total,
            'cases-INITIAL_FORMS': mg['INITIAL_FORMS'],
            'cases-MIN_NUM_FORMS': '0', 'cases-MAX_NUM_FORMS': '1000',
            'mirror-test_source': 'local',
            'external-enabled': '',
            'problem-data-grader': grader,
            'problem-data-io_method': 'standard',
            'problem-data-io_input_file': '', 'problem-data-io_output_file': '',
            'problem-data-custom_grader': '', 'problem-data-custom_header': '',
            'problem-data-grader_args': '',
            'problem-data-checker': checker,
            'problem-data-custom_checker': '', 'problem-data-checker_args': '',
            'problem-data-checker_type': 'default',
            'problem-data-output_limit': '',
        }
        for i, (pk, _) in enumerate(sorted(mg['ids'].items(), key=lambda kv: int(kv[0]))):
            data['cases-%s-id' % i] = pk
        for j, (inf, outf, pts) in enumerate(cases):
            k = int(mg['INITIAL_FORMS']) + j
            data.update({
                'cases-%d-order' % k: str(k + 1), 'cases-%d-type' % k: 'C',
                'cases-%d-input_file' % k: inf, 'cases-%d-output_file' % k: outf,
                'cases-%d-points' % k: str(pts),
            })
        files = None
        if zip_path:
            files = {'problem-data-zipfile': ('tests.zip', open(zip_path, 'rb'),
                                              'application/zip')}
        r = self.post(path, data, files)
        if r.status_code not in (301, 302):
            raise QhhojError('upload_testdata failed: %s' % self.form_errors(r.text))
        # apply/done: server redirects back to the same page

    @staticmethod
    def make_zip(files: dict, out_path: str) -> str:
        """files: {'1.in': '1 2\n', '1.ans': '3\n', ...}"""
        with zipfile.ZipFile(out_path, 'w') as z:
            for name, content in files.items():
                z.writestr(name, content)
        return out_path

    def import_polygon(self, zip_path: str, code: str) -> None:
        """POST /problems/import-polygon (judge.import_polygon_package).
        Package = Codeforces Polygon export zip (contains problem.xml).
        Creates problem + statement + tests + checkers automatically — the
        easiest full-upload path. Update existing: /problem/<code>/update-polygon.
        """
        data = {
            'code': code,
            'ignore_zero_point_batches': '', 'ignore_zero_point_cases': '',
            'append_main_solution_to_tutorial': 'on',
            'main_tutorial_language': '',
            'do_update': '',
        }
        files = {'package': (zip_path.split('/')[-1], open(zip_path, 'rb'),
                             'application/zip')}
        r = self.post('/problems/import-polygon', data, files)
        if r.status_code not in (301, 302):
            raise QhhojError('polygon import failed: %s' % self.form_errors(r.text))

    def clone_problem(self, code: str, new_code: str) -> None:
        r = self.post('/problem/%s/clone' % code, {'code': new_code})
        if r.status_code not in (301, 302):
            raise QhhojError('clone failed (need judge.clone_problem): %s'
                             % self.form_errors(r.text))

    # ---------------- contests ----------------

    def create_contest(self, key: str, name: str,
                       start: datetime = None, end: datetime = None,
                       duration_days: float = 2.0, description: str = '',
                       format_name: str = 'default',
                       scoreboard_visibility: str = 'V',
                       visible: bool = False,
                       problems: list = None, org_path: str = '') -> None:
        """POST /contests/new (judge.add_contest) or /organization/<slug>/contest-create.

        problems: [(problem_pk, points)] (pk from select2_problem).
        Limits: duration <= 14 days without judge.long_contest_duration;
        key ^[a-z0-9_]+$; org contests must start with <orgslug>_ prefix.
        format_name: default | icpc | ioi | ioi16 | atcoder | ecoo | vnoj |
                     final_submission | Ultimate
        scoreboard_visibility: V (visible) | C (contest-only) | P (after partial?)
        | H (hidden) — codes parsed from the live form.
        """
        path = (org_path or '') + '/contests/new'
        start = start or datetime.now().replace(microsecond=0)
        end = end or start + timedelta(days=duration_days)
        data = {
            'key': key, 'name': name,
            'start_time': start.strftime('%Y-%m-%d %H:%M:%S'),
            'end_time': end.strftime('%Y-%m-%d %H:%M:%S'),
            'is_visible': 'on' if visible else '',
            'format_name': format_name,
            'scoreboard_visibility': scoreboard_visibility,
            'description': description,
            'is_private': '', 'auto_judge': 'on',
            'contest_problems-TOTAL_FORMS': str(len(problems or [])),
            'contest_problems-INITIAL_FORMS': '0',
            'contest_problems-MIN_NUM_FORMS': '0',
            'contest_problems-MAX_NUM_FORMS': '1000',
        }
        for i, (pk, pts) in enumerate(problems or []):
            data.update({
                'contest_problems-%d-id' % i: '',
                'contest_problems-%d-problem' % i: str(pk),
                'contest_problems-%d-points' % i: str(pts),
                'contest_problems-%d-order' % i: str(i + 1),
                'contest_problems-%d-max_submissions' % i: '',
            })
        r = self.post(path, data)
        if r.status_code not in (301, 302):
            raise QhhojError('create_contest failed: %s' % self.form_errors(
                self.get(path).text if r.status_code == 200 else r.text))

    def edit_contest(self, key: str, problems: list = None, **fields) -> None:
        """POST /contest/<key>/edit. problems=[(pk, points)] sets the problem list.

        Row reconciliation (verified live): existing rows MUST be echoed with
        their `contest_problems-<i>-id`; dropping an existing row without its id
        raises "Contest problem with this Problem and Contest already exists".
        Kept rows keep their id; removed rows get id + DELETE=on; new rows have
        empty id.
        """
        path = '/contest/%s/edit' % key
        page = self.get(path)
        if page.status_code != 200:
            raise QhhojError('cannot edit contest %s' % key)
        # existing rows: index -> (row_pk, current problem pk)
        row_ids = dict((int(k), v) for k, v in re.findall(
            r'name="contest_problems-(\d+)-id"[^>]*value="(\d+)"', page.text))
        row_probs = {}
        for m in re.finditer(
                r'<select[^>]*name="contest_problems-(\d+)-problem"[^>]*>(.*?)</select>',
                page.text, re.S):
            vals = [v for v in re.findall(r'<option value="(\d+)"', m.group(2)) if v]
            if vals:
                row_probs[int(m.group(1))] = vals[0]
        desired = {} if problems is None else {int(pk): pts for pk, pts in problems}
        rows = []  # (id_or_empty, pk, points, order, delete)
        for i in sorted(row_ids):
            cur_pk = int(row_probs.get(i, 0))
            if cur_pk in desired:
                rows.append((row_ids[i], str(cur_pk), desired.pop(cur_pk), 0, False))
            else:
                rows.append((row_ids[i], str(cur_pk), 1, 0, True))
        for order, (pk, pts) in enumerate(desired.items(), start=len(rows) + 1):
            rows.append(('', str(pk), pts, order, False))
        for n, row in enumerate(rows):
            row_pk, pts, order = row[1], row[2], row[3] or (n + 1)
            if row[4]:
                rows[n] = (row[0], row_pk, row[2] or 1, n + 1, True)
            else:
                rows[n] = (row[0], row_pk, pts, n + 1, False)
        data = {
            'key': key,
            'name': fields.get('name') or re.search(
                r'name="name"[^>]*value="([^"]*)"', page.text).group(1),
            'start_time': fields.get('start_time') or re.search(
                r'name="start_time"[^>]*value="([^"]*)"', page.text).group(1),
            'end_time': fields.get('end_time') or re.search(
                r'name="end_time"[^>]*value="([^"]*)"', page.text).group(1),
            'is_visible': 'on' if fields.get('visible', True) else '',
            'format_name': self.select_selected(page.text, 'format_name') or 'default',
            'scoreboard_visibility': self.select_selected(
                page.text, 'scoreboard_visibility') or 'V',
            'description': fields.get('description', ''),
            'is_private': '', 'auto_judge': 'on',
            'contest_problems-TOTAL_FORMS': str(len(rows)),
            'contest_problems-INITIAL_FORMS': str(len(row_ids)),
            'contest_problems-MIN_NUM_FORMS': '0',
            'contest_problems-MAX_NUM_FORMS': '1000',
        }
        for i, (row_id, pk, pts, order, delete) in enumerate(rows):
            data.update({
                'contest_problems-%d-id' % i: row_id,
                'contest_problems-%d-problem' % i: pk,
                'contest_problems-%d-points' % i: str(pts),
                'contest_problems-%d-order' % i: str(order),
                'contest_problems-%d-max_submissions' % i: '',
            })
            if delete:
                data['contest_problems-%d-DELETE' % i] = 'on'
        r = self.post(path, data)
        if r.status_code not in (301, 302):
            raise QhhojError('edit_contest failed: %s' % self.form_errors(r.text))
    def announce(self, key: str, title: str, description: str) -> None:
        r = self.post('/contest/%s/announce' % key,
                      {'title': title, 'description': description})
        if r.status_code not in (301, 302):
            raise QhhojError('announce failed (not author/curator?): %s'
                             % self.form_errors(r.text))

    def join_contest(self, key: str, access_code: str = None) -> None:
        data = {'access_code': access_code} if access_code else {}
        r = self.post('/contest/%s/join' % key, data)
        if r.status_code not in (301, 302):
            raise QhhojError('join failed: %s' % self.form_errors(r.text))

    # ---------------- submissions ----------------

    def languages(self, code: str) -> list:
        """(id, name) of usable languages — requires an online judge serving
        this problem; empty list means no judge is available."""
        page = self.get('/problem/%s/submit' % code)
        m = re.search(r'<select id="id_language" name="language">(.*?)</select>',
                      page.text, re.S)
        return re.findall(r'<option value="(\d+)"[^>]*>([^<]*)', m.group(1)) if m else []

    def submit(self, code: str, source: str, language_id: str = None,
               language_name_hint: str = None, file_path: str = None) -> int:
        """POST /problem/<code>/submit. language_id from .languages(); returns
        submission id (from the redirect target /submission/<id>)."""
        langs = self.languages(code)
        if not langs:
            raise QhhojError('no judge online for %s — cannot submit' % code)
        if language_id is None and language_name_hint:
            for lid, lname in langs:
                if language_name_hint.lower() in lname.lower():
                    language_id = lid
                    break
        language_id = language_id or langs[0][0]
        files = None
        data = {'language': language_id, 'source': '' if file_path else source}
        if file_path:
            files = {'submission_file': open(file_path, 'rb')}
        r = self.post('/problem/%s/submit' % code, data, files)
        if r.status_code != 302:
            raise QhhojError('submit failed: %s' % self.form_errors(r.text))
        m = re.search(r'/submission/(\d+)', r.headers.get('Location', ''))
        return int(m.group(1)) if m else -1


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser(description='qhhoj site client CLI')
    p.add_argument('base_url')
    p.add_argument('username')
    p.add_argument('password')
    p.add_argument('--totp', help='TOTP secret for 2FA')
    p.add_argument('--probe', action='store_true',
                   help='login and print account/site capabilities')
    a = p.parse_args()
    c = QhhojClient(a.base_url, a.username, a.password, totp_secret=a.totp)
    c.login()
    print('logged in:', c.logged_in())
    api = c.api('contests')
    print('api/v2:', 'enabled' if api is not None else 'disabled')
    if api is not None:
        print('contests visible:', [o['key'] for o in api['objects']][:10])
