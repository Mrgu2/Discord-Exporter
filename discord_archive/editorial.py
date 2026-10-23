"""Source-bound local manuscripts and semantic long-image rendering."""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .context import build_context
from .assets import forwarded_texts, iter_message_assets
from .media import MediaArchive
from .readability import choose_reading_groups, clean_reading_text
from .scheduler import day_bounds, market_day
from .settings import atomic_json
from .speech import SpeechArchive
from . import render_cache
from .store import iso_time, parse_time


ACKNOWLEDGEMENTS = {"对", "对的", "是", "是的", "嗯", "嗯嗯", "好", "好的", "没错", "是这样", "谢谢", "可以", "不", "不是", "yes", "no", "ok", "okay"}


def _key(message):
    return message["channel_id"],message["message_id"]


def _order(message):
    return message.get("created_at") or "",len(message["message_id"]),message["message_id"]


def _short_ack(message):
    return re.sub(r"[\s。！!，,.?？]+", "", message.get("content", "")).lower() in ACKNOWLEDGEMENTS


def _unique(messages):
    return sorted({_key(message):message for message in messages}.values(),key=_order)


def _time(message, zone):
    parsed = parse_time(message.get("created_at"))
    return parsed.astimezone(zone).strftime("%m-%d %H:%M") if parsed else "时间未保存"


def _local_id(message):
    return f'{message["channel_id"]}/{message["message_id"]}'


class DraftService:
    def __init__(self, store, root, settings, credentials):
        self.store,self.root,self.settings,self.credentials = store,Path(root),settings,credentials
        self.output = self.root/"output"
        self.output.mkdir(parents=True,exist_ok=True)

    def _selection(self, request, config):
        scope = request.get("scope","latest")
        if scope not in {"latest","day","range"}:
            raise ValueError("整理范围须为 latest、day 或 range")
        rows = [row for row in config.get("channels",[]) if not isinstance(row,dict) or row.get("enabled",True)]
        layout = request.get("layout","horizontal")
        if layout == "board":
            rows = [row for row in rows if not isinstance(row,dict) or row.get("kind","feed") == "feed"]
            if len(rows) != 4:
                raise ValueError("四栏拼版需要配置四个 feed 类型的主题频道")
        elif layout == "qa" and any(isinstance(row,dict) and row.get("kind") == "qa" for row in rows):
            rows = [row for row in rows if isinstance(row,dict) and row.get("kind") == "qa"]
        channels = [str(row["id"] if isinstance(row,dict) else row) for row in rows]
        if not channels:
            raise ValueError("请先配置要整理的频道")
        zone = config.get("market_timezone","America/New_York")
        boundary = int(config.get("day_boundary_hour",4))
        selected = {"scope":scope,"channels":channels,"run_id":None,"run_ids":{},"since":None,"until":None}
        if scope == "latest":
            successful = [run for run in self.store.list_runs(limit=10000) if run["status"] == "success" and run["channel_id"] in channels]
            if not successful:
                raise ValueError("还没有成功保存的轮次，请先保存或导入一次")
            if layout in {"board","collage","horizontal","stacked"}:
                for channel in channels:
                    runs = [run for run in successful if run["channel_id"] == channel]
                    if runs:
                        selected["run_ids"][channel] = max(runs,key=lambda run:run["run_id"])["run_id"]
                selected["channels"] = [channel for channel in channels if channel in selected["run_ids"]]
            else:
                latest = max(successful,key=lambda run:run["run_id"])
                selected.update(run_id=latest["run_id"],channels=[latest["channel_id"]])
            selected["label"] = "最近一轮答疑"
        else:
            start = request.get("date") if scope == "day" else request.get("start")
            end = start if scope == "day" else request.get("end")
            if not start:
                start = market_day(datetime.now(timezone.utc),zone,boundary) if scope == "day" else None
            if not start or not end:
                if scope == "day" and start:
                    end = start
                else:
                    raise ValueError("请选择完整的开始和结束日期")
            for value in (start,end):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",value):
                    raise ValueError("日期须为 YYYY-MM-DD")
            lower,_ = day_bounds(start,zone,boundary)
            _,upper = day_bounds(end,zone,boundary)
            if lower >= upper:
                raise ValueError("结束日期不能早于开始日期")
            selected.update(since=iso_time(lower),until=iso_time(upper-timedelta(microseconds=1)),start=start,end=end)
            selected["label"] = f"{start} 答疑整理" if start == end else f"{start} 至 {end} 答疑整理"
        return selected

    def generate(self, request):
        config = self.settings.read()
        presentation = request.get("presentation", "reading")
        if presentation not in {"reading", "full"}:
            raise ValueError("请选择精简阅读或完整原文")
        mode = request.get("mode","evidence")
        layout = request.get("layout","horizontal")
        if layout not in {"qa","board","collage","horizontal","stacked"}:
            raise ValueError("请选择左右分区高清图、上下分区拼图、自动拼版、四栏拼版或问答页")
        if mode not in {"evidence","model"}:
            raise ValueError("整理方式须为 evidence 或 model")
        if mode == "model":
            raise ValueError("当前版本尚未接入模型整理，请选择本地证据稿；未向外部模型发送任何群聊。")
        author = str(config.get("target_author_id") or "").strip()
        if not author:
            raise ValueError("请先保存一轮以识别群主，或在设置中填写群主用户 ID")
        selection = self._selection(request,config)
        channel_rows = {str(row["id"] if isinstance(row,dict) else row):row if isinstance(row,dict) else {} for row in config.get("channels",[])}
        bundles = [build_context(self.store,author,channel_id=channel,run_id=selection["run_ids"].get(channel,selection["run_id"]),
            since=selection["since"],until=selection["until"]) for channel in selection["channels"]]
        items = [item for bundle in bundles for item in bundle["items"]]
        if not items:
            if selection["scope"] == "latest":
                raise ValueError("最近一轮没有新增或编辑的群主发言；可选择整个交易日查看已保存内容。")
            raise ValueError("所选范围没有已保存的群主发言，请调整范围或先保存一轮")
        groups = self._group(items)
        panels = []
        for bundle in bundles:
            row = channel_rows.get(bundle["channel_id"],{})
            kind = row.get("kind","qa")
            panel_groups = self._group(bundle["items"]) if kind == "qa" else self._feed_groups(bundle["seeds"])
            if panel_groups or layout == "board":
                panels.append({"channel_id":bundle["channel_id"],"title":row.get("label") or bundle["channel_id"],
                    "kind":kind,"groups":panel_groups,"messages":bundle["seeds"],"warnings":list(bundle["warnings"])})
        warnings = list(dict.fromkeys(warning for bundle in bundles for warning in bundle["warnings"]))
        all_groups = [group for panel in panels for group in panel["groups"]] if layout != "qa" else groups
        media_archive = getattr(self, 'media', None) or MediaArchive(self.root)
        self.media = media_archive
        source_messages = {_key(message): message for group in all_groups for message in group['messages']}
        for channel in selection['channels']:
            media_archive.archive_page(channel, None, [message for message in source_messages.values() if message['channel_id'] == channel])
        speech = getattr(self,'speech',None) or SpeechArchive(self.root,config.get('speech'))
        speech.options = config.get('speech') or {}
        audio_keys = {f'{message["channel_id"]}/{message["message_id"]}/{asset["id"]}'
            for message in source_messages.values() for asset in iter_message_assets(message) if asset.get('is_audio')}
        audio_summary = speech.process_saved(media_archive,keys=audio_keys)
        speech.attach([groups,panels,items,bundles],media_archive)
        missing_assets = {_key(message) for message in source_messages.values()
            if any(self._media(message,attachment).get("status") != "saved" for attachment in iter_message_assets(message))}
        channels_with_gaps = {channel for channel in selection["channels"] if self.store.channel_status(channel)["coverage_gaps"]}
        attachment_warning = "部分附件未保存在本地，离线阅读前请核对下载结果。"
        capture_warning = "归档存在可能的留存缺口，当前稿件只覆盖实际保存到的内容。"
        speech_warning = '部分语音尚未转写，原音频已保留；重新出稿可重试。'
        pending_audio_channels = {message['channel_id'] for message in source_messages.values()
            if any(item['status'] != 'complete' for item in message.get('audio_transcripts',[]))}
        if pending_audio_channels:
            warnings.append(speech_warning)
        if missing_assets:
            warnings.append(attachment_warning)
        if channels_with_gaps:
            warnings.append(capture_warning)
        for panel in panels:
            if any(_key(message) in missing_assets for group in panel["groups"] for message in group["messages"]):
                panel["warnings"].append(attachment_warning)
            if panel["channel_id"] in channels_with_gaps:
                panel["warnings"].append(capture_warning)
            if panel['channel_id'] in pending_audio_channels:
                panel['warnings'].append(speech_warning)
        title = str(request.get("title") or selection["label"]).strip()[:150]
        source_groups, source_panels = all_groups, panels
        decisions = []
        if presentation == 'reading':
            if layout == 'qa':
                all_groups, decisions = choose_reading_groups(all_groups, author)
            else:
                visible_panels = []
                for panel in panels:
                    visible_groups, omitted = choose_reading_groups(panel['groups'], author)
                    decisions.extend(omitted)
                    if visible_groups or layout == 'board':
                        answers = {_key(message): message for group in visible_groups for message in group['answers']}
                        visible_panels.append({**panel, 'groups': visible_groups, 'messages': list(answers.values())})
                panels = visible_panels
                all_groups = [group for panel in panels for group in panel['groups']]
            if not all_groups:
                raise ValueError('这个范围只有闲聊或简短回应，可切换“完整原文”查看。')
        visible_answers = {_key(message) for group in all_groups for message in group['answers']}
        identity = str(uuid.uuid4())
        folder = self.output/identity
        folder.mkdir(mode=0o700)
        now = iso_time()
        metadata = {"id":identity,"title":title,"status":"ready","created_at":now,
            "path":str(folder/"index.html"),"url":f"/output/{identity}/index.html",
            "scope":selection["scope"],"mode":mode,"message_count":len(visible_answers),
            "presentation":presentation,"source_message_count":len(items),"omitted_message_count":len(decisions),
            "topic_count":len(all_groups),"warnings":warnings,"images":[],"selection":selection,
            "layout":layout,"single_columns":[],
            "manuscript_url":f"/output/{identity}/manuscript.md","evidence_url":f"/output/{identity}/evidence.json",
            "archive_url":f"/output/{identity}/archive.html","archive_manuscript_url":f"/output/{identity}/archive.md",
            "date":request.get("date"),"market_timezone":config.get("market_timezone","America/New_York"),
            "audio":audio_summary}
        evidence = {"schema_version":1,"title":title,"created_at":now,"selection":selection,
            "target_author_id":author,"warnings":warnings,"groups":source_groups,"contexts":items,"panels":source_panels,"layout":layout,
            "reading":{"decisions":decisions,"visible_panels":panels,"visible_groups":all_groups}}
        atomic_json(folder/"evidence.json",evidence)
        manuscript,document = self._documents(metadata,all_groups,config)
        archive_md, archive_html = self._documents({**metadata, 'presentation':'full', 'message_count':len(items)},source_groups,config)
        (folder/'archive.md').write_text(archive_md,encoding='utf-8')
        (folder/'archive.html').write_text(archive_html,encoding='utf-8')
        if layout in {"collage","board","horizontal","stacked"}:
            document = self._panel_document(document,metadata,panels,config)
            for panel in panels:
                single_name = f'single-{panel["channel_id"]}.html'
                single_metadata = {**metadata,"title":f'{title} · {panel["title"]}',"message_count":len(panel["messages"]),"warnings":panel.get("warnings",[])}
                _,single_document = self._documents(single_metadata,panel["groups"],config)
                (folder/single_name).write_text(single_document,encoding="utf-8")
                metadata["single_columns"].append({"title":panel["title"],"channel_id":panel["channel_id"],"url":f"/output/{identity}/{single_name}","file":single_name,"images":[]})
        (folder/"manuscript.md").write_text(manuscript,encoding="utf-8")
        (folder/"index.html").write_text(document,encoding="utf-8")
        atomic_json(folder/"metadata.json",metadata)
        return metadata

    @staticmethod
    def _feed_groups(messages):
        return [{"title":"群主原文","answers":[message],"context":[],"followups":[],"missing_context":[],
            "version_history":[],"messages":[message],"continuous_only":False,"warnings":[]} for message in messages]

    def _media(self,message,attachment):
        path = self.root/"data"/"media"/"manifest.json"
        try:
            archive = getattr(self,'media',None)
            manifest = archive.manifest if archive is not None else (json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})
        except (OSError,ValueError):
            manifest = {}
        identity = attachment.get("id")
        saved = manifest.get(f'{message["channel_id"]}/{message["message_id"]}/{identity}',{})
        filename = saved.get("file")
        if saved.get("status") == "saved" and filename and Path(filename).name == filename and (self.root/"data"/"media"/filename).is_file():
            return {**saved,"status":"saved","url":f"/media/{filename}","local_src":f"../../data/media/{filename}"}
        return {**saved,"status":saved.get("status","not_requested") if saved.get("status") != "saved" else "failed"}

    def _panel_document(self,document,metadata,panels,config):
        warning = re.search(r'<article class="topic" data-archive-warnings>.*?</article>',document,re.S)
        panel_html = []
        for panel in panels:
            _,single = self._documents({**metadata,"warnings":[]},panel["groups"],config)
            content = re.search(r'</header>(.*?)<nav class="download-links">',single,re.S).group(1)
            if panel["kind"] == "feed":
                content = re.sub(r'<h2>.*?</h2>',"",content,flags=re.S)
            panel_html.append(f'<section class="content-panel" data-channel="{html.escape(panel["channel_id"])}" data-kind="{html.escape(panel["kind"])}"><h2 class="category-title">{html.escape(panel["title"])}</h2>{content}</section>')
        if warning and panel_html:
            # Keep the global notice in the renderer's topic flow without
            # turning a four-column board into a fifth channel column.
            panel_html[-1] = re.sub(r'</section>$',lambda match:warning.group(0)+match.group(0),panel_html[-1],count=1)
        wrapper = f'<div class="panel-grid" data-layout="{metadata["layout"]}">'+"".join(panel_html)+"</div>"
        document = re.sub(r'(</header>).*?(<nav class="download-links">)',lambda match:match.group(1)+wrapper+match.group(2),document,count=1,flags=re.S)
        document = re.sub(r'<body(?=[ >])',f'<body data-layout="{metadata["layout"]}"',document,count=1)
        return document

    def _group(self, items):
        by_seed = {_key(item["seed"]):item for item in items}
        parent = {key:key for key in by_seed}
        def find(key):
            if parent[key] != key:
                parent[key] = find(parent[key])
            return parent[key]
        def union(left,right):
            if right in parent:
                parent[find(right)] = find(left)
        roots = {}
        for key,item in by_seed.items():
            for linked in item["reply_chain"]+item["followups"]+item["continuations"]:
                union(key,_key(linked))
            if item["reply_chain"]:
                root = _key(item["reply_chain"][0])
            elif item["missing_context"]:
                missing = item["missing_context"][0]
                root = missing["channel_id"],missing["message_id"]
            elif _short_ack(item["seed"]):
                root = "__standalone_short_ack__",item["seed"]["channel_id"]
            else:
                root = key
            if root in roots:
                union(key,roots[root])
            roots[root] = key
        buckets = {}
        for key,item in by_seed.items():
            buckets.setdefault(find(key),[]).append(item)
        groups = []
        for bucket in buckets.values():
            answers = _unique([item["seed"] for item in bucket])
            answer_keys = {_key(message) for message in answers}
            context = _unique([message for item in bucket for message in item["reply_chain"] if _key(message) not in answer_keys])
            followups = _unique([message for item in bucket for message in item["followups"] if _key(message) not in answer_keys and _key(message) not in {_key(m) for m in context}])
            missing = list({(message["channel_id"],message["message_id"]):message for item in bucket for message in item["missing_context"]}.values())
            questions = [message for message in context if message["author_id"] != answers[0]["author_id"]]
            if questions:
                heading = questions[0]["content"].strip().split("\n")[0][:72] or "含附件的原问题"
            elif all(_short_ack(message) for message in answers):
                heading = "简短回应 · 原问题未明确关联"
            else:
                heading = next((message["content"].strip().split("\n")[0][:72] for message in answers if not _short_ack(message)),"群主发言") or "群主发言"
            versions = []
            for answer in answers:
                previous_content = set()
                for version in self.store.get_versions(*_key(answer)):
                    content = version["normalized"]["content"]
                    # A historical round cannot include edits observed later.
                    if answer.get("as_of_run_id") and version["version_hash"] != answer["version_hash"]:
                        current_versions = self.store.list_messages(channel_id=answer["channel_id"],as_of_run_id=answer["as_of_run_id"])
                        if not any(_key(message) == _key(answer) and message["version_hash"] == version["version_hash"] for message in current_versions):
                            continue
                    if content != answer["content"] and content not in previous_content:
                        versions.append({"message":answer,"content":content,"captured_at":version["captured_at"]})
                        previous_content.add(content)
            groups.append({"title":heading,"answers":answers,"context":context,"followups":followups,
                "missing_context":missing,"version_history":versions,
                "messages":_unique(context+answers+followups),
                "continuous_only":not questions and len(answers)>1,
                "warnings":list(dict.fromkeys(warning for item in bucket for warning in item["warnings"]))})
        return sorted(groups,key=lambda group:_order(group["answers"][0]))

    def _documents(self, metadata, groups, config):
        zone = ZoneInfo(config.get("market_timezone","America/New_York"))
        title = metadata["title"]
        reading = metadata.get('presentation') == 'reading'
        zone_name = '纽约时间' if zone.key == 'America/New_York' else '市场当地时间'
        period = f'{metadata["message_count"]} 条发言 · {zone_name}'
        markdown = [f"# {title}","",period,""]
        articles = []
        def block(label,content,message=None,extra_class=""):
            if reading:
                content = clean_reading_text(content, config.get('target_author_id'))
                label = {'原问题 / 回复背景':'问','此前群主发言':'此前回答','群主原话':'答','群主补充':'补充','追问 / 后续对话':'追问'}.get(label,label)
            meta = ""
            render_meta = ""
            if message:
                name = message.get("author_name") or message.get("author_id") or "未知发言人"
                meta = f"{name} · {_time(message,zone)} · 本地证据 {_local_id(message)}"
                display_name = "发言人" if str(name).isdigit() else str(name)[:18]
                render_meta = f'{display_name} · {_time(message,zone)} · 证据 {message["message_id"][-6:]}'
                if message.get("is_reference_snapshot"):
                    meta += " · 引用快照"
                    render_meta += " · 引用快照"
            if reading:
                meta = render_meta = ''
                if not content and extra_class != 'attachment':
                    return ''
            if label or content:
                markdown.extend(([f"**{label}**"+(f"　{meta}" if meta else ""),""] if label else [])+[content or "（无文字内容）",""])
            evidence_attr = f' data-evidence-id="{html.escape(_local_id(message),quote=True)}"' if message else ""
            body = html.escape(content or ('' if reading else '（无文字内容）'))
            if reading:
                body = re.sub(r'\*\*(.+?)\*\*',r'<strong>\1</strong>',body,flags=re.S)
            return f'<section class="block {extra_class}" data-segment{evidence_attr}>'+(f'<div class="block-label">{html.escape(label)}</div>' if label else '') + (f'<div class="source-meta" data-render-meta="{html.escape(render_meta,quote=True)}">{html.escape(meta)}</div>' if meta else "") + (f'<p class="message-text">{body}</p>' if body else '')+'</section>'
        def message_blocks(label,message,extra_class=''):
            parts = [block(label,message['content'],message,extra_class=extra_class)]
            assets = {asset['id']:asset for asset in iter_message_assets(message)}
            for transcript in message.get('audio_transcripts',[]):
                complete = transcript['status'] == 'complete'
                text = transcript.get('text') or ('（未识别到语音文字）' if complete else transcript.get('error') or '原音频已保留，重新出稿可重试。')
                rendered = block('语音转写' if complete else '语音待转写',text,message,extra_class=extra_class)
                asset = assets.get(transcript['asset_id'])
                media = self._media(message,asset) if asset else {}
                if media.get('status') == 'saved':
                    url = html.escape(media['url'],quote=True)
                    rendered = rendered.replace('</section>',f'<div class="audio-playback"><audio controls preload="none" src="{url}"></audio><a href="{url}" download>原音频</a></div></section>')
                    markdown.extend([f'[原音频]({media["url"]})',''])
                parts.append(rendered)
            return ''.join(parts)
        for index,group in enumerate(groups,1):
            heading = f'{index:02d} · {_time(group["answers"][0],zone).split()[-1]}' if reading else f'{index:02d}　{group["title"]}'
            if not reading:
                markdown.extend([f"## {heading}",""])
            parts = []
            for message in group["context"]:
                parts.append(message_blocks("原问题 / 回复背景" if message["author_id"] != group["answers"][0]["author_id"] else "此前群主发言",message))
            for missing in group["missing_context"]:
                text = '原问题未保存。' if reading else f'原消息 {missing["channel_id"]}/{missing["message_id"]} 未保存，无法核实原问题。'
                parts.append(block("上下文缺失",text,extra_class="note"))
            for answer_index,message in enumerate(group["answers"]):
                parts.append(message_blocks("群主原话" if answer_index == 0 else "群主补充",message,extra_class="answer"))
            for message in group["followups"]:
                parts.append(message_blocks("追问 / 后续对话",message))
            for version in group["version_history"]:
                parts.append(block("编辑前已保存版本",version["content"],version["message"],extra_class="note"))
            for message in group['messages']:
                for forwarded in forwarded_texts(message):
                    parts.append(block('转发内容',forwarded,message))
            attachments = [(message,attachment) for message in group["messages"] for attachment in iter_message_assets(message)]
            for message,attachment in attachments:
                if attachment.get('is_audio'):
                    continue
                filename = attachment.get("filename") or attachment.get("fileName") or "附件"
                link = attachment.get("url") or attachment.get("proxy_url") or attachment.get("proxyUrl") or "未保存链接"
                media = self._media(message,attachment)
                if media["status"] == "saved":
                    attachment_html = block('' if reading else "原图 / 附件",'' if reading else f"{filename}\n已保存本地副本。",message,extra_class="attachment")
                    if attachment.get('is_image'):
                        image_html = f'<img class="source-image" src="{html.escape(media["url"],quote=True)}" data-local-src="{html.escape(media["local_src"],quote=True)}" alt="{html.escape(filename,quote=True)}">'
                        attachment_html = attachment_html.replace('</section>',image_html+'</section>')
                    else:
                        attachment_html = attachment_html.replace('</section>',f'<a href="{html.escape(media["url"],quote=True)}">下载本地附件</a></section>')
                    parts.append(attachment_html)
                else:
                    description = '图片尚未保存。' if reading and attachment.get('is_image') else f"{filename}\n{link}\n本地副本未保存（{media['status']}）。"
                    parts.append(block("附件记录",description,message,extra_class="attachment"))
            articles.append(f'<article class="topic"><h2>{html.escape(heading)}</h2>'+"".join(parts)+"</article>")
        warning_html = ""
        if metadata["warnings"]:
            markdown.extend(["## 归档提示",""])
            warnings = "\n".join(metadata["warnings"])
            markdown.extend([warnings,""])
            warning_html = '<article class="topic" data-archive-warnings><h2>归档提示</h2>'+block("核对范围",warnings,extra_class="note")+"</article>"
        document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>
{(Path(__file__).resolve().parent.parent/"web"/"manuscript.css").read_text(encoding="utf-8")}
{(Path(__file__).resolve().parent.parent/"web"/"reading.css").read_text(encoding="utf-8") if reading else ''}
</style></head><body data-presentation="{'reading' if reading else 'full'}"><main id="manuscript"><header><h1>{html.escape(title)}</h1><div class="document-meta">{html.escape(period)}</div></header>{"".join(articles)}{warning_html}<nav class="download-links"><a href="manuscript.md" download>下载文字稿</a><a href="archive.html">完整原文</a><a href="evidence.json" download>查看出处</a></nav></main></body></html>'''
        return "\n".join(markdown),document

    def _folder(self, draft_id):
        try:
            identity = str(uuid.UUID(str(draft_id)))
        except ValueError as exc:
            raise ValueError("稿件 ID 无效") from exc
        folder = self.output/identity
        if not (folder/"metadata.json").is_file():
            raise ValueError("稿件不存在")
        return folder

    def list_drafts(self):
        result = []
        for path in self.output.glob("*/metadata.json"):
            try:
                result.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError,ValueError):
                continue
        return sorted(result,key=lambda draft:draft.get("created_at",""),reverse=True)

    def render(self, draft_id, target='all', force=False, render_scale=1):
        if type(render_scale) is not int or render_scale not in (1,2):
            raise ValueError('导出清晰度须为标准 1× 或 HiDPI 2×')
        if target not in {'all','main','mobile'}:
            raise ValueError('图片类型须为 main、mobile 或 all')
        folder = self._folder(draft_id)
        node = shutil.which("node")
        if not node:
            raise ValueError("生成长图需要 Node.js，请先安装 Node.js 后重试。")
        script = Path(__file__).resolve().parent.parent/"scripts"/"render.mjs"
        metadata = json.loads((folder/"metadata.json").read_text(encoding="utf-8"))
        variant_fields = ('images','image_url','rendered_at','layout_mode','image_dimensions','image_coverage',
            'render_scale','css_dimensions','pixel_font_sizes','render_verification','single_columns')
        variants = metadata.setdefault('image_variants',{})
        def empty_variant(scale):
            return {'images':[],'image_url':None,'rendered_at':None,'layout_mode':None,
                'image_dimensions':[],'image_coverage':None,'render_scale':scale,'css_dimensions':[],
                'pixel_font_sizes':[],'render_verification':{},'single_columns':[
                    {**{key:column[key] for key in ('title','channel_id','url','file') if key in column},'images':[]}
                    for column in metadata.get('single_columns',[])]}
        # Older mobile-only renders have density on each column, with no
        # top-level density. Migrate those independently from the main image.
        for scale in (1,2):
            main_matches = bool(metadata.get('images')) and (metadata.get('render_scale') or 1) == scale
            column_matches = [bool(column.get('images')) and (column.get('render_scale') or metadata.get('render_scale') or 1) == scale
                for column in metadata.get('single_columns',[])]
            if (main_matches or any(column_matches)) and str(scale) not in variants:
                legacy = empty_variant(scale)
                if main_matches:
                    legacy.update({key:metadata.get(key) for key in variant_fields if key not in {'single_columns','render_scale'}})
                for saved,source,matches in zip(legacy['single_columns'],metadata.get('single_columns',[]),column_matches):
                    if matches:
                        saved.update(source)
                variants[str(scale)] = legacy
        variant = variants.setdefault(str(render_scale),empty_variant(render_scale))
        density_folder = folder/f'scale-{render_scale}'
        def publish():
            metadata.update(variant)
            metadata['export_scale'] = render_scale
            atomic_json(folder/'metadata.json',metadata)
        cache_path = folder/'render-cache.json'
        try:
            cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
        except (OSError,ValueError):
            cache = {}
        hits = []
        def render_file(input_path,output_path,key):
            signature = render_cache.fingerprint(input_path,self.root,render_scale)
            cache_key = f'scale-{render_scale}:{key}'
            cached = None if force else render_cache.reuse(cache.get(cache_key),output_path,signature)
            if cached:
                hits.append(key)
                return cached
            result = subprocess.run([node,str(script),str(input_path),str(output_path),str(render_scale)],capture_output=True,text=True,timeout=180)
            if result.returncode:
                safe_error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "浏览器渲染失败"
                raise ValueError(safe_error[:500])
            rendered = json.loads(result.stdout)
            # Older renderer results describe 1x pixels; never label them HiDPI.
            rendered.setdefault('render_scale',1)
            if rendered['render_scale'] != render_scale:
                raise ValueError('渲染器没有按所选倍率输出，请重试')
            saved = render_cache.receipt(rendered,output_path,signature)
            if saved:
                cache[cache_key] = saved
                atomic_json(cache_path,cache)
            return rendered
        verification_keys=('source_coverage','image_coverage','text_coverage','reading_order','topic_integrity','body_font_sizes','blank_ratio','structure','raster_tiles','bands','render_scale','css_dimensions','pixel_font_sizes')
        identity = folder.name
        rendered = {}
        if target in {'all','main'}:
            rendered = render_file(folder/"index.html",density_folder,'main')
            images = [f"/output/{identity}/{density_folder.name}/{Path(path).name}" for path in rendered["images"]]
            variant.update(images=images,rendered_at=iso_time(),image_url=images[0] if images else None,
                layout_mode=rendered.get("layout_mode"),image_dimensions=rendered.get("dimensions",[]),image_coverage=rendered.get('image_coverage'),
                render_scale=rendered['render_scale'],css_dimensions=rendered.get('css_dimensions',[]),pixel_font_sizes=rendered.get('pixel_font_sizes',[]),
                render_verification={key:rendered.get(key) for key in verification_keys})
            # Publish the main export before optional phone columns. A failure
            # in a later column cannot hide an already verified main image.
            publish()
        for column in variant.get("single_columns",[]) if target in {'all','mobile'} else []:
            subfolder = density_folder/f'mobile-{column["channel_id"]}'
            single = render_file(folder/column["file"],subfolder,f'mobile:{column["channel_id"]}')
            column["images"] = [f'/output/{identity}/{density_folder.name}/{subfolder.name}/{Path(path).name}' for path in single["images"]]
            column['image_coverage'] = single.get('image_coverage')
            column.update(image_dimensions=single.get('dimensions',[]),render_scale=single['render_scale'],
                css_dimensions=single.get('css_dimensions',[]),pixel_font_sizes=single.get('pixel_font_sizes',[]))
            column['render_verification'] = {key:single.get(key) for key in verification_keys}
            publish()
        publish()
        return {"images":metadata.get('images',[]),"dimensions":metadata.get('image_dimensions',[]),"layout_mode":metadata.get('layout_mode'),
            "render_scale":metadata.get('render_scale'),"css_dimensions":metadata.get('css_dimensions',[]),"pixel_font_sizes":metadata.get('pixel_font_sizes',[]),
            "panel_heights":rendered.get("panel_heights",[]),"single_columns":metadata.get("single_columns",[]),
            "cache_hits":hits,"target":target,"draft":metadata}
