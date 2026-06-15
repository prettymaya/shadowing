from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from importer import DB_PATH, ensure_db


ROOT = Path(__file__).parent
STATIC_DATA = ROOT / "static" / "data"
LESSONS_DIR = STATIC_DATA / "lessons"


def row_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def main() -> None:
    ensure_db()
    STATIC_DATA.mkdir(parents=True, exist_ok=True)
    LESSONS_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        categories = [
            row_dict(row)
            for row in conn.execute(
                """
                SELECT slug, name, levels, description, lesson_count, position
                FROM categories
                ORDER BY position, name
                """
            )
        ]
        lessons = [
            row_dict(row)
            for row in conn.execute(
                """
                SELECT l.id, l.category_slug, c.name AS category_name, l.position, l.title,
                       l.subtitle, l.level, l.parts, l.url, l.audio_url, l.transcript,
                       l.details_cached_at
                FROM lessons l
                JOIN categories c ON c.slug = l.category_slug
                ORDER BY c.position, l.position, l.title
                """
            )
        ]
        for lesson in lessons:
            challenges = [
                row_dict(row)
                for row in conn.execute(
                    """
                    SELECT position, content, audio_url, time_start, time_end
                    FROM challenges
                    WHERE lesson_id = ?
                    ORDER BY position
                    """,
                    (lesson["id"],),
                )
            ]
            if challenges or lesson["transcript"]:
                detail = {**lesson, "challenges": challenges}
                (LESSONS_DIR / f"{lesson['id']}.json").write_text(
                    json.dumps(detail, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8",
                )

    catalog_lessons = [
        {
            key: lesson[key]
            for key in (
                "id",
                "category_slug",
                "category_name",
                "position",
                "title",
                "subtitle",
                "level",
                "parts",
                "url",
                "audio_url",
                "details_cached_at",
            )
        }
        for lesson in lessons
    ]
    (STATIC_DATA / "catalog.json").write_text(
        json.dumps({"categories": categories, "lessons": catalog_lessons}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Export tamam: {len(categories)} kategori, {len(lessons)} ders")


if __name__ == "__main__":
    main()
