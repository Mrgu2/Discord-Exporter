import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch

from discord_archive.assets import allowed_media_url,forwarded_texts,iter_message_assets
from discord_archive.media import MediaArchive,_CDNRedirect


class AssetTests(unittest.TestCase):
    def test_forwarded_raster_and_text_have_stable_namespaced_identity(self):
        source={'id':'2','message_snapshots':[{'message':{'content':'实际转发内容','attachments':[{'id':'9','filename':'x.png','url':'https://cdn.discordapp.com/attachments/1/9/x.png?ex=old&hm=a'}]}}]}
        first=iter_message_assets(source)[0]
        source['message_snapshots'][0]['message']['attachments'][0]['url']='https://cdn.discordapp.com/attachments/1/9/x.png?ex=new&hm=b'
        self.assertEqual(first['id'],iter_message_assets(source)[0]['id'])
        self.assertEqual(first['id'],'snapshot-0-9');self.assertTrue(first['is_image'])
        self.assertEqual(forwarded_texts(source),['实际转发内容'])

    def test_external_and_unsafe_redirect_targets_are_rejected(self):
        for url in ['http://cdn.discordapp.com/a.png','https://127.0.0.1/a.png','https://cdn.discordapp.com.attacker.invalid/a.png','https://cdn.discordapp.com:8443/a.png','https://elsewhere.invalid/a.png','https://images-ext-1.discordapp.net.attacker.invalid/a.png']:
            self.assertFalse(allowed_media_url(url))
        with self.assertRaises(ValueError):
            _CDNRedirect().redirect_request(None,None,302,'',{},'https://127.0.0.1/private')

    def test_proxy_embed_and_sticker_are_raster_but_svg_is_not(self):
        assets=iter_message_assets({'embeds':[{'image':{'url':'https://elsewhere.invalid/image','proxy_url':'https://media.discordapp.net/external/opaque/image.png'}}], 'sticker_items':[{'id':'4','format_type':1}], 'attachments':[{'id':'5','filename':'x.svg','content_type':'image/svg+xml','url':'https://cdn.discordapp.com/attachments/1/5/x.svg'}]})
        self.assertEqual(sum(asset['is_image'] for asset in assets),2)
        self.assertTrue(all(allowed_media_url(asset['download_url']) for asset in assets))

    def test_discord_external_image_proxy_is_downloaded_without_fetching_source_host(self):
        for host in ['images-ext-1.discordapp.net','images-ext-2.discordapp.net']:
            proxy=f'https://{host}/external/opaque/https/example.invalid/image.png'
            assets=iter_message_assets({'embeds':[{'image':{'url':'https://example.invalid/image.png','proxy_url':proxy}}]})
            self.assertEqual(assets[0]['download_url'],proxy)
            self.assertTrue(assets[0]['is_image'])

    def test_archiving_forwarded_and_cross_channel_images_never_adds_account_header(self):
        with tempfile.TemporaryDirectory() as directory:
            archive=MediaArchive(directory)
            response=MagicMock();response.__enter__.return_value.read.return_value=b'png-fixture'
            opener=MagicMock();opener.open.return_value=response
            source={'id':'2','channel_id':'100','message_snapshots':[{'message':{'attachments':[{'id':'9','filename':'image','content_type':'image/png','url':'https://cdn.discordapp.com/attachments/1/9/image'}]}}], 'message_reference':{'channel_id':'200'},'referenced_message':{'id':'3','attachments':[{'id':'10','filename':'q.png','url':'https://cdn.discordapp.com/attachments/1/10/q.png'}]}}
            with patch('discord_archive.media.build_opener',return_value=opener):
                archive.archive_page('100',None,[source])
            self.assertEqual(archive.manifest['100/2/snapshot-0-9']['status'],'saved')
            self.assertTrue(archive.manifest['100/2/snapshot-0-9']['file'].endswith('.png'))
            self.assertIn('200/3/10',archive.manifest)
            for call in opener.open.call_args_list:
                self.assertNotIn('Authorization',dict(call.args[0].header_items()))
