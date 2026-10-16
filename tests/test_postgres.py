"""Storage failure checks and opt-in integration tests against a dedicated test DB."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

import psycopg
from filelock import FileLock
from scrapy.statscollectors import StatsCollector
from scrapy.settings import Settings

from crawler.commands.crawl import Command
from crawler.pipelines import PostgresLinkPipeline


def make_pipeline():
    crawler = SimpleNamespace(settings=Settings())
    crawler.stats = StatsCollector(crawler)
    return PostgresLinkPipeline.from_crawler(crawler)


class PostgresTests(unittest.TestCase):
    def test_open_uses_existing_schema_without_creating_text_output(self):
        pipeline = make_pipeline()
        with TemporaryDirectory() as directory, \
                patch("crawler.pipelines.OUTPUT_FILE", Path(directory) / "links.txt"), \
                patch("crawler.pipelines.psycopg.connect") as connect:
            pipeline.open_spider()
            try:
                sql = connect.return_value.execute.call_args.args[0]
                self.assertIn("CREATE TABLE IF NOT EXISTS links", sql)
                self.assertIn("GENERATED ALWAYS AS IDENTITY", sql)
                self.assertIn("url TEXT NOT NULL UNIQUE", sql)
                self.assertFalse((Path(directory) / "links.txt").exists())
            finally:
                pipeline.close_spider()

    def test_connection_failure_is_recorded_and_releases_lock(self):
        pipeline = make_pipeline()
        with TemporaryDirectory() as directory, \
                patch("crawler.pipelines.OUTPUT_FILE", Path(directory) / "links.txt"), \
                patch("crawler.pipelines.psycopg.connect", side_effect=psycopg.OperationalError("offline")):
            with self.assertRaises(psycopg.OperationalError):
                pipeline.open_spider()
            self.assertEqual(pipeline.crawler.stats.get_value("storage/errors"), 1)
            with FileLock(Path(directory) / ".crawl.lock").acquire(timeout=0):
                pass

    def test_write_failure_is_not_deduplicated_and_can_be_retried(self):
        pipeline = make_pipeline()
        pipeline.seen = set()
        pipeline.connection = MagicMock()
        pipeline.connection.execute.side_effect = [psycopg.OperationalError("offline"), MagicMock()]
        item = {"url": "https://hust.edu.vn/test?value='quoted'"}
        with self.assertRaises(psycopg.OperationalError):
            pipeline.process_item(item)
        self.assertNotIn(item["url"], pipeline.seen)
        self.assertEqual(pipeline.crawler.stats.get_value("storage/errors"), 1)
        pipeline.process_item(item)
        pipeline.process_item(item)
        self.assertEqual(pipeline.connection.execute.call_count, 2)
        sql, values = pipeline.connection.execute.call_args.args
        self.assertNotIn(item["url"], sql)
        self.assertEqual(values, (item["url"],))
        self.assertIn("ON CONFLICT (url) DO UPDATE", sql)
        self.assertNotIn("first_seen_at =", sql)

    def test_crawl_command_returns_failure_for_storage_errors(self):
        command = Command()
        command.crawler_process = MagicMock()
        command.crawler_process.bootstrap_failed = False
        command.crawler_process.create_crawler.return_value.stats.get_value.return_value = 1
        command.run(["hust"], SimpleNamespace(spargs={}))
        self.assertEqual(command.exitcode, 1)

    @unittest.skipUnless(os.getenv("TEST_POSTGRES_DSN"), "Set TEST_POSTGRES_DSN to a dedicated test DB")
    def test_real_postgres_keeps_first_seen_and_upserts_across_crawls(self):
        dsn = os.environ["TEST_POSTGRES_DSN"]
        prefix = "https://hust.edu.vn/test-" + uuid4().hex
        urls = [prefix + "?q='quoted'", prefix + "/guide.pdf"]
        connect = psycopg.connect
        with TemporaryDirectory() as directory, \
                patch("crawler.pipelines.OUTPUT_FILE", Path(directory) / "links.txt"), \
                patch("crawler.pipelines.psycopg.connect", side_effect=lambda **kw: connect(dsn, **kw)), \
                connect(dsn, autocommit=True) as db:
            try:
                for run in range(2):
                    pipeline = make_pipeline()
                    pipeline.open_spider()
                    try:
                        for url in urls + urls:
                            pipeline.process_item({"url": url})
                    finally:
                        pipeline.close_spider()
                    rows = db.execute(
                        "SELECT id, url, first_seen_at, last_seen_at FROM links WHERE url = ANY(%s) ORDER BY url",
                        (urls,),
                    ).fetchall()
                    self.assertEqual(len(rows), 2)
                    self.assertEqual({row[1] for row in rows}, set(urls))
                    if run == 0:
                        previous = rows
                    else:
                        self.assertEqual([row[2] for row in rows], [row[2] for row in previous])
                        self.assertEqual([row[0] for row in rows], [row[0] for row in previous])
                        self.assertTrue(all(row[3] > old[3] for row, old in zip(rows, previous)))
            finally:
                db.execute("DELETE FROM links WHERE url = ANY(%s)", (urls,))
