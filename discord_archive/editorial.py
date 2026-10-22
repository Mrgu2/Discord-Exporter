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
from .scheduler import day_bounds, market_day
from .settings import atomic_json
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
        layout = request.get("layout","collage")
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
            if layout in {"board","collage"}:
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
        mode = request.get("mode","evidence")
        layout = request.get("layout","collage")
        if layout not in {"qa","board","collage"}:
            raise ValueError("排版须为 collage、board 或 qa")
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
            raise ValueError("所选范围没有已保存的群主发言，请调整范围或先保存一轮")
        groups = self._group(items)
        panels = []
        for bundle in bundles:
            row = channel_rows.get(bundle["channel_id"],{})
            kind = row.get("kind","qa")
            panel_groups = self._group(bundle["items"]) if kind == "qa" else self._feed_groups(bundle["seeds"])
            if panel_groups or layout == "board":
                panels.append({"channel_id":bundle["channel_id"],"title":row.get("label") or bundle["channel_id"],
                    "kind":kind,"groups":panel_groups,"messages":bundle["seeds"]})
        warnings = list(dict.fromkeys(warning for bundle in bundles for warning in bundle["warnings"]))
        all_groups = [group for panel in panels for group in panel["groups"]] if layout != "qa" else groups
        if any(self._media(message,attachment).get("status") != "saved" for group in all_groups for message in group["messages"] for attachment in message.get("attachments",[])):
            warnings.append("部分附件未保存在本地，离线阅读前请核对下载结果。")
        for channel in selection["channels"]:
            if self.store.channel_status(channel)["coverage_gaps"]:
                warnings.append("归档存在可能的留存缺口，当前稿件只覆盖实际保存到的内容。")
                break
        title = str(request.get("title") or selection["label"]).strip()[:150]
        identity = str(uuid.uuid4())
        folder = self.output/identity
        folder.mkdir(mode=0o700)
        now = iso_time()
        metadata = {"id":identity,"title":title,"status":"ready","created_at":now,
            "path":str(folder/"index.html"),"url":f"/output/{identity}/index.html",
            "scope":selection["scope"],"mode":mode,"message_count":len(items),
            "topic_count":len(all_groups),"warnings":warnings,"images":[],"selection":selection,
            "layout":layout,"single_columns":[],
            "manuscript_url":f"/output/{identity}/manuscript.md","evidence_url":f"/output/{identity}/evidence.json",
            "date":request.get("date"),"market_timezone":config.get("market_timezone","America/New_York")}
        evidence = {"schema_version":1,"title":title,"created_at":now,"selection":selection,
            "target_author_id":author,"warnings":warnings,"groups":all_groups,"contexts":items,"panels":panels,"layout":layout}
        atomic_json(folder/"evidence.json",evidence)
        manuscript,document = self._documents(metadata,all_groups,config)
        if layout in {"collage","board"}:
            document = self._panel_document(document,metadata,panels,config)
            for panel in panels:
                single_name = f'single-{panel["channel_id"]}.html'
                single_metadata = {**metadata,"title":f'{title} · {panel["title"]}',"message_count":len(panel["messages"]),"warnings":[]}
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
            manifest = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError,ValueError):
            manifest = {}
        identity = attachment.get("id")
        saved = manifest.get(f'{message["channel_id"]}/{message["message_id"]}/{identity}',{})
        filename = saved.get("file")
        if saved.get("status") == "saved" and filename and Path(filename).name == filename and (self.root/"data"/"media"/filename).is_file():
            return {**saved,"status":"saved","url":f"/media/{filename}","local_src":f"../../data/media/{filename}"}
        return {**saved,"status":saved.get("status","not_requested") if saved.get("status") != "saved" else "failed"}

    def _panel_document(self,document,metadata,panels,config):
        panel_html = []
        for panel in panels:
            _,single = self._documents({**metadata,"warnings":[]},panel["groups"],config)
            content = re.search(r'</header>(.*?)<nav class="download-links">',single,re.S).group(1)
            if panel["kind"] == "feed":
                content = re.sub(r'<h2>.*?</h2>',"",content,flags=re.S)
            panel_html.append(f'<section class="content-panel" data-channel="{html.escape(panel["channel_id"])}" data-kind="{html.escape(panel["kind"])}"><h2 class="category-title">{html.escape(panel["title"])}</h2>{content}</section>')
        wrapper = f'<div class="panel-grid" data-layout="{metadata["layout"]}">'+"".join(panel_html)+"</div>"
        document = re.sub(r'(</header>).*?(<nav class="download-links">)',lambda match:match.group(1)+wrapper+match.group(2),document,count=1,flags=re.S)
        document = document.replace('<body>',f'<body data-layout="{metadata["layout"]}">')
        style = '''.panel-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:40px;align-items:start}.content-panel{min-width:0}.category-title{font-size:34px;border-bottom:3px solid #303945;padding-bottom:20px;margin-bottom:30px}.content-panel .topic>h2{font-size:27px}.source-image{display:block;max-width:100%;width:auto;height:auto;object-fit:contain;object-position:left top;margin:20px 0}.panel-grid[data-layout="board"]{grid-template-columns:repeat(4,minmax(0,1fr))}body[data-layout="board"] main{width:3200px}body[data-layout="collage"] main{width:2400px}.composition-page{max-width:none}.composition-lanes{display:grid;gap:36px;align-items:start}.composition-lane{min-width:0;align-self:start}.composition-page .source-image{max-height:2600px}.composition-page .category-title{margin-top:0}.composition-page .topic>h2{font-size:27px}.composition-page .content-panel{margin-bottom:32px}.composition-page .topic{border-bottom:1px solid #d9dde0;padding-bottom:20px;margin-bottom:24px}@media(max-width:900px){.panel-grid,.panel-grid[data-layout="board"]{grid-template-columns:1fr}body[data-layout] main{width:100%}}'''
        return document.replace('</style>',style+'</style>')

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
        period = f'{len(groups)} 个条目 · {metadata["message_count"]} 条群主发言 · {zone.key}'
        markdown = [f"# {title}","",period,"","原文按回复关系归并，保留时间、条件与本地证据 ID。"," "]
        articles = []
        def block(label,content,message=None,extra_class=""):
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
            markdown.extend([f"**{label}**"+(f"　{meta}" if meta else ""),"",content or "（无文字内容）",""])
            evidence_attr = f' data-evidence-id="{html.escape(_local_id(message),quote=True)}"' if message else ""
            return f'<section class="block {extra_class}" data-segment{evidence_attr}><div class="block-label">{html.escape(label)}</div>' + (f'<div class="source-meta" data-render-meta="{html.escape(render_meta,quote=True)}">{html.escape(meta)}</div>' if meta else "") + f'<p class="message-text">{html.escape(content or "（无文字内容）")}</p></section>'
        for index,group in enumerate(groups,1):
            heading = f'{index:02d}　{group["title"]}'
            markdown.extend([f"## {heading}",""])
            parts = []
            if group["continuous_only"]:
                parts.append(block("阅读提示","以下为连续发言归并；时间邻接不等于已确认属于同一问题。",extra_class="note"))
            for message in group["context"]:
                parts.append(block("原问题 / 回复背景" if message["author_id"] != group["answers"][0]["author_id"] else "此前群主发言",message["content"],message))
            for missing in group["missing_context"]:
                parts.append(block("上下文缺失",f'原消息 {missing["channel_id"]}/{missing["message_id"]} 未保存，无法核实原问题。',extra_class="note"))
            for answer_index,message in enumerate(group["answers"]):
                parts.append(block("群主原话" if answer_index == 0 else "群主补充",message["content"],message,extra_class="answer"))
            for message in group["followups"]:
                parts.append(block("追问 / 后续对话",message["content"],message))
            for version in group["version_history"]:
                parts.append(block("编辑前已保存版本",version["content"],version["message"],extra_class="note"))
            attachments = [(message,attachment) for message in group["messages"] for attachment in message.get("attachments",[])]
            for message,attachment in attachments:
                filename = attachment.get("filename") or attachment.get("fileName") or "附件"
                link = attachment.get("url") or attachment.get("proxy_url") or attachment.get("proxyUrl") or "未保存链接"
                media = self._media(message,attachment)
                if media["status"] == "saved":
                    attachment_html = block("原图 / 附件",f"{filename}\n已保存本地副本。",message,extra_class="attachment")
                    if re.search(r'\.(?:png|jpe?g|gif|webp|avif|bmp)$',media.get("file",""),re.I):
                        image_html = f'<img class="source-image" src="{html.escape(media["url"],quote=True)}" data-local-src="{html.escape(media["local_src"],quote=True)}" alt="{html.escape(filename,quote=True)}">'
                        attachment_html = attachment_html.replace('</section>',image_html+'</section>')
                    else:
                        attachment_html = attachment_html.replace('</section>',f'<a href="{html.escape(media["url"],quote=True)}">下载本地附件</a></section>')
                    parts.append(attachment_html)
                else:
                    parts.append(block("附件记录",f"{filename}\n{link}\n本地副本未保存（{media['status']}）。",message,extra_class="attachment"))
            articles.append(f'<article class="topic"><h2>{html.escape(heading)}</h2>'+"".join(parts)+"</article>")
        warning_html = ""
        if metadata["warnings"]:
            markdown.extend(["## 归档提示",""])
            warnings = "\n".join(metadata["warnings"])
            markdown.extend([warnings,""])
            warning_html = '<article class="topic"><h2>归档提示</h2>'+block("核对范围",warnings,extra_class="note")+"</article>"
        document = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f3ef;color:#22252a;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}}main{{width:1080px;max-width:100%;margin:0 auto;background:white;padding:64px}}header{{padding-bottom:36px;border-bottom:2px solid #252b32;margin-bottom:40px}}h1{{font-size:44px;line-height:1.35;letter-spacing:-1px;margin:0 0 18px;font-weight:650}}.document-meta{{font-size:21px;line-height:1.6;color:#686e77}}.intro{{font-size:23px;line-height:1.6;margin:24px 0 0;color:#555d67}}.topic{{padding:0 0 35px;margin:0 0 38px;border-bottom:1px solid #d9dde0}}h2{{font-size:31px;line-height:1.5;font-weight:650;margin:0 0 25px;overflow-wrap:anywhere}}.block{{margin:0 0 28px;break-inside:avoid}}.block-label{{font-size:22px;font-weight:650;color:#3e4855;margin-bottom:8px}}.source-meta{{font-size:17px;color:#7a818b;line-height:1.65;overflow-wrap:anywhere;margin-bottom:10px}}.message-text{{font-size:27px;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere;margin:0}}.note .message-text,.attachment .message-text{{font-size:23px;color:#626a76}}.answer{{padding-left:22px;border-left:3px solid #c8d0d8}}.download-links{{display:flex;gap:22px;font-size:18px;margin-top:38px}}a{{color:#374b63;text-underline-offset:4px}}.page-heading{{font-size:25px;font-weight:650;line-height:1.4;margin-bottom:8px}}.page-subtitle{{font-size:16px;color:#7a818b;margin-bottom:34px}}.render-page{{width:1080px;background:white;padding:56px 60px 40px;margin:0 0 24px;overflow:hidden}}.page-footer{{font-size:16px;color:#7a818b;border-top:1px solid #d9dde0;padding-top:17px;margin-top:26px;display:flex;justify-content:space-between}}.render-page .topic{{margin-bottom:12px;padding-bottom:8px;border-bottom:0}}.render-page .block:last-child{{margin-bottom:0}}@media(max-width:700px){{main{{padding:30px 22px}}h1{{font-size:29px}}h2{{font-size:24px}}.message-text{{font-size:19px}}.block-label{{font-size:18px}}.source-meta{{font-size:13px}}.document-meta,.intro{{font-size:16px}}.note .message-text,.attachment .message-text{{font-size:17px}}.download-links{{font-size:15px;flex-wrap:wrap}}}}
</style></head><body><main id="manuscript"><header><h1>{html.escape(title)}</h1><div class="document-meta">{html.escape(period)}</div><p class="intro">原文按回复关系归并，保留时间、条件与本地证据 ID。</p></header>{"".join(articles)}{warning_html}<nav class="download-links"><a href="manuscript.md" download>下载文字稿</a><a href="evidence.json" download>查看本地证据</a></nav></main></body></html>'''
        document = document.replace('</style>','.source-image{display:block;max-width:100%;width:auto;height:auto;max-height:2600px;object-fit:contain;object-position:left top;margin:20px 0}</style>')
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

    def render(self, draft_id):
        folder = self._folder(draft_id)
        node = shutil.which("node")
        if not node:
            raise ValueError("生成长图需要 Node.js，请先安装 Node.js 后重试。")
        script = Path(__file__).resolve().parent.parent/"scripts"/"render.mjs"
        def render_file(input_path,output_path):
            result = subprocess.run([node,str(script),str(input_path),str(output_path)],capture_output=True,text=True,timeout=180)
            if result.returncode:
                safe_error = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "浏览器渲染失败"
                raise ValueError(safe_error[:500])
            return json.loads(result.stdout)
        rendered = render_file(folder/"index.html",folder)
        identity = folder.name
        images = [f"/output/{identity}/{Path(path).name}" for path in rendered["images"]]
        metadata = json.loads((folder/"metadata.json").read_text(encoding="utf-8"))
        for column in metadata.get("single_columns",[]):
            subfolder = folder/f'mobile-{column["channel_id"]}'
            single = render_file(folder/column["file"],subfolder)
            column["images"] = [f'/output/{identity}/{subfolder.name}/{Path(path).name}' for path in single["images"]]
        metadata.update(images=images,rendered_at=iso_time(),image_url=images[0] if images else None,
            layout_mode=rendered.get("layout_mode"),image_dimensions=rendered.get("dimensions",[]))
        atomic_json(folder/"metadata.json",metadata)
        return {"images":images,"dimensions":rendered.get("dimensions",[]),"layout_mode":rendered.get("layout_mode"),
            "panel_heights":rendered.get("panel_heights",[]),"single_columns":metadata.get("single_columns",[]),"draft":metadata}
