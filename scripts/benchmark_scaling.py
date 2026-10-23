#!/usr/bin/env python3
"""Synthetic ablation of archive reads, summaries and generation-local indexes.

The legacy reader below freezes the pre-optimization semantics. Every timed
variant must return the same complete JSON fingerprint. No real data is read.
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
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent
if str(SOURCE) not in sys.path:
    sys.path.insert(0,str(SOURCE))

from discord_archive.context import build_context, build_context_index
from discord_archive.store import ArchiveStore, iso_time
from scripts.benchmark_history import build_fixture


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,
        separators=(",",":")).encode()).hexdigest()


def legacy_list_messages(store, *, channel_id=None, author_id=None, run_id=None,
                         as_of_run_id=None, since=None, until=None, limit=None,
                         include_snapshots=True):
    """Pre-optimization retrieval, including both per-row SQL lookups."""
    clauses,args = [],[]
    for column,value in (("m.channel_id",channel_id),("m.author_id",author_id)):
        if value is not None:
            clauses.append(column+"=?")
            args.append(str(value))
    for selected,operator in ((run_id,"="),(as_of_run_id,"<=")):
        if selected is not None:
            clauses.append("EXISTS(SELECT 1 FROM run_messages r WHERE r.channel_id=m.channel_id "
                f"AND r.message_id=m.message_id AND r.run_id{operator}?)")
            args.append(selected)
    for name,value,operator in (("since",since,">="),("until",until,"<=")):
        if value is not None:
            clauses.append("m.created_at"+operator+"?")
            args.append(iso_time(value))
    if not include_snapshots:
        clauses.append("m.is_reference_snapshot=0")
    query = "SELECT m.* FROM messages m" + (" WHERE "+" AND ".join(clauses) if clauses else "")
    query += " ORDER BY m.created_at,LENGTH(m.message_id),m.message_id"
    if limit is not None:
        query += " LIMIT ?"
        args.append(int(limit))
    with store._lock:
        result = [store._message_dict(row) for row in store.conn.execute(query,args).fetchall()]
        selected = run_id if run_id is not None else as_of_run_id
        if selected is not None:
            for message in result:
                operator = "=" if run_id is not None else "<="
                observed = store.conn.execute(f"""SELECT r.version_hash,r.is_reference_snapshot,
                    v.raw_json,v.normalized_json,v.source FROM run_messages r
                    LEFT JOIN message_versions v ON v.channel_id=r.channel_id
                    AND v.message_id=r.message_id AND v.version_hash=r.version_hash
                    WHERE r.channel_id=? AND r.message_id=? AND r.run_id{operator}?
                    ORDER BY r.run_id DESC LIMIT 1""",
                    (message["channel_id"],message["message_id"],selected)).fetchone()
                if observed and observed["normalized_json"]:
                    current_hash = message["version_hash"]
                    message.update(json.loads(observed["normalized_json"]))
                    message["raw"] = json.loads(observed["raw_json"])
                    message["source"] = observed["source"]
                    message["is_reference_snapshot"] = bool(observed["is_reference_snapshot"])
                    message["current_version_hash"] = current_hash
                    message["as_of_run_id"] = selected
        return result if include_snapshots else [row for row in result if not row["is_reference_snapshot"]]


def measure(store, action, *, repeats, deadline_seconds):
    def execute():
        deadline = time.monotonic()+deadline_seconds
        store.conn.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
        try:
            started = time.perf_counter()
            value = action()
            elapsed = time.perf_counter()-started
            if elapsed > deadline_seconds:
                raise TimeoutError("Synthetic benchmark exceeded per-action deadline")
            return elapsed,value
        finally:
            store.conn.set_progress_handler(None,0)
    _,warm = execute()
    expected = fingerprint(warm)
    samples = []
    for _ in range(repeats):
        elapsed,value = execute()
        if fingerprint(value) != expected:
            raise AssertionError("Result changed between repetitions")
        samples.append(elapsed)
    statements = []
    store.conn.set_trace_callback(statements.append)
    try:
        _,value = execute()
    finally:
        store.conn.set_trace_callback(None)
    if fingerprint(value) != expected:
        raise AssertionError("Profile result differs from timed result")
    return {"wall_seconds":samples,"median_seconds":statistics.median(samples),
        "select_statements":sum(sql.lstrip().upper().startswith("SELECT") for sql in statements),
        "result_sha256":expected}


def run_benchmark(*, channels=5, messages_per_channel=2000, rounds=12, repeats=3,
                  deadline_seconds=30):
    if channels < 1 or messages_per_channel < 4 or rounds < 3 or repeats < 3 or deadline_seconds <= 0:
        raise ValueError("Positive bounded fixture and at least three repetitions required")
    with tempfile.TemporaryDirectory(prefix="discord-scaling-") as folder:
        with ArchiveStore(Path(folder)/"synthetic.sqlite3") as store:
            fixture = build_fixture(store,channels=channels,messages_per_channel=messages_per_channel,rounds=rounds)
            selected = fixture["selected_run_id"]
            variants = {}
            for mode,options in (("current",{}),("historical",{"as_of_run_id":selected})):
                for variant,action in (("legacy",lambda:legacy_list_messages(store,**options)),
                                        ("optimized",lambda:store.list_messages(**options))):
                    variants[mode+"_"+variant] = measure(store,action,repeats=repeats,deadline_seconds=deadline_seconds)
                if variants[mode+"_legacy"]["result_sha256"] != variants[mode+"_optimized"]["result_sha256"]:
                    raise AssertionError("Message semantics differ")

            def uncached_summary():
                store._summary_cache = None
                return store.summary()

            for variant,action in (("uncached",uncached_summary),("cached",store.summary)):
                variants["summary_"+variant] = measure(store,action,repeats=repeats,deadline_seconds=deadline_seconds)
            if variants["summary_uncached"]["result_sha256"] != variants["summary_cached"]["result_sha256"]:
                raise AssertionError("Summary counts differ")

            channel_ids = [str(101+index) for index in range(channels)]
            until = "2026-10-22T23:59:59Z"

            def bundles(shared):
                index = build_context_index(store,until=until) if shared else None
                return [build_context(store,"owner",channel_id=channel,until=until,_index=index) for channel in channel_ids]

            for variant,shared in (("independent",False),("shared",True)):
                variants["context_"+variant] = measure(store,lambda:bundles(shared),repeats=repeats,
                    deadline_seconds=deadline_seconds)
            if variants["context_independent"]["result_sha256"] != variants["context_shared"]["result_sha256"]:
                raise AssertionError("Context relationships differ")
            return {"status":"passed","all_results_equal":True,"fixture":fixture,"variants":variants,
                "environment":{"python":sys.version.split()[0],"sqlite":sqlite3.sqlite_version},
                "measurement":{"repeats":repeats,"cache":"warm; one unreported warmup per variant",
                    "deadline_seconds_per_execution":deadline_seconds,
                    "scope":"synthetic archive reads and context building; excludes browser rendering, ASR, network, cold-disk and concurrent lock waits",
                    "production_data_accessed":False,"storage":"temporary synthetic SQLite file"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channels",type=int,default=5)
    parser.add_argument("--messages-per-channel",type=int,default=2000)
    parser.add_argument("--rounds",type=int,default=12)
    parser.add_argument("--repeats",type=int,default=3)
    parser.add_argument("--deadline-seconds",type=float,default=30)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(**vars(args)),ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
