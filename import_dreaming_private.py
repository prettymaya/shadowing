from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).parent
PRIVATE_ROOT = ROOT / "private_data" / "dreaming"
LESSONS_DIR = PRIVATE_ROOT / "lessons"
APP_BASE = "https://app.dreaming.com"
CATALOG_URL = f"{APP_BASE}/videos/prod/es.json"
SSL_CONTEXT = ssl._create_unverified_context()


def request_json(url: str, token: str | None = None) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 ShadowingLocal/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30, context=SSL_CONTEXT) as res:
        return json.loads(res.read().decode("utf-8"))


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", str(value))
    return re.sub(r"\s+", " ", value).strip()


def split_transcript_text(value: str) -> list[str]:
    value = clean_text(value)
    if not value:
        return []
    lines = [line.strip() for line in re.split(r"(?:\r?\n)+", value) if line.strip()]
    if len(lines) > 1:
        return lines
    sentences = re.split(r"(?<=[.!?¿¡])\s+", value)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def text_from_caption_item(item) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("text", "content", "sentence", "line", "value"):
            if isinstance(item.get(key), str):
                return item[key]
    return ""


def transcript_candidates(value, path: str = "") -> list[list[str]]:
    candidates: list[list[str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            lower_key = str(key).lower()
            next_path = f"{path}.{lower_key}" if path else lower_key
            if any(word in lower_key for word in ("transcript", "caption", "subtitle", "subtitles")):
                if isinstance(item, str):
                    lines = split_transcript_text(item)
                    if lines:
                        candidates.append(lines)
                elif isinstance(item, list):
                    lines = [clean_text(text_from_caption_item(entry)) for entry in item]
                    lines = [line for line in lines if line]
                    if lines:
                        candidates.append(lines)
                elif isinstance(item, dict):
                    candidates.extend(transcript_candidates(item, next_path))
            elif isinstance(item, (dict, list)):
                candidates.extend(transcript_candidates(item, next_path))
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                candidates.extend(transcript_candidates(item, path))
    return candidates


def extract_transcript(detail: dict) -> list[str]:
    candidates = transcript_candidates(detail)
    if not candidates:
        return []
    return max(candidates, key=lambda lines: sum(len(line) for line in lines))


def category_slug(level: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", (level or "dreaming").lower()).strip("-")
    return f"dreaming-{safe or 'spanish'}"


def category_name(slug: str) -> str:
    label = slug.removeprefix("dreaming-").replace("-", " ").title()
    return f"Dreaming Spanish - {label}"


def lesson_from_video(video: dict, detail: dict, lines: list[str]) -> tuple[dict, dict]:
    lesson_id = f"ds-{video['_id']}"
    level = video.get("level") or detail.get("level") or ""
    slug = category_slug(level)
    now = datetime.now().replace(microsecond=0).isoformat()
    title = video.get("title") or detail.get("title") or lesson_id
    subtitle = ", ".join(video.get("guides") or detail.get("guides") or [])
    url = f"{APP_BASE}/spanish/watch?id={video['_id']}"
    challenges = [
        {"position": index, "content": line, "audio_url": "", "time_start": None, "time_end": None}
        for index, line in enumerate(lines, start=1)
    ]
    catalog_lesson = {
        "id": lesson_id,
        "language": "dreaming",
        "category_slug": slug,
        "category_name": category_name(slug),
        "position": video.get("difficultyScore") or 0,
        "title": title,
        "subtitle": subtitle,
        "level": level,
        "parts": len(challenges),
        "url": url,
        "audio_url": "",
        "youtube_video_id": "",
        "vimeo_video_id": "",
        "video_url": "",
        "details_cached_at": now,
        "private": True,
    }
    detail_lesson = {**catalog_lesson, "challenges": challenges}
    return catalog_lesson, detail_lesson


def write_catalog(lessons: list[dict]) -> None:
    counts: dict[str, int] = {}
    for lesson in lessons:
        counts[lesson["category_slug"]] = counts.get(lesson["category_slug"], 0) + 1
    categories = [
        {
            "slug": slug,
            "language": "dreaming",
            "name": category_name(slug),
            "levels": "",
            "description": "Private Dreaming Spanish transcripts",
            "lesson_count": counts[slug],
            "position": 200 + index,
            "private": True,
        }
        for index, slug in enumerate(sorted(counts), start=1)
    ]
    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    (PRIVATE_ROOT / "catalog.json").write_text(
        json.dumps({"categories": categories, "lessons": lessons}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Dreaming Spanish private transcript importer.")
    parser.add_argument("--token", default=os.environ.get("DREAMING_TOKEN"), help="Dreaming app localStorage token.")
    parser.add_argument("--limit", type=int, default=None, help="Test için maksimum video sayısı.")
    parser.add_argument("--delay", type=float, default=0.15, help="İstekler arası bekleme.")
    parser.add_argument("--include-private", action="store_true", help="Premium/private videoları da dener.")
    args = parser.parse_args()
    if not args.token:
        raise SystemExit("Token gerekli. DREAMING_TOKEN env var ya da --token kullan.")

    PRIVATE_ROOT.mkdir(parents=True, exist_ok=True)
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    catalog = request_json(CATALOG_URL)
    videos = catalog.get("videos", [])
    if not args.include_private:
        videos = [video for video in videos if not video.get("private")]
    if args.limit:
        videos = videos[: args.limit]

    lessons: list[dict] = []
    for index, video in enumerate(videos, start=1):
        video_id = video.get("_id")
        if not video_id:
            continue
        detail_url = f"{APP_BASE}/.netlify/functions/video?{urlencode({'id': video_id})}"
        try:
            detail = request_json(detail_url, args.token)
        except Exception as exc:
            print(f"{index}/{len(videos)} atlandı {video_id}: {exc}", flush=True)
            continue
        lines = extract_transcript(detail)
        if not lines:
            print(f"{index}/{len(videos)} transcript yok: {video.get('title')}", flush=True)
            continue
        lesson, lesson_detail = lesson_from_video(video, detail.get("video", detail), lines)
        lessons.append(lesson)
        (LESSONS_DIR / f"{lesson['id']}.json").write_text(
            json.dumps(lesson_detail, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"{index}/{len(videos)} eklendi {lesson['title']} ({len(lines)} satır)", flush=True)
        if args.delay:
            time.sleep(args.delay)

    write_catalog(lessons)
    print(f"Dreaming import tamam: {len(lessons)} transcriptli video", flush=True)


if __name__ == "__main__":
    main()
