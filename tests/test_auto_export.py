import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from discord_archive.auto_export import ScheduledExporter
from discord_archive.collector import AccessDenied, DiscordAPIError
from discord_archive.editorial import EmptyDraft
from discord_archive.export_schedule import normalize_auto_export


SLOT = {'key':'auto-export:2026-10-23:16:15','scheduled_at':'2026-10-23T20:15:00Z','market_date':'2026-10-23'}
BEFORE = '2026-10-23T20:14:00Z'
NOW = '2026-10-23T20:15:01.000000Z'


def configuration(**options):
    return {'market_timezone':'America/New_York','day_boundary_hour':4,
        'auto_export':normalize_auto_export({'enabled':True,**options}),
        'export':{'copy_directory':'/private/tmp/fictitious-export-directory'}}


def rendered(scale):
    return {'images':[f'/output/fictitious/scale-{scale}/image.png'],'render_scale':scale,
        'draft':{'id':'fictional-draft','export_copy':{'enabled':True,'copied':1,'failed':0}}}


class ScheduledExporterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.exporter = ScheduledExporter(self.root)
        self.config = configuration()
        self.worker = Mock()
        self.worker.settings.read.side_effect = lambda:copy.deepcopy(self.config)
        self.worker.capture.return_value = {'status':'success'}
        self.worker.drafts.generate.return_value = {'id':'fictional-draft'}
        self.worker.drafts.render.side_effect = lambda draft_id,**kw:rendered(kw['render_scale'])
        self.clock = patch('discord_archive.auto_export.utc_now',return_value=NOW)
        self.clock.start()

    def tearDown(self):
        self.clock.stop()
        self.temp.cleanup()

    def enabled(self):
        self.assertIsNone(self.exporter.due(self.config,BEFORE))

    def test_first_enable_checkpoint_does_not_backfill_and_restart_retains_it(self):
        self.assertIsNone(self.exporter.due(self.config,'2026-10-23T21:00:00Z'))
        self.assertEqual(self.exporter.state['enabled_since'],'2026-10-23T21:00:00.000000Z')
        restarted = ScheduledExporter(self.root)
        self.assertIsNone(restarted.due(self.config,'2026-10-23T21:01:00Z'))
        self.assertEqual(restarted.state['enabled_since'],self.exporter.state['enabled_since'])

    def test_exact_enable_minute_is_eligible_but_previous_minutes_are_not(self):
        self.assertEqual(self.exporter.due(self.config,NOW),SLOT)
        self.assertEqual(self.exporter.state['enabled_since'],'2026-10-23T20:15:00.000000Z')

    def test_disabled_and_reenabled_schedule_resets_checkpoint(self):
        self.enabled()
        self.assertEqual(self.exporter.due(self.config,NOW),SLOT)
        self.config['auto_export']['enabled']=False
        self.assertIsNone(self.exporter.due(self.config,NOW))
        self.assertFalse(self.exporter.state['enabled'])
        self.config['auto_export']['enabled']=True
        self.assertIsNone(self.exporter.due(self.config,'2026-10-23T21:00:00Z'))
        self.assertEqual(self.exporter.state['enabled_since'],'2026-10-23T21:00:00.000000Z')

    def test_success_captures_generates_and_verifies_both_densities(self):
        self.config=configuration(render_scales=[1,2],target='all')
        self.enabled()
        result=self.exporter.run(self.worker,SLOT)
        self.assertEqual(result['status'],'success')
        self.worker.capture.assert_called_once_with({'trigger':'scheduled_export'})
        request=self.worker.drafts.generate.call_args.args[0]
        self.assertEqual(request['date'],'2026-10-23');self.assertEqual(request['scope'],'day')
        self.assertEqual(request['mode'],'evidence');self.assertIn('16:15',request['title'])
        self.assertEqual([call.kwargs['render_scale'] for call in self.worker.drafts.render.call_args_list],[1,2])
        self.assertTrue(all(call.kwargs['target']=='all' for call in self.worker.drafts.render.call_args_list))
        self.assertEqual(self.exporter.state['last_completed_slot_at'],SLOT['scheduled_at'])
        self.assertEqual(self.exporter.state['last_draft_id'],'fictional-draft')
        self.assertIsNone(self.exporter.state['pending']);self.assertIsNone(self.exporter.stage)
        self.assertIsNone(self.exporter.due(self.config,NOW))

    def test_completed_slot_is_idempotent_even_after_restart(self):
        self.enabled();self.exporter.run(self.worker,SLOT)
        restarted=ScheduledExporter(self.root)
        self.assertTrue(restarted.run(self.worker,SLOT)['deduplicated'])
        self.worker.capture.assert_called_once();self.worker.drafts.generate.assert_called_once()
        self.worker.drafts.render.assert_called_once()

    def test_capture_network_failure_never_generates_and_retains_capture_stage(self):
        self.enabled();self.worker.capture.side_effect=DiscordAPIError(0,'fictitious network unavailable')
        with self.assertRaises(DiscordAPIError):self.exporter.run(self.worker,SLOT)
        self.worker.drafts.generate.assert_not_called();self.worker.drafts.render.assert_not_called()
        self.assertEqual(self.exporter.stage,'capture');self.assertEqual(self.exporter.state['failures'],1)
        self.assertEqual(self.exporter.state['retry_at'],'2026-10-23T20:15:31.000000Z')
        self.assertIsNone(self.exporter.due(self.config,'2026-10-23T20:15:30Z'))
        self.assertEqual(self.exporter.due(self.config,'2026-10-23T20:15:32Z'),SLOT)

    def test_partial_capture_pauses_export_without_a_network_failure_stage(self):
        self.enabled();self.worker.capture.return_value={'status':'partial'}
        with self.assertRaises(AccessDenied) as raised:self.exporter.run(self.worker,SLOT)
        self.assertEqual(raised.exception.status,403)
        self.assertEqual(self.exporter.stage,'capture_partial')
        self.worker.drafts.generate.assert_not_called();self.worker.drafts.render.assert_not_called()

    def test_copy_failure_resumes_only_missing_density_after_process_restart(self):
        self.config=configuration(render_scales=[1,2]);self.enabled()
        failed=rendered(2);failed['draft']['export_copy']['failed']=1
        self.worker.drafts.render.side_effect=[rendered(1),failed]
        with self.assertRaises(ValueError):self.exporter.run(self.worker,SLOT)
        self.assertEqual(self.exporter.stage,'render')
        self.assertEqual(self.exporter.state['pending']['rendered_scales'],[1])
        restarted=ScheduledExporter(self.root)
        self.worker.drafts.render.side_effect=lambda draft_id,**kw:rendered(kw['render_scale'])
        result=restarted.run(self.worker,SLOT)
        self.assertEqual(result['status'],'success')
        self.worker.capture.assert_called_once();self.worker.drafts.generate.assert_called_once()
        self.assertEqual([call.kwargs['render_scale'] for call in self.worker.drafts.render.call_args_list],[1,2,2])

    def test_no_copy_or_empty_copy_receipt_does_not_count_as_success(self):
        for receipt in ({},{'enabled':False,'copied':1,'failed':0},
                        {'enabled':True,'copied':0,'failed':0},{'enabled':True,'copied':1,'failed':1}):
            with self.subTest(receipt=receipt),tempfile.TemporaryDirectory() as temp:
                exporter=ScheduledExporter(temp)
                self.worker.drafts.render.side_effect=None
                self.worker.drafts.render.return_value={'draft':{'id':'fictional-draft','export_copy':receipt}}
                with self.assertRaises(ValueError):exporter.run(self.worker,SLOT)
                self.assertEqual(exporter.stage,'render');self.assertIsNone(exporter.state['last_completed_at'])

    def test_missing_destination_failure_preserves_draft_and_retries_only_render(self):
        self.enabled();self.worker.drafts.render.side_effect=ValueError('无法访问另存目录')
        with self.assertRaises(ValueError):self.exporter.run(self.worker,SLOT)
        self.worker.drafts.render.side_effect=lambda draft_id,**kw:rendered(kw['render_scale'])
        self.exporter.run(self.worker,SLOT)
        self.worker.capture.assert_called_once();self.worker.drafts.generate.assert_called_once()
        self.assertEqual(self.worker.drafts.render.call_count,2)
        self.assertEqual(self.exporter.state['last_draft_id'],'fictional-draft')

    def test_empty_draft_completes_slot_as_skipped_without_rendering(self):
        self.enabled();self.worker.drafts.generate.side_effect=EmptyDraft('fictitious empty period')
        result=self.exporter.run(self.worker,SLOT)
        self.assertEqual(result['status'],'skipped');self.assertEqual(self.exporter.state['last_status'],'skipped')
        self.assertIsNone(self.exporter.state['pending']);self.assertIsNone(self.exporter.state['retry_at'])
        self.worker.drafts.render.assert_not_called()
        self.assertTrue(self.exporter.run(self.worker,SLOT)['deduplicated'])

    def test_newer_due_slot_can_replace_pending_retry_wait(self):
        self.config=configuration(times=['16:15','16:30']);self.enabled()
        self.worker.drafts.render.side_effect=ValueError('fictitious failure')
        with self.assertRaises(ValueError):self.exporter.run(self.worker,SLOT)
        self.exporter._save(retry_at='2026-10-23T21:00:00Z')
        newer=self.exporter.due(self.config,'2026-10-23T20:30:00Z')
        self.assertEqual(newer['scheduled_at'],'2026-10-23T20:30:00Z')
        self.worker.drafts.render.side_effect=lambda draft_id,**kw:rendered(kw['render_scale'])
        self.exporter.run(self.worker,newer)
        self.assertEqual(self.worker.capture.call_count,2);self.assertEqual(self.worker.drafts.generate.call_count,2)

    def test_72_hour_restart_recovers_saved_draft_but_does_not_backfill_capture(self):
        self.enabled();self.worker.drafts.render.side_effect=ValueError('fictitious disconnected drive')
        with self.assertRaises(ValueError):self.exporter.run(self.worker,SLOT)
        restarted=ScheduledExporter(self.root)
        self.assertEqual(restarted.due(self.config,'2026-10-26T20:10:00Z'),SLOT)
        restarted._save(pending={**restarted.state['pending'],'stage':'capture'})
        self.assertIsNone(restarted.due(self.config,'2026-10-26T20:10:00Z'))

    def test_stage_checkpoints_are_independent_snapshots_and_survive_generate_failure(self):
        self.enabled();self.worker.drafts.generate.side_effect=ValueError('fictitious generate failure')
        with self.assertRaises(ValueError):self.exporter.run(self.worker,SLOT)
        saved=json.loads(self.exporter.path.read_text())
        self.assertEqual(saved['pending']['stage'],'draft')
        restarted=ScheduledExporter(self.root)
        self.worker.drafts.generate.side_effect=None
        restarted.run(self.worker,SLOT)
        self.worker.capture.assert_called_once();self.assertEqual(self.worker.drafts.generate.call_count,2)

    def test_summary_contains_no_copy_directory_or_operational_options(self):
        self.enabled()
        self.worker.drafts.render.side_effect=ValueError('cannot write '+self.config['export']['copy_directory']+'/file.png')
        with self.assertRaises(ValueError):self.exporter.run(self.worker,SLOT)
        summary=self.exporter.summary(self.config,NOW)
        self.assertEqual(summary['stage'],'render');self.assertEqual(summary['last_status'],'failed')
        serialized=json.dumps(summary)
        self.assertNotIn(self.config['export']['copy_directory'],serialized)
        self.assertNotIn('options',summary);self.assertNotIn('copy_directory',summary)
        self.assertTrue(summary['retry_at']);self.assertTrue(summary['next_at'])

    def test_all_rendered_checkpoint_completes_without_repeating_any_phase(self):
        self.config=configuration(render_scales=[1,2]);self.enabled()
        self.exporter._save(pending={'slot':SLOT,'options':self.config['auto_export'],
            'stage':'render','draft_id':'fictional-draft','rendered_scales':[1,2]})
        restarted=ScheduledExporter(self.root)
        self.assertEqual(restarted.run(self.worker,SLOT)['status'],'success')
        self.worker.capture.assert_not_called();self.worker.drafts.generate.assert_not_called()
        self.worker.drafts.render.assert_not_called()
        self.assertEqual(restarted.state['last_draft_id'],'fictional-draft')

    def test_failed_checkpoint_write_does_not_claim_unpersisted_completion(self):
        self.enabled();before=copy.deepcopy(self.exporter.state)
        with patch('discord_archive.auto_export.atomic_json',side_effect=OSError('fictitious full disk')):
            with self.assertRaises(OSError):self.exporter._save(last_status='success',pending=None)
        self.assertEqual(self.exporter.state,before)


if __name__=='__main__':unittest.main()
