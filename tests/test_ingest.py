"""Ingest upsert: logistics refresh, team edits survive, rows are never deleted."""

import csv
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP = tempfile.NamedTemporaryFile(prefix='pf-test-', suffix='.sqlite', delete=False)
_TMP.close()
os.environ['DATABASE_URL'] = 'sqlite:///' + _TMP.name
os.environ['TEAM_PASSWORD'] = 'test-pass'
os.environ['INGEST_TOKEN'] = 'test-token'
os.environ['SECRET_KEY'] = 'test-secret'
os.environ.pop('RENDER', None)

import server  # noqa: E402
from store import FIELDS  # noqa: E402

TOKEN = {'Authorization': 'Bearer test-token'}

LEG = {
    'swap_id': '11593/1/1',
    'pickup_date': '2026-11-24',
    'donor': 'UMinn',
    'recipient': 'Penn',
    'method': 'CommObc',
    'pickup': '11/24 10:00 CST',
    'delivery': '11/24 18:15 EST',
    'status': 'Scheduled',
    'first_seen': '2026-11-20',
    'last_seen': '2026-11-22',
}


class IngestTests(unittest.TestCase):
    def setUp(self):
        server.store.clear()
        self.client = server.app.test_client()

    def ingest(self, rows, token='test-token'):
        headers = {'Authorization': 'Bearer ' + token} if token is not None else {}
        return self.client.post('/api/ingest/moves', json=rows, headers=headers)

    def air(self, rows):
        return self.client.post('/api/ingest/airspace', json=rows, headers=TOKEN)

    def login(self, name='Alex'):
        response = self.client.post('/login', data={'name': name, 'password': 'test-pass'})
        self.assertEqual(response.status_code, 302)
        return response

    def moves(self):
        response = self.client.get('/api/moves')
        self.assertEqual(response.status_code, 200)
        return response.get_json()['moves']

    def test_health_and_auth_gates(self):
        health = self.client.get('/healthz')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.data, b'ok\n')
        icon = self.client.get('/favicon.ico')
        self.assertEqual(icon.status_code, 200)
        self.assertIn(b'<svg', icon.data)

        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/api/moves').status_code, 401)
        self.assertEqual(self.client.get('/api/moves.csv').status_code, 401)
        self.assertEqual(self.ingest([LEG], token=None).status_code, 401)
        self.assertEqual(self.ingest([LEG], token='nope').status_code, 401)

        self.login()
        # A session cookie does not authorize ingest. The bearer token does not authorize reads.
        self.assertEqual(self.ingest([LEG], token=None).status_code, 401)
        bare = server.app.test_client()
        self.assertEqual(bare.get('/api/moves', headers=TOKEN).status_code, 401)

    def test_upsert_keeps_team_edits_and_other_rows(self):
        self.login()
        first = self.ingest([
            LEG,
            {
                'swap_id': '11487/1/2',
                'pickup_date': '2026-11-25',
                'donor': 'MayoAZ',
                'recipient': 'Madison',
                'method': 'Charter',
                'pickup': '11/25 10:00 MST',
                'delivery': '11/25 16:15 CST',
                'status': 'Scheduled',
                'first_seen': '',
                'last_seen': '2026-11-22',
            },
        ])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()['inserted'], 2)

        air = self.air([{
            'swap_id': '11593/1/1',
            'airspace_order_id': 'AS-100',
            'driver_names': ['Sam Ruiz', 'Jo Park'],
            'flight_number': 'DL 1842',
            'awb': '001-12345678',
            'airspace_status': 'Tendered',
        }])
        self.assertEqual(air.get_json()['updated'], 1)

        edited = self.client.patch('/api/moves', json={
            'swap_id': '11593/1/1',
            'assigned_to': 'Alex Rivera',
            'aircraft': '',
            'phone': '555-0100',
            'notes': 'Wheels up 10:15',
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.get_json()['move']['assigned_to'], 'Alex Rivera')
        self.assertEqual(edited.get_json()['move']['edited_by'], 'Alex')
        self.assertIsNone(edited.get_json()['move']['aircraft'])

        # Re-ingest tries to clobber team fields and airspace, and blanks first_seen.
        again = self.ingest([{
            **LEG,
            'donor': 'UMinn-East',
            'status': 'Completed',
            'first_seen': '',
            'last_seen': '2026-11-23',
            'assigned_to': 'Somebody Else',
            'phone': '000',
            'notes': 'ignore me',
            'airspace_driver': 'Wrong Driver',
            'airspace_flight': 'XX 1',
        }])
        self.assertEqual(again.get_json()['updated'], 1)
        self.assertEqual(again.get_json()['inserted'], 0)

        # A payload that omits the charter must not delete it.
        self.assertEqual(len(self.moves()), 2)
        leg = next(row for row in self.moves() if row['swap_id'] == '11593/1/1')
        self.assertEqual(set(leg.keys()), set(FIELDS))
        self.assertEqual(leg['donor'], 'UMinn-East')
        self.assertEqual(leg['status'], 'Completed')
        self.assertEqual(leg['method'], 'CommObc')
        self.assertEqual(leg['first_seen'], '2026-11-20')
        self.assertEqual(leg['last_seen'], '2026-11-23')
        self.assertEqual(leg['assigned_to'], 'Alex Rivera')
        self.assertEqual(leg['phone'], '555-0100')
        self.assertEqual(leg['notes'], 'Wheels up 10:15')
        self.assertEqual(leg['edited_by'], 'Alex')
        self.assertTrue(leg['edited_at'])
        self.assertEqual(leg['airspace_driver'], 'Sam Ruiz, Jo Park')
        self.assertEqual(leg['airspace_flight'], 'DL 1842')
        self.assertEqual(leg['airspace_awb'], '001-12345678')
        self.assertEqual(leg['airspace_status'], 'Tendered')

        # Airspace refresh does not touch logistics or the crew assignment.
        follow = self.air({
            'orders': [{
                'swap_id': '11593/1/1',
                'driver': 'Sam Ruiz',
                'status': 'Recovered',
                'assigned_to': 'Nope',
                'donor': 'Nope',
            }],
        })
        self.assertEqual(follow.status_code, 200)
        leg = next(row for row in self.moves() if row['swap_id'] == '11593/1/1')
        self.assertEqual(leg['airspace_driver'], 'Sam Ruiz')
        self.assertEqual(leg['airspace_status'], 'Recovered')
        self.assertEqual(leg['airspace_flight'], 'DL 1842')
        self.assertEqual(leg['donor'], 'UMinn-East')
        self.assertEqual(leg['assigned_to'], 'Alex Rivera')

        # first_seen sticks even when a later payload offers a different date.
        self.ingest([{**LEG, 'first_seen': '2026-12-01', 'donor': 'UMinn-East'}])
        leg = next(row for row in self.moves() if row['swap_id'] == '11593/1/1')
        self.assertEqual(leg['first_seen'], '2026-11-20')

        exported = self.client.get('/api/moves.csv')
        self.assertEqual(exported.status_code, 200)
        self.assertIn('text/csv', exported.content_type)
        rows = list(csv.DictReader(io.StringIO(exported.data.decode('utf-8-sig'))))
        match = next(row for row in rows if row['swap_id'] == '11593/1/1')
        self.assertEqual(match['assigned_to'], 'Alex Rivera')
        self.assertEqual(match['method'], 'CommObc')

    def test_airspace_can_arrive_before_the_leg(self):
        created = self.air([{'swap_id': '90001/1/1', 'flight': 'PF 12', 'order_id': 'AS-9'}])
        self.assertEqual(created.get_json()['inserted'], 1)
        self.login()
        row = self.moves()[0]
        self.assertEqual(row['swap_id'], '90001/1/1')
        self.assertIsNone(row['donor'])
        self.assertEqual(row['airspace_flight'], 'PF 12')
        self.assertEqual(row['airspace_order_id'], 'AS-9')

        filled = self.ingest([{
            'swap_id': '90001/1/1',
            'donor_center': 'Center A',
            'recipient_center': 'Center B',
            'method': 'Charter',
            'status': 'Scheduled',
            'pickup_date': '2026-12-01',
        }])
        self.assertEqual(filled.get_json()['updated'], 1)
        row = self.moves()[0]
        self.assertEqual(row['donor'], 'Center A')
        self.assertEqual(row['recipient'], 'Center B')
        self.assertEqual(row['airspace_flight'], 'PF 12')
        self.assertIsNone(row['assigned_to'])

    def test_partial_update_and_unknown_edit(self):
        self.ingest([LEG])
        self.login('Jordan Lee')
        only_status = self.ingest([{'swap_id': '11593/1/1', 'status': 'Removed'}])
        self.assertEqual(only_status.get_json()['updated'], 1)
        row = self.moves()[0]
        self.assertEqual(row['status'], 'Removed')
        self.assertEqual(row['donor'], 'UMinn')

        missing = self.client.patch('/api/moves', json={'swap_id': 'nope/1/1', 'notes': 'x'})
        self.assertEqual(missing.status_code, 404)
        empty = self.client.patch('/api/moves', json={'swap_id': '11593/1/1'})
        self.assertEqual(empty.status_code, 400)


if __name__ == '__main__':
    unittest.main()
