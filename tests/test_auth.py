"""Staff accounts: signup, approval, login, admin access, and one-time tokens."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if 'server' not in sys.modules:
    handle = tempfile.NamedTemporaryFile(prefix='pf-auth-', suffix='.sqlite', delete=False)
    handle.close()
    os.environ['DATABASE_URL'] = 'sqlite:///' + handle.name
    os.environ.setdefault('TEAM_PASSWORD', 'test-pass')
    os.environ.setdefault('INGEST_TOKEN', 'test-token')
    os.environ.setdefault('SECRET_KEY', 'test-secret')
    os.environ.pop('RENDER', None)

os.environ.pop('ADMIN_EMAIL', None)

import server  # noqa: E402
from store import store  # noqa: E402

TOKEN = {'Authorization': 'Bearer test-token'}


class AuthTests(unittest.TestCase):
    def setUp(self):
        store.clear()
        store.clear_users()
        server._FAILS.clear()
        os.environ['ALLOW_TEAM_PASSWORD'] = '0'
        os.environ.pop('ADMIN_EMAIL', None)
        self.client = server.app.test_client()

    def tearDown(self):
        os.environ['ALLOW_TEAM_PASSWORD'] = '1'
        os.environ.pop('ADMIN_EMAIL', None)
        store.clear_users()

    def signup(self, name='Alex Rivera', email='alex@paraflight.aero', password='secret123', confirm=None, client=None):
        client = client or self.client
        return client.post('/signup', data={
            'name': name,
            'email': email,
            'password': password,
            'confirm': password if confirm is None else confirm,
        })

    def login(self, email='alex@paraflight.aero', password='secret123', client=None):
        client = client or self.client
        return client.post('/login', data={'email': email, 'password': password})

    def approve(self, email, admin_client=None):
        user = store.get_user_by_email(email)
        self.assertIsNotNone(user)
        client = admin_client or self.client
        return client.post('/admin', data={'user_id': user['id'], 'action': 'approve'})

    def make_admin(self, name='Sim Shain', email='sim@paraflight.aero', password='adminpass1'):
        self.signup(name=name, email=email, password=password)
        store.promote_admin(email)
        client = server.app.test_client()
        response = self.login(email=email, password=password, client=client)
        self.assertEqual(response.status_code, 302)
        return client

    def test_signup_pending_approve_login(self):
        created = self.signup()
        self.assertEqual(created.status_code, 200)
        self.assertIn(b'waiting for admin approval', created.data)
        user = store.get_user_by_email('alex@paraflight.aero')
        self.assertEqual(user['status'], 'pending')
        self.assertEqual(user['role'], 'staff')

        blocked = self.login()
        self.assertEqual(blocked.status_code, 401)
        self.assertIn(b'waiting for admin approval', blocked.data)
        self.assertEqual(self.client.get('/api/moves').status_code, 401)

        admin = self.make_admin()
        approved = self.approve('alex@paraflight.aero', admin_client=admin)
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(store.get_user_by_email('alex@paraflight.aero')['status'], 'active')

        staff = server.app.test_client()
        signed_in = self.login(client=staff)
        self.assertEqual(signed_in.status_code, 302)
        moves = staff.get('/api/moves')
        self.assertEqual(moves.status_code, 200)
        home = staff.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'Alex Rivera', home.data)
        self.assertNotIn(b'href="/admin"', home.data)

    def test_disabled_cannot_login(self):
        admin = self.make_admin()
        self.signup()
        self.approve('alex@paraflight.aero', admin_client=admin)
        user = store.get_user_by_email('alex@paraflight.aero')
        disabled = admin.post('/admin', data={'user_id': user['id'], 'action': 'disable'})
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(store.get_user_by_email('alex@paraflight.aero')['status'], 'disabled')

        staff = server.app.test_client()
        denied = self.login(client=staff)
        self.assertEqual(denied.status_code, 401)
        self.assertIn(b'disabled', denied.data)
        self.assertEqual(staff.get('/api/moves').status_code, 401)

    def test_non_admin_cannot_reach_admin(self):
        admin = self.make_admin()
        self.signup()
        self.approve('alex@paraflight.aero', admin_client=admin)
        staff = server.app.test_client()
        self.assertEqual(self.login(client=staff).status_code, 302)
        page = staff.get('/admin')
        self.assertEqual(page.status_code, 403)
        self.assertIn(b'Admin only', page.data)
        action = staff.post('/admin', data={
            'user_id': store.get_user_by_email('sim@paraflight.aero')['id'],
            'action': 'disable',
        })
        self.assertEqual(action.status_code, 403)
        self.assertEqual(store.get_user_by_email('sim@paraflight.aero')['status'], 'active')

    def test_setup_token_is_one_time(self):
        admin = self.make_admin()
        self.signup()
        self.approve('alex@paraflight.aero', admin_client=admin)
        user = store.get_user_by_email('alex@paraflight.aero')
        reset = admin.post('/admin', data={'user_id': user['id'], 'action': 'reset'})
        self.assertEqual(reset.status_code, 200)
        # The raw token appears only in the admin page reset link.
        html = reset.get_data(as_text=True)
        self.assertIn('/setup?token=', html)
        start = html.index('/setup?token=')
        end = html.index('"', start)
        link = html[start:end]
        token = parse_qs(urlparse(link).query)['token'][0]

        form = self.client.get('/setup', query_string={'token': token})
        self.assertEqual(form.status_code, 200)
        saved = self.client.post('/setup', data={
            'token': token,
            'password': 'newsecret1',
            'confirm': 'newsecret1',
        })
        self.assertEqual(saved.status_code, 302)

        reuse = self.client.post('/setup', data={
            'token': token,
            'password': 'anothersecret',
            'confirm': 'anothersecret',
        })
        self.assertEqual(reuse.status_code, 400)
        self.assertIn(b'invalid or has expired', reuse.data)

        staff = server.app.test_client()
        self.assertEqual(self.login(password='secret123', client=staff).status_code, 401)
        self.assertEqual(self.login(password='newsecret1', client=staff).status_code, 302)

    def test_admin_email_auto_activates_when_no_admin_exists(self):
        os.environ['ADMIN_EMAIL'] = 'Sim@paraflight.aero'
        created = self.signup(name='Sim Shain', email='sim@paraflight.aero', password='adminpass1')
        self.assertEqual(created.status_code, 302)
        self.assertTrue(created.headers['Location'].endswith('/login?ready=1'))
        user = store.get_user_by_email('Sim@paraflight.aero')
        self.assertEqual(user['role'], 'admin')
        self.assertEqual(user['status'], 'active')
        signed_in = self.login(email='sim@paraflight.aero', password='adminpass1')
        self.assertEqual(signed_in.status_code, 302)
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'href="/admin"', home.data)
        self.assertIn(b'Sim Shain', home.data)

        later = self.signup(name='Other Admin', email='other@paraflight.aero', password='otherpass1')
        # ADMIN_EMAIL only matches Sim's address; a second signup stays pending.
        self.assertEqual(later.status_code, 200)
        self.assertEqual(store.get_user_by_email('other@paraflight.aero')['status'], 'pending')
        self.assertEqual(store.get_user_by_email('other@paraflight.aero')['role'], 'staff')

    def test_bootstrap_promotes_existing_user_only(self):
        self.signup()
        missing = self.client.post(
            '/api/admin/bootstrap',
            json={'email': 'sim@paraflight.aero'},
            headers=TOKEN,
        )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json(), {'ok': False, 'error': 'not_found'})
        self.assertIsNone(store.get_user_by_email('sim@paraflight.aero'))

        unauthorized = self.client.post(
            '/api/admin/bootstrap',
            json={'email': 'alex@paraflight.aero'},
        )
        self.assertEqual(unauthorized.status_code, 401)

        promoted = self.client.post(
            '/api/admin/bootstrap',
            json={'email': 'Alex@paraflight.aero'},
            headers=TOKEN,
        )
        self.assertEqual(promoted.status_code, 200)
        body = promoted.get_json()
        self.assertEqual(body['ok'], True)
        self.assertEqual(body['email'], 'alex@paraflight.aero')
        self.assertEqual(body['role'], 'admin')
        self.assertEqual(body['status'], 'active')
        self.assertNotIn('token', body)
        self.assertNotIn('link', str(body).lower())
        user = store.get_user_by_email('alex@paraflight.aero')
        self.assertEqual(user['role'], 'admin')
        self.assertEqual(user['status'], 'active')

        staff = server.app.test_client()
        self.assertEqual(self.login(client=staff).status_code, 302)
        page = staff.get('/admin')
        self.assertEqual(page.status_code, 200)

    def test_shared_password_is_off_by_default(self):
        os.environ['ALLOW_TEAM_PASSWORD'] = '0'
        denied = self.client.post('/login', data={'name': 'Alex', 'password': 'test-pass'})
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(self.client.get('/api/moves').status_code, 401)
        page = self.client.get('/login')
        self.assertNotIn(b'team password', page.data.lower())

        os.environ['ALLOW_TEAM_PASSWORD'] = '1'
        allowed = self.client.post('/login', data={'name': 'Alex', 'password': 'test-pass'})
        self.assertEqual(allowed.status_code, 302)
        self.assertEqual(self.client.get('/api/moves').status_code, 200)

    def test_edits_stamp_account_name(self):
        admin = self.make_admin()
        self.signup()
        self.approve('alex@paraflight.aero', admin_client=admin)
        admin.post('/api/ingest/moves', json=[{
            'swap_id': '11593/1/1',
            'pickup_date': '2026-11-24',
            'donor': 'UMinn',
            'recipient': 'Penn',
            'method': 'CommObc',
            'status': 'Scheduled',
        }], headers=TOKEN)
        staff = server.app.test_client()
        self.assertEqual(self.login(client=staff).status_code, 302)
        edited = staff.patch('/api/moves', json={'swap_id': '11593/1/1', 'notes': 'On it'})
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.get_json()['move']['edited_by'], 'Alex Rivera')

    def test_public_pages_and_disabled_session(self):
        self.assertEqual(self.client.get('/signup').status_code, 200)
        self.assertEqual(self.client.get('/login').status_code, 200)
        self.assertEqual(self.client.get('/setup', query_string={'token': 'nope'}).status_code, 400)
        self.assertEqual(self.client.get('/admin').status_code, 302)

        admin = self.make_admin()
        self.signup()
        self.approve('alex@paraflight.aero', admin_client=admin)
        staff = server.app.test_client()
        self.assertEqual(self.login(client=staff).status_code, 302)
        user = store.get_user_by_email('alex@paraflight.aero')
        admin.post('/admin', data={'user_id': user['id'], 'action': 'disable'})
        self.assertEqual(staff.get('/api/moves').status_code, 401)
        self.assertEqual(staff.get('/').status_code, 302)


if __name__ == '__main__':
    unittest.main()
