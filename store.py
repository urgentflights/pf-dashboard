"""Move storage for PF Dashboard.

Render sets DATABASE_URL to Postgres. With no DATABASE_URL, or a sqlite:// URL,
the app uses a local SQLite file so it can run on a laptop. Ingest updates
logistics columns only. Crew columns (assigned_to, aircraft, phone, notes)
are never written by ingest. Airline, flight number, departure time, airport,
and terminal are team-editable; ingest may fill them only when empty.
"""

import hashlib
import os
import secrets
import re
import ssl
import threading
import urllib.parse
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')

FIELDS = (
    'swap_id', 'pickup_date', 'donor', 'recipient', 'method', 'pickup', 'delivery',
    'status', 'first_seen', 'last_seen',
    'airline', 'flight_number', 'departure_time', 'departure_airport', 'departure_terminal',
    'airspace_order_id', 'airspace_driver', 'airspace_flight', 'airspace_awb', 'airspace_status',
    'assigned_to', 'aircraft', 'phone', 'notes', 'edited_by', 'edited_at',
)

LOGISTICS = (
    'pickup_date', 'donor', 'recipient', 'method', 'pickup', 'delivery',
    'status', 'first_seen', 'last_seen',
)

AIRSPACE = (
    'airspace_order_id', 'airspace_driver', 'airspace_flight', 'airspace_awb', 'airspace_status',
)

FILLABLE = (
    'airline', 'flight_number', 'departure_time', 'departure_airport', 'departure_terminal',
)

TEAM = ('assigned_to', 'aircraft', 'phone', 'notes')

EDITABLE = TEAM + FILLABLE

_LIMITS = {
    'swap_id': 80,
    'pickup_date': 40,
    'donor': 120,
    'recipient': 120,
    'method': 40,
    'pickup': 80,
    'delivery': 80,
    'status': 40,
    'first_seen': 40,
    'last_seen': 40,
    'airspace_order_id': 80,
    'airspace_driver': 200,
    'airspace_flight': 40,
    'airspace_awb': 40,
    'airspace_status': 300,
    'airline': 40,
    'flight_number': 40,
    'departure_time': 80,
    'departure_airport': 40,
    'departure_terminal': 40,
    'assigned_to': 120,
    'aircraft': 40,
    'phone': 40,
    'notes': 4000,
}

_MOVE_ALIASES = (
    ('swap_id', 'swap_id'),
    ('pickup_date', 'pickup_date'),
    ('donor', 'donor'),
    ('donor_center', 'donor'),
    ('recipient', 'recipient'),
    ('recipient_center', 'recipient'),
    ('method', 'method'),
    ('pickup', 'pickup'),
    ('pickup_time', 'pickup'),
    ('delivery', 'delivery'),
    ('delivery_time', 'delivery'),
    ('status', 'status'),
    ('first_seen', 'first_seen'),
    ('last_seen', 'last_seen'),
)

_AIR_ALIASES = (
    ('swap_id', 'swap_id'),
    ('airspace_order_id', 'airspace_order_id'),
    ('order_id', 'airspace_order_id'),
    ('airspace_driver', 'airspace_driver'),
    ('driver_names', 'airspace_driver'),
    ('drivers', 'airspace_driver'),
    ('driver_name', 'airspace_driver'),
    ('driver', 'airspace_driver'),
    ('airspace_flight', 'airspace_flight'),
    ('flight_number', 'airspace_flight'),
    ('flight', 'airspace_flight'),
    ('airspace_awb', 'airspace_awb'),
    ('awb', 'airspace_awb'),
    ('airspace_status', 'airspace_status'),
    ('status', 'airspace_status'),
    ('airline', 'airline'),
    ('departure_time', 'departure_time'),
    ('etd', 'departure_time'),
    ('dep_time', 'departure_time'),
    ('departure_airport', 'departure_airport'),
    ('airport', 'departure_airport'),
    ('origin_airport', 'departure_airport'),
    ('departure_terminal', 'departure_terminal'),
    ('terminal', 'departure_terminal'),
)

_FILLABLE_ALIASES = (
    ('airline', 'airline'),
    ('flight_number', 'flight_number'),
    ('flight', 'flight_number'),
    ('departure_time', 'departure_time'),
    ('etd', 'departure_time'),
    ('dep_time', 'departure_time'),
    ('departure_airport', 'departure_airport'),
    ('airport', 'departure_airport'),
    ('origin_airport', 'departure_airport'),
    ('departure_terminal', 'departure_terminal'),
    ('terminal', 'departure_terminal'),
)

_TEAM_ALIASES = (
    ('assigned_to', 'assigned_to'),
    ('aircraft', 'aircraft'),
    ('aircraft_tail', 'aircraft'),
    ('tail', 'aircraft'),
    ('phone', 'phone'),
    ('contact', 'phone'),
    ('phone_contact', 'phone'),
    ('notes', 'notes'),
) + _FILLABLE_ALIASES

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SQLITE = os.path.join(ROOT, 'data', 'pf.sqlite')

_SCHEMA = """
CREATE TABLE IF NOT EXISTS moves (
    swap_id TEXT PRIMARY KEY,
    pickup_date TEXT,
    donor TEXT,
    recipient TEXT,
    method TEXT,
    pickup TEXT,
    delivery TEXT,
    status TEXT,
    first_seen TEXT,
    last_seen TEXT,
    airline TEXT,
    flight_number TEXT,
    departure_time TEXT,
    departure_airport TEXT,
    departure_terminal TEXT,
    airspace_order_id TEXT,
    airspace_driver TEXT,
    airspace_flight TEXT,
    airspace_awb TEXT,
    airspace_status TEXT,
    assigned_to TEXT,
    aircraft TEXT,
    phone TEXT,
    notes TEXT,
    edited_by TEXT,
    edited_at TEXT
)
"""

_USER_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT,
    role TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_login TEXT
)
"""

_TOKEN_SCHEMA = """
CREATE TABLE IF NOT EXISTS setup_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_at TEXT
)
"""


def today_ny():
    return datetime.now(NY).date().isoformat()


def norm_key(key):
    out = []
    prev = False
    for ch in str(key).strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev = False
        elif not prev:
            out.append('_')
            prev = True
    return ''.join(out).strip('_')


def as_text(value, limit):
    """Return a stripped string, or None when the value should be stored as SQL NULL.

    Lists (driver names) are joined. Numbers are stringified. Blank becomes None.
    Over-long text is truncated to the column cap.
    """
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        parts = [as_text(item, limit) for item in value]
        value = ', '.join(part for part in parts if part)
    elif isinstance(value, bool):
        value = 'true' if value else 'false'
    elif not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None
    if len(value) > limit:
        value = value[:limit]
    return value


def _pick(row, aliases):
    src = {norm_key(k): v for k, v in row.items()}
    out = {}
    for src_key, dest in aliases:
        if dest in out or src_key not in src:
            continue
        text = as_text(src[src_key], _LIMITS[dest])
        # Key was present. None means "clear this column" on update.
        out[dest] = text
    return out


def parse_move(row):
    out = _pick(row, _MOVE_ALIASES)
    for key, value in _pick(row, _FILLABLE_ALIASES).items():
        if key not in out:
            out[key] = value
    return out


def parse_airspace(row):
    out = _pick(row, _AIR_ALIASES)
    for key, value in _pick(row, _FILLABLE_ALIASES).items():
        if key not in out:
            out[key] = value
    return out


def parse_team(row):
    return _pick(row, _TEAM_ALIASES)


_FLIGHT_CODE_RE = re.compile(r'^([A-Za-z]{2,3})\s*(\d{1,4}[A-Za-z]?)$')
_FLIGHT_NAMED_RE = re.compile(r'^([A-Za-z][A-Za-z. ]{1,28}?)\s+(\d{1,4}[A-Za-z]?)$')


def split_flight(value):
    """Return (airline, number) from strings like 'AA 1234' or 'AA1234'.

    If the string cannot be split, both parts are None.
    """
    text = (value or '').strip()
    if not text:
        return None, None
    match = _FLIGHT_CODE_RE.match(text)
    if match:
        return match.group(1).upper(), match.group(2)
    match = _FLIGHT_NAMED_RE.match(text)
    if match:
        return match.group(1).strip(), match.group(2)
    return None, None


def is_commercial_method(method):
    key = re.sub(r'[^a-z]', '', (method or '').lower())
    if not key:
        return True
    return key in ('commercial', 'commobc', 'obc', 'onboardcourier')


def enrich_fillable_from_flight(fields, method=None):
    """Split a combined flight string into airline and flight_number in place."""
    explicit = fields.get('flight_number')
    source = explicit or (fields.get('airspace_flight') if is_commercial_method(method) else None)
    airline, number = split_flight(source)
    if not airline or not number:
        if is_commercial_method(method) and not explicit and fields.get('airspace_flight') and 'flight_number' not in fields:
            fields['flight_number'] = fields['airspace_flight']
        return fields
    if not fields.get('airline'):
        fields['airline'] = airline
    if explicit:
        fields['flight_number'] = number
    elif 'flight_number' not in fields or not fields.get('flight_number'):
        fields['flight_number'] = number
    return fields


def clean_swap_id(value):
    """Return (swap_id, error). Error is None when the id can be stored."""
    if isinstance(value, bool) or isinstance(value, (list, tuple, dict)):
        return None, 'invalid swap_id'
    if value is None:
        return None, 'missing swap_id'
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if not value:
        return None, 'missing swap_id'
    if len(value) > _LIMITS['swap_id']:
        return None, 'swap_id too long'
    if any(ord(ch) < 32 for ch in value):
        return None, 'invalid swap_id'
    return value, None


def _raw_swap(row):
    for key, value in row.items():
        if norm_key(key) == 'swap_id':
            return value
    return None


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.conn = None
        self.kind = None
        self.url = None

    def init(self, url=None):
        with self.lock:
            self.url = os.environ.get('DATABASE_URL', '') if url is None else url
            self._close()
            self._open()
            self._exec(_SCHEMA)
            self._migrate()
            self._ensure_user_tables()
            self.conn.commit()

    def describe(self):
        return self.kind or 'unconnected'

    def close(self):
        with self.lock:
            self._close()

    def ping(self):
        with self.lock:
            self._ensure()
            self._exec('SELECT 1')
            self.conn.commit()

    def clear(self):
        with self.lock:
            self._ensure()
            self._exec('DELETE FROM moves')
            self.conn.commit()

    def list_moves(self):
        with self.lock:
            self._ensure()
            cols = ', '.join(FIELDS)
            rows = self._exec(f'SELECT {cols} FROM moves')
            self.conn.commit()
        rows.sort(key=lambda row: (row.get('pickup_date') or '9999-99-99', row.get('swap_id') or ''))
        return rows

    def get(self, swap_id):
        with self.lock:
            self._ensure()
            cols = ', '.join(FIELDS)
            rows = self._exec(f'SELECT {cols} FROM moves WHERE swap_id = ?', (swap_id,))
            self.conn.commit()
        return rows[0] if rows else None

    def ingest_moves(self, rows):
        return self._ingest(rows, 'moves')

    def ingest_airspace(self, rows):
        return self._ingest(rows, 'airspace')

    def update_team(self, swap_id, fields, editor):
        stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        sets = []
        params = []
        for key in EDITABLE:
            if key not in fields:
                continue
            sets.append(f'{key} = ?')
            params.append(fields[key])
        sets.append('edited_by = ?')
        sets.append('edited_at = ?')
        params.extend((editor, stamp, swap_id))
        with self.lock:
            self._ensure()
            found = self._exec('SELECT swap_id FROM moves WHERE swap_id = ?', (swap_id,))
            if not found:
                self.conn.commit()
                return None
            self._exec(f'UPDATE moves SET {", ".join(sets)} WHERE swap_id = ?', params)
            row = self._one(swap_id)
            self.conn.commit()
            return row

    def _ingest(self, rows, kind):
        columns = LOGISTICS if kind == 'moves' else AIRSPACE
        parser = parse_move if kind == 'moves' else parse_airspace
        inserted = updated = skipped = 0
        errors = []
        with self.lock:
            self._ensure()
            try:
                for index, row in enumerate(rows):
                    if not isinstance(row, dict):
                        skipped += 1
                        errors.append({'index': index, 'error': 'expected an object'})
                        continue
                    swap_id, err = clean_swap_id(_raw_swap(row))
                    if err:
                        skipped += 1
                        errors.append({'index': index, 'error': err})
                        continue
                    parsed = parser(row)
                    parsed['swap_id'] = swap_id
                    action = self._upsert(parsed, columns)
                    if action == 'inserted':
                        inserted += 1
                    else:
                        updated += 1
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise
        return {
            'ok': True,
            'inserted': inserted,
            'updated': updated,
            'skipped': skipped,
            'errors': errors,
        }

    def _upsert(self, fields, columns):
        swap_id = fields['swap_id']
        existing_rows = self._exec('SELECT * FROM moves WHERE swap_id = ?', (swap_id,))
        existing = existing_rows[0] if existing_rows else None
        method = (existing or {}).get('method') or fields.get('method')
        enrich_fillable_from_flight(fields, method)
        if existing is None:
            cols = ['swap_id']
            vals = [swap_id]
            for key in list(columns) + list(FILLABLE):
                if key not in fields or fields[key] is None:
                    continue
                cols.append(key)
                vals.append(fields[key])
            marks = ', '.join('?' for _ in cols)
            self._exec(
                f'INSERT INTO moves ({", ".join(cols)}) VALUES ({marks})',
                vals,
            )
            return 'inserted'
        sets = []
        params = []
        for key in columns:
            if key not in fields:
                continue
            if key == 'first_seen':
                # Keep the first non-empty sighting. A later blank, or a later
                # different date, does not move it.
                if existing.get('first_seen') or not fields[key]:
                    continue
            sets.append(f'{key} = ?')
            params.append(fields[key])
        # Ingest may fill commercial flight fields only when the stored value is empty.
        for key in FILLABLE:
            if key not in fields or not fields[key]:
                continue
            if existing.get(key):
                continue
            sets.append(f'{key} = ?')
            params.append(fields[key])
        if sets:
            params.append(swap_id)
            self._exec(f'UPDATE moves SET {", ".join(sets)} WHERE swap_id = ?', params)
        return 'updated'

    def _migrate(self):
        existing = {name.lower() for name in self._column_names()}
        for column in FIELDS:
            if column.lower() in existing:
                continue
            self._exec(f'ALTER TABLE moves ADD COLUMN {column} TEXT')

    def _column_names(self):
        if self.kind == 'postgres':
            rows = self._exec(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'moves'"
            )
            return [row['column_name'] for row in rows]
        rows = self._exec('PRAGMA table_info(moves)')
        return [row['name'] for row in rows]

    def _one(self, swap_id):
        cols = ', '.join(FIELDS)
        rows = self._exec(f'SELECT {cols} FROM moves WHERE swap_id = ?', (swap_id,))
        return rows[0] if rows else None

    def _ensure_user_tables(self):
        self._exec(_USER_SCHEMA)
        self._exec(_TOKEN_SCHEMA)
        self._exec('CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users (email)')

    def clear_users(self):
        with self.lock:
            self._ensure()
            self._exec('DELETE FROM setup_tokens')
            self._exec('DELETE FROM users')
            self.conn.commit()

    def create_user(self, name, email, password_hash, role='staff', status='pending'):
        user_id = secrets.token_urlsafe(16)
        now = _utc_stamp()
        with self.lock:
            self._ensure()
            self._exec(
                'INSERT INTO users (id, email, name, password_hash, role, status, created_at, last_login) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (user_id, email, name, password_hash, role, status, now, None),
            )
            row = self._user_row(user_id)
            self.conn.commit()
            return row

    def get_user(self, user_id):
        with self.lock:
            self._ensure()
            row = self._user_row(user_id)
            self.conn.commit()
            return row

    def get_user_by_email(self, email):
        email = (email or '').strip().lower()
        if not email:
            return None
        with self.lock:
            self._ensure()
            rows = self._exec('SELECT * FROM users WHERE email = ?', (email,))
            self.conn.commit()
            return rows[0] if rows else None

    def list_users(self):
        with self.lock:
            self._ensure()
            rows = self._exec('SELECT * FROM users')
            self.conn.commit()
        order = {'pending': 0, 'active': 1, 'disabled': 2}
        rows.sort(key=lambda row: (
            order.get(row.get('status') or '', 9),
            0 if (row.get('role') or '') == 'admin' else 1,
            row.get('created_at') or '',
            row.get('email') or '',
        ))
        return rows

    def admin_exists(self):
        with self.lock:
            self._ensure()
            rows = self._exec("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
            self.conn.commit()
            return bool(rows)

    def set_user_fields(self, user_id, **fields):
        allowed = {'name', 'password_hash', 'role', 'status', 'last_login'}
        sets = []
        params = []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f'cannot update {key}')
            sets.append(f'{key} = ?')
            params.append(value)
        if not sets:
            return self.get_user(user_id)
        params.append(user_id)
        with self.lock:
            self._ensure()
            found = self._exec('SELECT id FROM users WHERE id = ?', (user_id,))
            if not found:
                self.conn.commit()
                return None
            self._exec(f'UPDATE users SET {", ".join(sets)} WHERE id = ?', params)
            row = self._user_row(user_id)
            self.conn.commit()
            return row

    def delete_pending_user(self, user_id):
        with self.lock:
            self._ensure()
            rows = self._exec('SELECT id, status FROM users WHERE id = ?', (user_id,))
            if not rows or rows[0].get('status') != 'pending':
                self.conn.commit()
                return False
            self._exec('DELETE FROM setup_tokens WHERE user_id = ?', (user_id,))
            self._exec('DELETE FROM users WHERE id = ?', (user_id,))
            self.conn.commit()
            return True

    def promote_admin(self, email):
        user = self.get_user_by_email(email)
        if not user:
            return None
        return self.set_user_fields(user['id'], role='admin', status='active')

    def count_active_admins(self, exclude_id=None):
        with self.lock:
            self._ensure()
            rows = self._exec("SELECT id FROM users WHERE role = 'admin' AND status = 'active'")
            self.conn.commit()
        if exclude_id:
            rows = [row for row in rows if row['id'] != exclude_id]
        return len(rows)

    def mark_login(self, user_id):
        return self.set_user_fields(user_id, last_login=_utc_stamp())

    def create_setup_token(self, user_id):
        raw = secrets.token_urlsafe(32)
        token_hash = hash_token(raw)
        now = _utc_stamp()
        expires = _utc_stamp(days=7)
        with self.lock:
            self._ensure()
            found = self._exec('SELECT id FROM users WHERE id = ?', (user_id,))
            if not found:
                self.conn.commit()
                return None
            self._exec(
                'UPDATE setup_tokens SET used_at = ? WHERE user_id = ? AND used_at IS NULL',
                (now, user_id),
            )
            self._exec(
                'INSERT INTO setup_tokens (token_hash, user_id, expires_at, used_at) VALUES (?, ?, ?, ?)',
                (token_hash, user_id, expires, None),
            )
            self.conn.commit()
        return raw

    def lookup_setup_token(self, raw):
        token_hash = hash_token(raw or '')
        if not token_hash:
            return None
        now = _utc_stamp()
        with self.lock:
            self._ensure()
            rows = self._exec(
                'SELECT token_hash, user_id, expires_at, used_at FROM setup_tokens WHERE token_hash = ?',
                (token_hash,),
            )
            if not rows:
                self.conn.commit()
                return None
            row = rows[0]
            if row.get('used_at') or (row.get('expires_at') or '') < now:
                self.conn.commit()
                return None
            user = self._user_row(row['user_id'])
            self.conn.commit()
            return user

    def consume_setup_token(self, raw):
        token_hash = hash_token(raw or '')
        if not token_hash:
            return None
        now = _utc_stamp()
        with self.lock:
            self._ensure()
            rows = self._exec(
                'SELECT token_hash, user_id, expires_at, used_at FROM setup_tokens WHERE token_hash = ?',
                (token_hash,),
            )
            if not rows:
                self.conn.commit()
                return None
            row = rows[0]
            if row.get('used_at') or (row.get('expires_at') or '') < now:
                self.conn.commit()
                return None
            self._exec(
                'UPDATE setup_tokens SET used_at = ? WHERE token_hash = ?',
                (now, token_hash),
            )
            user = self._user_row(row['user_id'])
            self.conn.commit()
            return user

    def _user_row(self, user_id):
        rows = self._exec('SELECT * FROM users WHERE id = ?', (user_id,))
        return rows[0] if rows else None

    def _ensure(self):
        if self.conn is None:
            self._open()
            self._exec(_SCHEMA)
            self._migrate()
            self._ensure_user_tables()
            self.conn.commit()

    def _open(self):
        url = self.url or ''
        if url.startswith('postgres://') or url.startswith('postgresql://'):
            self.conn = _connect_postgres(url)
            self.kind = 'postgres'
            return
        path = _sqlite_path(url)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        import sqlite3
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute('PRAGMA busy_timeout = 5000')
        self.conn = conn
        self.kind = 'sqlite'

    def _close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
        self.conn = None

    def _exec(self, sql, params=()):
        statement = sql.replace('?', '%s') if self.kind == 'postgres' else sql
        cur = self.conn.cursor()
        cur.execute(statement, tuple(params))
        if not cur.description:
            return []
        names = []
        for col in cur.description:
            name = col[0]
            if isinstance(name, bytes):
                name = name.decode()
            names.append(name)
        rows = []
        for raw in cur.fetchall():
            item = {}
            for name, value in zip(names, raw):
                if isinstance(value, bytes):
                    value = value.decode()
                item[name] = value
            rows.append(item)
        return rows


def _sqlite_path(url):
    if not url:
        return DEFAULT_SQLITE
    if url.startswith('sqlite:///'):
        return url[len('sqlite:///'):]
    raise ValueError('DATABASE_URL must be postgres, postgresql, or sqlite')


def _connect_postgres(url):
    import pg8000.dbapi

    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    mode = (query.get('sslmode') or [''])[0]
    host = parsed.hostname or 'localhost'
    kwargs = dict(
        user=urllib.parse.unquote(parsed.username or ''),
        password=urllib.parse.unquote(parsed.password or '') or None,
        host=host,
        port=parsed.port or 5432,
        database=(parsed.path or '/').lstrip('/') or None,
        timeout=15,
    )
    # Render's internal hostname has no dots and stays on the private network.
    # External hosts (and an explicit sslmode) use TLS.
    needs_tls = mode != 'disable' and (
        ('.' in host and host not in ('localhost', '127.0.0.1'))
        or mode in ('require', 'verify-full', 'verify-ca')
    )
    if needs_tls:
        ctx = ssl.create_default_context()
        if mode != 'verify-full':
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
    return pg8000.dbapi.connect(**kwargs)



COUNT_METHODS = ('Commercial', 'Charter', 'OBC', 'Ground', 'Internal')

_METHOD_LABELS = {
    'commercial': 'Commercial',
    'charter': 'Charter',
    'commobc': 'OBC',
    'obc': 'OBC',
    'onboardcourier': 'OBC',
    'ground': 'Ground',
    'internal': 'Internal',
}


def method_label(method):
    """Canonical type label for UI and totals. CommObc is shown as OBC."""
    key = re.sub(r'[^a-z]', '', (method or '').lower())
    if key in _METHOD_LABELS:
        return _METHOD_LABELS[key]
    return method if method else 'Other'


def week_start_sunday(iso):
    """Sunday that starts the Eastern calendar week containing YYYY-MM-DD."""
    if not iso:
        return None
    year, month, day = (int(part) for part in str(iso).split('-')[:3])
    current = datetime(year, month, day, tzinfo=timezone.utc)
    offset = (current.weekday() + 1) % 7
    return (current - timedelta(days=offset)).date().isoformat()


def week_end_saturday(start_iso):
    if not start_iso:
        return None
    year, month, day = (int(part) for part in str(start_iso).split('-')[:3])
    end = datetime(year, month, day, tzinfo=timezone.utc) + timedelta(days=6)
    return end.date().isoformat()


def week_label(start_iso):
    """Short Eastern week label, e.g. 'Nov 22–28' or 'Nov 29–Dec 5'."""
    if not start_iso:
        return ''
    year, month, day = (int(part) for part in str(start_iso).split('-')[:3])
    start = datetime(year, month, day, tzinfo=timezone.utc)
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f'{start.strftime("%b")} {start.day}–{end.day}'
    return f'{start.strftime("%b")} {start.day}–{end.strftime("%b")} {end.day}'


def month_label(year_month):
    year, month = (int(part) for part in year_month.split('-')[:2])
    return datetime(year, month, 1, tzinfo=timezone.utc).strftime('%B %Y')


def _empty_counts():
    counts = {name: 0 for name in COUNT_METHODS}
    counts['Other'] = 0
    counts['removed'] = 0
    counts['total'] = 0
    return counts


def _count_move(bucket, move):
    label = method_label(move.get('method'))
    if label in COUNT_METHODS:
        bucket[label] += 1
    else:
        bucket['Other'] += 1
    bucket['total'] += 1
    if (move.get('status') or '').strip().lower() == 'removed':
        bucket['removed'] += 1


def month_totals(moves, include_removed=False):
    """Totals by pickup month. Completed + Scheduled; Removed optional."""
    buckets = {}
    for move in moves:
        date = (move.get('pickup_date') or '').strip()
        if len(date) < 7:
            continue
        removed = (move.get('status') or '').strip().lower() == 'removed'
        if removed and not include_removed:
            continue
        key = date[:7]
        bucket = buckets.setdefault(key, _empty_counts())
        _count_move(bucket, move)
    rows = []
    for key in sorted(buckets):
        row = {'month': key, 'label': month_label(key)}
        row.update(buckets[key])
        rows.append(row)
    return rows


def week_counts(moves, start_iso, include_removed=False):
    """Type counts for the Sunday–Saturday week starting at start_iso."""
    end_iso = week_end_saturday(start_iso)
    bucket = _empty_counts()
    rows = []
    for move in moves:
        date = (move.get('pickup_date') or '').strip()
        if not start_iso or not date or date < start_iso or date > end_iso:
            continue
        removed = (move.get('status') or '').strip().lower() == 'removed'
        if removed and not include_removed:
            continue
        _count_move(bucket, move)
        rows.append(move)
    return bucket, rows



def _utc_stamp(days=0):
    when = datetime.now(timezone.utc) + timedelta(days=days)
    return when.strftime('%Y-%m-%dT%H:%M:%SZ')


def hash_token(raw):
    text = (raw or '').strip()
    if not text:
        return ''
    return hashlib.sha256(text.encode()).hexdigest()


def public_user(row):
    if not row:
        return None
    return {
        'id': row.get('id'),
        'email': row.get('email'),
        'name': row.get('name'),
        'role': row.get('role'),
        'status': row.get('status'),
        'created_at': row.get('created_at'),
        'last_login': row.get('last_login'),
    }


store = Store()
