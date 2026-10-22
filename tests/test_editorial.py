import json
import tempfile
import unittest
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
        folder = self.root/"output"/draft["id"]
        manuscript = (folder/"manuscript.md").read_text()
        self.assertIn("在什么条件下？",manuscript)
        self.assertIn("等待确认后再考虑。",manuscript)
        self.assertIn("还有成交量条件。",manuscript)
        self.assertIn("100/2",manuscript)
        self.assertEqual(draft["topic_count"],1)
        self.assertEqual(draft["message_count"],2)
        self.assertEqual(self.service.list_drafts()[0]["id"],draft["id"])
        evidence = json.loads((folder/"evidence.json").read_text())
        self.assertEqual(evidence["groups"][0]["answers"][0]["content"],"等待确认后再考虑。")

    def test_missing_reply_marked_and_neighbor_not_written_as_question(self):
        self.save([message(1,"邻近但无关的问题",author="member"),message(2,"对",message_reference={"message_id":"999"})])
        draft = self.service.generate({"scope":"latest"})
        text = (Path(draft["path"]).parent/"manuscript.md").read_text()
        self.assertIn("上下文缺失",text)
        self.assertIn("100/999",text)
        self.assertNotIn("邻近但无关的问题",text)

    def test_short_unlinked_acknowledgements_form_one_section(self):
        messages = []
        for index in range(5):
            messages.extend([message(index*2+1,"其他人的发言",author="member"),message(index*2+2,"对")])
        self.save(messages)
        draft = self.service.generate({"scope":"latest"})
        self.assertEqual(draft["topic_count"],1)
        self.assertEqual(draft["message_count"],5)

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


if __name__ == "__main__":
    unittest.main()
