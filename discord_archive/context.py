"""Recover explicitly linked reply context without inventing missing questions."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from .store import ArchiveStore, parse_time


def _key(message: dict[str, Any]) -> tuple[str, str]:
    return message["channel_id"], message["message_id"]


def source_for(store: ArchiveStore, message: dict[str, Any], channels=None) -> dict[str, Any]:
    channels = channels if channels is not None else {item["channel_id"]:item for item in store.list_channels()}
    channel = channels.get(message["channel_id"],{})
    guild = channel.get("guild_id") or "@me"
    return {"channel_id":message["channel_id"],"message_id":message["message_id"],
        "local_id":f'{message["channel_id"]}/{message["message_id"]}',
        "url":f'https://discord.com/channels/{guild}/{message["channel_id"]}/{message["message_id"]}',
        "source":message["source"],"is_reference_snapshot":message["is_reference_snapshot"],
        "version_count":message["version_count"],"created_at":message["created_at"],
        "edited_at":message["edited_at"]}


def build_context_for_seed(store: ArchiveStore, channel_id: str, message_id: str, *,
                           max_reply_depth: int = 30, max_followups: int = 100,
                           neighbor_count: int = 2, continuation_minutes: float = 5,
                           until: Any = None, _index=None) -> dict[str, Any]:
    """An exact reply link is evidence; adjacency is only a reading candidate.

    Reply ancestors may precede a requested reporting period because they are
    necessary to understand an in-period answer. Followups obey ``until``.
    """
    if _index is None:
        _index = _make_index(store,until=until)
    archived_seed = _index["messages"].get((str(channel_id),str(message_id)))
    seed = dict(archived_seed) if archived_seed else None
    if seed is None:
        raise ValueError("Seed message is absent from the local archive")
    seed["evidence_relation"] = "target_author_seed"
    ceiling = parse_time(until)
    chain, missing, warnings = [], [], []
    visited = {_key(seed)}
    current = seed
    for _depth in range(max_reply_depth):
        referenced_id = current.get("reply_to_message_id")
        if not referenced_id:
            break
        referenced_channel = current.get("reply_to_channel_id") or current["channel_id"]
        reference_key = str(referenced_channel), str(referenced_id)
        if reference_key in visited:
            warnings.append("Reply cycle detected; expansion stopped.")
            break
        visited.add(reference_key)
        archived_original = _index["messages"].get(reference_key)
        original = dict(archived_original) if archived_original else None
        if original is None:
            missing.append({"channel_id":reference_key[0],"message_id":reference_key[1],
                "referenced_by":source_for(store,current,_index["channels"]),"reason":"not_in_local_archive",
                "label":"原问题未保存，上下文缺失；不可依据邻近消息补写。"})
            break
        original["evidence_relation"] = "explicit_reply_ancestor"
        chain.append(original)
        current = original
    else:
        if current.get("reply_to_message_id"):
            warnings.append(f"Reply chain limited to {max_reply_depth} ancestors.")
    chain.reverse()

    # Read connected channels so a cross-channel reply or actual thread can be
    # followed. Context is always drawn from the user's already-local archive.
    def allowed(message):
        created = parse_time(message.get("created_at"))
        return ceiling is None or created is None or created <= ceiling

    children = _index["children"]
    followups, queue, followup_keys = [], [_key(seed)], set()
    while queue and len(followups) < max_followups:
        parent_key = queue.pop(0)
        for child in children.get(parent_key,[]):
            if not allowed(child):
                continue
            child_key = _key(child)
            if child_key in visited or child_key in followup_keys:
                continue
            item = dict(child)
            item["evidence_relation"] = "direct_reply" if parent_key == _key(seed) else "reply_descendant"
            followups.append(item)
            followup_keys.add(child_key)
            queue.append(child_key)
            if len(followups) >= max_followups:
                break
    if queue:
        warnings.append(f"Reply followups limited to {max_followups} messages.")

    # Thread membership is structural evidence, but not proof that every thread
    # message answers this specific seed. Keep that relation explicit.
    thread_id = seed.get("thread_id")
    thread_keys = {str(thread_id)} if thread_id else set()
    if seed["channel_id"] in _index["thread_channels"]:
        thread_keys.add(seed["channel_id"])
    seed_time = parse_time(seed.get("created_at"))
    if thread_keys:
        thread_messages = { _key(message):message for key in thread_keys for message in _index["by_thread"].get(key,[]) }
        for message in thread_messages.values():
            item_key, created = _key(message), parse_time(message.get("created_at"))
            if item_key not in visited and item_key not in followup_keys and allowed(message):
                if seed_time and created and created < seed_time:
                    continue
                if len(followups) >= max_followups:
                    warnings.append(f"Thread followups limited to {max_followups} messages.")
                    break
                item = dict(message)
                item["evidence_relation"] = "same_thread_membership"
                followups.append(item)
                followup_keys.add(item_key)

    channel_messages = _index["by_channel"].get(seed["channel_id"],[])
    seed_index = _index["positions"].get(_key(seed))
    continuations = []
    continuation_keys = set()
    candidates = []
    if seed_index is not None:
        for direction in (-1,1):
            previous = seed
            index = seed_index+direction
            while 0 <= index < len(channel_messages):
                item = channel_messages[index]
                item_time, previous_time = parse_time(item.get("created_at")),parse_time(previous.get("created_at"))
                if item["author_id"] != seed["author_id"] or not item_time or not previous_time:
                    break
                if abs(item_time-previous_time) > timedelta(minutes=continuation_minutes):
                    break
                # An explicit reply to a different question starts its own
                # context. Do not relabel it a supplement merely by proximity.
                if item.get("reply_to_message_id") and item.get("reply_to_message_id") != seed.get("reply_to_message_id"):
                    break
                if _key(item) not in visited and _key(item) not in followup_keys:
                    copy = dict(item)
                    copy["evidence_relation"] = "consecutive_same_author"
                    copy["relation_note"] = "目标作者连续发言；仅证明时间邻接，未证明属于同一观点。"
                    continuations.append(copy)
                    continuation_keys.add(_key(item))
                previous,index = item,index+direction
        for message in channel_messages[max(0,seed_index-neighbor_count):seed_index+neighbor_count+1]:
            if _key(message) in visited or _key(message) in followup_keys or _key(message) in continuation_keys:
                continue
            copy = dict(message)
            copy["evidence_relation"] = "candidate_neighbor_only"
            copy["relation_note"] = "仅供人工核对的邻近消息，不作为已确认原问题。"
            candidates.append(copy)
    ordering = lambda item: (item.get("created_at") or "",len(item["message_id"]),item["message_id"])
    followups.sort(key=ordering)
    continuations.sort(key=ordering)
    sources = [source_for(store,message,_index["channels"]) for message in chain+[seed]+followups+continuations]
    return {"seed":seed,"reply_chain":chain,"followups":followups,"continuations":continuations,
        "missing_context":missing,"candidate_neighbors":candidates,"sources":sources,"warnings":warnings,
        "context_status":"missing" if missing else ("linked" if chain else "standalone"),
        "reply_chain_order":"oldest_to_immediate_parent"}


def _make_index(store, as_of_run_id=None, until=None):
    all_messages = store.list_messages(as_of_run_id=as_of_run_id)
    ceiling = parse_time(until)
    children,by_channel,positions,by_thread = {},{},{},{}
    thread_channels = {str(message["thread_id"]) for message in all_messages if message.get("thread_id")}
    for message in all_messages:
        created = parse_time(message.get("created_at"))
        if ceiling and created and created > ceiling:
            continue
        channel_messages = by_channel.setdefault(message["channel_id"],[])
        positions[_key(message)] = len(channel_messages)
        channel_messages.append(message)
        thread_keys = set()
        if message.get("thread_id"):
            thread_keys.add(str(message["thread_id"]))
        if message["channel_id"] in thread_channels:
            thread_keys.add(message["channel_id"])
        for key in thread_keys:
            by_thread.setdefault(key,[]).append(message)
        if message.get("reply_to_message_id"):
            parent = message.get("reply_to_channel_id") or message["channel_id"],message["reply_to_message_id"]
            children.setdefault(parent,[]).append(message)
    return {"all_messages":all_messages,"messages":{_key(message):message for message in all_messages},
        "children":children,"by_channel":by_channel,"by_thread":by_thread,"positions":positions,"thread_channels":thread_channels,
        "channels":{item["channel_id"]:item for item in store.list_channels()}}


def build_context(store: ArchiveStore, target_author_id: str, channel_id: str | None = None,
                  run_id: int | None = None, since: Any = None, until: Any = None,
                  **options) -> dict[str, Any]:
    """Select target-author seeds, then recover their evidenced local context."""
    if not target_author_id:
        raise ValueError("target_author_id is required")
    seeds = store.list_messages(channel_id=channel_id,author_id=str(target_author_id),run_id=run_id,
        since=since,until=until,include_snapshots=False)
    index = _make_index(store,as_of_run_id=run_id,until=until)
    items = [build_context_for_seed(store,message["channel_id"],message["message_id"],until=until,_index=index,**options)
        for message in seeds]
    missing_keys = {(item["channel_id"],item["message_id"]) for context in items for item in context["missing_context"]}
    warnings = list(dict.fromkeys(warning for item in items for warning in item["warnings"]))
    if missing_keys:
        warnings.append(f"{len(missing_keys)} referenced messages are not in the local archive; no text was inferred.")
    if not seeds:
        warnings.append("No direct target-author messages match the selected period or run.")
    return {"target_author_id":str(target_author_id),"channel_id":channel_id,"run_id":run_id,
        "since":since,"until":until,"seeds":seeds,"items":items,"warnings":warnings,
        "stats":{"seed_count":len(seeds),"missing_context_count":len(missing_keys),
            "linked_context_count":sum(bool(item["reply_chain"]) for item in items),
            "followup_count":sum(len(item["followups"]) for item in items)}}
