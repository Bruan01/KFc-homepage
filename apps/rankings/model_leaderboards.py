"""Parse the public LLM Stats leaderboard tables without client-side scripts."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import parse_qs

LLM_STATS_SOURCE = "llm_stats"
LLM_STATS_ORIGIN = "https://llm-stats.com"
BOARD_URLS = {
    "overall": f"{LLM_STATS_ORIGIN}/leaderboards/llm-leaderboard/",
    "coding": f"{LLM_STATS_ORIGIN}/leaderboards/best-ai-for-coding/",
}
BOARD_LIMIT = 30
MODEL_PATH = re.compile(r"/models/[a-zA-Z0-9][a-zA-Z0-9._-]*/?")
LOGO_PATH = re.compile(r"/logos/[a-zA-Z0-9][a-zA-Z0-9._-]*\.(?:svg|png|webp|avif|jpe?g)", re.IGNORECASE)
BOARD_COLUMNS = {
    "overall": {
        "organization": "organization",
        "score": "llm stats score",
        "reasoning_score": "reasoning index",
        "coding_score": "coding index",
        "context_tokens": "context (tokens)",
        "input_price": "input ($/m tokens)",
        "output_price": "output ($/m tokens)",
    },
    "coding": {
        "score": "rating conservative",
        "swe_bench": "swe-bench verified",
        "live_code_bench": "livecodebench",
    },
}


@dataclass
class _Cell:
    parts: list[str] = field(default_factory=list)
    model_parts: list[str] = field(default_factory=list)
    model_path: str = ""
    prefix: str = ""
    logo: str = ""

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[_Cell]]] = []
        self.table: list[list[_Cell]] | None = None
        self.row: list[_Cell] | None = None
        self.cell: _Cell | None = None
        self.in_model_link = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table = []
        elif tag == "tr" and self.table is not None:
            self.row = []
        elif tag in ("th", "td") and self.row is not None:
            self.cell = _Cell()
        elif self.cell is not None and tag == "a":
            path = dict(attrs).get("href") or ""
            if MODEL_PATH.fullmatch(path):
                self.cell.model_path = path.rstrip("/")
                self.cell.prefix = self.cell.text
                self.in_model_link = True
        elif self.in_model_link and tag == "img":
            self.cell.logo = dict(attrs).get("src") or ""

    def handle_endtag(self, tag):
        if tag == "a":
            self.in_model_link = False
        elif tag in ("th", "td") and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
            self.in_model_link = False
        elif tag == "tr" and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == "table" and self.table is not None:
            self.tables.append(self.table)
            self.table = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.parts.append(data)
            if self.in_model_link:
                self.cell.model_parts.append(data)


def _read_metric(cell: _Cell, *, integer: bool = False, percent: bool = False):
    value = cell.text
    if value in {"", "-", "–", "—", "N/A"}:
        return None
    if percent:
        if not value.endswith("%"):
            raise ValueError(f"expected a percentage, got {value!r}")
        value = value[:-1].strip()
    value = value.replace(",", "")
    pattern = r"\d+" if integer else r"\d+(?:\.\d+)?"
    if not re.fullmatch(pattern, value):
        raise ValueError(f"invalid numeric cell: {value!r}")
    return int(value) if integer else float(value)


def _logo_url(src: str) -> str | None:
    path = src.removeprefix(LLM_STATS_ORIGIN)
    if path.startswith("/_next/image?"):
        path = parse_qs(path.partition("?")[2]).get("url", [""])[0]
    return LLM_STATS_ORIGIN + path if LOGO_PATH.fullmatch(path) else None


def _parse_board(html: str, board: str) -> list[dict]:
    parser = _TableParser()
    parser.feed(html)
    parser.close()
    for table in parser.tables:
        if not table:
            continue
        headers = [cell.text.casefold() for cell in table[0]]
        if "model" not in headers or BOARD_COLUMNS[board]["score"] not in headers:
            continue

        positions = {}
        for key, label in BOARD_COLUMNS[board].items():
            positions[key] = next(
                (idx for idx, header in enumerate(headers) if header == label
                 or (key in {"swe_bench", "live_code_bench"} and header.startswith(label + " "))),
                None,
            )
        if any(index is None for index in positions.values()):
            raise ValueError("expected leaderboard columns are missing")

        items = []
        seen_paths = set()
        for rank, cells in enumerate(table[1:BOARD_LIMIT + 1], 1):
            if len(cells) != len(headers):
                raise ValueError(f"incomplete row at position {rank}")
            model = cells[headers.index("model")]
            name = " ".join(" ".join(model.model_parts).split())
            if not name or not model.model_path or model.model_path in seen_paths:
                raise ValueError(f"invalid or duplicate model at position {rank}")
            if board == "coding" and model.prefix != str(rank):
                raise ValueError(f"unexpected coding rank at position {rank}")
            seen_paths.add(model.model_path)
            item = {
                "rank": rank,
                "name": name,
                "url": LLM_STATS_ORIGIN + model.model_path,
                "logo": model.logo,
            }
            for key, index in positions.items():
                cell = cells[index]
                item[key] = cell.text if key == "organization" else _read_metric(
                    cell, integer=key == "context_tokens", percent=key in {"swe_bench", "live_code_bench"}
                )
            if item["score"] is None:
                raise ValueError(f"missing score at position {rank}")
            items.append(item)

        if len(items) != BOARD_LIMIT:
            raise ValueError(f"expected {BOARD_LIMIT} models, found {len(items)}")
        return items
    raise ValueError("leaderboard table not found")


def parse_leaderboards(pages: dict[str, str]) -> dict[str, list[dict]]:
    boards = {}
    for board in BOARD_URLS:
        try:
            boards[board] = _parse_board(pages[board], board)
        except ValueError as exc:
            raise ValueError(f"LLM Stats {board}: {exc}") from exc

    # The coding table uses logos instead of organization names. Match by
    # model URL first, and share organization logos when the match is unique.
    organizations = {item["url"]: item["organization"] for item in boards["overall"]}
    logo_names = {}
    organization_icons = {}
    coding_icons = {}
    for item in boards["coding"]:
        organization = organizations.get(item["url"])
        icon = _logo_url(item["logo"])
        item["icon_url"] = icon
        if organization and item["logo"]:
            logo_names.setdefault(icon or item["logo"], set()).add(organization)
        if icon:
            coding_icons[item["url"]] = icon
            if organization:
                organization_icons.setdefault(organization, set()).add(icon)
    for item in boards["coding"]:
        names = logo_names.get(item["icon_url"] or item["logo"], set())
        item["organization"] = organizations.get(item["url"]) or (
            next(iter(names)) if len(names) == 1 else None
        )
        del item["logo"]
    for item in boards["overall"]:
        icons = organization_icons.get(item["organization"], set())
        item["icon_url"] = _logo_url(item.pop("logo")) or coding_icons.get(item["url"]) or (
            next(iter(icons)) if len(icons) == 1 else None
        )
    return boards
