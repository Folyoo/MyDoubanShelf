from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin

import requests


ProgressCallback = Callable[[str], None]

CATEGORY_CONFIG = {
    "book": {"label": "\u8bfb\u4e66", "base_url": "https://book.douban.com", "csv": "douban_book_marks.csv", "html": "book.html", "statuses": ("wish", "do", "collect"), "parser": "list"},
    "movie": {"label": "\u5f71\u89c6", "base_url": "https://movie.douban.com", "csv": "douban_movie_marks.csv", "html": "movie.html", "statuses": ("wish", "do", "collect"), "parser": "list"},
    "music": {"label": "\u97f3\u4e50", "base_url": "https://music.douban.com", "csv": "douban_music_marks.csv", "html": "music.html", "statuses": ("wish", "do", "collect"), "parser": "list"},
    "game": {"label": "\u6e38\u620f", "base_url": "https://www.douban.com", "csv": "douban_game_marks.csv", "html": "game.html", "statuses": ("wish", "do", "collect"), "parser": "game"},
    "drama": {"label": "\u821e\u53f0\u5267", "base_url": "https://www.douban.com", "csv": "douban_drama_marks.csv", "html": "drama.html", "statuses": ("wish", "collect"), "parser": "drama"},
}
STATUS_LABELS = {
    "book": {"wish": "\u60f3\u8bfb", "do": "\u5728\u8bfb", "collect": "\u8bfb\u8fc7"},
    "movie": {"wish": "\u60f3\u770b", "do": "\u5728\u770b", "collect": "\u770b\u8fc7"},
    "music": {"wish": "\u60f3\u542c", "do": "\u5728\u542c", "collect": "\u542c\u8fc7"},
    "game": {"wish": "\u60f3\u73a9", "do": "\u5728\u73a9", "collect": "\u73a9\u8fc7"},
    "drama": {"wish": "\u60f3\u770b", "collect": "\u770b\u8fc7"},
}
TIME_COLUMN_LABELS = {
    "book": "\u51fa\u7248\u65f6\u95f4",
    "movie": "\u4e0a\u6620\u65f6\u95f4",
    "music": "\u53d1\u884c\u65f6\u95f4",
    "game": "\u53d1\u552e\u65f6\u95f4",
    "drama": "\u6f14\u51fa\u65f6\u95f4",
}
INTRO_COLUMN_LABELS = {
    "book": "\u4f5c\u8005",
    "movie": "\u6f14\u804c\u4fe1\u606f",
    "music": "\u8868\u6f14\u8005",
    "game": "\u5e73\u53f0/\u7c7b\u578b",
    "drama": "\u6f14\u51fa\u4fe1\u606f",
}
DEFAULT_CATEGORIES = ("book", "movie", "music", "game", "drama")
DEFAULT_STATUSES = ("wish", "do", "collect")
DETAIL_COLUMNS = ("category", "category_label", "status", "status_label", "subject_id", "title", "url", "douban_rating", "rating", "marked_date", "content_date", "intro", "comment")
SUMMARY_COLUMNS = ("category", "category_label", "status", "status_label", "count")
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
RATING_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
PUBLIC_RATING_API_DELAY_SECONDS = 0.25
PUBLIC_RATING_MOVIE_DELAY_SECONDS = 1.2
PUBLIC_RATING_BACKOFF_SECONDS = (5.0, 12.0, 24.0)
PUBLIC_RATING_CACHE_VERSION = 1
PUBLIC_RATING_CACHE_ENV = "DOUBAN_EXPORT_RATING_CACHE"
INCREMENTAL_MIN_OVERLAP_ROWS = 8

ITEM_RE = re.compile(r'<li(?=[^>]*\bid="list(?P<subject_id>\d+)")(?=[^>]*\bclass="[^"]*\bitem\b[^"]*")[^>]*>(?P<body>.*?)</li>', re.S)
TITLE_RE = re.compile(r'<div class="title">\s*<a href="(?P<url>[^"]+)"[^>]*>\s*(?P<title>.*?)\s*</a>', re.S)
DATE_BLOCK_RE = re.compile(r'<div class="date">(?P<body>.*?)</div>', re.S)
INTRO_RE = re.compile(r'<span class="intro">(?P<intro>.*?)</span>', re.S)
COMMENT_RE = re.compile(r'<div class="comment">(?P<comment>.*?)</div>', re.S)
NEXT_RE = re.compile(r'<link rel="next" href="(?P<href>[^"]+)"', re.S)
TITLE_TAG_RE = re.compile(r"<title>\s*(?P<title>.*?)\s*</title>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
RATING_RE = re.compile(r"rating(?P<rating>[1-5])-t")
DETAIL_PAGE_RATING_RE = re.compile(r'rating_num[^>]*>\s*(?P<rating>\d+(?:\.\d+)?)\s*</strong>', re.S)
SEC_FORM_ACTION_RE = re.compile(r'<form[^>]*id="sec"[^>]*action="(?P<action>[^"]+)"', re.S)
SEC_FIELD_RE = re.compile(r'id="(?P<name>tok|cha|red)"\s+name="(?P=name)"\s+value="(?P<value>[^"]*)"', re.S)
POW_DIFFICULTY_RE = re.compile(r"process\(data,\s*difficulty\s*=\s*(?P<difficulty>\d+)\)")
PRICE_SEGMENT_RE = re.compile(r"(?i)^(?:[A-Z$￥¥€£]{0,4}\s*)?(?:\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?)(?:\s*(?:元|圆|RMB|CNY|USD|HKD|NT\$))?$")
DATE_SEGMENT_RE = re.compile(r"\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}(?:日)?)?(?:[-~至]\d{1,2}(?:[-/.月]\d{1,2})?)*(?:\([^)]+\))?")
DATE_VALUE_RE = re.compile(r"(?P<year>\d{4})(?:[-/.年](?P<month>\d{1,2}))?(?:[-/.月](?P<day>\d{1,2}))?")


class DoubanExportError(Exception):
    pass


class DoubanRatingRetryableError(Exception):
    pass


@dataclass(slots=True)
class ExportResult:
    account_id: str
    display_name: str
    output_dir: Path
    detail_csv_path: Path
    summary_csv_path: Path
    report_html_path: Path
    total_rows: int
    summary_rows: list[dict[str, str | int]]
    category_csv_paths: dict[str, Path]
    category_html_paths: dict[str, Path]


def normalize_account(raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise DoubanExportError("\u8bf7\u5148\u8f93\u5165\u8c46\u74e3\u8d26\u53f7\uff0c\u6216\u76f4\u63a5\u7c98\u8d34\u4e2a\u4eba\u4e3b\u9875\u94fe\u63a5\u3002")
    if "douban.com" in value:
        match = re.search(r"/people/([^/?#]+)/?", value)
        if not match:
            raise DoubanExportError("\u65e0\u6cd5\u4ece\u94fe\u63a5\u4e2d\u8bc6\u522b\u8c46\u74e3\u8d26\u53f7\u3002")
        return match.group(1).strip()
    return value.strip("/ ")


def clean_text(raw_value: str | None) -> str:
    if not raw_value:
        return ""
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", raw_value)).replace("\xa0", " ")).strip()


def safe_file_stem(value: str) -> str:
    normalized = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return normalized or "douban_export"


def parse_comma_separated_values(raw_value: str | None, allowed: tuple[str, ...]) -> tuple[str, ...]:
    if not raw_value:
        return allowed
    values = tuple(part.strip() for part in raw_value.split(",") if part.strip())
    return values or allowed


def build_counts(rows: list[dict[str, str]], categories: Iterable[str], statuses: Iterable[str]) -> list[dict[str, str | int]]:
    results: list[dict[str, str | int]] = []
    for category in categories:
        for status in statuses:
            if status not in STATUS_LABELS[category]:
                continue
            results.append(
                {
                    "category": category,
                    "category_label": CATEGORY_CONFIG[category]["label"],
                    "status": status,
                    "status_label": STATUS_LABELS[category][status],
                    "count": sum(1 for row in rows if row["category"] == category and row["status"] == status),
                }
            )
    return results


def group_rows_by_category(rows: list[dict[str, str]], categories: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    return {category: [row for row in rows if row["category"] == category] for category in categories}


def group_rows_by_category_status(rows: Iterable[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (row.get("category", ""), row.get("status", ""))
        grouped.setdefault(key, []).append(row)
    return grouped


def normalize_detail_row(row: dict[str, object]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for column in DETAIL_COLUMNS:
        normalized[column] = str(row.get(column, "") or "")
    category = normalized.get("category", "")
    status = normalized.get("status", "")
    if category in CATEGORY_CONFIG and not normalized.get("category_label"):
        normalized["category_label"] = CATEGORY_CONFIG[category]["label"]
    if category in STATUS_LABELS and status in STATUS_LABELS[category] and not normalized.get("status_label"):
        normalized["status_label"] = STATUS_LABELS[category][status]
    return normalized


def json_for_script(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def extract_earliest_date(raw_text: str) -> str:
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for match in DATE_VALUE_RE.finditer(raw_text):
        year = int(match.group("year"))
        month = int(match.group("month") or 0)
        day = int(match.group("day") or 0)
        if day:
            display = f"{year:04d}-{month:02d}-{day:02d}"
        elif month:
            display = f"{year:04d}-{month:02d}"
        else:
            display = f"{year:04d}"
        candidates.append(((year, month, day), display))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def split_intro_metadata(raw_intro: str) -> tuple[str, str]:
    if not raw_intro:
        return "", ""
    kept_segments: list[str] = []
    content_dates: list[str] = []
    for segment in [part.strip() for part in raw_intro.split(" / ") if part.strip()]:
        if DATE_SEGMENT_RE.search(segment):
            content_dates.append(extract_earliest_date(segment) or segment)
            continue
        if PRICE_SEGMENT_RE.match(segment):
            continue
        kept_segments.append(segment)
    earliest_date = extract_earliest_date(" | ".join(content_dates))
    return " / ".join(kept_segments), earliest_date


class DoubanExporter:
    def __init__(self, cookie: str | None = None, timeout_seconds: int = 20, delay_seconds: float = 0.6) -> None:
        self.timeout_seconds = timeout_seconds
        self.delay_seconds = delay_seconds
        self.manual_cookie = cookie.strip() if cookie else ""
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)
        if self.manual_cookie:
            self.session.headers["Cookie"] = self.manual_cookie
        self.thread_local = threading.local()
        self.subject_rating_cache: dict[tuple[str, str], str] = {}
        self.subject_rating_cache_updated_at: dict[tuple[str, str], float] = {}
        self.subject_rating_cache_lock = threading.Lock()
        self.subject_rating_cache_dirty = False
        self.rating_cache_path = self.resolve_rating_cache_path()
        self.public_rating_request_locks = {"api": threading.Lock(), "movie": threading.Lock()}
        self.last_public_rating_request_at = {"api": 0.0, "movie": 0.0}
        self.load_subject_rating_cache()

    def resolve_rating_cache_path(self) -> Path:
        override = os.environ.get(PUBLIC_RATING_CACHE_ENV, "").strip()
        if override:
            return Path(override).expanduser().resolve()
        return (Path.cwd() / ".douban_cache" / "public_rating_cache.json").resolve()

    def reset_main_session(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(REQUEST_HEADERS)
        if self.manual_cookie:
            self.session.headers["Cookie"] = self.manual_cookie

    def load_subject_rating_cache(self) -> None:
        if not self.rating_cache_path.exists():
            return
        try:
            payload = json.loads(self.rating_cache_path.read_text(encoding="utf-8"))
        except Exception:
            return
        entries = payload.get("entries") if isinstance(payload, dict) else None
        if not isinstance(entries, dict):
            if isinstance(payload, dict):
                entries = payload
            else:
                return
        now = time.time()
        with self.subject_rating_cache_lock:
            for raw_key, raw_entry in entries.items():
                if ":" not in raw_key:
                    continue
                category, subject_id = raw_key.split(":", 1)
                updated_at = now
                if isinstance(raw_entry, dict):
                    rating = self.normalize_public_rating(raw_entry.get("rating"))
                    raw_updated_at = raw_entry.get("updated_at")
                    if raw_updated_at not in (None, ""):
                        try:
                            updated_at = float(raw_updated_at)
                        except (TypeError, ValueError):
                            updated_at = now
                else:
                    rating = self.normalize_public_rating(raw_entry)
                if not rating or now - updated_at > RATING_CACHE_MAX_AGE_SECONDS:
                    continue
                cache_key = (category, subject_id)
                self.subject_rating_cache[cache_key] = rating
                self.subject_rating_cache_updated_at[cache_key] = updated_at

    def save_subject_rating_cache(self) -> None:
        with self.subject_rating_cache_lock:
            if not self.subject_rating_cache_dirty:
                return
            entries = {
                f"{category}:{subject_id}": {
                    "rating": rating,
                    "updated_at": self.subject_rating_cache_updated_at.get((category, subject_id), time.time()),
                }
                for (category, subject_id), rating in self.subject_rating_cache.items()
                if rating
            }
            self.subject_rating_cache_dirty = False
        payload = {
            "version": PUBLIC_RATING_CACHE_VERSION,
            "saved_at": int(time.time()),
            "entries": entries,
        }
        try:
            self.rating_cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self.rating_cache_path.with_suffix(f"{self.rating_cache_path.suffix}.tmp")
            temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp_path.replace(self.rating_cache_path)
        except Exception:
            with self.subject_rating_cache_lock:
                self.subject_rating_cache_dirty = True

    def get_cached_subject_rating(self, category: str, subject_id: str) -> str | None:
        with self.subject_rating_cache_lock:
            return self.subject_rating_cache.get((category, subject_id))

    def set_cached_subject_rating(self, category: str, subject_id: str, rating: str, persist: bool) -> str:
        normalized = self.normalize_public_rating(rating)
        cache_key = (category, subject_id)
        with self.subject_rating_cache_lock:
            if not normalized and self.subject_rating_cache.get(cache_key):
                return self.subject_rating_cache[cache_key]
            self.subject_rating_cache[cache_key] = normalized
            if persist and normalized:
                self.subject_rating_cache_updated_at[cache_key] = time.time()
                self.subject_rating_cache_dirty = True
        return normalized

    def throttle_public_rating_request(self, category: str) -> None:
        bucket = "movie" if category == "movie" else "api"
        delay_seconds = PUBLIC_RATING_MOVIE_DELAY_SECONDS if bucket == "movie" else PUBLIC_RATING_API_DELAY_SECONDS
        if delay_seconds <= 0:
            return
        lock = self.public_rating_request_locks[bucket]
        with lock:
            now = time.monotonic()
            last_time = self.last_public_rating_request_at[bucket]
            wait_seconds = delay_seconds - (now - last_time)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            self.last_public_rating_request_at[bucket] = time.monotonic()

    def backoff_public_rating_request(self, category: str, attempt: int, progress: ProgressCallback | None = None, reason: str = "") -> None:
        index = min(max(attempt - 1, 0), len(PUBLIC_RATING_BACKOFF_SECONDS) - 1)
        wait_seconds = PUBLIC_RATING_BACKOFF_SECONDS[index]
        if progress:
            prefix = "电影评分请求" if category == "movie" else "豆瓣评分请求"
            suffix = f"（{reason}）" if reason else ""
            progress(f"  {prefix}触发访问限制{suffix}，暂停 {int(wait_seconds)} 秒后重试...")
        time.sleep(wait_seconds)

    def export(
        self,
        account_input: str,
        output_root: str | Path,
        categories: Iterable[str] = DEFAULT_CATEGORIES,
        statuses: Iterable[str] = DEFAULT_STATUSES,
        incremental: bool = True,
        progress: ProgressCallback | None = None,
    ) -> ExportResult:
        account_id = normalize_account(account_input)
        selected_categories = tuple(dict.fromkeys(categories))
        selected_statuses = tuple(dict.fromkeys(statuses))
        self._validate_selection(selected_categories, selected_statuses)
        output_root_path = Path(output_root).expanduser().resolve()
        previous_rows_by_key: dict[tuple[str, str], list[dict[str, str]]] = {}
        if incremental:
            previous_rows_by_key = self.load_previous_export_rows(output_root_path, account_id, selected_categories, selected_statuses, progress)
        display_name = self.fetch_display_name(account_id, progress)
        rows: list[dict[str, str]] = []
        for category in selected_categories:
            for status in selected_statuses:
                if status not in CATEGORY_CONFIG[category]["statuses"]:
                    continue
                if progress:
                    progress(f"\u6b63\u5728\u6293\u53d6 {CATEGORY_CONFIG[category]['label']} - {STATUS_LABELS[category][status]} ...")
                rows.extend(self.fetch_category_status_rows(account_id, category, status, progress, previous_rows_by_key.get((category, status)) if incremental else None))
        if rows:
            self.enrich_rows_with_public_ratings(rows, progress)

        output_dir = output_root_path / f"{safe_file_stem(account_id)}_{datetime.now():%Y%m%d_%H%M%S}"
        output_dir.mkdir(parents=True, exist_ok=True)
        detail_csv_path = output_dir / "douban_marks_all.csv"
        summary_csv_path = output_dir / "douban_summary.csv"
        report_html_path = output_dir / "index.html"
        summary_rows = build_counts(rows, selected_categories, selected_statuses)
        rows_by_category = group_rows_by_category(rows, selected_categories)
        self.write_csv(detail_csv_path, DETAIL_COLUMNS, rows)
        self.write_csv(summary_csv_path, SUMMARY_COLUMNS, summary_rows)
        category_csv_paths = self.write_category_csvs(output_dir, rows_by_category)
        category_html_paths = self.write_html_reports(output_dir, account_id, display_name, selected_categories, selected_statuses, rows_by_category, summary_rows)
        if progress:
            progress(f"\u5bfc\u51fa\u5b8c\u6210\uff0c\u5171 {len(rows)} \u6761\u8bb0\u5f55\u3002")
        return ExportResult(account_id, display_name, output_dir, detail_csv_path, summary_csv_path, report_html_path, len(rows), summary_rows, category_csv_paths, category_html_paths)

    def fetch_display_name(self, account_id: str, progress: ProgressCallback | None = None) -> str:
        html_text = self.fetch_url(f"https://www.douban.com/people/{account_id}/", "https://www.douban.com/")
        match = TITLE_TAG_RE.search(html_text)
        if not match:
            if progress:
                progress("\u672a\u80fd\u4ece\u4e3b\u9875\u6807\u9898\u4e2d\u63d0\u53d6\u6635\u79f0\uff0c\u5df2\u56de\u9000\u4e3a\u8d26\u53f7\u3002")
            return account_id
        return clean_text(match.group("title")) or account_id

    def load_previous_export_rows(
        self,
        output_root: Path,
        account_id: str,
        selected_categories: tuple[str, ...],
        selected_statuses: tuple[str, ...],
        progress: ProgressCallback | None = None,
    ) -> dict[tuple[str, str], list[dict[str, str]]]:
        latest_dir = self.find_latest_export_dir(output_root, account_id)
        if latest_dir is None:
            if progress:
                progress("\u672a\u627e\u5230\u53ef\u590d\u7528\u7684\u4e0a\u6b21\u5bfc\u51fa\uff0c\u672c\u6b21\u5c06\u5168\u91cf\u6293\u53d6\u3002")
            return {}
        detail_csv_path = latest_dir / "douban_marks_all.csv"
        try:
            rows = self.read_detail_rows(detail_csv_path)
        except Exception as error:
            if progress:
                progress(f"\u4e0a\u6b21\u5bfc\u51fa\u8bfb\u53d6\u5931\u8d25\uff0c\u5df2\u56de\u9000\u5230\u5168\u91cf\u6293\u53d6\uff1a{error}")
            return {}
        allowed_categories = set(selected_categories)
        allowed_statuses = set(selected_statuses)
        filtered_rows = [row for row in rows if row["category"] in allowed_categories and row["status"] in allowed_statuses]
        grouped = group_rows_by_category_status(filtered_rows)
        if progress:
            progress(f"\u5df2\u627e\u5230\u4e0a\u6b21\u5bfc\u51fa\uff1a{latest_dir}\uff0c\u672c\u6b21\u5c06\u4f18\u5148\u589e\u91cf\u66f4\u65b0\u3002")
        return grouped

    def find_latest_export_dir(self, output_root: Path, account_id: str) -> Path | None:
        if not output_root.exists():
            return None
        prefix = f"{safe_file_stem(account_id)}_"
        candidates = [
            path for path in output_root.iterdir()
            if path.is_dir() and path.name.startswith(prefix) and (path / "douban_marks_all.csv").exists()
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))

    def read_detail_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            return [normalize_detail_row(row) for row in reader]

    def get_thread_session(self) -> requests.Session:
        session = getattr(self.thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(REQUEST_HEADERS)
            cookie = self.session.headers.get("Cookie")
            if cookie:
                session.headers["Cookie"] = cookie
            session.cookies.update(self.session.cookies)
            self.thread_local.session = session
        return session

    def build_incremental_row_signature(self, row: dict[str, str]) -> tuple[str, ...]:
        return (
            row.get("category", ""),
            row.get("status", ""),
            row.get("subject_id", ""),
            row.get("title", ""),
            row.get("url", ""),
            row.get("marked_date", ""),
            row.get("content_date", ""),
            row.get("intro", ""),
            row.get("comment", ""),
            row.get("rating", ""),
        )

    def find_overlap_start(self, previous_signatures: list[tuple[str, ...]], page_rows: list[dict[str, str]]) -> int | None:
        if len(page_rows) < INCREMENTAL_MIN_OVERLAP_ROWS:
            return None
        page_signatures = [self.build_incremental_row_signature(row) for row in page_rows]
        first_signature = page_signatures[0]
        max_index = len(previous_signatures) - len(page_signatures)
        for start in range(max_index + 1):
            if previous_signatures[start] != first_signature:
                continue
            if previous_signatures[start:start + len(page_signatures)] == page_signatures:
                return start
        return None

    def normalize_public_rating(self, value: object) -> str:
        return "" if value in (None, "", 0, 0.0, "0", "0.0") else str(value)

    def build_subject_url(self, category: str, subject_id: str) -> str:
        if category in {"book", "movie", "music"}:
            return f"{CATEGORY_CONFIG[category]['base_url']}/subject/{subject_id}/"
        if category == "game":
            return f"https://www.douban.com/game/{subject_id}/"
        return f"https://www.douban.com/location/drama/{subject_id}/"

    def fetch_subject_public_rating_from_api(self, category: str, subject_id: str, progress: ProgressCallback | None = None) -> str:
        api_url = f"https://m.douban.com/rexxar/api/v2/{category}/{subject_id}?for_mobile=1"
        for attempt in range(1, len(PUBLIC_RATING_BACKOFF_SECONDS) + 2):
            try:
                self.throttle_public_rating_request(category)
                response = self.get_thread_session().get(api_url, headers={"Referer": f"{CATEGORY_CONFIG[category]['base_url']}/"}, timeout=self.timeout_seconds)
                response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                if response.status_code == 404:
                    return ""
                if response.status_code in (403, 429):
                    raise DoubanRatingRetryableError(f"HTTP {response.status_code}")
                payload = response.json()
                if response.status_code >= 400:
                    error_code = str(payload.get("code", ""))
                    error_message = str(payload.get("msg", ""))
                    if error_code == "1309" or "rate_limit" in error_message.lower():
                        raise DoubanRatingRetryableError(error_message or error_code or f"HTTP {response.status_code}")
                    response.raise_for_status()
                return self.normalize_public_rating(payload.get("rating", {}).get("value"))
            except DoubanRatingRetryableError as error:
                if attempt < len(PUBLIC_RATING_BACKOFF_SECONDS) + 1:
                    self.backoff_public_rating_request(category, attempt, progress, str(error))
                    continue
                return ""
            except Exception:
                if attempt < len(PUBLIC_RATING_BACKOFF_SECONDS) + 1:
                    time.sleep(0.25 * attempt)
        return ""

    def solve_sec_challenge(self, challenge_html: str, challenge_url: str) -> requests.Response:
        fields = {match.group("name"): html.unescape(match.group("value")) for match in SEC_FIELD_RE.finditer(challenge_html)}
        action_match = SEC_FORM_ACTION_RE.search(challenge_html)
        if not action_match or not {"tok", "cha", "red"} <= fields.keys():
            raise DoubanExportError(f"\u65e0\u6cd5\u89e3\u6790\u8c46\u74e3\u9a8c\u8bc1\u9875\uff1a{challenge_url}")
        difficulty_match = POW_DIFFICULTY_RE.search(challenge_html)
        difficulty = int(difficulty_match.group("difficulty")) if difficulty_match else 4
        target_prefix = "0" * difficulty
        nonce = 0
        while True:
            nonce += 1
            if hashlib.sha512(f"{fields['cha']}{nonce}".encode("utf-8")).hexdigest().startswith(target_prefix):
                break
        response = self.session.post(
            urljoin(challenge_url, html.unescape(action_match.group("action"))),
            headers={"Referer": challenge_url},
            data={"tok": fields["tok"], "cha": fields["cha"], "sol": str(nonce), "red": fields["red"]},
            timeout=self.timeout_seconds,
            allow_redirects=True,
        )
        response.encoding = response.apparent_encoding or response.encoding or "utf-8"
        return response

    def fetch_detail_page_html(self, url: str, referer: str, progress: ProgressCallback | None = None) -> str:
        for attempt in range(1, len(PUBLIC_RATING_BACKOFF_SECONDS) + 2):
            try:
                self.throttle_public_rating_request("movie")
                response = self.session.get(url, headers={"Referer": referer}, timeout=self.timeout_seconds)
                response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                if response.status_code == 404:
                    return ""
                if response.status_code in (403, 429):
                    raise DoubanRatingRetryableError(f"HTTP {response.status_code}")
                html_text = response.text
                for _ in range(2):
                    if 'id="sec"' not in html_text or 'name="cha"' not in html_text:
                        break
                    response = self.solve_sec_challenge(html_text, response.url)
                    response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                    html_text = response.text
                if response.status_code in (403, 429):
                    raise DoubanRatingRetryableError(f"HTTP {response.status_code}")
                if "error code: 004" in html_text:
                    raise DoubanRatingRetryableError("error code 004")
                return html_text
            except DoubanRatingRetryableError as error:
                self.reset_main_session()
                if attempt < len(PUBLIC_RATING_BACKOFF_SECONDS) + 1:
                    self.backoff_public_rating_request("movie", attempt, progress, str(error))
                    continue
                return ""
            except Exception:
                if attempt < len(PUBLIC_RATING_BACKOFF_SECONDS) + 1:
                    time.sleep(0.5 * attempt)
        return ""

    def fetch_subject_public_rating_from_detail_page(self, category: str, subject_id: str, subject_url: str | None = None, progress: ProgressCallback | None = None) -> str:
        detail_url = subject_url or self.build_subject_url(category, subject_id)
        try:
            html_text = self.fetch_detail_page_html(detail_url, f"{CATEGORY_CONFIG[category]['base_url']}/", progress)
        except Exception:
            return ""
        match = DETAIL_PAGE_RATING_RE.search(html_text)
        return self.normalize_public_rating(match.group("rating")) if match else ""

    def fetch_subject_public_rating(self, category: str, subject_id: str, subject_url: str | None = None, progress: ProgressCallback | None = None) -> str:
        cached_rating = self.get_cached_subject_rating(category, subject_id)
        if cached_rating is not None:
            return cached_rating
        if not subject_id.isdigit():
            self.set_cached_subject_rating(category, subject_id, "", persist=False)
            return ""
        if category == "movie":
            rating = self.fetch_subject_public_rating_from_detail_page(category, subject_id, subject_url, progress)
        else:
            rating = self.fetch_subject_public_rating_from_api(category, subject_id, progress)
        return self.set_cached_subject_rating(category, subject_id, rating, persist=bool(rating))

    def enrich_rows_with_public_ratings(self, rows: list[dict[str, str]], progress: ProgressCallback | None = None) -> None:
        keys: list[tuple[str, str]] = []
        key_to_url: dict[tuple[str, str], str] = {}
        seen: set[tuple[str, str]] = set()
        for row in rows:
            cache_key = (row["category"], row["subject_id"])
            if cache_key in seen or not row["subject_id"].isdigit():
                continue
            seen.add(cache_key)
            key_to_url[cache_key] = row.get("url", "")
            if self.get_cached_subject_rating(row["category"], row["subject_id"]) is None:
                keys.append(cache_key)

        total = len(keys)
        cached_count = len(seen) - total
        if total:
            if progress:
                progress(f"\u6b63\u5728\u8865\u5145\u8c46\u74e3\u8bc4\u5206\uff0c\u9700\u8054\u7f51 {total} \u4e2a\u4f5c\u54c1\uff0c\u672c\u5730\u7f13\u5b58\u547d\u4e2d {cached_count} \u4e2a...")
            completed = 0
            movie_keys = [key for key in keys if key[0] == "movie"]
            other_keys = [key for key in keys if key[0] != "movie"]

            if other_keys:
                max_workers = min(3, len(other_keys))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_map = {
                        executor.submit(self.fetch_subject_public_rating, category, subject_id, key_to_url.get((category, subject_id), "")): (category, subject_id)
                        for category, subject_id in other_keys
                    }
                    for future in as_completed(future_map):
                        category, subject_id = future_map[future]
                        try:
                            future.result()
                        except Exception:
                            self.set_cached_subject_rating(category, subject_id, "", persist=False)
                        completed += 1
                        if progress and (completed == total or completed % 50 == 0):
                            progress(f"  \u8c46\u74e3\u8bc4\u5206\u8fdb\u5ea6: {completed}/{total}")

            for movie_index, (category, subject_id) in enumerate(movie_keys, 1):
                if movie_index > 1 and movie_index % 80 == 1:
                    self.reset_main_session()
                try:
                    self.fetch_subject_public_rating(category, subject_id, key_to_url.get((category, subject_id), ""), progress)
                except Exception:
                    self.set_cached_subject_rating(category, subject_id, "", persist=False)
                completed += 1
                if progress and (completed == total or completed % 20 == 0):
                    progress(f"  \u8c46\u74e3\u8bc4\u5206\u8fdb\u5ea6: {completed}/{total}")
            self.save_subject_rating_cache()

        for row in rows:
            row["douban_rating"] = self.get_cached_subject_rating(row["category"], row["subject_id"]) or ""

    def fetch_category_status_rows(
        self,
        account_id: str,
        category: str,
        status: str,
        progress: ProgressCallback | None = None,
        previous_rows: list[dict[str, str]] | None = None,
    ) -> list[dict[str, str]]:
        if status not in CATEGORY_CONFIG[category]["statuses"]:
            return []

        base_url = CATEGORY_CONFIG[category]["base_url"]
        next_url: str | None = self.build_first_url(account_id, category, status)
        rows: list[dict[str, str]] = []
        baseline_rows = [normalize_detail_row(row) for row in previous_rows or []]
        baseline_signatures = [self.build_incremental_row_signature(row) for row in baseline_rows]
        page = 0
        while next_url:
            page += 1
            if progress:
                progress(f"  \u7b2c {page} \u9875: {next_url}")
            try:
                html_text = self.fetch_url(next_url, f"{base_url}/")
            except DoubanExportError as error:
                if page == 1 and category in {"game", "drama"} and "\u9875\u9762" in str(error):
                    if progress:
                        progress(f"  {CATEGORY_CONFIG[category]['label']} \u6ca1\u6709\u516c\u5f00\u53ef\u6293\u53d6\u7684\u6761\u76ee\u3002")
                    return []
                raise
            parser_type = CATEGORY_CONFIG[category]["parser"]
            if parser_type == "list":
                page_rows = self.parse_list_items(html_text, category, status)
            elif parser_type == "game":
                page_rows = self.parse_game_items(html_text, category, status)
            else:
                page_rows = self.parse_drama_items(html_text, category, status)
            rows.extend(page_rows)
            overlap_start = self.find_overlap_start(baseline_signatures, page_rows) if baseline_rows else None
            if overlap_start is not None:
                reused_tail = [normalize_detail_row(row) for row in baseline_rows[overlap_start + len(page_rows):]]
                if reused_tail:
                    rows.extend(reused_tail)
                if progress:
                    progress(f"  \u547d\u4e2d\u4e0a\u6b21\u5bfc\u51fa\u7684\u7a33\u5b9a\u533a\u95f4\uff0c\u590d\u7528\u540e\u7eed {len(reused_tail)} \u6761\u8bb0\u5f55\u3002")
                if progress:
                    progress(f"  {CATEGORY_CONFIG[category]['label']} - {STATUS_LABELS[category][status]} \u5171 {len(rows)} \u6761\u3002")
                return rows
            next_url = self.parse_next_url(html_text, next_url)
            if next_url:
                time.sleep(self.delay_seconds)

        if progress:
            progress(f"  {CATEGORY_CONFIG[category]['label']} - {STATUS_LABELS[category][status]} \u5171 {len(rows)} \u6761\u3002")
        return rows

    def build_first_url(self, account_id: str, category: str, status: str) -> str:
        if category in {"book", "movie", "music"}:
            return f"{CATEGORY_CONFIG[category]['base_url']}/people/{account_id}/{status}?start=0&sort=time&rating=all&filter=all&mode=list"
        if category == "game":
            return f"https://www.douban.com/people/{account_id}/games?action={status}"
        return f"https://www.douban.com/location/people/{account_id}/drama/{status}?sort=time&start=0&filter=all&mode=grid&tags_sort=count"

    def fetch_url(self, url: str, referer: str) -> str:
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                response = self.session.get(url, headers={"Referer": referer}, timeout=self.timeout_seconds)
                response.encoding = response.apparent_encoding or response.encoding or "utf-8"
                self.raise_for_status(response, url)
                return response.text
            except Exception as error:
                last_error = error
                if attempt < 3:
                    time.sleep(self.delay_seconds * attempt)
        if isinstance(last_error, DoubanExportError):
            raise last_error
        raise DoubanExportError(f"\u8bbf\u95ee\u5931\u8d25\uff1a{url}\n{last_error}") from last_error

    def raise_for_status(self, response: requests.Response, url: str) -> None:
        if response.status_code < 400:
            if "\u9875\u9762\u4e0d\u5b58\u5728" in response.text or "\u4e0d\u5b58\u5728\u7684\u9875\u9762" in response.text:
                raise DoubanExportError(f"\u672a\u627e\u5230\u9875\u9762\uff1a{url}")
            if "\u4f60\u6ca1\u6709\u6743\u9650\u8bbf\u95ee\u8fd9\u4e2a\u9875\u9762" in response.text:
                raise DoubanExportError("\u5f53\u524d\u8d26\u53f7\u7684\u8c46\u74e3\u6807\u8bb0\u9875\u4e0d\u53ef\u516c\u5f00\u8bbf\u95ee\uff0c\u8bf7\u5728\u5de5\u5177\u91cc\u586b\u5165 Cookie \u540e\u91cd\u8bd5\u3002")
            return
        if response.status_code == 403:
            raise DoubanExportError("\u8c46\u74e3\u62d2\u7edd\u4e86\u672c\u6b21\u8bf7\u6c42\uff08HTTP 403\uff09\uff0c\u8bf7\u5728\u5de5\u5177\u91cc\u8865\u5145 Cookie \u540e\u91cd\u8bd5\u3002")
        raise DoubanExportError(f"\u8bf7\u6c42\u5931\u8d25\uff08HTTP {response.status_code}\uff09\uff1a{url}")

    def parse_list_items(self, html_text: str, category: str, status: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for item_match in ITEM_RE.finditer(html_text):
            body = item_match.group("body")
            title_match = TITLE_RE.search(body)
            if not title_match:
                continue
            date_block = DATE_BLOCK_RE.search(body)
            date_text = clean_text(date_block.group("body")) if date_block else ""
            date_match = DATE_RE.search(date_text)
            intro_match = INTRO_RE.search(body)
            comment_match = COMMENT_RE.search(body)
            rating_match = RATING_RE.search(body)
            intro_text, content_date = split_intro_metadata(clean_text(intro_match.group("intro")) if intro_match else "")
            rows.append({
                "category": category,
                "category_label": CATEGORY_CONFIG[category]["label"],
                "status": status,
                "status_label": STATUS_LABELS[category][status],
                "subject_id": item_match.group("subject_id"),
                "title": clean_text(title_match.group("title")),
                "url": html.unescape(title_match.group("url")),
                "douban_rating": "",
                "rating": rating_match.group("rating") if rating_match else "",
                "marked_date": date_match.group(0) if date_match else date_text,
                "content_date": content_date,
                "intro": intro_text,
                "comment": clean_text(comment_match.group("comment")) if comment_match else "",
            })
        return rows

    def parse_game_items(self, html_text: str, category: str, status: str) -> list[dict[str, str]]:
        if '<div class="game-list">' not in html_text:
            return []
        segment = html_text.split('<div class="game-list">', 1)[1]
        segment = segment.split('<script type="text/html" id="template-collect-popup">', 1)[0]
        blocks = [part for part in segment.split('<div class="common-item">')[1:] if part.strip()]
        rows: list[dict[str, str]] = []
        for index, block in enumerate(blocks, 1):
            title_match = re.search(r'<div class="title">\s*<a href="(?P<url>[^"]+)">(?P<title>.*?)</a>', block, re.S)
            if not title_match:
                continue
            desc_match = re.search(r'<div class="desc">\s*(?P<desc>.*?)\s*<div class="rating-info">', block, re.S)
            date_match = re.search(r'<span class="date">(?P<date>.*?)</span>', block, re.S)
            subject_match = re.search(r'/game/(?P<id>\d+)/', title_match.group("url"))
            intro_text, content_date = split_intro_metadata(clean_text(desc_match.group("desc")) if desc_match else "")
            rows.append(
                {
                    "category": category,
                    "category_label": CATEGORY_CONFIG[category]["label"],
                    "status": status,
                    "status_label": STATUS_LABELS[category][status],
                    "subject_id": subject_match.group("id") if subject_match else f"game-{index}",
                    "title": clean_text(title_match.group("title")),
                    "url": html.unescape(title_match.group("url")),
                    "douban_rating": "",
                    "rating": "",
                    "marked_date": clean_text(date_match.group("date")) if date_match else "",
                    "content_date": content_date,
                    "intro": intro_text,
                    "comment": "",
                }
            )
        return rows

    def parse_drama_items(self, html_text: str, category: str, status: str) -> list[dict[str, str]]:
        if '<div class="grid-view">' not in html_text:
            return []
        segment = html_text.split('<div class="grid-view">', 1)[1]
        segment = segment.split('</div>\n\n\n\n', 1)[0]
        blocks = [part for part in segment.split('<div class="item">')[1:] if part.strip()]
        rows: list[dict[str, str]] = []
        for index, block in enumerate(blocks, 1):
            title_match = re.search(r'<li class="title">\s*<a href="(?P<url>[^"]+)">\s*(?P<title>.*?)\s*</a>', block, re.S)
            if not title_match:
                continue
            intro_match = re.search(r'<li class="intro">(?P<intro>.*?)</li>', block, re.S)
            date_match = re.search(r'<span class="date">(?P<date>.*?)</span>', block, re.S)
            rating_match = RATING_RE.search(block)
            comment_match = re.findall(r'<li>\s*(?!<span)(?P<comment>.*?)\s*</li>', block, re.S)
            subject_match = re.search(r'/location/drama/(?P<id>\d+)/', title_match.group("url"))
            intro_text, content_date = split_intro_metadata(clean_text(intro_match.group("intro")) if intro_match else "")
            marked_date = clean_text(date_match.group("date")) if date_match else ""
            extra_comments: list[str] = []
            for value in comment_match:
                normalized = clean_text(value)
                if marked_date and normalized.startswith(marked_date):
                    normalized = normalized[len(marked_date):].lstrip(" /")
                if normalized and normalized != marked_date:
                    extra_comments.append(normalized)
            rows.append(
                {
                    "category": category,
                    "category_label": CATEGORY_CONFIG[category]["label"],
                    "status": status,
                    "status_label": STATUS_LABELS[category][status],
                    "subject_id": subject_match.group("id") if subject_match else f"drama-{index}",
                    "title": clean_text(title_match.group("title")),
                    "url": html.unescape(title_match.group("url")),
                    "douban_rating": "",
                    "rating": rating_match.group("rating") if rating_match else "",
                    "marked_date": marked_date,
                    "content_date": content_date,
                    "intro": intro_text,
                    "comment": " / ".join(extra_comments),
                }
            )
        return rows

    def parse_next_url(self, html_text: str, current_url: str) -> str | None:
        match = NEXT_RE.search(html_text)
        return urljoin(current_url, html.unescape(match.group("href"))) if match else None

    def write_csv(self, path: Path, columns: Iterable[str], rows: Iterable[dict[str, object]]) -> None:
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns))
            writer.writeheader()
            writer.writerows(rows)

    def write_category_csvs(self, output_dir: Path, rows_by_category: dict[str, list[dict[str, str]]]) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        for category, rows in rows_by_category.items():
            path = output_dir / CATEGORY_CONFIG[category]["csv"]
            self.write_csv(path, DETAIL_COLUMNS, rows)
            paths[category] = path
        return paths

    def write_html_reports(
        self,
        output_dir: Path,
        account_id: str,
        display_name: str,
        selected_categories: tuple[str, ...],
        selected_statuses: tuple[str, ...],
        rows_by_category: dict[str, list[dict[str, str]]],
        summary_rows: list[dict[str, str | int]],
    ) -> dict[str, Path]:
        paths: dict[str, Path] = {}
        for category in selected_categories:
            path = output_dir / CATEGORY_CONFIG[category]["html"]
            path.write_text(self.render_category_page_v2(account_id, display_name, category, selected_categories, selected_statuses, rows_by_category[category], [row for row in summary_rows if row["category"] == category]), encoding="utf-8")
            paths[category] = path
        (output_dir / "index.html").write_text(self.render_index_page(account_id, display_name, selected_categories, summary_rows, sum(len(rows) for rows in rows_by_category.values())), encoding="utf-8")
        return paths

    def render_index_page(self, account_id: str, display_name: str, selected_categories: tuple[str, ...], summary_rows: list[dict[str, str | int]], total_rows: int) -> str:
        cards = []
        for category in selected_categories:
            items = [row for row in summary_rows if row["category"] == category]
            stats = "".join(f"<li><span>{html.escape(str(row['status_label']))}</span><strong>{row['count']}</strong></li>" for row in items)
            cards.append(f'<a class="card" href="{CATEGORY_CONFIG[category]["html"]}"><h2>{CATEGORY_CONFIG[category]["label"]}</h2><ul>{stats}</ul></a>')
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>\u8c46\u74e3\u6807\u8bb0\u6c47\u603b</title><style>body{{margin:0;font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#f6f2e8;color:#221b13}}.wrap{{max-width:1100px;margin:auto;padding:28px 18px}}.box{{background:#fffaf1;border:1px solid #decfb4;border-radius:20px;padding:22px;box-shadow:0 12px 36px rgba(0,0,0,.05)}}.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-top:16px}}.card{{display:block;padding:18px;border:1px solid #decfb4;border-radius:16px;background:#fff;text-decoration:none;color:inherit}}.card h2{{margin:0 0 12px}}.card ul{{list-style:none;margin:0;padding:0}}.card li{{display:flex;justify-content:space-between;padding:6px 0;border-top:1px solid #eee3d1}}.muted{{color:#7f6f5d}}@media (max-width:860px){{.cards{{grid-template-columns:repeat(2,minmax(0,1fr))}}}}@media (max-width:560px){{.cards{{grid-template-columns:1fr}}}}</style></head><body><div class="wrap"><div class="box"><h1>{html.escape(display_name)} \u7684\u8c46\u74e3\u6807\u8bb0\u6c47\u603b</h1><p class="muted">\u8d26\u53f7\uff1a{html.escape(account_id)}</p><p class="muted">\u751f\u6210\u65f6\u95f4\uff1a{now_text()}</p><p class="muted">\u603b\u8bb0\u5f55\u6570\uff1a{total_rows}</p><div class="cards">{''.join(cards)}</div></div></div></body></html>"""

    def render_category_page(
        self,
        account_id: str,
        display_name: str,
        category: str,
        selected_categories: tuple[str, ...],
        selected_statuses: tuple[str, ...],
        detail_rows: list[dict[str, str]],
        summary_rows: list[dict[str, str | int]],
    ) -> str:
        nav = ['<a class="nav" href="index.html">\u603b\u89c8</a>'] + [f'<a class="nav{" active" if item == category else ""}" href="{CATEGORY_CONFIG[item]["html"]}">{CATEGORY_CONFIG[item]["label"]}</a>' for item in selected_categories]
        summary = "".join(f"<div class='sum'><span>{html.escape(str(row['status_label']))}</span><strong>{row['count']}</strong></div>" for row in summary_rows)
        options = "".join(f'<option value="{status}">{STATUS_LABELS[category][status]}</option>' for status in selected_statuses if status in STATUS_LABELS[category] and any(row["status"] == status for row in summary_rows))
        data = json_for_script(detail_rows)
        time_label = TIME_COLUMN_LABELS[category]
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{CATEGORY_CONFIG[category]["label"]}</title><style>body{{margin:0;font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#f6f2e8;color:#221b13}}.wrap{{max-width:1380px;margin:auto;padding:20px 16px 36px}}.box{{background:#fffaf1;border:1px solid #decfb4;border-radius:20px;padding:20px;box-shadow:0 12px 36px rgba(0,0,0,.05)}}.top{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}}.nav{{padding:7px 12px;border:1px solid #decfb4;border-radius:999px;background:#fff;text-decoration:none;color:#6e5f4f;font-weight:700}}.active{{background:#e5f0e8;color:#2f6442}}.muted{{color:#7f6f5d}}.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:16px 0}}.sum{{padding:12px;border:1px solid #decfb4;border-radius:14px;background:#fff}}.sum span{{display:block;color:#7f6f5d;margin-bottom:6px}}.sum strong{{font-size:22px;color:#2f6442}}.controls{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:18px 0 12px;align-items:end}}.control{{min-width:0}}.wide{{grid-column:span 2}}label{{display:block;font-size:12px;line-height:1.2;color:#7f6f5d;margin-bottom:5px;white-space:nowrap}}input,select,button{{width:100%;height:38px;padding:0 10px;border:1px solid #decfb4;border-radius:12px;background:#fff;font:inherit;box-sizing:border-box}}button{{background:#e5f0e8;color:#2f6442;font-weight:700;cursor:pointer}}button:disabled{{cursor:not-allowed;opacity:.55}}.meta{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;color:#7f6f5d;margin-bottom:10px}}.meta-right{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}.pager{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.pager button{{width:auto;min-width:84px;padding:0 14px}}.page-info{{min-width:84px;text-align:center;white-space:nowrap}}.table-wrap{{overflow:auto;border:1px solid #decfb4;border-radius:16px;background:#fff}}table{{width:100%;min-width:1180px;border-collapse:collapse}}th,td{{padding:12px 14px;border-bottom:1px solid #eee3d1;text-align:left;vertical-align:top}}th{{position:sticky;top:0;background:#f2f8f4;white-space:nowrap}}th button{{width:auto;height:auto;padding:0;border:0;background:transparent;font-weight:700;white-space:nowrap;display:inline-flex;align-items:center}}tbody tr:nth-child(even) td{{background:#fffdf8}}a.link{{color:#2f6442;text-decoration:none}}a.link:hover{{text-decoration:underline}}.empty{{padding:24px;text-align:center;color:#7f6f5d}}@media (max-width:980px){{.controls{{grid-template-columns:repeat(2,minmax(150px,1fr))}}.wide{{grid-column:span 2}}}}@media (max-width:640px){{.controls{{grid-template-columns:1fr}}.wide{{grid-column:span 1}}.meta{{align-items:flex-start;flex-direction:column}}}}</style></head><body><div class="wrap"><div class="box"><div class="top">{''.join(nav)}</div><h1>{html.escape(display_name)} \u7684{CATEGORY_CONFIG[category]["label"]}\u5217\u8868</h1><p class="muted">\u8d26\u53f7\uff1a{html.escape(account_id)}</p><p class="muted">\u751f\u6210\u65f6\u95f4\uff1a{now_text()}</p><div class="summary">{summary}</div><div class="controls"><div class="control wide"><label>\u641c\u7d22</label><input id="searchInput" placeholder="\u6807\u9898/\u65f6\u95f4/\u7b80\u4ecb/\u77ed\u8bc4"></div><div class="control"><label>\u72b6\u6001</label><select id="statusFilter"><option value="">\u5168\u90e8\u72b6\u6001</option>{options}</select></div><div class="control"><label>\u5f00\u59cb\u65e5\u671f</label><input id="startDate" type="date"></div><div class="control"><label>\u7ed3\u675f\u65e5\u671f</label><input id="endDate" type="date"></div><div class="control"><label>\u6392\u5e8f\u5b57\u6bb5</label><select id="sortKey"><option value="marked_date">\u6807\u8bb0\u65e5\u671f</option><option value="content_date">{html.escape(time_label)}</option><option value="title">\u6807\u9898</option><option value="rating">\u8bc4\u5206</option><option value="status_label">\u72b6\u6001</option></select></div><div class="control"><label>\u6392\u5e8f\u65b9\u5411</label><select id="sortOrder"><option value="desc">\u964d\u5e8f</option><option value="asc">\u5347\u5e8f</option></select></div><div class="control"><label>\u6bcf\u9875\u6761\u6570</label><select id="pageSize"><option value="20" selected>20</option><option value="10">10</option><option value="50">50</option><option value="100">100</option><option value="200">200</option><option value="all">\u5168\u90e8</option></select></div><div class="control"><label>&nbsp;</label><button id="resetButton" type="button">\u91cd\u7f6e</button></div></div><div class="meta"><div id="resultCount">\u6b63\u5728\u8ba1\u7b97...</div><div class="meta-right"><span>\u53ef\u4ee5\u70b9\u51fb\u8868\u5934\u5feb\u901f\u6392\u5e8f</span><div class="pager"><button id="prevButton" type="button">\u4e0a\u4e00\u9875</button><span id="pageInfo" class="page-info">\u7b2c 1 / 1 \u9875</span><button id="nextButton" type="button">\u4e0b\u4e00\u9875</button></div></div></div><div class="table-wrap"><table><thead><tr><th><button type="button" data-sort-key="status_label">\u72b6\u6001</button></th><th><button type="button" data-sort-key="title">\u6807\u9898</button></th><th><button type="button" data-sort-key="rating">\u8bc4\u5206</button></th><th><button type="button" data-sort-key="marked_date">\u6807\u8bb0\u65e5\u671f</button></th><th><button type="button" data-sort-key="content_date">{html.escape(time_label)}</button></th><th>\u7b80\u4ecb</th><th>\u77ed\u8bc4</th><th>ID</th><th>\u94fe\u63a5</th></tr></thead><tbody id="rowsBody"></tbody></table></div><div id="emptyState" class="empty" hidden>\u6ca1\u6709\u5339\u914d\u7684\u8bb0\u5f55\u3002</div></div></div><script>const ALL_ROWS={data};const $=id=>document.getElementById(id);const searchInput=$("searchInput"),statusFilter=$("statusFilter"),startDate=$("startDate"),endDate=$("endDate"),sortKeySelect=$("sortKey"),sortOrderSelect=$("sortOrder"),pageSizeSelect=$("pageSize"),resetButton=$("resetButton"),prevButton=$("prevButton"),nextButton=$("nextButton"),pageInfo=$("pageInfo"),rowsBody=$("rowsBody"),resultCount=$("resultCount"),emptyState=$("emptyState");let currentPage=1;function e(v){{return String(v??"").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#39;")}}function n(v){{return String(v??"").toLowerCase()}}function cmp(a,b,key){{if(key==="rating"){{return (a[key]===""?-1:Number(a[key]))-(b[key]===""?-1:Number(b[key]))}}return String(a[key]||"").localeCompare(String(b[key]||""),"zh-Hans-CN")}}function dateOk(row){{const d=row.marked_date||"";if(startDate.value&&(!d||d<startDate.value))return false;if(endDate.value&&(!d||d>endDate.value))return false;return true}}function filteredSorted(){{const terms=n(searchInput.value).split(/\\s+/).filter(Boolean),status=statusFilter.value,key=sortKeySelect.value,dir=sortOrderSelect.value==="asc"?1:-1;return ALL_ROWS.filter(row=>{{if(status&&row.status!==status)return false;if(!dateOk(row))return false;if(!terms.length)return true;const hay=n([row.title,row.content_date,row.intro,row.comment,row.subject_id,row.status_label].join(" "));return terms.every(term=>hay.includes(term))}}).sort((a,b)=>cmp(a,b,key)*dir)}}function pageSizeValue(){{return pageSizeSelect.value==="all"?0:Number(pageSizeSelect.value||20)}}function render(){{const rows=filteredSorted(),size=pageSizeValue(),totalPages=size?Math.max(1,Math.ceil(rows.length/size)):1;currentPage=Math.min(Math.max(currentPage,1),totalPages);const startIndex=rows.length===0?0:(size?(currentPage-1)*size:0),endIndex=rows.length===0?0:(size?Math.min(startIndex+size,rows.length):rows.length),pageRows=rows.slice(startIndex,endIndex),from=rows.length===0?0:startIndex+1,to=rows.length===0?0:endIndex;resultCount.textContent=`\\u5f53\\u524d\\u663e\\u793a ${{from}}-${{to}} / ${{rows.length}} \\u6761`;pageInfo.textContent=`\\u7b2c ${{rows.length===0?0:currentPage}} / ${{rows.length===0?0:totalPages}} \\u9875`;prevButton.disabled=rows.length===0||currentPage<=1;nextButton.disabled=rows.length===0||currentPage>=totalPages;emptyState.hidden=rows.length!==0;rowsBody.innerHTML=pageRows.map(row=>`<tr><td>${{e(row.status_label)}}</td><td>${{e(row.title)}}</td><td>${{e(row.rating||"-")}}</td><td>${{e(row.marked_date||"-")}}</td><td>${{e(row.content_date||"-")}}</td><td>${{e(row.intro)}}</td><td>${{e(row.comment)}}</td><td>${{e(row.subject_id)}}</td><td>${{row.url?`<a class="link" href="${{e(row.url)}}" target="_blank" rel="noreferrer">\\u6253\\u5f00</a>`:"-"}}</td></tr>`).join("")}}function rerenderFromFirstPage(){{currentPage=1;render()}}function headerSort(ev){{const key=ev.currentTarget.dataset.sortKey;if(sortKeySelect.value===key)sortOrderSelect.value=sortOrderSelect.value==="asc"?"desc":"asc";else{{sortKeySelect.value=key;sortOrderSelect.value=key==="title"||key==="status_label"?"asc":"desc"}}currentPage=1;render()}}function goToPage(delta){{currentPage+=delta;render()}}function reset(){{searchInput.value="";statusFilter.value="";startDate.value="";endDate.value="";sortKeySelect.value="marked_date";sortOrderSelect.value="desc";pageSizeSelect.value="20";currentPage=1;render()}}[searchInput,statusFilter,startDate,endDate,sortKeySelect,sortOrderSelect,pageSizeSelect].forEach(el=>el.addEventListener(el.tagName==="INPUT"?"input":"change",rerenderFromFirstPage));resetButton.addEventListener("click",reset);prevButton.addEventListener("click",()=>goToPage(-1));nextButton.addEventListener("click",()=>goToPage(1));document.querySelectorAll("[data-sort-key]").forEach(btn=>btn.addEventListener("click",headerSort));render();</script></body></html>"""

    def render_category_page_v2(
        self,
        account_id: str,
        display_name: str,
        category: str,
        selected_categories: tuple[str, ...],
        selected_statuses: tuple[str, ...],
        detail_rows: list[dict[str, str]],
        summary_rows: list[dict[str, str | int]],
    ) -> str:
        nav = ['<a class="nav" href="index.html">\u603b\u89c8</a>'] + [f'<a class="nav{" active" if item == category else ""}" href="{CATEGORY_CONFIG[item]["html"]}">{CATEGORY_CONFIG[item]["label"]}</a>' for item in selected_categories]
        summary = "".join(f"<div class='sum'><span>{html.escape(str(row['status_label']))}</span><strong>{row['count']}</strong></div>" for row in summary_rows)
        options = "".join(f'<option value="{status}">{STATUS_LABELS[category][status]}</option>' for status in selected_statuses if status in STATUS_LABELS[category] and any(row["status"] == status for row in summary_rows))
        data = json_for_script(detail_rows)
        time_label = TIME_COLUMN_LABELS[category]
        intro_label = INTRO_COLUMN_LABELS[category]
        time_prefix = time_label[:-2] if time_label.endswith("\u65f6\u95f4") else time_label
        time_start_label = f"{time_prefix}\u5f00\u59cb\u65f6\u95f4"
        time_end_label = f"{time_prefix}\u7ed3\u675f\u65f6\u95f4"
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{CATEGORY_CONFIG[category]["label"]}</title>
  <style>
    body{{margin:0;font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#f6f2e8;color:#221b13}}
    .wrap{{max-width:1380px;margin:auto;padding:20px 16px 36px}}
    .box{{background:#fffaf1;border:1px solid #decfb4;border-radius:20px;padding:20px;box-shadow:0 12px 36px rgba(0,0,0,.05)}}
    .top{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}}
    .nav{{padding:7px 12px;border:1px solid #decfb4;border-radius:999px;background:#fff;text-decoration:none;color:#6e5f4f;font-weight:700}}
    .active{{background:#e5f0e8;color:#2f6442}}
    .muted{{color:#7f6f5d}}
    .summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:12px;margin:16px 0}}
    .sum{{padding:12px;border:1px solid #decfb4;border-radius:14px;background:#fff}}
    .sum span{{display:block;color:#7f6f5d;margin-bottom:6px}}
    .sum strong{{font-size:22px;color:#2f6442}}
    .controls{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:18px 0 12px;align-items:end}}
    .control{{min-width:0}}
    .control.search{{grid-column:span 2}}
    label{{display:block;font-size:12px;line-height:1.2;color:#7f6f5d;margin-bottom:5px;white-space:nowrap}}
    input,select,button{{width:100%;height:38px;padding:0 10px;border:1px solid #decfb4;border-radius:12px;background:#fff;font:inherit;box-sizing:border-box}}
    button{{background:#e5f0e8;color:#2f6442;font-weight:700;cursor:pointer}}
    button:disabled{{cursor:not-allowed;opacity:.55}}
    .meta{{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:center;color:#7f6f5d;margin-bottom:10px}}
    .meta-left{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}}
    .meta-hint{{color:#2f6442;font-weight:700;white-space:nowrap}}
    .meta-right{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}
    .result-count{{white-space:nowrap}}
    .page-size-inline{{display:flex;gap:8px;align-items:center;white-space:nowrap}}
    .page-size-inline label{{margin:0;color:#7f6f5d;font-size:inherit;line-height:inherit}}
    .page-size-inline select{{width:92px}}
    .ghost-button{{width:auto;height:34px;padding:0 12px;background:#fff;color:#2f6442;border:1px solid #b6d1be;border-radius:999px;white-space:nowrap}}
    .ghost-button:hover{{background:#edf7f0}}
    .pager{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}
    .pager button{{width:auto;min-width:84px;padding:0 14px}}
    .page-info{{min-width:84px;text-align:center;white-space:nowrap}}
    .table-wrap{{overflow:auto;border:1px solid #decfb4;border-radius:16px;background:#fff}}
    table{{width:100%;min-width:1060px;border-collapse:collapse}}
    th,td{{padding:12px 14px;border-bottom:1px solid #eee3d1;text-align:left;vertical-align:top}}
    th{{position:sticky;top:0;background:#f2f8f4;white-space:nowrap}}
    th button{{width:auto;height:auto;padding:0;border:0;background:transparent;font-weight:700;white-space:nowrap;display:inline-flex;align-items:center;color:#2f6442}}
    tbody tr:nth-child(even) td{{background:#fffdf8}}
    a.link{{color:#2f6442;text-decoration:none}}
    a.link:hover{{text-decoration:underline}}
    td.fold-cell{{max-width:340px}}
    td.intro-cell{{width:26%}}
    td.comment-cell{{width:22%}}
    .cell-block{{display:flex;flex-direction:column;align-items:flex-start;gap:6px}}
    .cell-text{{line-height:1.6;white-space:normal;word-break:break-word}}
    .cell-text.is-collapsed{{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:3;overflow:hidden}}
    .cell-toggle{{width:auto;height:auto;padding:0;border:0;background:transparent;color:#2f6442;font-weight:700;cursor:pointer}}
    .cell-placeholder{{color:#9a8b7b}}
    .empty{{padding:24px;text-align:center;color:#7f6f5d}}
    @media (max-width:1200px){{
      .controls{{grid-template-columns:repeat(3,minmax(0,1fr))}}
      .control.search{{grid-column:span 3}}
    }}
    @media (max-width:640px){{
      .controls{{grid-template-columns:1fr}}
      .control.search{{grid-column:span 1}}
      .meta{{align-items:flex-start;flex-direction:column}}
      .meta-right{{justify-content:flex-start}}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="box">
      <div class="top">{''.join(nav)}</div>
      <h1>{html.escape(display_name)} \u7684{CATEGORY_CONFIG[category]["label"]}\u5217\u8868</h1>
      <p class="muted">\u8d26\u53f7\uff1a{html.escape(account_id)}</p>
      <p class="muted">\u751f\u6210\u65f6\u95f4\uff1a{now_text()}</p>
      <div class="summary">{summary}</div>
      <div class="controls">
        <div class="control search">
          <label>\u641c\u7d22</label>
          <input id="searchInput" placeholder="\u6807\u9898/{html.escape(time_label)}/{html.escape(intro_label)}/\u77ed\u8bc4">
        </div>
        <div class="control">
          <label>\u72b6\u6001</label>
          <select id="statusFilter"><option value="">\u5168\u90e8\u72b6\u6001</option>{options}</select>
        </div>
        <div class="control">
          <label>\u6392\u5e8f\u5b57\u6bb5</label>
          <select id="sortKey"><option value="marked_date">\u6807\u8bb0\u65e5\u671f</option><option value="content_date">{html.escape(time_label)}</option><option value="title">\u6807\u9898</option><option value="douban_rating">\u8c46\u74e3\u8bc4\u5206</option><option value="rating">\u6211\u7684\u8bc4\u5206</option><option value="status_label">\u72b6\u6001</option></select>
        </div>
        <div class="control">
          <label>\u6392\u5e8f\u65b9\u5411</label>
          <select id="sortOrder"><option value="desc">\u964d\u5e8f</option><option value="asc">\u5347\u5e8f</option></select>
        </div>
        <div class="control">
          <label>&nbsp;</label>
          <button id="resetButton" type="button">\u91cd\u7f6e</button>
        </div>
        <div class="control">
          <label>{html.escape(time_start_label)}</label>
          <input id="contentStartDate" type="date">
        </div>
        <div class="control">
          <label>{html.escape(time_end_label)}</label>
          <input id="contentEndDate" type="date">
        </div>
        <div class="control">
          <label>\u6807\u8bb0\u5f00\u59cb\u65e5\u671f</label>
          <input id="markedStartDate" type="date">
        </div>
        <div class="control">
          <label>\u6807\u8bb0\u7ed3\u675f\u65e5\u671f</label>
          <input id="markedEndDate" type="date">
        </div>
      </div>
      <div class="meta">
        <div class="meta-left">
          <div class="meta-hint">\u70b9\u51fb\u8868\u5934\u5feb\u901f\u6392\u5e8f</div>
          <button id="introToggleAllButton" class="ghost-button" type="button">\u5168\u5c40\u5c55\u5f00{html.escape(intro_label)}</button>
          <button id="commentToggleAllButton" class="ghost-button" type="button">\u5168\u5c40\u5c55\u5f00\u77ed\u8bc4</button>
        </div>
        <div class="meta-right">
          <div id="resultCount" class="result-count">\u6b63\u5728\u8ba1\u7b97...</div>
          <div class="page-size-inline">
            <label for="pageSize">\u6bcf\u9875\u6761\u6570</label>
            <select id="pageSize"><option value="20" selected>20</option><option value="10">10</option><option value="50">50</option><option value="100">100</option><option value="200">200</option><option value="all">\u5168\u90e8</option></select>
          </div>
          <div class="pager">
            <button id="prevButton" type="button">\u4e0a\u4e00\u9875</button>
            <span id="pageInfo" class="page-info">\u7b2c 1 / 1 \u9875</span>
            <button id="nextButton" type="button">\u4e0b\u4e00\u9875</button>
          </div>
        </div>
      </div>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th><button type="button" data-sort-key="status_label">\u72b6\u6001</button></th>
              <th><button type="button" data-sort-key="title">\u6807\u9898</button></th>
              <th><button type="button" data-sort-key="douban_rating">\u8c46\u74e3\u8bc4\u5206</button></th>
              <th><button type="button" data-sort-key="rating">\u6211\u7684\u8bc4\u5206</button></th>
              <th><button type="button" data-sort-key="marked_date">\u6807\u8bb0\u65e5\u671f</button></th>
              <th><button type="button" data-sort-key="content_date">{html.escape(time_label)}</button></th>
              <th>{html.escape(intro_label)}</th>
              <th>\u77ed\u8bc4</th>
            </tr>
          </thead>
          <tbody id="rowsBody"></tbody>
        </table>
      </div>
      <div id="emptyState" class="empty" hidden>\u6ca1\u6709\u5339\u914d\u7684\u8bb0\u5f55\u3002</div>
    </div>
  </div>
  <script>
    const ALL_ROWS = {data};
    const $ = id => document.getElementById(id);
    const searchInput = $("searchInput");
    const statusFilter = $("statusFilter");
    const markedStartDate = $("markedStartDate");
    const markedEndDate = $("markedEndDate");
    const contentStartDate = $("contentStartDate");
    const contentEndDate = $("contentEndDate");
    const sortKeySelect = $("sortKey");
    const sortOrderSelect = $("sortOrder");
    const pageSizeSelect = $("pageSize");
    const resetButton = $("resetButton");
    const introToggleAllButton = $("introToggleAllButton");
    const commentToggleAllButton = $("commentToggleAllButton");
    const prevButton = $("prevButton");
    const nextButton = $("nextButton");
    const pageInfo = $("pageInfo");
    const rowsBody = $("rowsBody");
    const resultCount = $("resultCount");
    const emptyState = $("emptyState");
    let currentPage = 1;
    const globalCollapsed = {{ intro: true, comment: true }};
    const cellExpandedState = new Map();

    function e(v) {{
      return String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
    }}

    function n(v) {{
      return String(v ?? "").toLowerCase();
    }}

    function cmp(a, b, key) {{
      if (key === "douban_rating" || key === "rating") {{
        return (a[key] === "" ? -1 : Number(a[key])) - (b[key] === "" ? -1 : Number(b[key]));
      }}
      return String(a[key] || "").localeCompare(String(b[key] || ""), "zh-Hans-CN");
    }}

    function normalizeDate(value, fillEnd = false) {{
      const parts = String(value ?? "").trim().split("-").filter(Boolean);
      if (!parts.length) return "";
      const year = parts[0].padStart(4, "0");
      const month = (parts[1] || (fillEnd ? "12" : "01")).padStart(2, "0");
      const day = (parts[2] || (fillEnd ? "31" : "01")).padStart(2, "0");
      return `${{year}}-${{month}}-${{day}}`;
    }}

    function inDateRange(value, start, end) {{
      const startValue = normalizeDate(value, false);
      const endValue = normalizeDate(value, true);
      if ((start || end) && !startValue) return false;
      if (start && endValue < start) return false;
      if (end && startValue > end) return false;
      return true;
    }}

    function markedDateOk(row) {{
      return inDateRange(row.marked_date || "", markedStartDate.value, markedEndDate.value);
    }}

    function contentDateOk(row) {{
      return inDateRange(row.content_date || "", contentStartDate.value, contentEndDate.value);
    }}

    function filteredSorted() {{
      const terms = n(searchInput.value).split(/\\s+/).filter(Boolean);
      const status = statusFilter.value;
      const key = sortKeySelect.value;
      const dir = sortOrderSelect.value === "asc" ? 1 : -1;
      return ALL_ROWS.filter(row => {{
        if (status && row.status !== status) return false;
        if (!markedDateOk(row) || !contentDateOk(row)) return false;
        if (!terms.length) return true;
        const hay = n([row.title, row.content_date, row.intro, row.comment, row.status_label, row.douban_rating, row.rating].join(" "));
        return terms.every(term => hay.includes(term));
      }}).sort((a, b) => cmp(a, b, key) * dir);
    }}

    function pageSizeValue() {{
      return pageSizeSelect.value === "all" ? 0 : Number(pageSizeSelect.value || 20);
    }}

    function cellStateKey(row, field) {{
      return [row.category, row.subject_id, row.status, row.marked_date, row.title, field].join("||");
    }}

    function isExpandableText(value) {{
      return String(value ?? "").trim().length > 90;
    }}

    function isCellExpanded(row, field) {{
      const key = cellStateKey(row, field);
      if (cellExpandedState.has(key)) return cellExpandedState.get(key);
      return !globalCollapsed[field];
    }}

    function clearFieldOverrides(field) {{
      for (const key of Array.from(cellExpandedState.keys())) {{
        if (key.endsWith(`||${{field}}`)) cellExpandedState.delete(key);
      }}
    }}

    function updateGlobalToggleButtons() {{
      introToggleAllButton.textContent = globalCollapsed.intro ? "\\u5168\\u5c40\\u5c55\\u5f00{html.escape(intro_label)}" : "\\u5168\\u5c40\\u6298\\u53e0{html.escape(intro_label)}";
      commentToggleAllButton.textContent = globalCollapsed.comment ? "\\u5168\\u5c40\\u5c55\\u5f00\\u77ed\\u8bc4" : "\\u5168\\u5c40\\u6298\\u53e0\\u77ed\\u8bc4";
    }}

    function renderFoldableCell(row, field, className) {{
      const rawText = String(row[field] ?? "").trim();
      if (!rawText) return `<td class="fold-cell ${{className}}"><span class="cell-placeholder">-</span></td>`;
      if (!isExpandableText(rawText)) {{
        return `<td class="fold-cell ${{className}}"><div class="cell-block"><div class="cell-text">${{e(rawText)}}</div></div></td>`;
      }}
      const expanded = isCellExpanded(row, field);
      return `<td class="fold-cell ${{className}}"><div class="cell-block"><div class="cell-text${{expanded ? "" : " is-collapsed"}}">${{e(rawText)}}</div><button type="button" class="cell-toggle" data-action="toggle-cell" data-key="${{e(cellStateKey(row, field))}}" data-expanded="${{expanded ? "1" : "0"}}">${{expanded ? "\\u6536\\u8d77" : "\\u5c55\\u5f00"}}</button></div></td>`;
    }}

    function render() {{
      const rows = filteredSorted();
      const size = pageSizeValue();
      const totalPages = size ? Math.max(1, Math.ceil(rows.length / size)) : 1;
      currentPage = Math.min(Math.max(currentPage, 1), totalPages);
      const startIndex = rows.length === 0 ? 0 : (size ? (currentPage - 1) * size : 0);
      const endIndex = rows.length === 0 ? 0 : (size ? Math.min(startIndex + size, rows.length) : rows.length);
      const pageRows = rows.slice(startIndex, endIndex);
      const from = rows.length === 0 ? 0 : startIndex + 1;
      const to = rows.length === 0 ? 0 : endIndex;
      resultCount.textContent = `\\u5f53\\u524d\\u663e\\u793a ${{from}}-${{to}} / ${{rows.length}} \\u6761`;
      pageInfo.textContent = `\\u7b2c ${{rows.length === 0 ? 0 : currentPage}} / ${{rows.length === 0 ? 0 : totalPages}} \\u9875`;
      prevButton.disabled = rows.length === 0 || currentPage <= 1;
      nextButton.disabled = rows.length === 0 || currentPage >= totalPages;
      emptyState.hidden = rows.length !== 0;
      updateGlobalToggleButtons();
      rowsBody.innerHTML = pageRows.map(row => `<tr><td>${{e(row.status_label)}}</td><td>${{row.url ? `<a class="link" href="${{e(row.url)}}" target="_blank" rel="noreferrer">${{e(row.title)}}</a>` : e(row.title)}}</td><td>${{e(row.douban_rating || "-")}}</td><td>${{e(row.rating || "-")}}</td><td>${{e(row.marked_date || "-")}}</td><td>${{e(row.content_date || "-")}}</td>${{renderFoldableCell(row, "intro", "intro-cell")}}${{renderFoldableCell(row, "comment", "comment-cell")}}</tr>`).join("");
    }}

    function rerenderFromFirstPage() {{
      currentPage = 1;
      render();
    }}

    function headerSort(ev) {{
      const key = ev.currentTarget.dataset.sortKey;
      if (sortKeySelect.value === key) sortOrderSelect.value = sortOrderSelect.value === "asc" ? "desc" : "asc";
      else {{
        sortKeySelect.value = key;
        sortOrderSelect.value = key === "title" || key === "status_label" ? "asc" : "desc";
      }}
      currentPage = 1;
      render();
    }}

    function goToPage(delta) {{
      currentPage += delta;
      render();
    }}

    function reset() {{
      searchInput.value = "";
      statusFilter.value = "";
      markedStartDate.value = "";
      markedEndDate.value = "";
      contentStartDate.value = "";
      contentEndDate.value = "";
      sortKeySelect.value = "marked_date";
      sortOrderSelect.value = "desc";
      pageSizeSelect.value = "20";
      currentPage = 1;
      render();
    }}

    function toggleGlobalField(field) {{
      globalCollapsed[field] = !globalCollapsed[field];
      clearFieldOverrides(field);
      render();
    }}

    function toggleSingleCell(button) {{
      const key = button.dataset.key || "";
      const expanded = button.dataset.expanded === "1";
      cellExpandedState.set(key, !expanded);
      render();
    }}

    [searchInput, statusFilter, markedStartDate, markedEndDate, contentStartDate, contentEndDate, sortKeySelect, sortOrderSelect, pageSizeSelect].forEach(el => el.addEventListener(el.tagName === "INPUT" ? "input" : "change", rerenderFromFirstPage));
    resetButton.addEventListener("click", reset);
    introToggleAllButton.addEventListener("click", () => toggleGlobalField("intro"));
    commentToggleAllButton.addEventListener("click", () => toggleGlobalField("comment"));
    prevButton.addEventListener("click", () => goToPage(-1));
    nextButton.addEventListener("click", () => goToPage(1));
    rowsBody.addEventListener("click", event => {{
      const button = event.target.closest("[data-action='toggle-cell']");
      if (!button) return;
      toggleSingleCell(button);
    }});
    document.querySelectorAll("[data-sort-key]").forEach(btn => btn.addEventListener("click", headerSort));
    render();
  </script>
</body>
</html>"""

    def _validate_selection(self, categories: Iterable[str], statuses: Iterable[str]) -> None:
        invalid_categories = [category for category in categories if category not in CATEGORY_CONFIG]
        invalid_statuses = [status for status in statuses if status not in DEFAULT_STATUSES]
        if invalid_categories:
            raise DoubanExportError(f"\u4e0d\u652f\u6301\u7684\u5206\u7c7b: {', '.join(invalid_categories)}")
        if invalid_statuses:
            raise DoubanExportError(f"\u4e0d\u652f\u6301\u7684\u72b6\u6001: {', '.join(invalid_statuses)}")


def open_in_file_explorer(path: Path) -> None:
    resolved_path = Path(path).resolve()
    if sys.platform.startswith("win"):
        os.startfile(resolved_path)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.run(["open", str(resolved_path)], check=True)
        return
    subprocess.run(["xdg-open", str(resolved_path)], check=True)
