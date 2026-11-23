"""Dashboard tabs, week bounds, and month-by-month totals."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if 'server' not in sys.modules:
    handle = tempfile.NamedTemporaryFile(prefix='pf-tabs-', suffix='.sqlite', delete=False)
    handle.close()
    os.environ['DATABASE_URL'] = 'sqlite:///' + handle.name
    os.environ.setdefault('TEAM_PASSWORD', 'test-pass')
    os.environ.setdefault('INGEST_TOKEN', 'test-token')
    os.environ.setdefault('SECRET_KEY', 'test-secret')
    os.environ.pop('RENDER', None)

import server  # noqa: E402
from store import (  # noqa: E402
    method_label,
    month_totals,
    week_counts,
    week_end_saturday,
    week_label,
    week_start_sunday,
)


class WeekMonthHelpers(unittest.TestCase):
    def test_week_is_sunday_through_saturday(self):
        self.assertEqual(week_start_sunday('2026-11-22'), '2026-11-22')
        self.assertEqual(week_start_sunday('2026-11-23'), '2026-11-22')
        self.assertEqual(week_start_sunday('2026-11-28'), '2026-11-22')
        self.assertEqual(week_end_saturday('2026-11-22'), '2026-11-28')
        self.assertEqual(week_label('2026-11-22'), 'Nov 22–28')
        self.assertEqual(week_label('2026-11-29'), 'Nov 29–Dec 5')

    def test_method_label_maps_commobc_to_obc(self):
        self.assertEqual(method_label('CommObc'), 'OBC')
        self.assertEqual(method_label('OBC'), 'OBC')
        self.assertEqual(method_label('on-board courier'), 'OBC')
        self.assertEqual(method_label('Commercial'), 'Commercial')
        self.assertEqual(method_label('Charter'), 'Charter')

    def test_month_totals_exclude_removed_unless_asked(self):
        rows = [
            {'pickup_date': '2026-10-15', 'method': 'Commercial', 'status': 'Completed'},
            {'pickup_date': '2026-11-24', 'method': 'CommObc', 'status': 'Scheduled'},
            {'pickup_date': '2026-11-24', 'method': 'Ground', 'status': 'Removed'},
            {'pickup_date': '2026-11-25', 'method': 'Charter', 'status': 'Scheduled'},
            {'pickup_date': '', 'method': 'Ground', 'status': 'Scheduled'},
        ]
        months = month_totals(rows)
        self.assertEqual([row['month'] for row in months], ['2026-10', '2026-11'])
        october = months[0]
        self.assertEqual(october['label'], 'October 2026')
        self.assertEqual(october['Commercial'], 1)
        self.assertEqual(october['total'], 1)
        self.assertEqual(october['removed'], 0)
        november = months[1]
        self.assertEqual(november['label'], 'November 2026')
        self.assertEqual(november['OBC'], 1)
        self.assertEqual(november['Charter'], 1)
        self.assertEqual(november['Ground'], 0)
        self.assertEqual(november['total'], 2)
        self.assertEqual(november['removed'], 0)

        with_removed = month_totals(rows, include_removed=True)
        november = with_removed[1]
        self.assertEqual(november['Ground'], 1)
        self.assertEqual(november['total'], 3)
        self.assertEqual(november['removed'], 1)

        counts, week_rows = week_counts(rows, '2026-11-22')
        self.assertEqual(counts['OBC'], 1)
        self.assertEqual(counts['Charter'], 1)
        self.assertEqual(counts['Ground'], 0)
        self.assertEqual(counts['total'], 2)
        self.assertEqual({row['method'] for row in week_rows}, {'CommObc', 'Charter'})

        counts, week_rows = week_counts(rows, '2026-11-22', include_removed=True)
        self.assertEqual(counts['Ground'], 1)
        self.assertEqual(counts['total'], 3)
        self.assertEqual(counts['removed'], 1)


class TabPageTests(unittest.TestCase):
    def setUp(self):
        server.store.clear()
        self.client = server.app.test_client()

    def login(self, name='Alex'):
        response = self.client.post('/login', data={'name': name, 'password': 'test-pass'})
        self.assertEqual(response.status_code, 302)
        return response

    def test_dashboard_has_three_tabs_and_board_is_default(self):
        self.login()
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('id="tab-board"', html)
        self.assertIn('id="tab-nkr"', html)
        self.assertIn('id="tab-history"', html)
        self.assertIn('NKR Moves', html)
        self.assertIn('>History<', html)
        self.assertIn('id="panel-board"', html)
        self.assertIn('id="panel-nkr"', html)
        self.assertIn('id="panel-history"', html)
        self.assertIn('aria-selected="true"', html)
        self.assertIn('id="nkr-table"', html)
        self.assertIn('id="nkr-months"', html)
        self.assertIn('id="hist-table"', html)
        self.assertIn('Month-by-month totals', html)
        self.assertIn('Show removed', html)
        self.assertIn('Past dates', html)
        # Board is the default selected tab in the markup.
        self.assertIn('id="tab-board" aria-controls="panel-board" aria-selected="true"', html)
        self.assertIn('id="tab-nkr" aria-controls="panel-nkr" aria-selected="false"', html)
        self.assertIn('id="tab-history" aria-controls="panel-history" aria-selected="false"', html)
        self.assertIn('hidden', html)

    def test_tab_assets_are_served(self):
        self.login()
        js = self.client.get('/static/app.js')
        self.assertEqual(js.status_code, 200)
        body = js.get_data(as_text=True)
        self.assertIn('function renderNkr(', body)
        self.assertIn('function renderHistory(', body)
        self.assertIn('Show removed', self.client.get('/').get_data(as_text=True))
        self.assertIn('weekStartSunday', body)
        self.assertIn("method_label('CommObc')" if False else 'function methodLabel', body)
        self.assertIn("'OBC'", body)
        css = self.client.get('/static/app.css')
        self.assertEqual(css.status_code, 200)
        sheet = css.get_data(as_text=True)
        self.assertIn('.tabs', sheet)
        self.assertIn('table.moves', sheet)
        self.assertIn('body[data-tab="nkr"]', sheet)

    def test_history_payload_includes_completed_and_removed(self):
        self.login()
        rows = [
            {
                'swap_id': '10800/1/1',
                'pickup_date': '2026-11-20',
                'donor': 'BethIsrael',
                'recipient': 'UMinn',
                'method': 'Commercial',
                'pickup': '11/20 10:00 EST',
                'delivery': '11/20 16:15 CST',
                'status': 'Completed',
            },
            {
                'swap_id': '11487/1/3',
                'pickup_date': '2026-11-19',
                'donor': 'MayoAZ',
                'recipient': 'Madison',
                'method': 'Charter',
                'status': 'Removed',
            },
            {
                'swap_id': '11593/1/1',
                'pickup_date': '2026-11-24',
                'donor': 'UMinn',
                'recipient': 'Penn',
                'method': 'CommObc',
                'status': 'Scheduled',
            },
        ]
        ingest = self.client.post(
            '/api/ingest/moves',
            json=rows,
            headers={'Authorization': 'Bearer test-token'},
        )
        self.assertEqual(ingest.status_code, 200)
        payload = self.client.get('/api/moves').get_json()['moves']
        by_id = {row['swap_id']: row for row in payload}
        self.assertEqual(by_id['10800/1/1']['status'], 'Completed')
        self.assertEqual(by_id['11487/1/3']['status'], 'Removed')
        self.assertEqual(method_label(by_id['11593/1/1']['method']), 'OBC')
        totals = month_totals(payload)
        november = next(row for row in totals if row['month'] == '2026-11')
        self.assertEqual(november['Commercial'], 1)
        self.assertEqual(november['OBC'], 1)
        self.assertEqual(november['Charter'], 0)
        self.assertEqual(november['total'], 2)


if __name__ == '__main__':
    unittest.main()
