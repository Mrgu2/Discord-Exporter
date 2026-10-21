import tempfile
import unittest
from pathlib import Path

from discord_archive.context import build_context, build_context_for_seed
from discord_archive.store import ArchiveStore


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


if __name__ == "__main__":
    unittest.main()
