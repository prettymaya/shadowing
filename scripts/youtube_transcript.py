from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import yt_dlp


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "private_data" / "youtube_transcripts"


def clean_text(value: str) -> str:
    value = html.unescape(str(value or ""))
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_url(value: str) -> str:
    value = value.strip()
    if re.fullmatch(r"[\w-]{11}", value):
        return f"https://www.youtube.com/watch?v={value}"
    return value


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 ShadowingLocal/1.0"})
    with urlopen(req, timeout=30) as res:
        return res.read().decode("utf-8", errors="replace")


def parse_json3(raw: str) -> list[dict]:
    data = json.loads(raw)
    cues = []
    for event in data.get("events", []):
        text = clean_text("".join(seg.get("utf8", "") for seg in event.get("segs", [])))
        if not text:
            continue
        start = (event.get("tStartMs") or 0) / 1000
        end = start + ((event.get("dDurationMs") or 0) / 1000)
        cues.append({"start": start, "end": end, "text": text})
    return cues


def parse_xml(raw: str) -> list[dict]:
    matches = re.findall(r"<text\b([^>]*)>(.*?)</text>", raw, flags=re.S)
    cues = []
    for index, (attrs, body) in enumerate(matches):
        start_match = re.search(r'start="([^"]+)"', attrs)
        dur_match = re.search(r'dur="([^"]+)"', attrs)
        start = float(start_match.group(1)) if start_match else float(index)
        duration = float(dur_match.group(1)) if dur_match else 0.0
        text = clean_text(body)
        if text:
            cues.append({"start": start, "end": start + duration, "text": text})
    return cues


def parse_vtt(raw: str) -> list[dict]:
    cues = []
    for index, block in enumerate(re.split(r"\n{2,}", raw.replace("\r", ""))):
        lines = [line for line in block.split("\n") if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), -1)
        if timing_index == -1:
            continue
        text = clean_text(" ".join(lines[timing_index + 1 :]))
        if text:
            cues.append({"start": float(index), "end": float(index), "text": text})
    return cues


def parse_subtitle(raw: str, ext: str) -> list[dict]:
    if ext == "json3" or raw.lstrip().startswith("{"):
        return parse_json3(raw)
    if ext in {"srv1", "srv2", "srv3", "ttml"} or raw.lstrip().startswith("<"):
        return parse_xml(raw)
    return parse_vtt(raw)


def choose_track(info: dict, languages: list[str]) -> tuple[str, dict] | None:
    sources = []
    for source_name in ("subtitles", "automatic_captions"):
        tracks = info.get(source_name) or {}
        for language in languages:
            if language in tracks:
                sources.append((language, tracks[language]))
        if sources:
            break
    if not sources:
        return None
    language, formats = sources[0]
    preferred = sorted(
        formats,
        key=lambda item: {"json3": 0, "srv3": 1, "vtt": 2}.get(item.get("ext"), 9),
    )
    return language, preferred[0]


def write_outputs(info: dict, language: str, cues: list[dict], out_dir: Path) -> None:
    video_id = info.get("id") or "youtube"
    title = clean_text(info.get("title") or video_id)
    safe_title = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-")[:80] or video_id
    base = out_dir / f"{video_id}-{safe_title}"
    out_dir.mkdir(parents=True, exist_ok=True)
    text = "\n".join(cue["text"] for cue in cues)
    (base.with_suffix(".txt")).write_text(text + "\n", encoding="utf-8")
    (base.with_suffix(".json")).write_text(
        json.dumps(
            {
                "id": video_id,
                "title": title,
                "url": info.get("webpage_url"),
                "language": language,
                "parts": len(cues),
                "transcript": text,
                "challenges": [
                    {
                        "position": index,
                        "content": cue["text"],
                        "audio_url": "",
                        "time_start": cue["start"],
                        "time_end": cue["end"],
                    }
                    for index, cue in enumerate(cues, start=1)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(base.with_suffix(".txt"))
    print(base.with_suffix(".json"))


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube videosundan sadece transcript/altyazi cek.")
    parser.add_argument("url_or_id", help="YouTube URL veya 11 karakterlik video ID.")
    parser.add_argument("--lang", default="es,en", help="Virgullu dil onceligi. Ornek: es,en")
    parser.add_argument("--cookies-from-browser", default="", help="Gerekirse chrome/safari/firefox.")
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
    }
    if args.cookies_from_browser:
        ydl_opts["cookiesfrombrowser"] = (args.cookies_from_browser,)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(normalize_url(args.url_or_id), download=False)

    picked = choose_track(info, [item.strip() for item in args.lang.split(",") if item.strip()])
    if not picked:
        raise SystemExit("Bu video icin subtitle/auto-caption bulunamadi.")
    language, track = picked
    raw = fetch_text(track["url"])
    cues = parse_subtitle(raw, track.get("ext") or "")
    if not cues:
        raise SystemExit("Subtitle bulundu ama parse edilemedi.")
    write_outputs(info, language, cues, args.out_dir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
