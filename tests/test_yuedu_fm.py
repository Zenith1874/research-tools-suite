# -*- coding: utf-8 -*-
"""RSS parsing, local-file reconciliation, and path-boundary tests for YueDu FM."""

import json
import tempfile
import unittest
from pathlib import Path

from services.yuedu_fm_service import YueduFMError, YueduFMManager, html_to_text, parse_feed
from scripts.sync_yuedu_fm_wechat import build_combined, extract_article, stable_url


FEED = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
 xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
 xmlns:content="http://purl.org/rss/1.0/modules/content/">
 <channel>
  <title>YueDu FM</title><link>https://example.test/show</link><language>zh-CN</language>
  <itunes:summary>Local listening fixture</itunes:summary>
  <itunes:image href="https://example.test/show.jpg"/>
  <item>
   <title>Episode One</title><guid>fixture-guid-1</guid>
   <pubDate>Sun, 06 Jul 2025 11:36:00 +0000</pubDate>
   <itunes:duration>784</itunes:duration>
   <itunes:image href="https://example.test/one.jpg"/>
   <content:encoded><![CDATA[<p>Author: Example</p><p>First line.<br>Second line.</p>]]></content:encoded>
   <enclosure url="https://example.test/one.mp3" length="12" type="audio/mpeg"/>
  </item>
 </channel>
</rss>'''


class YueduFMParserTests(unittest.TestCase):
    def test_feed_keeps_metadata_and_plain_text(self):
        library = parse_feed(FEED, feed_url='https://example.test/feed')
        self.assertEqual(library['stats']['episode_count'], 1)
        self.assertEqual(library['stats']['declared_audio_bytes'], 12)
        episode = library['episodes'][0]
        self.assertEqual(episode['title'], 'Episode One')
        self.assertEqual(episode['duration_seconds'], 784)
        self.assertIn('First line.\nSecond line.', episode['description_text'])
        self.assertEqual(episode['audio']['relative_path'][-4:], '.mp3')
        self.assertRegex(episode['episode_id'], r'^[0-9a-f]{24}$')

    def test_html_text_extraction_does_not_run_markup(self):
        self.assertEqual(html_to_text('<p>Hello &amp; goodbye</p><script>x()</script>'),
                         'Hello & goodbye')

    def test_invalid_xml_is_explicit(self):
        with self.assertRaises(YueduFMError):
            parse_feed(b'<html>not rss</html>')


class YueduFMManagerTests(unittest.TestCase):
    def test_library_reconciles_only_complete_declared_audio(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = YueduFMManager(temp_dir)
            library = parse_feed(FEED)
            episode = library['episodes'][0]
            audio = Path(temp_dir) / episode['audio']['relative_path']
            image = Path(temp_dir) / episode['image']['relative_path']
            audio.parent.mkdir(parents=True, exist_ok=True)
            image.parent.mkdir(parents=True, exist_ok=True)
            audio.write_bytes(b'not-12')
            image.write_bytes(b'image')
            manager._write_library(library)
            stored = json.loads(manager.library_path.read_text(encoding='utf-8'))
            self.assertFalse(stored['episodes'][0]['audio']['downloaded'])
            self.assertTrue(stored['episodes'][0]['image']['downloaded'])
            self.assertEqual(stored['stats']['downloaded_image_count'], 1)
            self.assertEqual(stored['stats']['signature_invalid_audio_count'], 0)

    def test_media_path_rejects_unknown_and_traversal_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = YueduFMManager(temp_dir)
            with self.assertRaises(YueduFMError):
                manager.media_path('../escape', 'audio')
            with self.assertRaises(YueduFMError):
                manager.media_path('0' * 24, 'audio')


class YueduFMWechatImportTests(unittest.TestCase):
    def test_wechat_extracts_audio_and_related_article_links(self):
        html = '''
        <html><head><title>Page title</title></head><body>
        <script>
        var nickname = htmlDecode("YueDu FM");
        var ct = "1591444861";
        var msg_title = 'Page title'.html(false);
        </script>
        <div id="js_content">
          <p>Body text</p>
          <mp-common-mpaudio voice_encode_fileid="media-1" name="Program"
            author="Reader" play_length="1258000"></mp-common-mpaudio>
          <a href="http://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=abc&chksm=def&scene=21#wechat_redirect">old</a>
          <img data-src="https://mmbiz.qpic.cn/example.jpg">
        </div></body></html>
        '''
        article = extract_article("https://mp.weixin.qq.com/s/seed", html)
        self.assertEqual(article["title"], "Program")
        self.assertEqual(article["account"], "YueDu FM")
        self.assertEqual(article["audio"]["duration_seconds"], 1258)
        self.assertIn("Body text", article["content_text"])
        self.assertEqual(article["image_urls"], ["https://mmbiz.qpic.cn/example.jpg"])
        self.assertIn("chksm=def", article["discovered_article_urls"][0])

    def test_stable_url_keeps_public_old_article_parameters(self):
        url = stable_url(
            "http://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=abc"
            "&chksm=def&scene=21&pass_ticket=private#wechat_redirect"
        )
        self.assertEqual(
            url,
            "https://mp.weixin.qq.com/s?__biz=biz&mid=1&idx=1&sn=abc&chksm=def&scene=21",
        )

    def test_combined_library_skips_duplicate_title_duration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = parse_feed(FEED)
            base_episode = base["episodes"][0]
            base_episode["title"] = "Program"
            base_episode["duration_seconds"] = 1258
            (root / "library.json").write_text(json.dumps(base), encoding="utf-8")
            wechat = {
                "articles": [
                    {
                        "article_id": "1" * 24,
                        "source_url": "https://mp.weixin.qq.com/s/one",
                        "title": "Program",
                        "page_title": "Program",
                        "published_at": "2020-01-01T00:00:00+00:00",
                        "audio": {"duration_seconds": 1258, "downloaded": True},
                        "images": [],
                    },
                    {
                        "article_id": "2" * 24,
                        "source_url": "https://mp.weixin.qq.com/s/two",
                        "title": "New Program",
                        "page_title": "New Program",
                        "published_at": "2020-01-02T00:00:00+00:00",
                        "audio": {"duration_seconds": 60, "downloaded": True},
                        "images": [],
                    },
                ]
            }
            result = build_combined(root, wechat)
            self.assertEqual(result["combined"]["stats"]["wechat_imported_episode_count"], 1)
            self.assertEqual(result["combined"]["stats"]["wechat_skipped_duplicate_count"], 1)
            self.assertEqual(result["combined"]["episodes"][-1]["title"], "New Program")


if __name__ == '__main__':
    unittest.main()
