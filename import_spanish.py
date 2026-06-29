from __future__ import annotations

import argparse
import json
import re
import ssl
import time
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).parent
STATIC_DATA = ROOT / "static" / "data"
LESSONS_DIR = STATIC_DATA / "lessons"
BASE_URL = "https://www.spanishlistening.org/"
INDEXES = [
    "content/index-001.html",
    "content/index-051.html",
    "content/index-101.html",
    "content/index-151.html",
    "content/index-201.html",
    "content/index-251.html",
    "content/index-301.html",
    "content/index-351.html",
    "content/index-401.html",
]


SSL_CONTEXT = ssl._create_unverified_context()
HEADERS = {"User-Agent": "Mozilla/5.0 ShadowingLocal/1.0"}


def request_text(url: str) -> str:
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30, context=SSL_CONTEXT) as res:
        return res.read().decode("utf-8", errors="replace")


def clean_html(value: str) -> str:
    value = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style\b.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"</?(?:span|strong|em|b|i)\b[^>]*>", "", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"([¿¡])\s+", r"\1", value)


def extract_links() -> list[dict]:
    lessons: dict[int, dict] = {}
    for index_url in INDEXES:
        url = urljoin(BASE_URL, index_url)
        html = request_text(url)
        for number, href, title_html in re.findall(r"#\s*(\d+)\s*<a\s+href=\"([^\"]+\.html)\"[^>]*>(.*?)</a>", html, flags=re.I | re.S):
            lesson_number = int(number)
            lessons[lesson_number] = {
                "number": lesson_number,
                "url": urljoin(url, href.replace(" ", "%20")),
                "title": clean_html(title_html).lstrip("#").strip(),
            }
    return [lessons[key] for key in sorted(lessons)]


def extract_first(pattern: str, html: str, default: str = "") -> str:
    match = re.search(pattern, html, flags=re.I | re.S)
    return clean_html(match.group(1)) if match else default


def extract_media(html: str) -> dict:
    iframe = re.search(r"<iframe[^>]+src=\"([^\"]+)\"", html, flags=re.I)
    src = unescape(iframe.group(1)) if iframe else ""
    vimeo = re.search(r"player\.vimeo\.com/video/(\d+)", src)
    youtube = re.search(r"(?:youtube\.com/embed/|youtu\.be/)([A-Za-z0-9_-]+)", src)
    return {
        "video_url": src,
        "vimeo_video_id": vimeo.group(1) if vimeo else "",
        "youtube_video_id": youtube.group(1) if youtube else "",
    }


def extract_transcript(html: str) -> list[dict]:
    match = re.search(r"<div\s+class=\"transcript\"\s+id=\"transcript\"\s*>(.*?)</div>", html, flags=re.I | re.S)
    if not match:
        return []
    paragraphs = re.findall(r"<p\b[^>]*>(.*?)</p>", match.group(1), flags=re.I | re.S)
    return [
        {"position": index, "content": clean_html(paragraph), "audio_url": "", "time_start": None, "time_end": None}
        for index, paragraph in enumerate(paragraphs, start=1)
        if clean_html(paragraph)
    ]


def level_slug(level: str) -> str:
    value = level.lower()
    if "beginner" in value:
        return "spanish-beginner"
    if "intermediate" in value:
        return "spanish-intermediate"
    if "advanced" in value:
        return "spanish-advanced"
    return "spanish-listening"


def category_name(slug: str) -> str:
    return {
        "spanish-beginner": "Spanish Listening - Beginner",
        "spanish-intermediate": "Spanish Listening - Intermediate",
        "spanish-advanced": "Spanish Listening - Advanced",
        "spanish-listening": "Spanish Listening",
    }[slug]


def parse_lesson(seed: dict) -> tuple[dict, dict]:
    html = request_text(seed["url"])
    number = seed["number"]
    title = extract_first(r"<div\s+class=\"video-question\"\s*>(.*?)</div>", html, seed["title"])
    level = extract_first(r"<div\s+class=\"video-number\"\s*>.*?<strong>(.*?)</strong>", html, "")
    speaker = extract_first(r"<div\s+class=\"video-speaker-names\"\s*>.*?<h3>(.*?)</h3>", html, "")
    media = extract_media(html)
    challenges = extract_transcript(html)
    category_slug = level_slug(level)
    lesson_id = f"es-{number}"
    now = datetime.now().replace(microsecond=0).isoformat()
    catalog_lesson = {
        "id": lesson_id,
        "language": "spanish",
        "category_slug": category_slug,
        "category_name": category_name(category_slug),
        "position": number,
        "title": f"{number}. {title}" if title and not title.startswith(str(number)) else title,
        "subtitle": speaker,
        "level": level,
        "parts": len(challenges),
        "url": seed["url"],
        "audio_url": "",
        "youtube_video_id": media["youtube_video_id"],
        "vimeo_video_id": media["vimeo_video_id"],
        "video_url": media["video_url"],
        "details_cached_at": now,
    }
    detail = {**catalog_lesson, "challenges": challenges}
    return catalog_lesson, detail


def merge_catalog(spanish_lessons: list[dict]) -> dict:
    catalog_path = STATIC_DATA / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {"categories": [], "lessons": []}
    english_categories = [
        {"language": "english", **category}
        for category in catalog.get("categories", [])
        if category.get("language", "english") != "spanish"
    ]
    english_lessons = [
        {"language": "english", **lesson}
        for lesson in catalog.get("lessons", [])
        if lesson.get("language", "english") != "spanish"
    ]
    counts: dict[str, int] = {}
    for lesson in spanish_lessons:
        counts[lesson["category_slug"]] = counts.get(lesson["category_slug"], 0) + 1
    spanish_categories = [
        {
            "slug": slug,
            "language": "spanish",
            "name": category_name(slug),
            "levels": "",
            "description": "SpanishListening.org video lessons",
            "lesson_count": counts[slug],
            "position": 100 + index,
        }
        for index, slug in enumerate(["spanish-beginner", "spanish-intermediate", "spanish-advanced", "spanish-listening"], start=1)
        if slug in counts
    ]
    return {"categories": english_categories + spanish_categories, "lessons": english_lessons + spanish_lessons}


def main() -> None:
    parser = argparse.ArgumentParser(description="SpanishListening.org derslerini statik kataloğa ekler.")
    parser.add_argument("--limit", type=int, default=None, help="Test için maksimum ders sayısı.")
    parser.add_argument("--delay", type=float, default=0.1, help="İstekler arası bekleme.")
    args = parser.parse_args()

    STATIC_DATA.mkdir(parents=True, exist_ok=True)
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    seeds = extract_links()
    if args.limit:
        seeds = seeds[: args.limit]

    lessons: list[dict] = []
    for index, seed in enumerate(seeds, start=1):
        try:
            lesson, detail = parse_lesson(seed)
        except Exception as exc:
            print(f"Atlandı #{seed.get('number')}: {exc}", flush=True)
            continue
        lessons.append(lesson)
        (LESSONS_DIR / f"{lesson['id']}.json").write_text(
            json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"{index}/{len(seeds)} {lesson['id']} {lesson['title']} ({lesson['parts']} satır)", flush=True)
        if args.delay:
            time.sleep(args.delay)

    catalog = merge_catalog(lessons)
    (STATIC_DATA / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Spanish import tamam: {len(lessons)} ders", flush=True)


if __name__ == "__main__":
    main()
