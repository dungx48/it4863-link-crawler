"""Offline checks for the crawler; no requests to HUST are sent."""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import scrapy
from scrapy.http import HtmlResponse

from crawler.pipelines import LinkFilePipeline
from crawler.spiders.hust_spider import HustSpider
from crawler.urlutils import in_scope, is_document, normalize, should_skip


class CrawlerTests(unittest.TestCase):
    def test_normalize_relative_url_and_remove_tracking(self):
        self.assertEqual(
            normalize('/vi/news/?b=2&utm_source=test&a=1#section',
                      'https://www.hust.edu.vn/'),
            'https://hust.edu.vn/vi/news/?a=1&b=2',
        )
        self.assertIsNone(normalize('mailto:test@hust.edu.vn'))

    def test_scope_and_resource_filters(self):
        with patch('crawler.urlutils.ALLOW_SUBDOMAINS', True):
            self.assertTrue(in_scope('https://soict.hust.edu.vn/'))
            for url in ('https://hust.edu.vn.example.com/',
                        'https://example.com/', 'https://test.hust.edu.vn/'):
                with self.subTest(url=url):
                    self.assertFalse(in_scope(url))
        self.assertTrue(is_document('https://hust.edu.vn/files/guide.PDF?v=1'))
        self.assertTrue(should_skip('https://hust.edu.vn/photo.jpg'))
        self.assertTrue(should_skip('https://hust.edu.vn/vi/search?q=test'))
        self.assertFalse(should_skip('https://hust.edu.vn/vi/news/'))

    @staticmethod
    def page():
        return HtmlResponse(
            url='https://hust.edu.vn/', encoding='utf-8',
            headers={'Content-Type': 'text/html'},
            body=b'''<a href="/vi/news/">News</a>
                     <a href="/vi/news/#top">Duplicate</a>
                     <a href="/files/guide.pdf">Document</a>
                     <a href="https://example.com/">External</a>
                     <a href="/photo.jpg">Image</a>''',
        )

    def test_page_records_documents_and_follows_only_internal_pages(self):
        results = list(HustSpider(use_sitemap='0').parse_page(self.page()))
        self.assertEqual(
            [item['url'] for item in results if isinstance(item, dict)],
            ['https://hust.edu.vn/', 'https://hust.edu.vn/files/guide.pdf'],
        )
        self.assertEqual(
            [item.url for item in results if isinstance(item, scrapy.Request)],
            ['https://hust.edu.vn/vi/news/'],
        )

    def test_follow_disabled_records_only_seed_page(self):
        results = list(HustSpider(follow='0').parse_page(self.page()))
        self.assertEqual(results, [{'url': 'https://hust.edu.vn/'}])

    def test_pipeline_writes_unique_sorted_links(self):
        with TemporaryDirectory() as directory:
            output = Path(directory) / 'output' / 'links.txt'
            with patch('crawler.pipelines.OUTPUT_FILE', output):
                pipeline = LinkFilePipeline()
                pipeline.open_spider()
                try:
                    for url in ('https://hust.edu.vn/b',
                                'https://hust.edu.vn/a',
                                'https://hust.edu.vn/b'):
                        pipeline.process_item({'url': url})
                finally:
                    pipeline.close_spider()
            self.assertEqual(
                output.read_text(encoding='utf-8'),
                'https://hust.edu.vn/a\nhttps://hust.edu.vn/b\n',
            )
