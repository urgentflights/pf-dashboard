"""Move storage for PF Dashboard.

Render sets DATABASE_URL to Postgres. With no DATABASE_URL, or a sqlite:// URL,
the app uses a local SQLite file so it can run on a laptop. Ingest updates
logistics columns only. Team-edited columns are never written by ingest.
"""

import os
import ssl
import threading
import urllib.parse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')

FIELDS = (
    'swap_id', 'pickup_date', 'donor', 'recipient', 'method', 'pickup', 'delivery',
    'status', 'first_seen', 'last_seen',
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

TEAM = ('assigned_to', 'aircraft', 'phone', 'notes')

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
)

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
    return _pick(row, _MOVE_ALIASES)


def parse_airspace(row):
    return _pick(row, _AIR_ALIASES)


def parse_team(row):
    return _pick(row, _TEAM_ALIASES)


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
        for key in TEAM:
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
        if existing is None:
            cols = ['swap_id']
            vals = [swap_id]
            for key in columns:
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
        if sets:
            params.append(swap_id)
            self._exec(f'UPDATE moves SET {", ".join(sets)} WHERE swap_id = ?', params)
        return 'updated'

    def _one(self, swap_id):
        cols = ', '.join(FIELDS)
        rows = self._exec(f'SELECT {cols} FROM moves WHERE swap_id = ?', (swap_id,))
        return rows[0] if rows else None

    def _ensure(self):
        if self.conn is None:
            self._open()
            self._exec(_SCHEMA)
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


store = Store()
