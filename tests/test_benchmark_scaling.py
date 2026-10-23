import unittest

from discord_archive.store import ArchiveStore
from scripts.benchmark_history import build_fixture
from scripts.benchmark_scaling import legacy_list_messages, run_benchmark


class ScalingBenchmarkTests(unittest.TestCase):
    def test_frozen_legacy_reader_matches_filters_and_historical_fallbacks(self):
        with ArchiveStore(":memory:") as store:
            fixture = build_fixture(store,channels=2,messages_per_channel=18,rounds=4)
            for mode in ({},{"run_id":fixture["selected_run_id"]},
                         {"as_of_run_id":fixture["selected_run_id"]}):
                for filters in ({},{"author_id":"owner","channel_id":"101"},
                                {"include_snapshots":False,"limit":4},
                                {"since":"2026-10-21T14:00:03Z","until":"2026-10-21T14:00:10Z"}):
                    options = {**mode,**filters}
                    with self.subTest(**options):
                        self.assertEqual(legacy_list_messages(store,**options),store.list_messages(**options))

    def test_small_complete_ablation_has_equal_results_and_bounded_queries(self):
        report = run_benchmark(channels=2,messages_per_channel=18,rounds=4)
        self.assertEqual(report["status"],"passed")
        rows = report["variants"]
        for before,after in (("current_legacy","current_optimized"),
                             ("historical_legacy","historical_optimized"),
                             ("summary_uncached","summary_cached"),
                             ("context_independent","context_shared")):
            self.assertEqual(rows[before]["result_sha256"],rows[after]["result_sha256"])
            self.assertGreater(rows[before]["select_statements"],rows[after]["select_statements"])
        self.assertEqual(rows["summary_cached"]["select_statements"],0)
        self.assertEqual(rows["current_optimized"]["select_statements"],1)

    def test_invalid_workload_limits_rejected(self):
        for options in ({"channels":0},{"messages_per_channel":3},{"rounds":2},
                        {"repeats":2},{"deadline_seconds":0}):
            with self.subTest(**options),self.assertRaises(ValueError):
                run_benchmark(**options)
