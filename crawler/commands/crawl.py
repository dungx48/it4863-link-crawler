"""Make persistence failures visible to CLI users and the API job manager."""
from scrapy.commands.crawl import Command as ScrapyCrawlCommand
from scrapy.exceptions import UsageError


class Command(ScrapyCrawlCommand):
    def run(self, args, opts):
        if len(args) != 1:
            raise UsageError("Specify exactly one spider")
        crawler = self.crawler_process.create_crawler(args[0])
        self.crawler_process.crawl(crawler, **opts.spargs)
        self.crawler_process.start()
        if self.crawler_process.bootstrap_failed or crawler.stats.get_value("storage/errors", 0):
            self.exitcode = 1
