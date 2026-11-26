from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from .model_leaderboards import BOARD_LIMIT, BOARD_URLS, LLM_STATS_SOURCE, parse_leaderboards
from .models import CrawlRun, ExternalProject, ModelLeaderboardSnapshot
from .services import CRAWLERS, run_crawl


def _page(headers, rows):
    header = "".join(f"<th>{text}</th>" for text in headers)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _upstream_pages(*, overall_score="60.6", coding_count=BOARD_LIMIT):
    overall = _page(
        ["Model", "Organization", "LLM Stats Score", "Reasoning index", "Coding index",
         "Context (tokens)", "Input ($/M tokens)", "Output ($/M tokens)"],
        [[f'<a href="/models/m{i}">Model {i}</a>', "Example Lab", overall_score, "59.8",
          "50.2", "1,000,000", "0", "&mdash;"] for i in range(1, BOARD_LIMIT + 1)],
    )
    coding = _page(
        ["Model", "<span>Rating</span><div>conservative</div>",
         "SWE-Bench Verified <span>125 models</span>", "LiveCodeBench <span>76 models</span>"],
        [[f'<span>{rank}</span><a href="/models/m{model}"><img src="/logos/lab.svg" />Model {model}</a>'
          '<a href="https://example.com">Try</a>', "48.0", "75.4%", "&mdash;"]
         for rank, model in enumerate(range(2, coding_count + 2), 1)],
    )
    return {BOARD_URLS["overall"]: overall, BOARD_URLS["coding"]: coding}


class ModelRankingsTests(TestCase):
    def test_command_crawls_both_tables_and_publishes_source_metrics(self):
        pages = _upstream_pages()
        output = StringIO()
        with patch("apps.rankings.services._http_get_text", side_effect=lambda url, **_: pages[url]) as fetch:
            call_command("crawl_external", source=LLM_STATS_SOURCE, stdout=output)
        self.assertIn("llm_stats: success (60 items)", output.getvalue())
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(CrawlRun.objects.get().status, CrawlRun.STATUS_SUCCESS)
        self.assertFalse(ExternalProject.objects.exists())

        overall = self.client.get("/api/rankings/models").json()
        self.assertEqual(overall["source_url"], BOARD_URLS["overall"])
        self.assertEqual(len(overall["items"]), BOARD_LIMIT)
        self.assertEqual(overall["items"][0], {
            "rank": 1, "name": "Model 1", "organization": "Example Lab", "score": 60.6,
            "reasoning_score": 59.8, "coding_score": 50.2, "context_tokens": 1000000,
            "input_price": 0, "output_price": None, "url": "https://llm-stats.com/models/m1",
            "icon_url": "https://llm-stats.com/logos/lab.svg",
        })

        coding = self.client.get("/api/rankings/models?board=coding").json()
        self.assertEqual(coding["source_url"], BOARD_URLS["coding"])
        self.assertEqual(coding["updated_at"], overall["updated_at"])
        self.assertEqual([row["rank"] for row in coding["items"]], list(range(1, BOARD_LIMIT + 1)))
        self.assertEqual(coding["items"][0]["name"], "Model 2")
        self.assertEqual(coding["items"][0]["score"], 48.0)
        self.assertEqual(coding["items"][0]["swe_bench"], 75.4)
        self.assertIsNone(coding["items"][0]["live_code_bench"])
        self.assertEqual(coding["items"][-1]["organization"], "Example Lab")
        self.assertEqual(coding["items"][-1]["icon_url"], "https://llm-stats.com/logos/lab.svg")

    def test_logo_urls_unwrap_first_party_images_and_ignore_other_origins(self):
        upstream = _upstream_pages()
        pages = {board: upstream[url] for board, url in BOARD_URLS.items()}
        pages["coding"] = pages["coding"].replace(
            "/logos/lab.svg", "/_next/image?url=%2Flogos%2Flab.svg&amp;w=32", 1,
        ).replace(
            'src="/logos/lab.svg"', 'src="//example.com/logos/lab.svg"', 1,
        )
        boards = parse_leaderboards(pages)
        self.assertEqual(boards["coding"][0]["icon_url"], "https://llm-stats.com/logos/lab.svg")
        self.assertIsNone(boards["coding"][1]["icon_url"])
        self.assertEqual(boards["overall"][0]["icon_url"], "https://llm-stats.com/logos/lab.svg")

    def test_default_crawl_keeps_last_complete_snapshot_when_one_table_is_truncated(self):
        pages = _upstream_pages()
        with (
            patch("apps.rankings.services._http_get_text", side_effect=lambda url, **_: pages[url]),
            patch.dict(CRAWLERS, {"kaiyuanbang": lambda run: 0}),
        ):
            self.assertEqual(run_crawl(analyze=False)[LLM_STATS_SOURCE]["status"], "success")
            snapshot = ModelLeaderboardSnapshot.objects.get()
            pages = _upstream_pages(overall_score="72.1", coding_count=29)
            result = run_crawl(analyze=False)

        self.assertEqual(result["kaiyuanbang"]["status"], "success")
        self.assertEqual(result[LLM_STATS_SOURCE]["status"], "failed")
        self.assertEqual(ModelLeaderboardSnapshot.objects.count(), 1)
        response = self.client.get("/api/rankings/models").json()
        self.assertEqual(response["items"][0]["score"], 60.6)
        self.assertEqual(response["updated_at"], snapshot.captured_at)
        self.assertTrue(response["update_failed"])

    def test_no_snapshot_and_unknown_board(self):
        response = self.client.get("/api/rankings/models?board=coding")
        self.assertEqual(response.json(), {
            "items": [], "updated_at": None, "source_url": BOARD_URLS["coding"], "update_failed": False,
        })
        self.assertEqual(self.client.get("/api/rankings/models?board=other").status_code, 400)
