import unittest

from discord_archive.store import ArchiveStore
from scripts.benchmark_history import batch_history, build_fixture, fingerprint, run_benchmark


class HistoryBenchmarkTests(unittest.TestCase):
    def test_batch_candidate_matches_current_history_and_edge_cases(self):
        with ArchiveStore(":memory:") as store:
            fixture = build_fixture(store, channels=2, messages_per_channel=18, rounds=4)
            for runs in fixture["round_run_ids"]:
                for selected in runs:
                    for channel in (None, "101", "102", "absent"):
                        for snapshots in (True, False):
                            for limit in (None, 3):
                                options = {"as_of_run_id":selected,"channel_id":channel,
                                    "include_snapshots":snapshots,"limit":limit}
                                with self.subTest(**options):
                                    self.assertEqual(batch_history(store, **options), store.list_messages(**options))
            first = batch_history(store, as_of_run_id=fixture["round_run_ids"][0][-1])
            self.assertTrue(any(item["is_reference_snapshot"] for item in first))
            self.assertTrue(any("as_of_run_id" not in item for item in first))
            self.assertLess(len(first), fixture["messages"])

    def test_fixture_is_deterministic(self):
        digests = []
        for _ in range(2):
            with ArchiveStore(":memory:") as store:
                fixture = build_fixture(store, channels=2, messages_per_channel=18, rounds=4)
                digests.append(fingerprint(store.list_messages(as_of_run_id=fixture["selected_run_id"])))
        self.assertEqual(*digests)

    def test_four_ablation_variants_report_equal_results_and_real_plans(self):
        result = run_benchmark(channels=2, messages_per_channel=18, rounds=4)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["all_results_equal"])
        variants = {(row["query"], row["index_enabled"]):row for row in result["variants"]}
        self.assertEqual(len(variants), 4)
        self.assertEqual(len({row["result_sha256"] for row in variants.values()}), 1)
        for (name, indexed), row in variants.items():
            self.assertEqual(len(row["wall_seconds"]), 3)
            self.assertGreater(row["vm_steps"], 0)
            if name == "batch_join_candidate":
                self.assertEqual(row["sql_statements"], 1)
            else:
                self.assertEqual(row["sql_statements"], 1 + 2 * row["result_count"])
                observation = " ".join(row["plans"]["observation"])
                self.assertEqual("idx_run_messages_message_run" in observation, indexed)
        self.assertGreater(variants[("current_n_plus_one", False)]["vm_steps"],
            variants[("current_n_plus_one", True)]["vm_steps"])

    def test_small_repetition_or_unbounded_budget_is_rejected(self):
        for options in ({"repeats":2}, {"deadline_seconds":0}, {"max_vm_steps":0}):
            with self.subTest(**options), self.assertRaises(ValueError):
                run_benchmark(**options)


if __name__ == "__main__":
    unittest.main()
