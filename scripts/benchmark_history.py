#!/usr/bin/env python3
"""Bounded, synthetic ablation of historical archive lookups.

No production paths, network, credentials, or browser are accessed. The real
ArchiveStore N+1 path and an experimental single-SELECT equivalent run against
one temporary fixture, with the message-first observation index on and off.
Wall times use warm caches; VM counts are measured separately. This measures
database retrieval and JSON decoding, not a complete draft or disk-cold reads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import statistics
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


SOURCE = Path(__file__).resolve().parent.parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from discord_archive.store import ArchiveStore  # noqa: E402


INDEX = "idx_run_messages_message_run"
CREATE_INDEX = f"CREATE INDEX IF NOT EXISTS {INDEX} ON run_messages(channel_id,message_id,run_id)"
START = datetime(2026, 10, 21, 14, tzinfo=timezone.utc)


def timestamp(seconds: int) -> str:
    return (START + timedelta(seconds=seconds)).isoformat()


def fingerprint(messages: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()


def build_fixture(store: ArchiveStore, *, channels: int, messages_per_channel: int,
                  rounds: int) -> dict[str, Any]:
    """Create fixed overlap, edits, future messages, snapshots, and legacy rows."""
    run_ids = []
    future_count = max(1, messages_per_channel // 10)
    base_count = messages_per_channel - future_count
    for round_index in range(rounds):
        round_runs = []
        for channel_index in range(channels):
            channel = str(101 + channel_index)
            observed = timestamp(3600 + round_index * 600 + channel_index)
            run = store.start_run(channel, trigger="synthetic_benchmark", started_at=observed)
            values = []
            for index in range(messages_per_channel):
                born = 0 if index < base_count else 1 + (index - base_count) % (rounds - 1)
                if round_index < born:
                    continue
                # Old questions are intentionally not refreshed every round.
                if round_index > born and (index == 0 or (index + round_index) % 5 == 0):
                    continue
                revision = round_index // 3 if index % 13 == 0 else 0
                identity = str(100000 + channel_index * 10000 + index)
                value = {"id":identity,"channel_id":channel,
                    "author":{"id":"owner" if index % 3 else "member","username":"synthetic"},
                    "content":f"synthetic channel {channel_index} message {index} revision {revision}",
                    "timestamp":timestamp(index),"attachments":[]}
                if revision:
                    value["edited_timestamp"] = timestamp(1800 + revision * 600)
                if index % 29 == 1:
                    parent = str(900000 + channel_index)
                    value["message_reference"] = {"channel_id":channel,"message_id":parent}
                    value["referenced_message"] = {"id":parent,"channel_id":channel,
                        "author":{"id":"questioner","username":"synthetic"},
                        "content":"synthetic quoted question","timestamp":timestamp(-60)}
                values.append(value)
            # A previously quoted message later becomes directly observed.
            if round_index == rounds - 1:
                values.append({"id":str(900000 + channel_index),"channel_id":channel,
                    "author":{"id":"questioner","username":"synthetic"},
                    "content":"synthetic quoted question","timestamp":timestamp(-60)})
            store.ingest_messages(channel, values, run, observed_at=observed)
            failed = round_index == 1 and channel_index == 0
            store.finish_run(run, not failed, error="synthetic interrupted page" if failed else None,
                ended_at=timestamp(3601 + round_index * 600 + channel_index))
            round_runs.append(run)
        run_ids.append(round_runs)
    selected_run = run_ids[max(0, rounds // 2 - 1)][-1]
    # Simulate pre-version-observation archives. Both paths must retain their
    # existing fallback to the current saved message when no version joins.
    with store.conn:
        store.conn.execute("UPDATE run_messages SET version_hash=NULL WHERE message_id='100000'")
        store.conn.execute("UPDATE run_messages SET version_hash='synthetic-unavailable-version' WHERE message_id='100002'")
    return {"channels":channels,"rounds":rounds,"messages_per_channel":messages_per_channel,
        "selected_run_id":selected_run,"round_run_ids":run_ids,
        "messages":store.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "versions":store.conn.execute("SELECT COUNT(*) FROM message_versions").fetchone()[0],
        "observations":store.conn.execute("SELECT COUNT(*) FROM run_messages").fetchone()[0]}


def batch_history(store: ArchiveStore, *, as_of_run_id: int, channel_id: str | None = None,
                  include_snapshots: bool = True, limit: int | None = None) -> list[dict[str, Any]]:
    """Experimental query only; not imported by production code.

    This implements the subset used by the context index. It preserves current
    filtering before historical overlay, current version counts, NULL/missing
    version fallback, snapshot filtering after overlay, and the existing order.
    """
    clauses, args = [], {"selected_run":as_of_run_id}
    if channel_id is not None:
        clauses.append("m.channel_id=:channel")
        args["channel"] = str(channel_id)
    if not include_snapshots:
        clauses.append("m.is_reference_snapshot=0")
    query = """SELECT m.*,
        (SELECT COUNT(*) FROM message_versions vc
            WHERE vc.channel_id=m.channel_id AND vc.message_id=m.message_id) AS version_count,
        r.is_reference_snapshot AS observed_snapshot,
        v.raw_json AS observed_raw_json,v.normalized_json AS observed_normalized_json,
        v.source AS observed_source
        FROM messages m JOIN run_messages r ON r.rowid=(
            SELECT rr.rowid FROM run_messages rr WHERE rr.channel_id=m.channel_id
            AND rr.message_id=m.message_id AND rr.run_id<=:selected_run
            ORDER BY rr.run_id DESC LIMIT 1)
        LEFT JOIN message_versions v ON v.channel_id=r.channel_id
            AND v.message_id=r.message_id AND v.version_hash=r.version_hash"""
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY m.created_at,LENGTH(m.message_id),m.message_id"
    if limit is not None:
        query += " LIMIT :limit"
        args["limit"] = int(limit)
    with store._lock:
        result = []
        for row in store.conn.execute(query, args).fetchall():
            message = dict(row)
            observed = {key:message.pop(key) for key in (
                "observed_snapshot","observed_raw_json","observed_normalized_json","observed_source")}
            normalized = json.loads(message.pop("normalized_json"))
            message["raw"] = json.loads(message.pop("raw_json"))
            for key in ("attachments","embeds","stickers"):
                message[key] = normalized[key]
            message["id"] = message["message_id"]
            message["is_reference_snapshot"] = bool(message["is_reference_snapshot"])
            if observed["observed_normalized_json"]:
                current_hash = message["version_hash"]
                message.update(json.loads(observed["observed_normalized_json"]))
                message["raw"] = json.loads(observed["observed_raw_json"])
                message["source"] = observed["observed_source"]
                message["is_reference_snapshot"] = bool(observed["observed_snapshot"])
                message["current_version_hash"] = current_hash
                message["as_of_run_id"] = as_of_run_id
            if include_snapshots or not message["is_reference_snapshot"]:
                result.append(message)
        return result


def measure_wall(store: ArchiveStore, action: Callable, *, repeats: int,
                 deadline_seconds: float) -> tuple[list[float], list[dict[str, Any]]]:
    samples, result = [], []
    for _ in range(repeats):
        deadline = time.monotonic() + deadline_seconds
        store.conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        try:
            started = time.perf_counter()
            result = action()
            samples.append(time.perf_counter() - started)
        finally:
            store.conn.set_progress_handler(None, 0)
    return samples, result


def profile(store: ArchiveStore, action: Callable, *, max_vm_steps: int,
            deadline_seconds: float, label: str) -> dict[str, Any]:
    steps, sql_count, examples = 0, 0, {}
    deadline = time.monotonic() + deadline_seconds

    def progress():
        nonlocal steps
        steps += 1
        return int(steps > max_vm_steps or (steps % 10000 == 0 and time.monotonic() > deadline))

    def trace(statement):
        nonlocal sql_count
        if statement.lstrip().upper().startswith("SELECT"):
            sql_count += 1
            category = "version_count" if statement.startswith("SELECT COUNT(*)") else (
                "observation" if statement.startswith("SELECT r.version_hash") else "messages")
            examples.setdefault(category, statement)

    store.conn.set_progress_handler(progress, 1)
    store.conn.set_trace_callback(trace)
    try:
        result = action()
    finally:
        store.conn.set_progress_handler(None, 0)
        store.conn.set_trace_callback(None)
    plans = {key:[row[3] for row in store.conn.execute(
        f"EXPLAIN QUERY PLAN /* {label} {key} */ " + sql)] for key, sql in examples.items()}
    return {"vm_steps":steps,"sql_statements":sql_count,"plans":plans,
        "result_sha256":fingerprint(result),"result_count":len(result)}


def run_benchmark(*, channels: int = 5, messages_per_channel: int = 200, rounds: int = 10,
                  repeats: int = 3, deadline_seconds: float = 15,
                  max_vm_steps: int = 50_000_000) -> dict[str, Any]:
    if channels < 1 or messages_per_channel < 4 or rounds < 3 or repeats < 3:
        raise ValueError("channels >= 1, messages_per_channel >= 4, rounds >= 3, repeats >= 3 required")
    if deadline_seconds <= 0 or max_vm_steps < 1:
        raise ValueError("positive deadline and VM budget required")
    with tempfile.TemporaryDirectory(prefix="discord-history-benchmark-") as folder:
        with ArchiveStore(Path(folder)/"synthetic.sqlite3") as store:
            fixture = build_fixture(store, channels=channels,
                messages_per_channel=messages_per_channel, rounds=rounds)
            selected = fixture["selected_run_id"]
            actions = {"current_n_plus_one":lambda:store.list_messages(as_of_run_id=selected),
                "batch_join_candidate":lambda:batch_history(store, as_of_run_id=selected)}
            variants, expected = [], None
            for indexed in (False, True):
                store.conn.execute(CREATE_INDEX if indexed else f"DROP INDEX IF EXISTS {INDEX}")
                store.conn.commit()
                for name, action in actions.items():
                    # The first unreported run also warms the query cache.
                    _, warm = measure_wall(store, action, repeats=1, deadline_seconds=deadline_seconds)
                    digest = fingerprint(warm)
                    expected = expected or digest
                    if digest != expected:
                        raise AssertionError("Historical results differ between query/index variants")
                    wall, result = measure_wall(store, action, repeats=repeats, deadline_seconds=deadline_seconds)
                    if fingerprint(result) != expected:
                        raise AssertionError("Historical results changed between repetitions")
                    details = profile(store, action, max_vm_steps=max_vm_steps,
                        deadline_seconds=deadline_seconds, label=f"{name}_{indexed}")
                    if details["result_sha256"] != expected:
                        raise AssertionError("Profile result differs from timed result")
                    variants.append({"query":name,"index_enabled":indexed,
                        "wall_seconds":wall,"wall_median_seconds":statistics.median(wall),**details})
            return {"status":"passed","all_results_equal":True,
                "fixture":fixture,"variants":variants,
                "environment":{"python":sys.version.split()[0],"sqlite":sqlite3.sqlite_version,
                    "journal_mode":store.conn.execute("PRAGMA journal_mode").fetchone()[0],
                    "automatic_index":bool(store.conn.execute("PRAGMA automatic_index").fetchone()[0])},
                "measurement":{"repeats":repeats,"cache":"warm; one unreported warmup per variant",
                    "wall_timeout_guard_vm_interval":10000,"vm_count":"exact progress callback at each SQLite VM step; separate from wall timings",
                    "deadline_seconds_per_execution":deadline_seconds,"max_profile_vm_steps":max_vm_steps,
                    "scope":"synthetic historical retrieval plus JSON decoding; no production data, draft rendering, lock contention, or cold-disk I/O",
                    "storage":"temporary synthetic SQLite file removed on exit"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels", type=int, default=5)
    parser.add_argument("--messages-per-channel", type=int, default=200)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--deadline-seconds", type=float, default=15)
    parser.add_argument("--max-vm-steps", type=int, default=50_000_000)
    args = parser.parse_args()
    try:
        result = run_benchmark(channels=args.channels, messages_per_channel=args.messages_per_channel,
            rounds=args.rounds, repeats=args.repeats, deadline_seconds=args.deadline_seconds,
            max_vm_steps=args.max_vm_steps)
    except (ValueError, AssertionError, sqlite3.OperationalError) as error:
        print(json.dumps({"status":"failed","error":str(error),
            "bounded":True,"production_accessed":False}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
