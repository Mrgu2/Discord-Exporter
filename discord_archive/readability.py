"""Conservative, reversible selection for a reading copy of an archive.

These rules remove only recognisable social noise.  They do not summarise,
rewrite financial statements, infer a question, or alter the evidence input.
"""

from __future__ import annotations

from copy import deepcopy
import re
import unicodedata
from typing import Any, Mapping


_USER_MENTION = re.compile(r"<@!?(\d+)>")
_CUSTOM_EMOJI = re.compile(r"<a?:[A-Za-z0-9_]+:\d+>")
_MASS_MENTION = re.compile(r"@(?:everyone|here)(?![A-Za-z0-9_])")
_TICKER = re.compile(r"\$[A-Za-z]{1,8}\b|\b[A-Z]{2,6}\b")
_TICKER_SOCIAL_WORDS = {"OK", "OKAY", "YES", "NO", "LOL", "LMAO", "ROFL", "HAHA"}
_KNOWN_SYMBOL = re.compile(r"\b(?:aapl|nvda|tsla|spx|spy|qqq|vix|btc|eth|iwm|dia|msft|amzn|meta|googl?)\b", re.I)
_MARKET_INFORMATION = re.compile(
    r"行情|交易|期权|股票|指数|美股|美债|市场|涨|跌|突破|止损|止盈|风险|仓位|持仓|成交|"
    r"量价|波动|震荡|买|卖|多头|空头|做多|做空|开仓|平仓|加仓|减仓|仓|看多|看空|"
    r"抄底|持有|挂单|价格|股价|价位|收盘|开盘|尾盘|盘前|盘后|估值|财报|利率|利好|利空|"
    r"盈利|亏|成本|回撤|支撑|压力位|回补|确认|趋势|指标|消息面|基本面|到期|交割|"
    r"利差|资金|流动性|通胀|杠杆|期货|合约|筹码|横盘|止跌|fomo|bull|bear|put|call|short|long",
    re.I,
)

_STANDALONE_ACK = {
    "嗯", "嗯嗯", "嗯嗯嗯", "哦", "噢", "哦哦", "是", "是的", "对", "对的", "没错",
    "好", "好的", "好滴", "好哒", "行", "可以", "不", "不是", "不用", "没", "有", "没有",
    "谢谢", "感谢", "多谢", "收到", "了解", "明白", "明白了", "懂了", "知道了",
    "ok", "okay", "yes", "no",
}
_RECEIPTS = {"好", "好的", "好滴", "好哒", "收到", "了解", "明白", "明白了", "懂了", "知道了", "ok", "okay"}
_THANKS = re.compile(
    r"(?:(?:好|好的|收到|明白|懂了|ok|okay))?"
    r"(?:谢谢|多谢|感谢)"
    r"(?:(?:你|您|老大|大佬|群主|老师|老板|哥|分享|回复|解答|指点|提醒))*"
    r"(?:啦|了|啊|呀|哈)*"
)
_LAUGHTER = re.compile(r"(?:哈{2,}|嘿嘿|呵呵|嘻嘻|笑死|笑死我了)+")
_ACTIVITY = re.compile(
    r"(?:兄弟们|各位|大家)?(?:我|我们|俺)?"
    r"(?:先|要|准备|得|刚刚|刚|正|正在|一会儿|等会儿|马上|现在|已经)?"
    r"(?:去|在|回去|出去)?"
    r"(?:(?:升篝火|生篝火|生火|生个火)?(?:烧咖啡|泡咖啡|煮咖啡|喝咖啡)|吃饭|干饭|做饭|煮饭|吃早餐|吃午饭|吃晚饭|"
    r"睡觉|补觉|休息|洗澡|洗个澡|上厕所|抽烟|散步|遛狗)"
    r"(?:了|啦|咯|去|一下|一会儿|一会|会儿|先|呢|中)*"
)
_LOCATION_CHAT = re.compile(
    r"(?:今天|今日|刚才|现在|刚刚)?(?:在|到|到了|回|回到)?"
    r"(?:办公室|公司|家里|家|工位)"
    r"(?:了|啦|咯|呢|好冷|很冷|太冷了|好热|很热|太热了|没人|没有人|人好多|人很多|"
    r"好多人|来了好多人|人少|没空调|开空调|停电了|停电)+"
)
_STATUS_ONLY = re.compile(
    r"(?:我)?(?:又)?被管理员罚款(?:了)?(?:你们|大家)?等尾盘(?:吧)?|"
    r"我(?:去|先去)?看(?:会|会儿|一会|一会儿)?盘(?:晚点|等会|一会儿|稍后)(?:再)?回(?:复)?(?:你们|大家)?(?:了|哈|吧)?|"
    r"(?:今天|今日)(?:的)?(?:办公室|工位)"
)
_CAMPING_CHAT = re.compile(r"(?:(?:夜哥|雨哥|老大)(?:在)?)?(?:烧烤|露营)(?:吗|嘛)?")


def clean_reading_text(text: Any, target_author_id: str | None = None,
                       author_names: Mapping[str, Any] | None = None, *, keep_custom_emoji=False) -> str:
    """Clean call-outs and blank lines without changing substantive wording.

    Only boundary mentions of the target author are omitted. Other mentions
    become a known display name, or the neutral ``群友`` when no name was saved.
    The caller keeps the source text separately in the archive/evidence.
    """
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = _MASS_MENTION.sub("", value)
    if target_author_id:
        mention = rf"<@!?{re.escape(str(target_author_id))}>"
        leading = re.compile(rf"^\s*{mention}[\s,，、:：]*")
        trailing = re.compile(rf"[ \t,，、:：]*{mention}\s*$")
        while True:
            trimmed = trailing.sub("", leading.sub("", value))
            if trimmed == value:
                break
            value = trimmed
    names = author_names or {}

    def name_for(match):
        identity = match.group(1)
        found = names.get(identity)
        if isinstance(found, Mapping):
            found = found.get("author_name") or found.get("display_name") or found.get("username")
        if found:
            return str(found)
        return "群主" if target_author_id and identity == str(target_author_id) else "群友"

    value = _USER_MENTION.sub(name_for, value)
    if not keep_custom_emoji:
        without_emoji = _CUSTOM_EMOJI.sub('', value)
        # Inline animated-emote IDs add no readable content. Keep a neutral
        # marker when an explicitly linked answer consists only of emotes.
        value = without_emoji if without_emoji.strip() else ('（表情）' if _CUSTOM_EMOJI.search(value) else value)
    # An emptied mass-mention line should not leave indentation or blank pages.
    lines = [line.rstrip() if line.strip() else "" for line in value.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _identity(message: Mapping[str, Any]) -> tuple[str, str]:
    return str(message.get("channel_id") or ""), str(message.get("message_id") or message.get("id") or "")


def _snapshots(message: Mapping[str, Any]):
    """Yield the actual forwarded content, including nested API snapshots."""
    seen = set()
    queue = [message]
    while queue:
        current = queue.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        raw = current.get("raw")
        sources = [current] + ([raw] if isinstance(raw, Mapping) else [])
        for source in sources:
            for snapshot in source.get("message_snapshots") or []:
                inner = snapshot.get("message") if isinstance(snapshot, Mapping) else None
                if isinstance(inner, Mapping):
                    yield inner
                    queue.append(inner)


def _has_media(message: Mapping[str, Any]) -> bool:
    # Preserve even un-downloaded media. The media layer decides what can be
    # rendered, and a missing image must not become a reason to omit its message.
    return any(bool(item.get("attachments") or item.get("embeds") or item.get("stickers")
                    or item.get("sticker_items")) for item in [message, *_snapshots(message)])


def _effective_text(message, target_author_id):
    return "\n".join(clean_reading_text(item.get("content"), target_author_id, keep_custom_emoji=True)
                     for item in [message, *_snapshots(message)]).strip()


def _compact(text):
    return "".join(char for char in _CUSTOM_EMOJI.sub("", text).casefold() if char.isalnum())


def _has_information(text):
    if _MARKET_INFORMATION.search(text) or _KNOWN_SYMBOL.search(text):
        return True
    # Numbers may be prices, sizing, dates, or an answer to a quantitative
    # question. Be conservative even if their purpose is not apparent here.
    if any(char.isdigit() for char in _USER_MENTION.sub("", _CUSTOM_EMOJI.sub("", text))):
        return True
    return any(match.group().startswith("$") or match.group() not in _TICKER_SOCIAL_WORDS
               for match in _TICKER.finditer(text))


def _pure_emoji(text):
    custom = bool(_CUSTOM_EMOJI.search(text))
    remainder = _CUSTOM_EMOJI.sub("", text)
    return not any(char.isalnum() for char in remainder) and (
        custom or any(unicodedata.category(char).startswith("S") for char in remainder)
    )


def _social_reason(message, target_author_id, *, allow_short_ack):
    if _has_media(message):
        return None
    text = _effective_text(message, target_author_id)
    if not text:
        return "无正文且无图片或附件"
    if _STATUS_ONLY.fullmatch(_compact(text)) or _CAMPING_CHAT.fullmatch(_compact(text)):
        return "仅生活问候、管理提醒或暂离状态"
    if _has_information(text):
        return None
    compact = _compact(text)
    if _THANKS.fullmatch(compact) or _LAUGHTER.fullmatch(compact):
        return "仅感谢、客套或笑声"
    if _pure_emoji(text):
        return "仅表情回应"
    if compact in (_STANDALONE_ACK if allow_short_ack else _RECEIPTS):
        return "无明确原问题的简短回应" if allow_short_ack else "仅确认收到或表示理解"
    if _ACTIVITY.fullmatch(compact) or _LOCATION_CHAT.fullmatch(compact):
        return "与交易内容无关的日常闲聊"
    return None


def choose_reading_groups(groups: list[dict[str, Any]], target_author_id: str):
    """Return ``(reading_groups, exclusions)`` without mutating ``groups``.

    Explicit reply context and missing references protect yes/no and other
    short owner answers. We never manufacture a question from adjacent text.
    Every omitted message is recorded as channel_id/message_id/reason; source
    records and edit history remain available to the caller in the input.
    """
    result, decisions = [], []
    recorded = set()

    def record(message, reason):
        channel, identity = _identity(message)
        key = (channel, identity)
        if key not in recorded:
            decisions.append({"channel_id":channel, "message_id":identity, "reason":reason})
            recorded.add(key)

    for original in groups:
        group = deepcopy(original)
        answers = group.get("answers", [])
        context = group.get("context", [])
        followups = group.get("followups", [])
        owner_texts=[_effective_text(message,target_author_id) for message in answers]
        # Explicit lifestyle captions can accompany a video or moderation
        # screenshot. A blank media-only post alone is never enough to omit it:
        # the group must have a clear status caption and no other owner content.
        if any(_STATUS_ONLY.fullmatch(_compact(text)) for text in owner_texts) and all(
            not text or _STATUS_ONLY.fullmatch(_compact(text)) for text in owner_texts):
            for message in group.get('messages',context+answers+followups):
                record(message,"仅生活记录、管理提醒或暂离状态，完整内容仍在原文归档中")
            continue
        # A forwarded image can occur in any role, not just in the owner's
        # normalized top-level attachments list.
        media_group = any(_has_media(message) for message in context + answers + followups)
        explicit_context = bool(context or group.get("missing_context"))
        kept_answers, pending = [], []
        for answer in answers:
            linked = explicit_context or bool(answer.get("reply_to_message_id"))
            reason = None if media_group else _social_reason(answer, target_author_id, allow_short_ack=not linked)
            # A minimal answer to an actual question is substantive even when
            # it coincides with a social receipt (e.g. "好的" or an emoji).
            if linked and reason in {"无正文且无图片或附件", "仅感谢、客套或笑声", "仅表情回应", "仅确认收到或表示理解"}:
                if _compact(_effective_text(answer, target_author_id)) in _STANDALONE_ACK - {"谢谢", "感谢", "多谢"}:
                    reason = None
                elif _pure_emoji(_effective_text(answer, target_author_id)):
                    reason = None
            if reason:
                pending.append((answer, reason))
            else:
                kept_answers.append(answer)
        if not kept_answers:
            for message, reason in pending:
                record(message, reason)
            # Context/followups are not reclassified as owner answers merely
            # to keep an otherwise empty reading group alive.
            for message in context + followups:
                record(message, "随纯社交回应移出阅读稿，原文仍在归档证据中")
            continue
        for message, reason in pending:
            record(message, reason)
        kept_followups = []
        for message in followups:
            reason = _social_reason(message, target_author_id, allow_short_ack=False)
            # Preserve the owner's short response when it answers an explicit
            # follow-up rather than being only a receipt or social thanks.
            if str(message.get("author_id") or "") == str(target_author_id) and message.get("reply_to_message_id"):
                if _compact(_effective_text(message, target_author_id)) in _STANDALONE_ACK - {"谢谢", "感谢", "多谢"}:
                    reason = None
            if reason:
                record(message, reason)
            else:
                kept_followups.append(message)
        group["answers"], group["followups"] = kept_answers, kept_followups
        # Rebuild from roles so no omitted message reappears through the
        # separate attachment/source traversal, and no retained role loses media.
        distinct = {}
        for message in context + kept_answers + kept_followups:
            distinct.setdefault(_identity(message), message)
        group["messages"] = sorted(distinct.values(), key=lambda message:(
            message.get("created_at") or "", len(_identity(message)[1]), _identity(message)[1]))
        result.append(group)
    return result, decisions
