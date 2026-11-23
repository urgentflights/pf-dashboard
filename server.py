"""PF Dashboard — upcoming and recent NKR organ moves for ParaFlight Aero.

One process, no build step. Render starts it with `python3 server.py` and
injects PORT. Session login covers the pages and the team API. The ingest
API uses a bearer token instead.
"""

import csv
import hmac
import io
import os
import re
import time
import urllib.parse
from datetime import timedelta

from flask import (
    Flask,
    Response,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)
from werkzeug.security import check_password_hash, generate_password_hash

import store as store_mod
from store import EDITABLE, FIELDS, public_user, store

_FAILS = {}
_FAIL_WINDOW = 600
_FAIL_LIMIT = 8
_MIN_PASSWORD = 8
_EMAIL_RE = re.compile(r'^[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}$')


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get('SECRET_KEY') or os.urandom(32)
    app.config.update(
        SESSION_COOKIE_NAME='pf_session',
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('RENDER', '').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
        JSON_SORT_KEYS=False,
    )
    app.json.ensure_ascii = False
    store.init()

    @app.before_request
    def auth_gate():
        path = request.path
        g.user = None
        g.is_admin = False
        if path in ('/login', '/signup', '/setup', '/healthz', '/favicon.ico') or path.startswith('/static/'):
            return _reject_cross_origin()
        if path.startswith('/api/ingest/') or path == '/api/admin/bootstrap':
            if not _token_ok():
                return jsonify(error='unauthorized'), 401
            return None
        crossed = _reject_cross_origin()
        if crossed is not None:
            return crossed
        user, error = _current_user()
        if error:
            session.clear()
            if path.startswith('/api/'):
                return jsonify(error='unauthorized'), 401
            return redirect('/login')
        if user is not None:
            g.user = user
            g.is_admin = user.get('role') == 'admin'
            session['display_name'] = user.get('name') or session.get('display_name')
            return None
        if session.get('auth') == 'team' and session.get('display_name') and _team_password_allowed():
            return None
        if path.startswith('/api/'):
            return jsonify(error='unauthorized'), 401
        return redirect('/login')

    @app.after_request
    def headers(resp):
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Referrer-Policy'] = 'same-origin'
        resp.headers['Cache-Control'] = 'no-store'
        return resp

    @app.get('/favicon.ico')
    def favicon():
        icon = os.path.join(app.root_path, 'static', 'favicon.svg')
        with open(icon, 'rb') as handle:
            body = handle.read()
        return Response(body, mimetype='image/svg+xml')

    @app.get('/healthz')
    def healthz():
        try:
            store.ping()
        except Exception:
            return Response('db unavailable\n', status=503, mimetype='text/plain')
        return Response('ok\n', mimetype='text/plain')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if _already_signed_in() and request.method == 'GET':
            return redirect('/')
        error = None
        email = ''
        name = ''
        pending = request.args.get('pending') == '1'
        ready = request.args.get('ready') == '1'
        if request.method == 'POST':
            ip = _client_ip()
            if _locked_out(ip, 'login'):
                error = 'Too many attempts. Wait a few minutes and try again.'
                return render_template(
                    'login.html',
                    error=error,
                    email='',
                    name='',
                    pending=False,
                    ready=False,
                    allow_team=_team_password_allowed(),
                ), 429
            email = _clean_email(request.form.get('email', ''))
            name = _clean_name(request.form.get('name', ''))
            password = request.form.get('password', '')
            raw_email = (request.form.get('email') or '').strip()
            if raw_email and not email:
                _record_fail(ip, 'login')
                error = 'Enter a valid email address.'
            elif email:
                user = store.get_user_by_email(email)
                if not user or not user.get('password_hash') or not password or not check_password_hash(user['password_hash'], password):
                    _record_fail(ip, 'login')
                    error = 'Wrong email or password.'
                elif user.get('status') == 'pending':
                    error = 'Your account is waiting for admin approval.'
                    pending = True
                elif user.get('status') != 'active':
                    error = 'This account has been disabled.'
                else:
                    _FAILS.pop(_fail_key(ip, 'login'), None)
                    _start_session(user)
                    return redirect('/')
            elif _team_password_allowed():
                expected = os.environ.get('TEAM_PASSWORD') or ''
                if not expected:
                    error = 'TEAM_PASSWORD is not set on the server.'
                elif not name:
                    error = 'Enter your name so edits can be stamped.'
                elif not password or not _secret_equal(password, expected):
                    _record_fail(ip, 'login')
                    error = 'Wrong team password.'
                else:
                    _FAILS.pop(_fail_key(ip, 'login'), None)
                    session.clear()
                    session.permanent = True
                    session['display_name'] = name
                    session['auth'] = 'team'
                    return redirect('/')
            else:
                error = 'Enter your email and password.'
            status = 429 if error and 'Too many' in error else (401 if error else 200)
            return render_template(
                'login.html',
                error=error,
                email=email or raw_email,
                name=name,
                pending=pending,
                ready=False,
                allow_team=_team_password_allowed(),
            ), status
        return render_template(
            'login.html',
            error=None,
            email='',
            name='',
            pending=pending,
            ready=ready,
            allow_team=_team_password_allowed(),
        )

    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if _already_signed_in() and request.method == 'GET':
            return redirect('/')
        error = None
        name = ''
        email = ''
        waiting = False
        admin_ready = False
        if request.method == 'POST':
            ip = _client_ip()
            if _locked_out(ip, 'signup'):
                error = 'Too many attempts. Wait a few minutes and try again.'
                return render_template(
                    'signup.html',
                    error=error,
                    name='',
                    email='',
                    waiting=False,
                    admin_ready=False,
                ), 429
            name = _clean_name(request.form.get('name', ''))
            email = _clean_email(request.form.get('email', ''))
            raw_email = (request.form.get('email') or '').strip()
            password = request.form.get('password', '')
            confirm = request.form.get('confirm', '')
            if not name:
                error = 'Enter your name so edits can be stamped.'
            elif raw_email and not email:
                error = 'Enter a valid email address.'
            elif not email:
                error = 'Enter a valid email address.'
            elif not _password_ok(password):
                error = f'Choose a password of at least {_MIN_PASSWORD} characters.'
            elif password != confirm:
                error = 'Passwords do not match.'
            elif store.get_user_by_email(email):
                _record_fail(ip, 'signup')
                error = 'An account with that email already exists. Sign in, or ask an admin for a reset link.'
            else:
                role = 'staff'
                status = 'pending'
                if _is_pending_admin_email(email) and not store.admin_exists():
                    role = 'admin'
                    status = 'active'
                    admin_ready = True
                store.create_user(
                    name=name,
                    email=email,
                    password_hash=_hash_password(password),
                    role=role,
                    status=status,
                )
                _FAILS.pop(_fail_key(ip, 'signup'), None)
                if admin_ready:
                    return redirect('/login?ready=1')
                waiting = True
                return render_template(
                    'signup.html',
                    error=None,
                    name=name,
                    email=email,
                    waiting=True,
                    admin_ready=False,
                )
            status = 429 if error and 'Too many' in error else 400
            return render_template(
                'signup.html',
                error=error,
                name=name,
                email=email or raw_email,
                waiting=False,
                admin_ready=False,
            ), status
        return render_template(
            'signup.html',
            error=None,
            name=name,
            email=email,
            waiting=waiting,
            admin_ready=admin_ready,
        )

    @app.route('/setup', methods=['GET', 'POST'])
    def setup():
        raw = (request.values.get('token') or request.args.get('token') or '').strip()
        user = store.lookup_setup_token(raw)
        if user is None:
            return render_template('setup.html', error='This setup link is invalid or has expired.', token='', valid=False), 400
        error = None
        if request.method == 'POST':
            password = request.form.get('password', '')
            confirm = request.form.get('confirm', '')
            if not _password_ok(password):
                error = f'Choose a password of at least {_MIN_PASSWORD} characters.'
            elif password != confirm:
                error = 'Passwords do not match.'
            else:
                consumed = store.consume_setup_token(raw)
                if consumed is None:
                    return render_template(
                        'setup.html',
                        error='This setup link is invalid or has expired.',
                        token='',
                        valid=False,
                    ), 400
                store.set_user_fields(consumed['id'], password_hash=_hash_password(password))
                return redirect('/login?ready=1')
            return render_template('setup.html', error=error, token=raw, valid=True), 400
        return render_template('setup.html', error=None, token=raw, valid=True)

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    @app.get('/')
    def home():
        return render_template(
            'dashboard.html',
            name=session['display_name'],
            today=store_mod.today_ny(),
            is_admin=bool(g.is_admin),
        )

    @app.route('/admin', methods=['GET', 'POST'])
    def admin():
        denied = _require_admin()
        if denied is not None:
            return denied
        message = None
        reset_link = None
        error = None
        if request.method == 'POST':
            action = (request.form.get('action') or '').strip()
            user_id = (request.form.get('user_id') or '').strip()
            target = store.get_user(user_id) if user_id else None
            if not target:
                error = 'That account was not found.'
            else:
                result_error, result_message, result_link = _apply_admin_action(g.user, target, action)
                error = result_error
                message = result_message
                reset_link = result_link
            status = 400 if error else 200
            return render_template(
                'admin.html',
                name=session['display_name'],
                users=[public_user(row) for row in store.list_users()],
                message=message,
                error=error,
                reset_link=reset_link,
            ), status
        return render_template(
            'admin.html',
            name=session['display_name'],
            users=[public_user(row) for row in store.list_users()],
            message=message,
            error=error,
            reset_link=reset_link,
        )

    @app.get('/api/moves')
    def api_moves():
        return jsonify(
            timezone='America/New_York',
            today=store_mod.today_ny(),
            moves=store.list_moves(),
        )

    @app.get('/api/moves.csv')
    def api_moves_csv():
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction='ignore')
        writer.writeheader()
        for move in store.list_moves():
            writer.writerow({key: _csv_cell(move.get(key)) for key in FIELDS})
        body = buf.getvalue().encode('utf-8-sig')
        return Response(
            body,
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': 'attachment; filename="moves.csv"'},
        )

    @app.patch('/api/moves')
    def api_patch_move():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error='expected a JSON object'), 400
        parsed = store_mod.parse_team(payload)
        swap_id, err = store_mod.clean_swap_id(payload.get('swap_id'))
        if err:
            return jsonify(error=err), 400
        if not any(key in parsed for key in EDITABLE):
            return jsonify(error='no team fields'), 400
        editor = session['display_name']
        move = store.update_team(swap_id, parsed, editor)
        if move is None:
            return jsonify(error='unknown swap_id'), 404
        print(f'[edit] {editor} updated {swap_id}', flush=True)
        return jsonify(ok=True, move=move)

    @app.post('/api/ingest/moves')
    def api_ingest_moves():
        rows, error = _json_list()
        if error:
            return error
        result = store.ingest_moves(rows)
        print(
            f'[ingest] moves inserted={result["inserted"]} updated={result["updated"]} skipped={result["skipped"]}',
            flush=True,
        )
        return jsonify(result)

    @app.post('/api/ingest/airspace')
    def api_ingest_airspace():
        rows, error = _json_list()
        if error:
            return error
        result = store.ingest_airspace(rows)
        print(
            f'[ingest] airspace inserted={result["inserted"]} updated={result["updated"]} skipped={result["skipped"]}',
            flush=True,
        )
        return jsonify(result)

    @app.post('/api/admin/bootstrap')
    def api_admin_bootstrap():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        email = _clean_email(payload.get('email', ''))
        if not email:
            return jsonify(ok=False, error='invalid_email'), 400
        user = store.promote_admin(email)
        if user is None:
            return jsonify(ok=False, error='not_found'), 404
        return jsonify(ok=True, email=user['email'], role=user['role'], status=user['status'])

    @app.errorhandler(404)
    def missing(err):
        if request.path.startswith('/api/'):
            return jsonify(error='not found'), 404
        return err

    @app.errorhandler(413)
    def too_big(err):
        return jsonify(error='payload too large'), 413

    @app.errorhandler(Exception)
    def crashed(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return err
        import traceback
        traceback.print_exc()
        if request.path.startswith('/api/'):
            return jsonify(error='server error'), 500
        return 'Server error', 500

    return app


def _json_list():
    payload = request.get_json(silent=True)
    if isinstance(payload, list):
        return payload, None
    if isinstance(payload, dict):
        for key in ('moves', 'legs', 'items', 'orders', 'data'):
            if isinstance(payload.get(key), list):
                return payload[key], None
    return None, (jsonify(error='expected a JSON list'), 400)


def _token_ok():
    expected = os.environ.get('INGEST_TOKEN') or ''
    header = request.headers.get('Authorization', '')
    parts = header.split(None, 1)
    got = parts[1].strip() if len(parts) == 2 and parts[0].lower() == 'bearer' else ''
    return _secret_equal(got, expected)


def _secret_equal(got, expected):
    if not got or not expected:
        return False
    return hmac.compare_digest(got.encode(), expected.encode())


def _clean_name(value):
    name = ' '.join((value or '').split())
    name = ''.join(ch for ch in name if ch.isprintable() and ord(ch) >= 32)
    name = name.strip()
    if not name:
        return ''
    return name[:40]


def _clean_email(value):
    email = ' '.join((value or '').split()).strip().lower()
    if not email or len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        return ''
    return email


def _password_ok(password):
    if not isinstance(password, str):
        return False
    if len(password) < _MIN_PASSWORD or len(password) > 200:
        return False
    return True


def _hash_password(password):
    return generate_password_hash(password, method='pbkdf2:sha256', salt_length=16)


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _team_password_allowed():
    return _env_flag('ALLOW_TEAM_PASSWORD', default=False)


def _admin_email():
    return _clean_email(os.environ.get('ADMIN_EMAIL') or '')


def _is_pending_admin_email(email):
    expected = _admin_email()
    return bool(expected) and email == expected


def _already_signed_in():
    user, error = _current_user()
    if error:
        session.clear()
        return False
    if user is not None:
        return True
    return session.get('auth') == 'team' and bool(session.get('display_name')) and _team_password_allowed()


def _current_user():
    user_id = session.get('user_id')
    if not user_id:
        return None, None
    user = store.get_user(user_id)
    if user is None or user.get('status') != 'active':
        return None, 'invalid'
    return user, None


def _start_session(user):
    session.clear()
    session.permanent = True
    session['user_id'] = user['id']
    session['display_name'] = user['name']
    session['auth'] = 'user'
    store.mark_login(user['id'])


def _require_admin():
    if g.user is not None and g.is_admin:
        return None
    if request.path.startswith('/api/'):
        return jsonify(error='forbidden'), 403
    if session.get('display_name') or g.user is not None:
        return render_template('admin.html', name=session.get('display_name') or '', users=[], message=None, error='Admin only.', reset_link=None, forbidden=True), 403
    return redirect('/login')


def _apply_admin_action(actor, target, action):
    actor_id = actor['id']
    if action == 'approve':
        if target.get('status') != 'pending':
            return 'Only pending accounts can be approved.', None, None
        store.set_user_fields(target['id'], status='active')
        return None, f"Approved {target['email']}.", None
    if action == 'disable':
        if target['id'] == actor_id:
            return 'You cannot disable your own account.', None, None
        if target.get('role') == 'admin' and store.count_active_admins(exclude_id=target['id']) < 1:
            return 'There must be at least one active admin.', None, None
        store.set_user_fields(target['id'], status='disabled')
        return None, f"Disabled {target['email']}.", None
    if action == 'enable':
        if target.get('status') != 'disabled':
            return 'Only disabled accounts can be re-enabled.', None, None
        store.set_user_fields(target['id'], status='active')
        return None, f"Re-enabled {target['email']}.", None
    if action == 'promote':
        if target.get('status') != 'active':
            return 'Approve the account before promoting it.', None, None
        store.set_user_fields(target['id'], role='admin')
        return None, f"Promoted {target['email']} to admin.", None
    if action == 'demote':
        if target['id'] == actor_id:
            return 'You cannot demote your own account.', None, None
        if target.get('role') != 'admin':
            return 'That account is not an admin.', None, None
        if store.count_active_admins(exclude_id=target['id']) < 1:
            return 'There must be at least one active admin.', None, None
        store.set_user_fields(target['id'], role='staff')
        return None, f"Demoted {target['email']} to staff.", None
    if action == 'delete':
        if target.get('status') != 'pending':
            return 'Only pending accounts can be deleted.', None, None
        if not store.delete_pending_user(target['id']):
            return 'Could not delete that account.', None, None
        return None, f"Deleted {target['email']}.", None
    if action == 'reset':
        raw = store.create_setup_token(target['id'])
        if not raw:
            return 'Could not create a reset link.', None, None
        link = request.host_url.rstrip('/') + '/setup?token=' + raw
        return None, f"Password reset link for {target['email']} (valid 7 days, one-time use):", link
    return 'Unknown action.', None, None


def _same_origin():
    source = request.headers.get('Origin') or request.headers.get('Referer') or ''
    if not source:
        return True
    parsed = urllib.parse.urlparse(source)
    host = (parsed.netloc or '').lower()
    return host == (request.host or '').lower()


def _reject_cross_origin():
    if request.method in ('GET', 'HEAD', 'OPTIONS'):
        return None
    if request.path.startswith('/api/ingest/') or request.path == '/api/admin/bootstrap':
        return None
    if _same_origin():
        return None
    if request.path.startswith('/api/'):
        return jsonify(error='forbidden'), 403
    return 'Forbidden', 403


def _client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _fail_key(ip, action):
    return f'{ip}:{action}'


def _locked_out(ip, action='login'):
    now = time.time()
    key = _fail_key(ip, action)
    recent = [stamp for stamp in _FAILS.get(key, []) if now - stamp < _FAIL_WINDOW]
    _FAILS[key] = recent
    return len(recent) >= _FAIL_LIMIT


def _record_fail(ip, action='login'):
    _FAILS.setdefault(_fail_key(ip, action), []).append(time.time())


def _csv_cell(value):
    if value is None:
        return ''
    text = str(value)
    if text[:1] in ('=', '+', '-', '@', '\t', '\r'):
        return "'" + text
    return text


app = create_app()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', '10000'))
    print(f'[pf] listening on 0.0.0.0:{port} db={store.describe()}', flush=True)
    app.run(host='0.0.0.0', port=port, threaded=True)
