from __future__ import annotations

import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from scripts import antigravity_desktop_ledger as ledger

OBSERVED = 1792718000.0


def generation(identity=b"private-native-response-id", **changes):
    values = {"response_id": identity, "selector": "private-conversation-selector",
              "row_index": 9, "tokens": {"uncached_input_tokens": 100, "total_output_tokens": 20},
              "source_timestamp_seconds": OBSERVED - 100,
              "source_time_kind": "first-referenced-step-created-at"}
    values.update(changes)
    return SimpleNamespace(**values)


class GenerationLedgerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="antigravity-ledger-")
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "ledger.sqlite3"

    def ingest(self, records):
        return ledger.GenerationLedger(self.path).ingest(records, observed_at_seconds=OBSERVED)

    def test_repeat_copy_fork_and_reordered_rows_do_not_add_again(self):
        first = self.ingest([generation(), generation(b"second-id")])
        repeated = self.ingest([generation(b"second-id", selector="copied", row_index=0),
                                generation(selector="forked", row_index=47)])
        self.assertEqual(first["generation_count"], 2)
        self.assertEqual(repeated["new_generations"], 0)
        self.assertEqual(repeated["duplicate_generations"], 2)
        self.assertEqual(first["totals"], repeated["totals"])

    def test_positive_refinement_adds_only_delta_and_preserves_missing_fields(self):
        self.ingest([generation()])
        changed = self.ingest([generation(tokens={"total_output_tokens": 25, "cache_read_input_tokens": 0})])
        self.assertEqual(changed["generation_count"], 1)
        self.assertEqual(changed["refined_generations"], 1)
        self.assertEqual(changed["totals"], {"uncached_input_tokens": 100, "total_output_tokens": 25,
                                            "cache_read_input_tokens": 0})
        self.assertNotIn("cache_write_input_tokens", changed["totals"])

    def test_decrease_or_conflicting_time_is_rejected_without_partial_delta(self):
        original = self.ingest([generation()])
        for changed in (generation(tokens={"uncached_input_tokens": 90, "total_output_tokens": 50}),
                        generation(source_timestamp_seconds=OBSERVED-80)):
            result = self.ingest([changed])
            self.assertEqual(result["conflicting_records"], 1)
            self.assertEqual(result["totals"], original["totals"])

    def test_missing_identity_time_and_invalid_values_do_not_become_trusted_totals(self):
        result = self.ingest([generation(None), generation(source_timestamp_seconds=None),
                              generation(tokens={"uncached_input_tokens": True})])
        self.assertEqual(result["missing_identity"], 1)
        self.assertEqual(result["missing_source_time"], 1)
        self.assertEqual(result["invalid_records"], 1)
        self.assertEqual(result["generation_count"], 0)
        self.assertEqual(result["totals"], {})

    def test_restart_and_transport_retry_keep_start_and_totals_without_raw_ids(self):
        first = self.ingest([generation()])
        second = self.ingest([generation()])
        self.assertEqual(first["ledger_start_at_unix_seconds"], second["ledger_start_at_unix_seconds"])
        self.assertEqual(first["totals"], second["totals"])
        self.assertNotIn(b"private-native-response-id", self.path.read_bytes())
        self.assertNotIn(b"private-conversation-selector", self.path.read_bytes())

    def test_concurrent_collectors_accept_a_native_generation_once(self):
        with ThreadPoolExecutor(max_workers=3) as workers:
            results = list(workers.map(lambda _: self.ingest([generation()]), range(3)))
        self.assertEqual(sum(item["new_generations"] for item in results), 1)
        self.assertTrue(all(item["generation_count"] == 1 for item in results))
        self.assertTrue(all(item["totals"]["total_output_tokens"] == 20 for item in results))

    def test_capacity_never_prunes_seen_ids_and_recounts_history(self):
        with mock.patch.object(ledger, "MAX_GENERATIONS", 1):
            self.ingest([generation()])
            result = self.ingest([generation(b"other-response-id")])
            self.assertTrue(result["capacity_reached"])
            self.assertEqual(result["generation_count"], 1)
            self.assertEqual(self.ingest([generation()])["duplicate_generations"], 1)

    def test_corrupt_state_fails_closed_without_resetting_cumulative_values(self):
        self.ingest([generation()])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE meta SET value='not-json' WHERE key='totals'")
            db.commit()
        with self.assertRaisesRegex(ledger.LedgerError, "^invalid_ledger_state$"):
            self.ingest([generation()])

    def test_missing_meta_never_rekeys_an_existing_generation(self):
        self.ingest([generation()])
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("DELETE FROM meta")
            db.commit()
        with self.assertRaisesRegex(ledger.LedgerError, "^invalid_ledger_state$"):
            self.ingest([generation()])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM generations").fetchone()[0], 1)

    def test_filesystem_failure_has_only_a_fixed_diagnostic(self):
        with mock.patch.object(Path, "mkdir", side_effect=PermissionError("private-source-path")):
            with self.assertRaisesRegex(ledger.LedgerError, "^ledger_unavailable$"):
                self.ingest([generation()])


if __name__ == "__main__":
    unittest.main()
