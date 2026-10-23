from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import antigravity_desktop_tokens as tokens


SENTINEL = b"PRIVATE_PROMPT_RESPONSE_PATH_ACCOUNT_IDENTIFIER_SENTINEL"


def varint(value: int) -> bytes:
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def integer(number: int, value: int) -> bytes:
    return varint(number << 3) + varint(value)


def message(number: int, data: bytes) -> bytes:
    return varint((number << 3) | 2) + varint(len(data)) + data


def metadata(values: dict[int, int], *, timestamp: int | None = None,
             private_fields: bool = False) -> bytes:
    usage = b"".join(integer(number, value) for number, value in values.items())
    if private_fields:
        usage += b"".join(message(number, SENTINEL) for number in (7, 8, 11, 12, 13, 14, 15))
    chat = message(4, usage)
    if timestamp is not None:
        chat += message(9, message(4, integer(1, timestamp) + integer(2, 123000000)))
    if private_fields:
        chat += message(19, SENTINEL) + message(20, SENTINEL) + message(21, SENTINEL)
    return message(1, chat) + message(2, SENTINEL)


def database(root: Path, rows: list[tuple[int, bytes]], name: str = "private.db") -> Path:
    path = root / name
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE gen_metadata(idx INTEGER, data BLOB, size INTEGER)")
        connection.executemany("INSERT INTO gen_metadata VALUES (?, ?, ?)",
                               [(index, data, len(data)) for index, data in rows])
        connection.execute("CREATE TABLE steps(private_content BLOB)")
        connection.execute("INSERT INTO steps VALUES (?)", (SENTINEL,))
        connection.commit()
    finally:
        connection.close()
    return path


class AntigravityDesktopTokenTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(tokens.local, "get_desktop_version", return_value="2.25.0")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_unreviewed_desktop_version_is_rejected_before_source_access(self):
        root = mock.Mock(spec=Path)
        tokens.local.get_desktop_version.return_value = "2.26.0"
        result = tokens.collect_desktop_tokens(source_root=root)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "desktop_version_review_required")
        self.assertEqual(result["actual_desktop_version"], "2.26.0")
        self.assertEqual(result["token_fields"], {})
        root.iterdir.assert_not_called()

    def test_missing_desktop_version_is_unavailable_without_source_access(self):
        root = mock.Mock(spec=Path)
        tokens.local.get_desktop_version.side_effect = tokens.local.LocalVerificationError("desktop_version_unavailable")
        result = tokens.collect_desktop_tokens(source_root=root)
        self.assertEqual(result["reason"], "desktop_version_unavailable")
        self.assertIsNone(result["actual_desktop_version"])
        root.iterdir.assert_not_called()

    def test_numeric_usage_matches_local_descriptor_without_double_counting_thinking(self):
        parsed = tokens.parse_generation_numeric_metadata(metadata(
            {2: 10, 3: 8, 4: 2, 5: 30, 9: 3, 10: 5}, private_fields=True))
        self.assertEqual(parsed["tokens"], {
            "uncached_input_tokens": 10, "total_output_tokens": 8,
            "cache_write_input_tokens": 2, "cache_read_input_tokens": 30,
            "thinking_output_tokens": 3, "response_output_tokens": 5,
        })
        self.assertIsNone(parsed["source_event_timestamp_seconds"])
        self.assertNotIn(SENTINEL.decode(), json.dumps(parsed))

    def test_missing_is_unknown_and_an_explicit_zero_remains_zero(self):
        parsed = tokens.parse_generation_numeric_metadata(metadata({2: 0, 3: 12}))
        self.assertEqual(parsed["tokens"], {"uncached_input_tokens": 0, "total_output_tokens": 12})
        self.assertNotIn("cache_read_input_tokens", parsed["tokens"])

    def test_numeric_event_timestamp_is_independent_of_observation_time(self):
        parsed = tokens.parse_generation_numeric_metadata(metadata({2: 1}, timestamp=1770000000))
        self.assertAlmostEqual(parsed["source_event_timestamp_seconds"], 1770000000.123)

    def test_string_event_timestamp_is_not_decoded_or_guessed(self):
        blob = message(1, message(4, integer(2, 1)) + message(9, message(4, b"2026-10-23T00:00:00Z")))
        parsed = tokens.parse_generation_numeric_metadata(blob)
        self.assertIsNone(parsed["source_event_timestamp_seconds"])

    def test_invalid_numeric_wire_duplicate_and_overflow_are_rejected(self):
        for usage in (message(2, SENTINEL), integer(2, 1) + integer(2, 2),
                      integer(3, 1 << 63), b"\x10\x80", b"\x00"):
            with self.subTest(kind=usage[:2]):
                with self.assertRaises(tokens.DesktopTokenError):
                    tokens.parse_generation_numeric_metadata(message(1, message(4, usage)))

    def test_unknown_protobuf_fields_are_skipped_without_being_reported(self):
        blob = metadata({2: 3}) + integer(30, 1000) + message(31, SENTINEL) + b"\x85\x02abcd"
        parsed = tokens.parse_generation_numeric_metadata(blob)
        self.assertEqual(parsed["tokens"], {"uncached_input_tokens": 3})

    def test_latest_bounded_records_and_pb_exclusion_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root, [(1, metadata({2: 100})), (2, metadata({2: 7})), (3, metadata({2: 9}))])
            (root / "private-conversation.pb").write_bytes(SENTINEL)
            result = tokens.collect_desktop_tokens(source_root=root, max_rows=2)
            self.assertEqual(result["status"], "partial")
            self.assertEqual(result["token_fields"]["uncached_input_tokens"]["sampled_sum"], 16)
            self.assertTrue(result["coverage"]["read_limited"])
            self.assertEqual(result["coverage"]["legacy_pb_files_skipped"], 1)
            self.assertEqual(result["coverage"]["rows_selected"], 2)
            self.assertIsNone(result["source_event_timestamp_seconds"])
            self.assertNotIn(directory, json.dumps(result))
            self.assertNotIn("private-conversation", json.dumps(result))
            self.assertNotIn(SENTINEL.decode(), json.dumps(result))

    def test_partial_coverage_is_not_fabricated_into_full_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root, [(1, metadata({2: 0, 3: 8})), (2, metadata({3: 4}))])
            result = tokens.collect_desktop_tokens(source_root=root)
            self.assertEqual(result["token_fields"]["uncached_input_tokens"], {
                "sampled_sum": 0, "records_present": 1, "records_absent": 1, "coverage": "partial"})
            self.assertEqual(result["token_fields"]["total_output_tokens"]["sampled_sum"], 12)
            self.assertIsNone(result["token_fields"]["cache_read_input_tokens"]["sampled_sum"])
            self.assertEqual(result["status"], "partial")

    def test_complete_explicit_sample_is_observed_but_still_not_billing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database(root, [(1, metadata({number: 0 for number in tokens.TOKEN_FIELDS}))])
            result = tokens.collect_desktop_tokens(source_root=root)
            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["billing_usage"], "not_established")
            self.assertEqual(result["context_occupancy"], "not_measured")

    def test_only_metadata_table_is_read_and_database_is_opened_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = database(root, [(1, metadata({2: 5}))])
            queries = []
            real_connect = sqlite3.connect
            def connect(database_uri, *args, **kwargs):
                self.assertIn("mode=ro", database_uri)
                self.assertNotIn("immutable", database_uri)
                connection = real_connect(database_uri, *args, **kwargs)
                connection.set_trace_callback(queries.append)
                return connection
            before = path.read_bytes()
            with mock.patch.object(tokens.sqlite3, "connect", side_effect=connect):
                result = tokens.collect_desktop_tokens(source_root=root)
            self.assertEqual(result["coverage"]["databases_read"], 1)
            self.assertEqual(path.read_bytes(), before)
            self.assertFalse(any("steps" in query.lower() for query in queries))
            self.assertTrue(any("query_only" in query.lower() for query in queries))
            self.assertTrue(any(query == "BEGIN" for query in queries))

    def test_mode_ro_includes_wal_generation_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = database(root, [])
            writer = sqlite3.connect(path)
            try:
                writer.execute("PRAGMA journal_mode=WAL")
                writer.execute("INSERT INTO gen_metadata VALUES (1, ?, 1)", (metadata({2: 13}),))
                writer.commit()
                result = tokens.collect_desktop_tokens(source_root=root)
                self.assertEqual(result["token_fields"]["uncached_input_tokens"]["sampled_sum"], 13)
            finally:
                writer.close()

    def test_oversized_malformed_and_empty_rows_have_bounded_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = database(root, [(1, SENTINEL), (2, b"x" * (tokens.MAX_RECORD_BYTES + 1)), (3, b"")])
            connection = sqlite3.connect(path)
            try:
                connection.execute("INSERT INTO gen_metadata VALUES (4, 'private-text-not-blob', 21)")
                connection.commit()
            finally:
                connection.close()
            result = tokens.collect_desktop_tokens(source_root=root)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["coverage"]["invalid_records"], 3)
            self.assertEqual(result["coverage"]["records_without_usage"], 1)
            self.assertEqual(result["coverage"]["record_diagnostics"]["oversized_metadata"], 1)
            self.assertEqual(result["coverage"]["record_diagnostics"]["non_blob_metadata"], 1)
            self.assertEqual(sum(result["coverage"]["record_diagnostics"].values()), 3)
            self.assertNotIn(SENTINEL.decode(), json.dumps(result))

    def test_database_failures_never_echo_paths_or_exception_text(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "private.db").write_bytes(SENTINEL)
            result = tokens.collect_desktop_tokens(source_root=root)
            self.assertEqual(result["status"], "unavailable")
            self.assertEqual(result["coverage"]["databases_unavailable"], 1)
            self.assertNotIn(directory, json.dumps(result))
            self.assertNotIn(SENTINEL.decode(), json.dumps(result))

    def test_invalid_limits_fail_before_source_access(self):
        for options in ({"max_databases": 0}, {"max_databases": 4},
                        {"max_rows": True}, {"max_rows": 4097}):
            with self.subTest(options=options):
                with self.assertRaisesRegex(tokens.DesktopTokenError, "invalid_read_limit"):
                    tokens.collect_desktop_tokens(**options)

    def test_existing_wal_storage_recency_selects_active_database_first(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / "active-private.db"
            closed = root / "closed-private.db"
            wal = root / "active-private.db-wal"
            for path in (active, closed, wal):
                path.write_bytes(b"synthetic")
            os.utime(active, (1000, 1000))
            os.utime(closed, (2000, 2000))
            os.utime(wal, (3000, 3000))
            with mock.patch.object(tokens, "_read_database", return_value={"status": "unavailable"}) as read:
                result = tokens.collect_desktop_tokens(source_root=root, max_databases=1)
            read.assert_called_once_with(active, 512)
            self.assertTrue(result["coverage"]["read_limited"])


if __name__ == "__main__":
    unittest.main()
