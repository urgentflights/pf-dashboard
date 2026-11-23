"""PF Dashboard — upcoming and recent NKR organ moves for ParaFlight Aero.

One process, no build step. Render starts it with `python3 server.py` and
injects PORT. Session login covers the pages and the team API. The ingest
API uses a bearer token instead.
"""

import csv
import hmac
import io
import os
import time
from datetime import timedelta

from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
)

import store as store_mod
from store import EDITABLE, FIELDS, store

_FAILS = {}
_FAIL_WINDOW = 600
_FAIL_LIMIT = 8


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
        if path in ('/login', '/healthz', '/favicon.ico') or path.startswith('/static/'):
            return None
        if path.startswith('/api/ingest/'):
            if not _token_ok():
                return jsonify(error='unauthorized'), 401
            return None
        if session.get('display_name'):
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
        if session.get('display_name') and request.method == 'GET':
            return redirect('/')
        error = None
        name = ''
        if request.method == 'POST':
            ip = _client_ip()
            if _locked_out(ip):
                error = 'Too many attempts. Wait a few minutes and try again.'
                return render_template('login.html', error=error, name=''), 429
            name = _clean_name(request.form.get('name', ''))
            password = request.form.get('password', '')
            expected = os.environ.get('TEAM_PASSWORD') or ''
            if not expected:
                error = 'TEAM_PASSWORD is not set on the server.'
            elif not name:
                error = 'Enter your name so edits can be stamped.'
            elif not password or not _secret_equal(password, expected):
                _record_fail(ip)
                error = 'Wrong team password.'
            else:
                _FAILS.pop(ip, None)
                session.clear()
                session.permanent = True
                session['display_name'] = name
                return redirect('/')
            status = 401 if error else 200
            return render_template('login.html', error=error, name=name), status
        return render_template('login.html', error=None, name='')

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
        move = store.update_team(swap_id, parsed, session['display_name'])
        if move is None:
            return jsonify(error='unknown swap_id'), 404
        print(f'[edit] {session["display_name"]} updated {swap_id}', flush=True)
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


def _client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _locked_out(ip):
    now = time.time()
    recent = [stamp for stamp in _FAILS.get(ip, []) if now - stamp < _FAIL_WINDOW]
    _FAILS[ip] = recent
    return len(recent) >= _FAIL_LIMIT


def _record_fail(ip):
    _FAILS.setdefault(ip, []).append(time.time())


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
