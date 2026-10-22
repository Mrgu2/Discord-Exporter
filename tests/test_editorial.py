import json
import tempfile
import unittest
from unittest.mock import patch
from html.parser import HTMLParser
from pathlib import Path

from discord_archive.editorial import DraftService
from discord_archive.store import ArchiveStore


class FakeSettings:
    def __init__(self,channels=None):
        self.value = {"channels":channels or [{"id":"100","label":"答疑"}],"target_author_id":"owner",
            "market_timezone":"America/New_York","day_boundary_hour":4}

    def read(self):
        return self.value


class FakeCredentials:
    def get(self,_kind):
        raise AssertionError("Evidence generation must not read model credentials")


class WarningLocations(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack, self.locations = [], []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'article' and 'data-archive-warnings' in attributes:
            self.locations.append([(name, attrs.get('class', '')) for name, attrs in self.stack])
        if tag not in {'meta', 'link', 'img', 'br', 'hr', 'input'}:
            self.stack.append((tag, attributes))

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


def message(identity,content,author="owner",timestamp="2026-10-21T14:00:00Z",**extra):
    return {"id":str(identity),"channel_id":"100","author":{"id":author,"username":author},
        "content":content,"timestamp":timestamp,**extra}


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = ArchiveStore(self.root/"archive.sqlite3")
        self.settings = FakeSettings()
        self.service = DraftService(self.store,self.root,self.settings,FakeCredentials())

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def save(self,messages):
        run = self.store.start_run("100")
        self.store.ingest_messages("100",messages,run)
        self.store.finish_run(run,True)
        return run

    def test_evidence_contains_original_question_answer_and_local_ids(self):
        self.save([message(1,"在什么条件下？",author="member"),
            message(2,"等待确认后再考虑。",message_reference={"message_id":"1"}),
            message(3,"还有成交量条件。",timestamp="2026-10-21T14:01:00Z")])
        draft = self.service.generate({"scope":"latest"})
        self.assertEqual(draft["layout"],"horizontal")
        folder = self.root/"output"/draft["id"]
        manuscript = (folder/"manuscript.md").read_text()
        self.assertIn("在什么条件下？",manuscript)
        self.assertIn("等待确认后再考虑。",manuscript)
        self.assertIn("还有成交量条件。",manuscript)
        self.assertIn("100/2",(folder/"archive.md").read_text())
        self.assertEqual(draft["topic_count"],1)
        self.assertEqual(draft["message_count"],2)
        self.assertEqual(self.service.list_drafts()[0]["id"],draft["id"])
        evidence = json.loads((folder/"evidence.json").read_text())
        self.assertEqual(evidence["groups"][0]["answers"][0]["content"],"等待确认后再考虑。")

    def test_render_saves_actual_resolution_for_main_and_mobile_images(self):
        self.save([message(1,'等待市场确认之后再考虑。')])
        draft = self.service.generate({'scope':'latest'})
        outputs = [
            {'images':['long-01.png'],'dimensions':[{'width':8000,'height':4000}],'layout_mode':'horizontal',
                'render_scale':2,'css_dimensions':[{'width':4000,'height':2000}],'pixel_font_sizes':['54px']},
            {'images':['long-01.png'],'dimensions':[{'width':2120,'height':3000}],'layout_mode':'single',
                'render_scale':2,'css_dimensions':[{'width':1060,'height':1500}],'pixel_font_sizes':['48px']},
        ]
        with patch('discord_archive.editorial.shutil.which',return_value='/fixture/node'), \
                patch('discord_archive.editorial.subprocess.run') as run:
            run.side_effect = [type('Result',(),{'returncode':0,'stdout':json.dumps(output)}) for output in outputs]
            result = self.service.render(draft['id'])
        stored = json.loads((Path(draft['path']).parent/'metadata.json').read_text())
        for actual,expected in [(stored,outputs[0]),(stored['single_columns'][0],outputs[1])]:
            self.assertEqual(actual['image_dimensions'],expected['dimensions'])
            for key in ['render_scale','css_dimensions','pixel_font_sizes']:
                self.assertEqual(actual[key],expected[key])
                self.assertEqual(actual['render_verification'][key],expected[key])
        for key in ['render_scale','css_dimensions','pixel_font_sizes']:
            self.assertEqual(result[key],outputs[0][key])

    def test_legacy_render_result_is_not_labeled_hidpi(self):
        self.save([message(1,'等待市场确认之后再考虑。')])
        draft = self.service.generate({'scope':'latest','layout':'qa'})
        output = {'images':['long-01.png'],'dimensions':[{'width':1060,'height':1500}],'layout_mode':'single'}
        with patch('discord_archive.editorial.shutil.which',return_value='/fixture/node'), \
                patch('discord_archive.editorial.subprocess.run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(output)
            rendered = self.service.render(draft['id'])
        self.assertEqual(rendered['draft']['render_scale'],1)

    def test_missing_reply_marked_and_neighbor_not_written_as_question(self):
        self.save([message(1,"邻近但无关的问题",author="member"),message(2,"对",message_reference={"message_id":"999"})])
        draft = self.service.generate({"scope":"latest"})
        text = (Path(draft["path"]).parent/"manuscript.md").read_text()
        self.assertIn("上下文缺失",text)
        self.assertIn("100/999",(Path(draft["path"]).parent/"archive.md").read_text())
        self.assertNotIn("邻近但无关的问题",text)

    def test_short_unlinked_acknowledgements_form_one_section(self):
        messages = []
        for index in range(5):
            messages.extend([message(index*2+1,"其他人的发言",author="member"),message(index*2+2,"对")])
        self.save(messages)
        draft = self.service.generate({"scope":"latest","presentation":"full"})
        self.assertEqual(draft["topic_count"],1)
        self.assertEqual(draft["message_count"],5)

    def test_reading_copy_removes_noise_and_hint_but_keeps_full_archive(self):
        self.save([message(1,'VIX尾盘再看吗？',author='member'),
            message(2,'是的',message_reference={'message_id':'1'}),
            message(3,'谢谢老大',author='member',message_reference={'message_id':'2'}),
            message(4,'我去喝咖啡了')])
        draft=self.service.generate({'scope':'latest','layout':'qa'})
        folder=Path(draft['path']).parent
        document=Path(draft['path']).read_text();manuscript=(folder/'manuscript.md').read_text()
        self.assertEqual(document.count('VIX尾盘再看吗？'),1)
        self.assertIn('是的',manuscript)
        self.assertNotIn('谢谢老大',manuscript)
        self.assertNotIn('我去喝咖啡了',manuscript)
        self.assertNotIn('阅读提示',document)
        self.assertNotIn('时间邻接',document)
        self.assertNotIn('本地证据',document)
        self.assertIn('我去喝咖啡了',(folder/'archive.md').read_text())
        self.assertEqual(draft['message_count'],1)

    def test_forwarded_text_and_image_are_not_empty_content(self):
        media=self.root/'data'/'media';media.mkdir(parents=True)
        (media/'forward.png').write_bytes(b'fixture')
        (media/'manifest.json').write_text(json.dumps({'100/2/snapshot-0-9':{'status':'saved','file':'forward.png'}}))
        self.save([message(2,'',message_snapshots=[{'message':{'content':'转发的市场信息','attachments':[{'id':'9','filename':'chart.png','content_type':'image/png','url':'https://cdn.discordapp.com/attachments/1/9/chart.png'}]}}])])
        draft=self.service.generate({'scope':'latest','layout':'qa'})
        document=Path(draft['path']).read_text()
        self.assertIn('转发的市场信息',document)
        self.assertIn('src="/media/forward.png"',document)
        self.assertNotIn('无文字内容',document)

    def test_trade_day_includes_next_early_morning_but_excludes_boundary(self):
        self.save([message(1,"开盘",timestamp="2026-10-21T14:00:00Z"),
            message(2,"纽约凌晨三点",timestamp="2026-10-22T07:00:00Z"),
            message(3,"下一交易日",timestamp="2026-10-22T08:00:00Z")])
        draft = self.service.generate({"scope":"day","date":"2026-10-21"})
        text = (Path(draft["path"]).parent/"manuscript.md").read_text()
        self.assertIn("纽约凌晨三点",text)
        self.assertNotIn("下一交易日",text)
        self.assertEqual(draft["message_count"],2)

    def test_html_escapes_source_and_title(self):
        self.save([message(1,"<script>alert(1)</script>")])
        draft = self.service.generate({"title":"<img src=x onerror=alert(1)>"})
        document = Path(draft["path"]).read_text()
        self.assertNotIn("<script>",document)
        self.assertIn("&lt;script&gt;",document)
        self.assertNotIn("<img src=x",document)

    def test_model_mode_explicitly_unsupported_and_no_output_written(self):
        self.save([message(1,"原文")])
        with self.assertRaisesRegex(ValueError,"尚未接入模型"):
            self.service.generate({"mode":"model"})
        self.assertEqual(self.service.list_drafts(),[])

    def test_invalid_range_and_draft_paths_rejected(self):
        self.save([message(1,"原文")])
        with self.assertRaises(ValueError):
            self.service.generate({"scope":"range","start":"2026-10-22","end":"2026-10-21"})
        with self.assertRaises(ValueError):
            self.service.render("../../credentials")

    def test_collage_feed_keeps_only_target_originals_and_omits_empty_panels(self):
        self.settings.value["channels"] = [{"id":"100","label":"示例栏目甲","kind":"feed"},{"id":"200","label":"空栏目","kind":"feed"}]
        self.save([message(1,"别人的提问",author="member"),message(2,"群主原文",message_reference={"message_id":"1"})])
        draft = self.service.generate({"layout":"collage"})
        document = Path(draft["path"]).read_text()
        self.assertIn('data-layout="collage"',document)
        self.assertIn("群主原文",document)
        self.assertNotIn("别人的提问",document)
        self.assertNotIn("空栏目",document)
        self.assertEqual(len(draft["single_columns"]),1)
        self.assertTrue((Path(draft["path"]).parent/draft["single_columns"][0]["file"]).is_file())

    def test_board_requires_four_feed_channels(self):
        self.save([message(1,"原文")])
        with self.assertRaisesRegex(ValueError,"四个"):
            self.service.generate({"layout":"board"})

    def test_global_missing_context_warning_survives_every_panel_layout_once(self):
        self.settings.value['channels'] = [{'id':str(identity), 'label':f'栏目{identity}', 'kind':'feed'}
                                           for identity in [100,200,300,400]]
        self.save([message(2,'等待量价确认。',message_reference={'message_id':'999'})])
        for layout in ['stacked','horizontal','collage','board']:
            with self.subTest(layout=layout):
                draft = self.service.generate({'scope':'day','date':'2026-10-21','layout':layout})
                document = Path(draft['path']).read_text()
                self.assertEqual(len(draft['warnings']),1)
                self.assertEqual(document.count(draft['warnings'][0]),1)
                self.assertEqual(document.count('data-archive-warnings'),1)
                self.assertNotIn('阅读提示',document)
                self.assertNotIn('已经删除',document)
                parsed = WarningLocations(); parsed.feed(document)
                self.assertEqual(len(parsed.locations),1)
                self.assertIn(('div','panel-grid'),parsed.locations[0])
                self.assertIn(('section','content-panel'),parsed.locations[0])
                warning = document.split('data-archive-warnings>',1)[1].split('</article>',1)[0]
                self.assertIn('class="message-text"',warning)
                self.assertIn('data-segment',warning)
                self.assertEqual(document.count('class="content-panel"'),4 if layout == 'board' else 1)

    def test_no_global_notice_is_added_to_normal_panel_documents(self):
        self.settings.value['channels'] = [{'id':str(identity), 'label':f'栏目{identity}', 'kind':'feed'}
                                           for identity in [100,200,300,400]]
        self.save([message(2,'等待量价确认。')])
        for layout in ['stacked','horizontal','collage','board']:
            with self.subTest(layout=layout):
                draft = self.service.generate({'scope':'day','date':'2026-10-21','layout':layout})
                document = Path(draft['path']).read_text()
                self.assertEqual(draft['warnings'],[])
                self.assertNotIn('data-archive-warnings',document)
                self.assertNotIn('归档提示',document)
                self.assertNotIn('阅读提示',document)

    def test_mobile_column_only_keeps_its_own_channel_warning(self):
        self.settings.value['channels'] = [{'id':str(identity), 'label':f'栏目{identity}', 'kind':'feed'}
                                           for identity in [100,200,300,400]]
        self.save([message(2,'等待量价确认。',message_reference={'message_id':'999'})])
        run = self.store.start_run('200')
        self.store.ingest_messages('200',[message(3,'控制仓位。',channel_id='200')],run)
        self.store.finish_run(run,True)
        for layout in ['stacked','horizontal','collage','board']:
            with self.subTest(layout=layout):
                draft = self.service.generate({'scope':'day','date':'2026-10-21','layout':layout})
                folder = Path(draft['path']).parent
                self.assertEqual(len(draft['warnings']),1)
                warning = draft['warnings'][0]
                columns = {column['channel_id']:(folder/column['file']).read_text()
                           for column in draft['single_columns']}
                self.assertEqual(columns['100'].count(warning),1)
                self.assertEqual(columns['100'].count('data-archive-warnings'),1)
                for channel,document in columns.items():
                    if channel != '100':
                        self.assertNotIn(warning,document)
                        self.assertNotIn('data-archive-warnings',document)
                self.assertEqual(Path(draft['path']).read_text().count(warning),1)

    def test_stacked_and_horizontal_select_latest_changes_from_all_configured_channels(self):
        self.settings.value['channels']=[{'id':'100','label':'示例栏目甲','kind':'feed'},{'id':'200','label':'答疑','kind':'qa'}]
        self.save([message(1,'仓位控制。')])
        run=self.store.start_run('200')
        self.store.ingest_messages('200',[{**message(2,'等待确认。'),'channel_id':'200'}],run)
        self.store.finish_run(run,True)
        for layout in ['stacked','horizontal']:
            with self.subTest(layout=layout):
                draft=self.service.generate({'scope':'latest','layout':layout})
                self.assertEqual(draft['message_count'],2)
                self.assertEqual(len(draft['selection']['run_ids']),2)
                self.assertEqual(len(draft['single_columns']),2)
                document=Path(draft['path']).read_text()
                self.assertIn(f'data-layout="{layout}"',document)
                self.assertIn('data-kind="feed"',document)
                self.assertIn('data-kind="qa"',document)

    def test_mobile_columns_keep_only_their_own_capture_and_attachment_gaps(self):
        self.settings.value['channels']=[{'id':str(channel),'label':f'栏目{channel}','kind':'feed'}
                                          for channel in (100,200,300,400)]
        self.save([message(1,'等待确认。')])
        self.store.record_gap('100','2026-10-20T00:00:00Z','2026-10-21T00:00:00Z')
        for channel in ('200','300'):
            run=self.store.start_run(channel)
            attachments=[{'id':'image','filename':'missing.png','url':'https://example.invalid/missing.png'}] if channel=='200' else []
            self.store.ingest_messages(channel,[message(channel,'控制仓位。',channel_id=channel,attachments=attachments)],run)
            self.store.finish_run(run,True)
        capture_warning='归档存在可能的留存缺口，当前稿件只覆盖实际保存到的内容。'
        attachment_warning='部分附件未保存在本地，离线阅读前请核对下载结果。'
        for layout in ('stacked','horizontal','collage','board'):
            with self.subTest(layout=layout):
                draft=self.service.generate({'scope':'day','date':'2026-10-21','layout':layout})
                folder=Path(draft['path']).parent
                columns={column['channel_id']:(folder/column['file']).read_text() for column in draft['single_columns']}
                self.assertEqual(columns['100'].count(capture_warning),1)
                self.assertNotIn(attachment_warning,columns['100'])
                self.assertEqual(columns['200'].count(attachment_warning),1)
                self.assertNotIn(capture_warning,columns['200'])
                for channel in ('300','400'):
                    if channel in columns:
                        self.assertNotIn(capture_warning,columns[channel])
                        self.assertNotIn(attachment_warning,columns[channel])
                main=Path(draft['path']).read_text()
                self.assertEqual(main.count(capture_warning),1)
                self.assertEqual(main.count(attachment_warning),1)
                self.assertNotIn('阅读提示',main)

    def test_media_manifest_embeds_local_image_and_preserves_full_source_id(self):
        media = self.root/"data"/"media"
        media.mkdir(parents=True)
        (media/"sample.png").write_bytes(b"fixture file only; renderer checks actual images separately")
        (media/"manifest.json").write_text(json.dumps({"100/2/3":{"status":"saved","file":"sample.png"}}))
        self.save([message(2,"原图说明",attachments=[{"id":"3","filename":"chart.png","url":"https://example.invalid/chart.png"}])])
        draft = self.service.generate({"layout":"qa"})
        document = Path(draft["path"]).read_text()
        self.assertIn('src="/media/sample.png"',document)
        self.assertIn('data-local-src="../../data/media/sample.png"',document)
        self.assertIn("100/2",document)
        self.assertNotIn("部分附件未保存在本地",draft["warnings"])

    def test_latest_is_incremental_while_trade_day_keeps_all_target_messages(self):
        question = message(1,"原问题",author="member")
        morning = message(2,"上午条件",message_reference={"message_id":"1"})
        unrelated = message(3,"上午另一条未变化发言")
        self.save([question,morning,unrelated])
        first = self.service.generate({"scope":"latest","layout":"qa"})
        self.assertEqual(first["message_count"],2)
        closing = message(4,"尾盘补充",timestamp="2026-10-21T20:00:00Z",message_reference={"message_id":"2"})
        self.save([question,morning,unrelated,closing])
        latest = self.service.generate({"scope":"latest","layout":"qa"})
        text = (Path(latest["path"]).parent/"manuscript.md").read_text()
        self.assertEqual(latest["message_count"],1)
        self.assertIn("原问题",text)
        self.assertIn("上午条件",text)
        self.assertIn("此前回答",text)
        self.assertIn("尾盘补充",text)
        self.assertNotIn("上午另一条未变化发言",text)
        day = self.service.generate({"scope":"day","date":"2026-10-21","layout":"qa"})
        self.assertEqual(day["message_count"],3)
        self.save([question,morning,unrelated,closing])
        with self.assertRaisesRegex(ValueError,"没有新增或编辑"):
            self.service.generate({"scope":"latest"})


if __name__ == "__main__":
    unittest.main()
