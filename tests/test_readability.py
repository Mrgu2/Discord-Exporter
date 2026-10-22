import copy
import unittest

from discord_archive.readability import choose_reading_groups,clean_reading_text


def message(identity,text,author='owner',**extra):
    return {'channel_id':'100','message_id':str(identity),'author_id':author,'content':text,'created_at':'2026-10-21T14:00:00Z',**extra}


def group(answer,context=None,followups=None):
    context=context or [];followups=followups or []
    return {'answers':[answer],'context':context,'followups':followups,'messages':context+[answer]+followups,'missing_context':[]}


class ReadingTests(unittest.TestCase):
    def test_clear_noise_is_reversible_and_explicit_short_answer_survives(self):
        source=[group(message(1,'VIX尾盘确认吗？','member'),[]),group(message(2,'是的'),[message(3,'VIX尾盘确认吗？','member')],[message(4,'谢谢老大','member')]),group(message(5,'我去喝咖啡了'))]
        before=copy.deepcopy(source);visible,decisions=choose_reading_groups(source,'owner')
        self.assertEqual(source,before)
        self.assertTrue(any(m['content']=='是的' for g in visible for m in g['answers']))
        self.assertFalse(any(m['content']=='谢谢老大' for g in visible for m in g['messages']))
        self.assertIn('5',{d['message_id'] for d in decisions})
        self.assertTrue(all(d.get('reason') for d in decisions))

    def test_financial_conditions_and_forwarded_content_survive(self):
        source=[group(message(1,'等确认后再加仓，止损42。')),group(message(2,'',raw={'message_snapshots':[{'message':{'content':'等待量价确认。'}}]})),group(message(3,'',raw={'message_snapshots':[{'message':{'attachments':[{'id':'9'}]}}]}))]
        visible,_=choose_reading_groups(source,'owner')
        self.assertEqual(len(visible),3)

    def test_standalone_ack_and_emoji_are_omitted(self):
        visible,decisions=choose_reading_groups([group(message(1,'嗯嗯')),group(message(2,'🤣🤣'))],'owner')
        self.assertEqual(visible,[]);self.assertEqual(len(decisions),2)

    def test_callouts_are_cleaned_without_removing_conditions(self):
        self.assertEqual(clean_reading_text('@everyone\n\n\n等待确认后再加仓。\n<@123>','123'),'等待确认后再加仓。')
        self.assertIn('某位群友',clean_reading_text('和<@456>确认。','123',{'456':'某位群友'}))

    def test_custom_emoji_ids_do_not_enter_reading_text(self):
        self.assertEqual(clean_reading_text('等待确认<a:200w:123456789>，再加仓。'),'等待确认，再加仓。')
        self.assertEqual(clean_reading_text('<:yes:123456789>'),'（表情）')
        visible,_=choose_reading_groups([group(message(1,'<:yes:123456789>'),[message(2,'这样可以吗？','member')])],'owner')
        self.assertEqual(len(visible),1)

    def test_status_caption_can_omit_social_media_but_sleep_caption_keeps_chart(self):
        office=group(message(1,'今天的办公室',attachments=[{'id':'v','filename':'clip.mp4'}]))
        office['answers'].insert(0,message(2,'',attachments=[{'id':'v','filename':'clip.mp4'}]))
        office['messages']=office['answers']
        chart=group(message(3,'去睡觉了',attachments=[{'id':'chart','filename':'chart.png'}]))
        information=group(message(4,'等量价确认，晚点回复。'))
        visible,decisions=choose_reading_groups([office,chart,information,group(message(5,'我去看会儿盘晚点回你们。'))],'owner')
        self.assertEqual([g['answers'][0]['message_id'] for g in visible],['3','4'])
        self.assertEqual({d['message_id'] for d in decisions},{'1','2','5'})

    def test_lifestyle_followup_is_omitted_without_removing_trade_context(self):
        source=group(message(1,'等确认。'),[message(2,'现在加仓吗？','member')],[message(3,'夜哥在烧烤🍖吗','member'),message(4,'iv高的话呢？','member')])
        visible,_=choose_reading_groups([source],'owner')
        self.assertEqual([m['message_id'] for m in visible[0]['followups']],['4'])
