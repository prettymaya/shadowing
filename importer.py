from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sqlite3
import ssl
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://dailydictation.com"
ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "shadowing.sqlite3"
EXCLUDED = {"IPA", "Numbers", "Spelling Names"}


def request_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "ShadowingLocal/1.0 (+local personal study)"})
    try:
        with urlopen(req, timeout=40) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        if "CERTIFICATE_VERIFY_FAILED" not in str(exc):
            raise
        context = ssl._create_unverified_context()
        with urlopen(req, timeout=40, context=context) as response:
            return response.read().decode("utf-8", errors="replace")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def ensure_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS categories (
              slug TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              levels TEXT,
              description TEXT,
              lesson_count INTEGER DEFAULT 0,
              position INTEGER DEFAULT 0,
              imported_at TEXT
            );

            CREATE TABLE IF NOT EXISTS lessons (
              id INTEGER PRIMARY KEY,
              category_slug TEXT NOT NULL,
              position INTEGER DEFAULT 0,
              title TEXT NOT NULL,
              subtitle TEXT DEFAULT '',
              level TEXT DEFAULT '',
              parts INTEGER DEFAULT 0,
              url TEXT NOT NULL UNIQUE,
              audio_url TEXT DEFAULT '',
              local_audio_path TEXT DEFAULT '',
              transcript TEXT DEFAULT '',
              completed_at TEXT,
              notes TEXT DEFAULT '',
              details_cached_at TEXT,
              imported_at TEXT,
              FOREIGN KEY(category_slug) REFERENCES categories(slug)
            );

            CREATE TABLE IF NOT EXISTS challenges (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              lesson_id INTEGER NOT NULL,
              remote_id INTEGER,
              position INTEGER NOT NULL,
              content TEXT NOT NULL,
              audio_url TEXT DEFAULT '',
              time_start REAL,
              time_end REAL,
              FOREIGN KEY(lesson_id) REFERENCES lessons(id)
            );

            CREATE TABLE IF NOT EXISTS lesson_sessions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              lesson_id INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              seconds INTEGER DEFAULT 0,
              notes TEXT DEFAULT '',
              FOREIGN KEY(lesson_id) REFERENCES lessons(id)
            );
            """
        )
        existing_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(lessons)").fetchall()
        }
        if "youtube_video_id" not in existing_columns:
            conn.execute("ALTER TABLE lessons ADD COLUMN youtube_video_id TEXT DEFAULT ''")


def parse_categories() -> list[dict]:
    page = request_text(urljoin(BASE_URL, "/exercises"))
    cards = re.findall(r'<div class="col-lg-4 mb-4">(.*?)</div>\s*</div>\s*</div>\s*</div>', page, flags=re.S)
    categories = []
    for index, card in enumerate(cards, start=1):
        link = re.search(r'<a[^>]+href="(/exercises/[^"]+)"[^>]*>\s*(?:<img[^>]+>)?\s*</a>|<a class="fs-4" href="(/exercises/[^"]+)">\s*([^<]+)</a>', card, flags=re.S)
        title_match = re.search(r'<a class="fs-4" href="(/exercises/[^"]+)">\s*([^<]+)</a>', card, flags=re.S)
        if not title_match:
            continue
        path, name = title_match.group(1), clean_text(title_match.group(2))
        if name in EXCLUDED:
            continue
        levels = clean_text((re.search(r"Levels:\s*([^<]+)", card) or ["", ""])[1])
        count_match = re.search(r"(\d+)\s*lessons", card)
        desc_match = re.search(r'<div class="card-text[^"]*"[^>]*>\s*(.*?)\s*</div>', card, flags=re.S)
        categories.append(
            {
                "slug": path.rsplit("/", 1)[-1],
                "name": name,
                "url": urljoin(BASE_URL, path),
                "levels": levels,
                "lesson_count": int(count_match.group(1)) if count_match else 0,
                "description": clean_text(desc_match.group(1) if desc_match else ""),
                "position": index,
            }
        )
    return categories


def json_ld_items(page: str) -> list[dict]:
    items = []
    for block in re.findall(r'<script type="application/ld\+json">\s*(.*?)\s*</script>', page, flags=re.S):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and isinstance(data.get("itemListElement"), list):
            items.extend(data["itemListElement"])
    return items


def title_key(value: str) -> str:
    value = re.sub(r"\s*-\s*Listen (and|&) (Type|Read)\s*$", "", value, flags=re.I)
    return clean_text(value).lower()


def stable_id(value: str) -> int:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def parse_lessons(category: dict) -> list[dict]:
    page = request_text(category["url"])
    audio_by_title = {}
    name_by_title = {}
    for item in json_ld_items(page):
        if item.get("@type") == "Quiz":
            key = title_key(item.get("name", ""))
            audio_by_title[key] = item.get("audio", "")
            name_by_title[key] = clean_text(re.sub(r"\s*-\s*Listen (and|&) Type\s*$", "", item.get("name", ""), flags=re.I))

    lessons = []
    pattern = re.compile(
        r'<a class="text-decoration-none" href="([^"]+/listen-and-type)">\s*<span class="fw-semibold">(.*?)</span>\s*</a>',
        flags=re.S,
    )
    matches = list(pattern.finditer(page))
    for position, match in enumerate(matches, start=1):
        path, title = match.groups()
        next_start = matches[position].start() if position < len(matches) else len(page)
        block = page[match.end():next_start]
        url = urljoin(BASE_URL, path)
        lesson_id_match = re.search(r"\.(\d+)/listen-and-type", path)
        subtitle_match = re.search(r'<small class="text-muted">(.*?)</small>', block, flags=re.S)
        parts_match = re.search(r"(\d+)\s*parts", block)
        level_match = re.search(r"Vocab level:\s*([A-C][12])", block)
        title = clean_text(title)
        lessons.append(
            {
                "id": int(lesson_id_match.group(1)) if lesson_id_match else stable_id(url),
                "category_slug": category["slug"],
                "position": position,
                "title": title,
                "subtitle": clean_text(subtitle_match.group(1) if subtitle_match else ""),
                "level": level_match.group(1) if level_match else "",
                "parts": int(parts_match.group(1)) if parts_match else 0,
                "url": url,
                "audio_url": audio_by_title.get(title_key(title), ""),
            }
        )
    seen = {title_key(lesson["title"]) for lesson in lessons}
    for raw_title, audio_url in audio_by_title.items():
        if raw_title in seen:
            continue
        display_title = name_by_title.get(raw_title) or raw_title
        audio_only_id = stable_id(f"{category['slug']}:{raw_title}:{audio_url}")
        lessons.append(
            {
                "id": audio_only_id,
                "category_slug": category["slug"],
                "position": len(lessons) + 1,
                "title": display_title,
                "subtitle": "Audio-only",
                "level": "",
                "parts": 0,
                "url": f"dd-local://audio-only/{audio_only_id}",
                "audio_url": audio_url,
            }
        )
    return lessons


def import_catalog() -> None:
    ensure_db()
    now = datetime.now().isoformat(timespec="seconds")
    categories = parse_categories()
    with sqlite3.connect(DB_PATH) as conn:
        for category in categories:
            conn.execute(
                """
                INSERT INTO categories (slug, name, levels, description, lesson_count, position, imported_at)
                VALUES (:slug, :name, :levels, :description, :lesson_count, :position, :imported_at)
                ON CONFLICT(slug) DO UPDATE SET
                  name = excluded.name,
                  levels = excluded.levels,
                  description = excluded.description,
                  lesson_count = excluded.lesson_count,
                  position = excluded.position,
                  imported_at = excluded.imported_at
                """,
                {**category, "imported_at": now},
            )
            lessons = parse_lessons(category)
            for lesson in lessons:
                conn.execute(
                    """
                    INSERT INTO lessons (id, category_slug, position, title, subtitle, level, parts, url, audio_url, imported_at)
                    VALUES (:id, :category_slug, :position, :title, :subtitle, :level, :parts, :url, :audio_url, :imported_at)
                    ON CONFLICT(id) DO UPDATE SET
                      category_slug = excluded.category_slug,
                      position = excluded.position,
                      title = excluded.title,
                      subtitle = excluded.subtitle,
                      level = excluded.level,
                      parts = excluded.parts,
                      url = excluded.url,
                      audio_url = COALESCE(NULLIF(excluded.audio_url, ''), lessons.audio_url),
                      imported_at = excluded.imported_at
                    """,
                    {**lesson, "imported_at": now},
                )
            print(f"{category['name']}: {len(lessons)} ders")
        conn.commit()
    print(f"Import bitti: {DB_PATH}")


def extract_app_globals(page: str) -> dict:
    match = re.search(r"<script>window\.appGlobals = (.*?);</script>", page, flags=re.S)
    if not match:
        raise ValueError("window.appGlobals bulunamadı")
    return json.loads(match.group(1))


def fetch_lesson_details(lesson_id: int) -> None:
    ensure_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        lesson = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        if lesson is None:
            raise ValueError("Ders bulunamadı")
        if str(lesson["url"]).startswith("dd-local://"):
            conn.execute(
                "UPDATE lessons SET details_cached_at = COALESCE(details_cached_at, ?) WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), lesson_id),
            )
            conn.commit()
            return
    page = request_text(lesson["url"])
    data = extract_app_globals(page)
    transcript = "\n".join(challenge.get("content", "") for challenge in data.get("challenges", []))
    now = datetime.now().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM challenges WHERE lesson_id = ?", (lesson_id,))
        for challenge in data.get("challenges", []):
            conn.execute(
                """
                INSERT INTO challenges (lesson_id, remote_id, position, content, audio_url, time_start, time_end)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    lesson_id,
                    challenge.get("id"),
                    challenge.get("position") or 0,
                    challenge.get("content") or "",
                    challenge.get("audioSrc") or "",
                    challenge.get("timeStart"),
                    challenge.get("timeEnd"),
                ),
            )
        conn.execute(
            """
            UPDATE lessons
            SET transcript = ?,
                audio_url = COALESCE(NULLIF(?, ''), audio_url),
                youtube_video_id = ?,
                details_cached_at = ?
            WHERE id = ?
            """,
            (transcript, data.get("audioSrc") or "", data.get("youtubeVideoId") or "", now, lesson_id),
        )
        conn.commit()


def import_details(limit: int | None = None, delay: float = 0.2) -> None:
    ensure_db()
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            """
            SELECT id, title FROM lessons
            WHERE details_cached_at IS NULL
              AND url NOT LIKE 'dd-local://%'
            ORDER BY category_slug, position
            """
        ).fetchall()
    if limit:
        rows = rows[:limit]
    for index, (lesson_id, title) in enumerate(rows, start=1):
        print(f"[{index}/{len(rows)}] {title}")
        try:
            fetch_lesson_details(lesson_id)
        except Exception as exc:
            print(f"  Atlandı: {exc}")
        time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily Dictation katalogunu local SQLite'a aktarır.")
    parser.add_argument("--details", action="store_true", help="Her dersin transcript/challenge detaylarını da çek.")
    parser.add_argument("--limit", type=int, default=None, help="--details için maksimum ders sayısı.")
    parser.add_argument("--delay", type=float, default=0.2, help="--details için istekler arası bekleme saniyesi.")
    args = parser.parse_args()
    import_catalog()
    if args.details:
        import_details(limit=args.limit, delay=args.delay)


if __name__ == "__main__":
    main()
