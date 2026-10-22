import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from discord_archive.context import build_context, build_context_for_seed
from discord_archive.store import ArchiveStore, normalize_message


def msg(identifier, content="hello", author="owner", timestamp="2026-10-21T14:00:00Z", **extra):
    return {"id":str(identifier),"channel_id":"100","author":{"id":author,"username":author},
        "content":content,"timestamp":timestamp,**extra}


class StoreContextTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.store = ArchiveStore(Path(self.directory.name)/"archive.sqlite3")

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def save(self, messages, *, success=True, started_at=None, ended_at=None):
        run_id = self.store.start_run("100",started_at=started_at)
        self.store.ingest_messages("100",messages,run_id)
        self.store.finish_run(run_id,success,error=None if success else "network down",ended_at=ended_at)
        return run_id

    def test_rounds_idempotent_and_old_messages_are_never_deleted(self):
        first = self.save([msg(1),msg(2)])
        second = self.save([msg(2)])
        self.assertEqual(len(self.store.list_messages("100")),2)
        self.assertEqual(len(self.store.get_versions("100","2")),1)
        self.assertEqual(self.store.get_cursor("100"),"2")
        self.assertEqual(len(self.store.list_messages(run_id=first)),2)
        self.assertEqual(len(self.store.list_messages(run_id=second)),1)

    def test_edit_versions_preserve_original_raw(self):
        original = msg(1,"first")
        edited = msg(1,"corrected",edited_timestamp="2026-10-21T14:05:00Z")
        self.save([original])
        self.save([edited])
        self.save([edited])
        versions = self.store.get_versions("100","1")
        self.assertEqual([version["raw"]["content"] for version in versions],["first","corrected"])
        self.assertEqual(self.store.get_message("100","1")["content"],"corrected")
        # An old quote cannot roll a newer directly collected message backward.
        self.save([msg(2,referenced_message=original,message_reference={"message_id":"1"})])
        self.assertEqual(self.store.get_message("100","1")["content"],"corrected")

    def test_historical_run_restores_observed_text_and_excludes_later_followups(self):
        morning = self.save([msg(1,"morning answer")])
        self.save([msg(1,"edited at close",edited_timestamp="2026-10-21T21:00:00Z"),
            msg(2,"late followup",author="member",timestamp="2026-10-21T21:01:00Z",message_reference={"message_id":"1"})])
        self.assertEqual(self.store.list_messages(run_id=morning)[0]["content"],"morning answer")
        historical = build_context(self.store,"owner",channel_id="100",run_id=morning)
        self.assertEqual(historical["items"][0]["seed"]["content"],"morning answer")
        self.assertEqual(historical["items"][0]["followups"],[])

    def test_nested_reply_snapshot_and_context(self):
        question = msg(10,"what is the condition?",author="member")
        self.save([msg(11,"only after confirmation",referenced_message=question,
            message_reference={"message_id":"10","channel_id":"100"})])
        archived_question = self.store.get_message("100","10")
        self.assertTrue(archived_question["is_reference_snapshot"])
        context = build_context_for_seed(self.store,"100","11")
        self.assertEqual([message["message_id"] for message in context["reply_chain"]],["10"])
        self.assertEqual(context["context_status"],"linked")
        self.assertTrue(context["sources"][0]["is_reference_snapshot"])
        self.save([question])
        self.assertFalse(self.store.get_message("100","10")["is_reference_snapshot"])

    def test_failure_stores_partial_pages_but_does_not_advance_cursor(self):
        self.save([msg(10)])
        run_id = self.save([msg(20)],success=False)
        self.assertIsNotNone(self.store.get_message("100","20"))
        self.assertEqual(self.store.get_cursor("100"),"10")
        self.assertEqual(self.store.get_run(run_id)["cursor_after"],"10")
        self.save([msg(20)])
        self.assertEqual(self.store.get_cursor("100"),"20")
        self.assertEqual(len(self.store.get_versions("100","20")),1)

    def test_missing_reference_does_not_promote_neighbor_to_question(self):
        self.save([msg(1,"unrelated nearby question",author="member"),
            msg(2,"answer",message_reference={"message_id":"999","channel_id":"100"})])
        context = build_context_for_seed(self.store,"100","2")
        self.assertEqual(context["reply_chain"],[])
        self.assertEqual(context["missing_context"][0]["message_id"],"999")
        self.assertEqual(context["candidate_neighbors"][0]["evidence_relation"],"candidate_neighbor_only")

    def test_dce_import_deduplicates_without_claiming_live_success(self):
        document = {"channel":{"id":"100","name":"test"},"guild":{"id":"300"},"messages":[
            {"id":"11","timestamp":"2026-10-21T14:00:00+00:00","content":"answer","author":{"id":"owner","name":"Owner"},
             "reference":{"messageId":"10","channelId":"100"}}]}
        imported = self.store.import_dce(document)
        self.store.import_dce(document)
        self.assertEqual(len(self.store.list_messages()),1)
        self.assertEqual(self.store.get_message("100","11")["reply_to_message_id"],"10")
        self.assertIsNone(self.store.channel_status("100")["last_success_at"])
        self.assertIsNone(self.store.get_cursor("100"))
        self.assertEqual(self.store.get_run(imported["run_id"])["source"],"dce")

    def test_coverage_gap_is_risk_not_claimed_deletion(self):
        self.save([msg(1)],started_at="2026-10-19T00:00:00Z",ended_at="2026-10-19T00:01:00Z")
        status = self.store.channel_status("100",now="2026-10-21T02:01:00Z")
        self.assertEqual(status["coverage_status"],"retention_at_risk")
        self.assertEqual(status["hours_since_success"],50)
        self.save([msg(2)],started_at="2026-10-21T02:01:00Z",ended_at="2026-10-21T02:02:00Z")
        status = self.store.channel_status("100",now="2026-10-21T02:03:00Z")
        self.assertEqual(status["coverage_status"],"healthy")
        self.assertEqual(status["coverage_gaps"][0]["kind"],"possible_retention_loss")
        self.assertIn("not proven",status["coverage_gaps"][0]["reason"])

    def test_run_and_date_filters_select_only_target_seeds_then_expand_ancestors(self):
        self.save([msg(1,"earlier question",author="member",timestamp="2026-10-20T14:00:00Z")])
        chosen = self.save([msg(2,"answer",message_reference={"message_id":"1"}),
            msg(3,"followup",author="member",timestamp="2026-10-21T14:01:00Z",message_reference={"message_id":"2"}),
            msg(4,"late correction",timestamp="2026-10-21T21:00:00Z",message_reference={"message_id":"3"})])
        bundle = build_context(self.store,"owner",channel_id="100",run_id=chosen,
            since="2026-10-21T13:00:00Z",until="2026-10-21T15:00:00Z")
        self.assertEqual([message["message_id"] for message in bundle["seeds"]],["2"])
        self.assertEqual([message["message_id"] for message in bundle["items"][0]["reply_chain"]],["1"])
        self.assertEqual([message["message_id"] for message in bundle["items"][0]["followups"]],["3"])

    def test_recovery_marks_interrupted_run_failed(self):
        self.save([msg(1)])
        interrupted = self.store.start_run("100")
        self.store.ingest_messages("100",[msg(2)],interrupted)
        self.store.close()
        self.store = ArchiveStore(Path(self.directory.name)/"archive.sqlite3")
        self.assertEqual(self.store.recover_interrupted_runs(),1)
        self.assertEqual(self.store.get_run(interrupted)["status"],"failed")
        self.assertEqual(self.store.get_cursor("100"),"1")

    def test_reply_chain_oldest_to_parent_and_cycle_safe(self):
        self.save([msg(1,"original",author="member"),msg(2,"clarification",author="member",message_reference={"message_id":"1"}),
            msg(3,"answer",message_reference={"message_id":"2"})])
        context = build_context_for_seed(self.store,"100","3")
        self.assertEqual([message["message_id"] for message in context["reply_chain"]],["1","2"])

    def test_thread_followups_and_continuations_keep_relation_labels(self):
        self.save([msg(1,"main answer",thread={"id":"200"}),
            msg(2,"same-author adjacent",timestamp="2026-10-21T14:01:00Z"),
            msg(3,"different question answer",timestamp="2026-10-21T14:02:00Z",message_reference={"message_id":"999"})])
        run_id = self.store.start_run("200")
        self.store.ingest_messages("200",[{"id":"4","channel_id":"200","author":{"id":"member"},
            "content":"inside actual thread","timestamp":"2026-10-21T14:03:00Z"}],run_id)
        self.store.finish_run(run_id,True)
        context = build_context_for_seed(self.store,"100","1")
        self.assertEqual([message["message_id"] for message in context["continuations"]],["2"])
        self.assertEqual(context["continuations"][0]["evidence_relation"],"consecutive_same_author")
        self.assertEqual(context["followups"][0]["evidence_relation"],"same_thread_membership")
        self.assertEqual(context["followups"][0]["channel_id"],"200")

    def test_run_changes_exclude_overlap_but_keep_new_and_edited_targets(self):
        question = msg(1,"original question",author="member")
        morning = msg(2,"morning answer",message_reference={"message_id":"1"})
        unchanged = msg(3,"unchanged morning note")
        first = self.save([question,morning,unchanged])
        self.assertEqual([item["message_id"] for item in self.store.list_run_changes(first,author_id="owner")],["2","3"])
        edited = msg(2,"edited at close",edited_timestamp="2026-10-21T20:00:00Z",message_reference={"message_id":"1"})
        closing = msg(4,"closing supplement",timestamp="2026-10-21T20:01:00Z",message_reference={"message_id":"2"})
        second = self.save([question,edited,unchanged,closing])
        changes = self.store.list_run_changes(second,author_id="owner")
        self.assertEqual([(item["message_id"],item["change_type"]) for item in changes],[("2","edited"),("4","new")])
        self.assertTrue(all(item["baseline_run_id"] == first for item in changes))
        context = build_context(self.store,"owner",channel_id="100",run_id=second)
        self.assertEqual([item["message_id"] for item in context["seeds"]],["2","4"])
        self.assertEqual(context["items"][1]["reply_chain"][0]["content"],"original question")
        # A successful unchanged rescan produces no new manuscript seeds.
        third = self.save([question,edited,unchanged,closing])
        self.assertEqual(self.store.list_run_changes(third,author_id="owner"),[])

    def test_failed_run_is_not_the_change_baseline(self):
        morning = msg(1,"morning")
        first = self.save([morning])
        edited = msg(1,"updated",edited_timestamp="2026-10-21T20:00:00Z")
        closing = msg(2,"new message",timestamp="2026-10-21T20:01:00Z",message_reference={"message_id":"1"})
        self.save([edited,closing],success=False)
        recovered = self.save([edited,closing])
        changes = self.store.list_run_changes(recovered,author_id="owner")
        self.assertEqual([item["message_id"] for item in changes],["1","2"])
        self.assertTrue(all(item["baseline_run_id"] == first for item in changes))
        # With no prior success at all, partial saved pages must not suppress
        # the first successful round's contribution.
        run = self.store.start_run("200")
        self.store.ingest_messages("200",[{**morning,"channel_id":"200"}],run)
        self.store.finish_run(run,False,error="interrupted")
        success = self.store.start_run("200")
        self.store.ingest_messages("200",[{**morning,"channel_id":"200"}],success)
        self.store.finish_run(success,True)
        self.assertEqual(len(self.store.list_run_changes(success,author_id="owner")),1)

    def test_new_reply_keeps_unchanged_previous_answer_as_explicit_context(self):
        question = msg(1,"original question",author="member")
        morning = msg(2,"morning condition",message_reference={"message_id":"1"})
        self.save([question,morning])
        closing = msg(3,"condition still applies",timestamp="2026-10-21T20:00:00Z",message_reference={"message_id":"2"})
        second = self.save([question,morning,closing])
        context = build_context(self.store,"owner",channel_id="100",run_id=second)
        self.assertEqual([item["message_id"] for item in context["seeds"]],["3"])
        self.assertEqual([item["message_id"] for item in context["items"][0]["reply_chain"]],["1","2"])
        day = build_context(self.store,"owner",channel_id="100",since="2026-10-21T00:00:00Z",until="2026-10-21T23:59:59Z")
        self.assertEqual([item["message_id"] for item in day["seeds"]],["2","3"])

    def signed_attachment(self,signature="old",**extra):
        return {"id":"800","filename":"chart.png",
            "url":f"https://cdn.discordapp.com/attachments/100/800/chart.png?ex={signature}&is=abc&hm={signature}",
            "proxy_url":f"https://media.discordapp.net/attachments/100/800/chart.png?ex={signature}&is=abc&hm={signature}",**extra}

    def test_attachment_signature_rotation_is_not_an_edit_or_incremental_seed(self):
        original = msg(1,"unchanged chart",attachments=[self.signed_attachment()])
        self.save([original])
        refreshed = msg(1,"unchanged chart",attachments=[self.signed_attachment("new")])
        second = self.save([refreshed])
        self.assertEqual(len(self.store.get_versions("100","1")),1)
        self.assertEqual(self.store.list_run_changes(second,author_id="owner"),[])
        self.assertEqual(build_context(self.store,"owner",channel_id="100",run_id=second)["seeds"],[])
        current = self.store.get_message("100","1")
        self.assertEqual(current["raw"]["attachments"],refreshed["attachments"])
        self.assertEqual(current["attachments"],refreshed["attachments"])
        self.assertIn("ex=new",current["raw"]["attachments"][0]["url"])

    def test_attachment_canonicalization_preserves_real_edits_and_add_remove(self):
        self.save([msg(1,"original text",attachments=[self.signed_attachment()])])
        changed = self.save([msg(1,"changed text",attachments=[self.signed_attachment("second")])])
        self.assertEqual(len(self.store.get_versions("100","1")),2)
        self.assertEqual(len(self.store.list_run_changes(changed,author_id="owner")),1)
        another = self.signed_attachment("third",id="801",filename="other.png",url="https://cdn.discordapp.com/attachments/100/801/other.png?ex=x&is=y&hm=z")
        added = self.save([msg(1,"changed text",attachments=[self.signed_attachment("third"),another])])
        self.assertEqual(len(self.store.list_run_changes(added,author_id="owner")),1)
        removed = self.save([msg(1,"changed text",attachments=[another])])
        self.assertEqual(len(self.store.get_versions("100","1")),4)
        self.assertEqual(len(self.store.list_run_changes(removed,author_id="owner")),1)
        replacement = {**another,"url":"https://cdn.discordapp.com/attachments/100/801/replaced.png?ex=next&is=y&hm=z"}
        self.save([msg(1,"changed text",attachments=[replacement])])
        self.assertEqual(len(self.store.get_versions("100","1")),5)

    def test_only_known_discord_attachment_signature_parameters_are_ignored(self):
        cases = [
            ("https://example.invalid/attachments/100/800/chart.png?ex=old","https://example.invalid/attachments/100/800/chart.png?ex=new"),
            ("https://cdn.discordapp.com.example.invalid/attachments/100/800/chart.png?ex=old","https://cdn.discordapp.com.example.invalid/attachments/100/800/chart.png?ex=new"),
            ("https://cdn.discordapp.com/avatars/800/chart.png?ex=old","https://cdn.discordapp.com/avatars/800/chart.png?ex=new"),
            ("https://cdn.discordapp.com/attachments/100/800/chart.png?ex=old&width=640","https://cdn.discordapp.com/attachments/100/800/chart.png?ex=new&width=320"),
        ]
        for before,after in cases:
            left = normalize_message(msg(1,attachments=[{"id":"800","url":before}]),"100")
            right = normalize_message(msg(1,attachments=[{"id":"800","url":after}]),"100")
            self.assertNotEqual(left["version_hash"],right["version_hash"])
        before = msg(1,"literal signed URL: ex=old",attachments=[self.signed_attachment()])
        after = msg(1,"literal signed URL: ex=new",attachments=[self.signed_attachment("new")])
        self.assertNotEqual(normalize_message(before,"100")["version_hash"],normalize_message(after,"100")["version_hash"])

    def test_attachment_proxy_signature_in_embed_metadata_is_also_transient(self):
        old = self.signed_attachment()
        new = self.signed_attachment("new")
        before = msg(1,embeds=[{"image":{"url":old["url"],"proxy_url":old["proxy_url"]}}])
        after = msg(1,embeds=[{"image":{"url":new["url"],"proxy_url":new["proxy_url"]}}])
        self.save([before])
        refreshed = self.save([after])
        self.assertEqual(len(self.store.get_versions("100","1")),1)
        self.assertEqual(self.store.list_run_changes(refreshed,author_id="owner"),[])

    def test_empty_target_channel_is_not_a_context_warning(self):
        run = self.save([msg(1,"other participant only",author="member")])
        for selection in ({"run_id":run},{"since":"2026-10-21T00:00:00Z","until":"2026-10-21T23:59:59Z"}):
            context = build_context(self.store,"owner",channel_id="100",**selection)
            self.assertEqual(context["seeds"],[])
            self.assertEqual(context["warnings"],[])
            self.assertEqual(context["stats"]["missing_context_count"],0)

    def test_missing_reference_warning_is_chinese_precise_and_deduplicated(self):
        run = self.save([msg(1,"unrelated neighbor",author="member"),
            msg(2,"first answer",message_reference={"message_id":"999"}),
            msg(3,"second answer",message_reference={"message_id":"999"})])
        context = build_context(self.store,"owner",channel_id="100",run_id=run)
        self.assertEqual(context["stats"]["missing_context_count"],1)
        self.assertEqual(context["warnings"],["有 1 条被引用消息未保存在本地，相关上下文缺失；未推断或补写原文。"])
        missing = context["items"][0]["missing_context"][0]
        self.assertEqual(missing["message_id"],"999")
        self.assertEqual(missing["reason"],"not_in_local_archive")
        self.assertIn("原消息未保存在本地",missing["label"])
        self.assertIn("不可根据邻近消息补写",missing["label"])
        self.assertEqual(context["items"][0]["reply_chain"],[])

    def test_cycle_and_expansion_limit_warnings_are_chinese(self):
        self.save([msg(1,"question",author="member",message_reference={"message_id":"2"}),
            msg(2,"answer",message_reference={"message_id":"1"})])
        cycle = build_context_for_seed(self.store,"100","2")
        self.assertIn("发现循环回复引用，已停止继续展开。",cycle["warnings"])
        limited = build_context_for_seed(self.store,"100","2",max_reply_depth=1)
        self.assertIn("回复链已达到 1 层展开上限，更早的上下文未继续展开。",limited["warnings"])
        followups = build_context_for_seed(self.store,"100","1",max_followups=0)
        self.assertIn("后续回复已达到 0 条展开上限。",followups["warnings"])

    def test_legacy_signed_hash_survives_upgrade_without_false_edit(self):
        original = msg(1,"legacy text",attachments=[self.signed_attachment()])
        first = self.save([original])
        normalized = normalize_message(original,"100")
        legacy_substance = {key:normalized[key] for key in ("content","edited_at","reply_to_message_id","reply_to_channel_id","attachments","embeds","stickers")}
        legacy_hash = hashlib.sha256(json.dumps(legacy_substance,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        self.assertNotEqual(legacy_hash,normalized["version_hash"])
        normalized["version_hash"] = legacy_hash
        # Simulate exactly the rows produced by the previous hashing algorithm.
        with self.store.conn:
            self.store.conn.execute("UPDATE messages SET version_hash=?,normalized_json=? WHERE channel_id='100' AND message_id='1'",(legacy_hash,json.dumps(normalized)))
            self.store.conn.execute("UPDATE message_versions SET version_hash=?,normalized_json=? WHERE channel_id='100' AND message_id='1'",(legacy_hash,json.dumps(normalized)))
            self.store.conn.execute("UPDATE run_messages SET version_hash=? WHERE run_id=?",(legacy_hash,first))
        refreshed = msg(1,"legacy text",attachments=[self.signed_attachment("new")])
        second = self.save([refreshed])
        self.assertEqual(len(self.store.get_versions("100","1")),1)
        self.assertEqual(self.store.get_message("100","1")["version_hash"],legacy_hash)
        self.assertEqual(self.store.get_message("100","1")["raw"]["attachments"],refreshed["attachments"])
        self.assertEqual(self.store.list_run_changes(second,author_id="owner"),[])
        edited = self.save([msg(1,"actual new text",attachments=[self.signed_attachment("third")])])
        self.assertEqual(len(self.store.get_versions("100","1")),2)
        self.assertEqual(len(self.store.list_run_changes(edited,author_id="owner")),1)
        rotated = self.save([msg(1,"actual new text",attachments=[self.signed_attachment("fourth")])])
        self.assertEqual(len(self.store.get_versions("100","1")),2)
        self.assertEqual(self.store.list_run_changes(rotated,author_id="owner"),[])


if __name__ == "__main__":
    unittest.main()
