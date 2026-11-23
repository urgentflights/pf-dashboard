"""PF Dashboard trips: create, edit, cancel, delete, auth, and pages."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if 'server' not in sys.modules:
    handle = tempfile.NamedTemporaryFile(prefix='pf-trips-', suffix='.sqlite', delete=False)
    handle.close()
    os.environ['DATABASE_URL'] = 'sqlite:///' + handle.name
    os.environ.setdefault('TEAM_PASSWORD', 'test-pass')
    os.environ['ALLOW_TEAM_PASSWORD'] = '1'
    os.environ.setdefault('INGEST_TOKEN', 'test-token')
    os.environ.setdefault('SECRET_KEY', 'test-secret')
    os.environ.pop('RENDER', None)

import server  # noqa: E402
from store import parse_trip, store, trip_month_totals  # noqa: E402


TRIP = {
    'trip_type': 'Organ',
    'client': 'Regional Organ Bank',
    'trip_date': '2026-11-26',
    'origin': 'TEB',
    'destination': 'PIT',
    'pickup_time': '09:00 ET',
    'delivery_time': '11:30 ET',
    'mode': 'Charter',
    'operator_aircraft': 'N123PF',
    'assigned_to': 'Jordan Lee',
    'status': 'Booked',
    'phone': '201-555-0100',
    'notes': 'Kidneys on board. Crew staging at 07:30.',
}


class TripParseTests(unittest.TestCase):
    def test_requires_type_and_normalizes_aliases(self):
        fields, err = parse_trip({})
        self.assertEqual(err, 'trip_type is required')
        self.assertEqual(fields, {})

        fields, err = parse_trip({'type': 'air ambulance', 'customer': 'Acme', 'from': 'JFK', 'to': 'LAX', 'date': '2026-12-01'})
        self.assertIsNone(err)
        self.assertEqual(fields['trip_type'], 'Air Ambulance')
        self.assertEqual(fields['client'], 'Acme')
        self.assertEqual(fields['origin'], 'JFK')
        self.assertEqual(fields['destination'], 'LAX')
        self.assertEqual(fields['trip_date'], '2026-12-01')
        self.assertEqual(fields['status'], 'Quote')

        _, err = parse_trip({'trip_type': 'Cruise'})
        self.assertEqual(err, 'trip_type must be Organ, Air Ambulance, or Corporate')
        _, err = parse_trip({'trip_type': 'Corporate', 'mode': 'Ferry'})
        self.assertEqual(err, 'mode must be Charter, Commercial, OBC, or Ground')
        _, err = parse_trip({'trip_type': 'Corporate', 'status': 'Maybe'})
        self.assertEqual(err, 'status must be Quote, Booked, In progress, Completed, or Cancelled')
        _, err = parse_trip({'trip_type': 'Organ', 'trip_date': '11/26/2026'})
        self.assertEqual(err, 'trip_date must be YYYY-MM-DD')
        _, err = parse_trip({'trip_type': 'Organ', 'trip_date': '2026-13-40'})
        self.assertEqual(err, 'trip_date must be YYYY-MM-DD')

    def test_partial_update_can_omit_type(self):
        fields, err = parse_trip({'status': 'Cancelled'}, partial=True)
        self.assertIsNone(err)
        self.assertEqual(fields, {'status': 'Cancelled'})

    def test_month_totals(self):
        rows = [
            {'trip_date': '2026-11-26', 'trip_type': 'Organ'},
            {'trip_date': '2026-11-27', 'trip_type': 'Corporate'},
            {'trip_date': '2026-12-01', 'trip_type': 'Air Ambulance'},
            {'trip_date': '', 'trip_type': 'Organ'},
        ]
        months = trip_month_totals(rows)
        self.assertEqual([row['month'] for row in months], ['2026-11', '2026-12'])
        self.assertEqual(months[0]['Organ'], 1)
        self.assertEqual(months[0]['Corporate'], 1)
        self.assertEqual(months[0]['total'], 2)
        self.assertEqual(months[1]['Air Ambulance'], 1)
        self.assertEqual(months[1]['label'], 'December 2026')


class TripApiTests(unittest.TestCase):
    def setUp(self):
        os.environ['ALLOW_TEAM_PASSWORD'] = '1'
        store.clear()
        store.clear_trips()
        store.clear_users()
        server._FAILS.clear()
        self.client = server.app.test_client()

    def login(self, name='Alex'):
        response = self.client.post('/login', data={'name': name, 'password': 'test-pass'})
        self.assertEqual(response.status_code, 302)
        return response

    def make_admin(self, name='Sim Shain', email='sim@paraflight.aero', password='adminpass1'):
        if not store.get_user_by_email(email):
            self.client.post('/signup', data={
                'name': name,
                'email': email,
                'password': password,
                'confirm': password,
            })
        store.promote_admin(email)
        client = server.app.test_client()
        response = client.post('/login', data={'email': email, 'password': password})
        self.assertEqual(response.status_code, 302)
        return client

    def make_staff(self, name='Alex Rivera', email='alex@paraflight.aero', password='secret123'):
        admin = self.make_admin()
        self.client.post('/signup', data={
            'name': name,
            'email': email,
            'password': password,
            'confirm': password,
        })
        user = store.get_user_by_email(email)
        admin.post('/admin', data={'user_id': user['id'], 'action': 'approve'})
        client = server.app.test_client()
        response = client.post('/login', data={'email': email, 'password': password})
        self.assertEqual(response.status_code, 302)
        return client

    def test_auth_required_for_pages_and_api(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/nkr').status_code, 302)
        self.assertEqual(self.client.get('/pf').status_code, 302)
        self.assertEqual(self.client.get('/api/trips').status_code, 401)
        self.assertEqual(self.client.get('/api/trips.csv').status_code, 401)
        self.assertEqual(self.client.post('/api/trips', json=TRIP).status_code, 401)

    def test_staff_can_create_edit_and_cancel(self):
        self.login('Alex')
        created = self.client.post('/api/trips', json=TRIP)
        self.assertEqual(created.status_code, 201)
        body = created.get_json()
        self.assertTrue(body['ok'])
        trip = body['trip']
        trip_id = trip['id']
        self.assertTrue(trip_id)
        self.assertEqual(trip['trip_type'], 'Organ')
        self.assertEqual(trip['client'], 'Regional Organ Bank')
        self.assertEqual(trip['mode'], 'Charter')
        self.assertEqual(trip['operator_aircraft'], 'N123PF')
        self.assertEqual(trip['created_by'], 'Alex')
        self.assertEqual(trip['edited_by'], 'Alex')
        self.assertTrue(trip['created_at'])
        self.assertEqual(trip['notes'], TRIP['notes'])

        listed = self.client.get('/api/trips').get_json()
        self.assertEqual(listed['timezone'], 'America/New_York')
        self.assertEqual(len(listed['trips']), 1)
        self.assertEqual(listed['trips'][0]['id'], trip_id)
        self.assertEqual(listed['months'][0]['Organ'], 1)

        patched = self.client.patch(
            '/api/trips/' + trip_id,
            json={'assigned_to': 'Sam Chen', 'status': 'In progress', 'notes': 'Wheels up'},
        )
        self.assertEqual(patched.status_code, 200)
        updated = patched.get_json()['trip']
        self.assertEqual(updated['assigned_to'], 'Sam Chen')
        self.assertEqual(updated['status'], 'In progress')
        self.assertEqual(updated['client'], 'Regional Organ Bank')
        self.assertEqual(updated['edited_by'], 'Alex')

        cancelled = self.client.patch('/api/trips/' + trip_id, json={'status': 'Cancelled'})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()['trip']['status'], 'Cancelled')

    def test_staff_cannot_delete_admin_can(self):
        staff = self.make_staff()
        created = staff.post('/api/trips', json={'trip_type': 'Corporate', 'client': 'Acme Co', 'trip_date': '2026-12-02'})
        self.assertEqual(created.status_code, 201)
        trip_id = created.get_json()['trip']['id']
        self.assertEqual(created.get_json()['trip']['created_by'], 'Alex Rivera')

        denied = staff.delete('/api/trips/' + trip_id)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(denied.get_json(), {'error': 'forbidden'})
        self.assertIsNotNone(store.get_trip(trip_id))

        admin = self.make_admin()
        missing = admin.delete('/api/trips/does-not-exist')
        self.assertEqual(missing.status_code, 404)
        deleted = admin.delete('/api/trips/' + trip_id)
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.get_json(), {'ok': True})
        self.assertIsNone(store.get_trip(trip_id))
        self.assertEqual(admin.get('/api/trips').get_json()['trips'], [])

    def test_validation_and_csv(self):
        self.login()
        bad = self.client.post('/api/trips', json={'client': 'Nobody'})
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.get_json()['error'], 'trip_type is required')

        commercial = self.client.post('/api/trips', json={
            'trip_type': 'Corporate',
            'client': 'Northwind',
            'trip_date': '2026-12-03',
            'origin': 'JFK',
            'destination': 'SFO',
            'mode': 'Commercial',
            'airline': 'UA',
            'flight_number': '15',
            'departure_time': '08:15',
            'departure_airport': 'JFK',
            'departure_terminal': '8',
            'status': 'Booked',
        })
        self.assertEqual(commercial.status_code, 201)
        trip = commercial.get_json()['trip']
        self.assertEqual(trip['airline'], 'UA')
        self.assertEqual(trip['departure_terminal'], '8')

        csv_resp = self.client.get('/api/trips.csv')
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn('text/csv', csv_resp.mimetype)
        text = csv_resp.get_data(as_text=True)
        self.assertIn('trip_type,client,trip_date', text.replace(' ', ''))
        self.assertIn('Northwind', text)
        self.assertIn('UA', text)
        self.assertIn('pf-trips.csv', csv_resp.headers.get('Content-Disposition', ''))

        unknown = self.client.patch('/api/trips/missing', json={'notes': 'x'})
        self.assertEqual(unknown.status_code, 404)

    def test_pages_and_existing_nkr_urls_still_work(self):
        self.login()
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'NKR Dashboard', home.data)
        self.assertIn(b'PF Dashboard', home.data)

        nkr = self.client.get('/nkr')
        self.assertEqual(nkr.status_code, 200)
        html = nkr.get_data(as_text=True)
        self.assertIn('NKR Dashboard', html)
        self.assertIn('id="tab-board"', html)
        self.assertIn('id="tab-nkr"', html)
        self.assertIn('id="tab-history"', html)
        self.assertIn('href="/pf"', html)

        pf = self.client.get('/pf')
        self.assertEqual(pf.status_code, 200)
        page = pf.get_data(as_text=True)
        self.assertIn('PF Dashboard', page)
        self.assertIn('id="tab-board"', page)
        self.assertIn('id="tab-history"', page)
        self.assertIn('Add trip', page)
        self.assertIn('/api/trips.csv', page)
        self.assertIn('/static/pf.js', page)
        self.assertNotIn('id="tab-nkr"', page)

        js = self.client.get('/static/pf.js')
        self.assertEqual(js.status_code, 200)
        body = js.get_data(as_text=True)
        self.assertIn("fetch('/api/trips'", body)
        self.assertIn('Cancel trip', body)
        self.assertIn('DELETE', body)


if __name__ == '__main__':
    unittest.main()
