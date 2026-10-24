import copy
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from discord_archive.export_schedule import (
    AUTO_EXPORT_DEFAULTS,
    latest_export_slot,
    next_export_at,
    normalize_auto_export,
)


def moment(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def config(**changes):
    result = {'market_timezone': 'America/New_York', 'day_boundary_hour': 4,
        'auto_export': {'enabled': True}}
    result['auto_export'].update(changes)
    return result


class NormalizeAutoExportTests(unittest.TestCase):
    def test_defaults_are_complete_and_independent(self):
        normalized = normalize_auto_export()
        self.assertEqual(normalized, AUTO_EXPORT_DEFAULTS)
        normalized['times'].append('17:00')
        normalized['weekdays'].append(6)
        normalized['render_scales'].append(2)
        self.assertEqual(AUTO_EXPORT_DEFAULTS['times'], ['16:15'])
        self.assertEqual(AUTO_EXPORT_DEFAULTS['weekdays'], [0, 1, 2, 3, 4])
        self.assertEqual(AUTO_EXPORT_DEFAULTS['render_scales'], [1])

    def test_partial_settings_fill_defaults_without_mutating_input(self):
        saved = {'enabled': True, 'times': ['16:15', '10:30', '16:15'],
            'weekdays': [4, 0, 4], 'render_scales': [2, 1, 2]}
        before = copy.deepcopy(saved)
        result = normalize_auto_export(saved)
        self.assertEqual(result['times'], ['10:30', '16:15'])
        self.assertEqual(result['weekdays'], [0, 4])
        self.assertEqual(result['render_scales'], [1, 2])
        self.assertEqual(result['layout'], 'horizontal')
        self.assertEqual(result['presentation'], 'reading')
        self.assertEqual(result['target'], 'main')
        self.assertEqual(saved, before)

    def test_all_supported_output_choices(self):
        for layout in ('horizontal', 'stacked', 'collage', 'qa', 'board'):
            self.assertEqual(normalize_auto_export({'layout': layout})['layout'], layout)
        for scales in ([1], [2], [1, 2]):
            self.assertEqual(normalize_auto_export({'render_scales': scales})['render_scales'], scales)
        for presentation in ('reading', 'full'):
            self.assertEqual(normalize_auto_export({'presentation': presentation})['presentation'], presentation)
        for target in ('main', 'all'):
            self.assertEqual(normalize_auto_export({'target': target})['target'], target)

    def test_invalid_settings_are_rejected_strictly(self):
        invalid = [False, [], 'settings', {'enabled': 1}, {'enabled': 'true'}, {'enabled': None},
            {'times': []}, {'times': '16:15'}, {'times': ['9:30']}, {'times': ['24:00']},
            {'times': ['16:60']}, {'times': ['16:15\n']}, {'times': ['１６:１５']}, {'times': [1]},
            {'times': ['16:15'] * 25}, {'weekdays': []}, {'weekdays': [7]}, {'weekdays': [-1]},
            {'weekdays': [True]}, {'weekdays': ['0']}, {'weekdays': (0, 1)},
            {'render_scales': []}, {'render_scales': [True]}, {'render_scales': [0]},
            {'render_scales': [3]}, {'render_scales': ['1']}, {'render_scales': 1},
            {'layout': 'wide'}, {'presentation': 'summary'}, {'target': 'mobile'}]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_auto_export(value)


class ExportSlotTests(unittest.TestCase):
    def test_disabled_schedule_returns_none_without_parsing_time(self):
        for saved in ({}, {'auto_export': {'enabled': False}}):
            self.assertIsNone(latest_export_slot(saved, 'invalid'))
            self.assertIsNone(next_export_at(saved, 'invalid'))

    def test_summer_and_winter_follow_new_york_dst(self):
        for now, expected in (('2026-07-20T20:16:00Z', '2026-07-20T20:15:00Z'),
                              ('2026-12-21T21:16:00Z', '2026-12-21T21:15:00Z')):
            with self.subTest(now=now):
                slot = latest_export_slot(config(), now)
                self.assertEqual(slot['scheduled_at'], expected)
                self.assertEqual(slot['market_date'], now[:10])
                self.assertEqual(next_export_at(config(), expected), expected)

    def test_display_timezone_and_travel_do_not_move_schedule(self):
        utc = moment('2026-10-23T20:16:00Z')
        expected = latest_export_slot(config(), utc)
        for display_zone in ('Asia/Shanghai', 'Asia/Tokyo', 'Europe/London', 'Pacific/Honolulu'):
            saved = config()
            saved['timezone'] = display_zone
            saved['schedule'] = {'timezone': display_zone}
            self.assertEqual(latest_export_slot(saved, utc.astimezone(ZoneInfo(display_zone))), expected)
            self.assertEqual(next_export_at(saved, utc.astimezone(ZoneInfo(display_zone))),
                '2026-10-26T20:15:00Z')

    def test_latest_selects_one_most_recent_due_slot_after_restart(self):
        saved = config(times=['10:30', '16:15'])
        slot = latest_export_slot(saved, '2026-10-23T20:20:00Z', after='2026-10-22T14:30:00Z')
        self.assertEqual(slot, {'key': 'auto-export:2026-10-23:16:15',
            'scheduled_at': '2026-10-23T20:15:00Z', 'market_date': '2026-10-23'})

    def test_no_early_run_and_exact_minute_is_due(self):
        saved = config(weekdays=[4])
        self.assertIsNone(latest_export_slot(saved, '2026-10-23T20:14:59.999999Z'))
        slot = latest_export_slot(saved, '2026-10-23T20:15:00Z')
        self.assertEqual(slot['scheduled_at'], '2026-10-23T20:15:00Z')

    def test_latest_catchup_is_limited_to_48_actual_hours(self):
        saved = config(weekdays=[4])
        self.assertEqual(latest_export_slot(saved, '2026-10-25T20:15:00Z')['market_date'], '2026-10-23')
        self.assertIsNone(latest_export_slot(saved, '2026-10-25T20:15:00.000001Z'))

    def test_completed_time_is_exclusive_and_compared_as_actual_instants(self):
        now = '2026-10-23T20:16:00Z'
        for completed in ('2026-10-23T20:15:00Z', '2026-10-24T04:15:00+08:00',
                          '2026-10-23T20:16:00Z', '2026-10-24T20:16:00Z'):
            with self.subTest(completed=completed):
                self.assertIsNone(latest_export_slot(config(), now, after=completed))
        self.assertEqual(latest_export_slot(config(), now, after='2026-10-23T20:14:59.999999Z')
            ['scheduled_at'], '2026-10-23T20:15:00Z')

    def test_first_enable_does_not_backfill_earlier_slot(self):
        saved = config()
        self.assertIsNone(latest_export_slot(saved, '2026-10-23T20:20:00Z',
            not_before='2026-10-23T20:16:00Z'))
        self.assertEqual(latest_export_slot(saved, '2026-10-23T20:20:00Z',
            not_before='2026-10-23T20:15:00Z')['scheduled_at'], '2026-10-23T20:15:00Z')
        self.assertIsNone(latest_export_slot(saved, '2026-10-23T20:20:00Z',
            not_before='2026-10-23T20:21:00Z'))

    def test_weekend_clock_and_next_weekday(self):
        self.assertIsNone(latest_export_slot(config(), '2026-10-26T19:00:00Z'))
        self.assertEqual(next_export_at(config(), '2026-10-24T00:00:00Z'), '2026-10-26T20:15:00Z')
        saved = config(weekdays=[6])
        self.assertEqual(latest_export_slot(saved, '2026-10-25T20:16:00Z')['market_date'], '2026-10-25')

    def test_market_day_boundary_is_separate_from_schedule_weekday(self):
        saved = config(times=['02:30'], weekdays=[5])
        slot = latest_export_slot(saved, '2026-10-24T06:31:00Z')
        self.assertEqual(slot['key'], 'auto-export:2026-10-24:02:30')
        self.assertEqual(slot['market_date'], '2026-10-23')
        saved['day_boundary_hour'] = 0
        self.assertEqual(latest_export_slot(saved, '2026-10-24T06:31:00Z')['market_date'], '2026-10-24')

    def test_next_includes_exact_now_but_excludes_an_earlier_microsecond(self):
        self.assertEqual(next_export_at(config(), '2026-10-23T20:15:00Z'), '2026-10-23T20:15:00Z')
        self.assertEqual(next_export_at(config(), '2026-10-23T20:15:00.000001Z'),
            '2026-10-26T20:15:00Z')

    def test_next_uses_earliest_of_multiple_unsorted_times(self):
        saved = config(times=['16:15', '09:30', '10:30'])
        self.assertEqual(next_export_at(saved, '2026-10-23T13:00:00Z'), '2026-10-23T13:30:00Z')
        self.assertEqual(next_export_at(saved, '2026-10-23T13:31:00Z'), '2026-10-23T14:30:00Z')

    def test_spring_nonexistent_wall_time_is_skipped(self):
        saved = config(times=['02:30'], weekdays=[6])
        self.assertIsNone(latest_export_slot(saved, '2026-03-08T08:00:00Z'))
        self.assertEqual(next_export_at(saved, '2026-03-08T05:00:00Z'), '2026-03-15T06:30:00Z')
        # An ordinary valid time on the same transition day still runs.
        saved['auto_export']['times'] = ['02:30', '03:30']
        self.assertEqual(latest_export_slot(saved, '2026-03-08T08:00:00Z')['scheduled_at'],
            '2026-03-08T07:30:00Z')

    def test_fall_ambiguous_wall_time_runs_only_first_occurrence(self):
        saved = config(times=['01:30'], weekdays=[6])
        self.assertEqual(next_export_at(saved, '2026-11-01T05:00:00Z'), '2026-11-01T05:30:00Z')
        self.assertEqual(latest_export_slot(saved, '2026-11-01T06:45:00Z')['scheduled_at'],
            '2026-11-01T05:30:00Z')
        self.assertIsNone(latest_export_slot(saved, '2026-11-01T06:45:00Z', after='2026-11-01T05:30:00Z'))
        self.assertEqual(next_export_at(saved, '2026-11-01T05:30:00.000001Z'), '2026-11-08T06:30:00Z')

    def test_dst_catchup_uses_utc_hours_instead_of_local_calendar_days(self):
        saved = config(times=['01:30'], weekdays=[6])
        self.assertEqual(latest_export_slot(saved, '2026-11-03T05:30:00Z')['scheduled_at'],
            '2026-11-01T05:30:00Z')
        self.assertIsNone(latest_export_slot(saved, '2026-11-03T05:30:00.000001Z'))

    def test_next_looks_far_enough_to_cross_a_full_week(self):
        saved = config(weekdays=[0])
        self.assertEqual(next_export_at(saved, '2026-10-19T20:16:00Z'), '2026-10-26T20:15:00Z')

    def test_next_is_bounded_when_only_upcoming_weekly_slot_is_nonexistent(self):
        saved = config(times=['02:30'], weekdays=[6])
        self.assertIsNone(next_export_at(saved, '2026-03-02T05:00:00Z'))

    def test_invalid_timestamps_timezone_and_boundary_raise_clear_errors(self):
        for now in ('invalid', '2026-10-23T20:16:00', datetime(2026, 10, 23), None):
            with self.subTest(now=now), self.assertRaises(ValueError):
                latest_export_slot(config(), now)
        saved = config()
        saved['market_timezone'] = 'Unknown/Zone'
        with self.assertRaisesRegex(ValueError, '市场时区'):
            next_export_at(saved, '2026-10-23T20:16:00Z')
        saved = config()
        saved['day_boundary_hour'] = True
        with self.assertRaisesRegex(ValueError, '分界'):
            latest_export_slot(saved, '2026-10-23T20:16:00Z')


if __name__ == '__main__':
    unittest.main()
