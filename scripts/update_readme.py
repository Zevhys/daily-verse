from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Tuple, Any

import requests

README_PATH = Path("README.md")
STATE_PATH = Path("state.json")
SURAH_META_PATH = Path("data/surah_meta.json")

READING_START = "<!-- READING:START -->"
READING_END = "<!-- READING:END -->"
AYAHADAY_START = "<!-- AYAHADAY:START -->"
AYAHADAY_END = "<!-- AYAHADAY:END -->"

TOTAL_VERSES = 6229
DAILY_VERSES = 30


@dataclass(frozen=True)
class SurahMeta:
    number: int
    name_en: str
    ayah_count: int
    revelation: str


QURAN_CLOUD_TRANSLIT_URL = (
    "https://cdn.jsdelivr.net/npm/quran-cloud@1.0.0/dist/quran_transliteration.json"
)

_TRANSLIT_CACHE: Any = None


def load_quran_cloud_transliteration() -> dict:
    global _TRANSLIT_CACHE
    if _TRANSLIT_CACHE is not None:
        return _TRANSLIT_CACHE

    resp = requests.get(QURAN_CLOUD_TRANSLIT_URL, timeout=30)
    resp.raise_for_status()
    _TRANSLIT_CACHE = resp.json()
    return _TRANSLIT_CACHE


def fetch_transliteration_from_quran_cloud(surah: int, ayah: int) -> str:
    data = load_quran_cloud_transliteration()

    if isinstance(data, dict):
        chapters = data.get("chapters")
        if chapters is None:
            raise RuntimeError(
                "Unexpected transliteration JSON: missing 'chapters' key"
            )
    elif isinstance(data, list):
        chapters = data
    else:
        raise RuntimeError(f"Unexpected transliteration JSON type: {type(data)}")

    try:
        chapter = chapters[surah - 1]
    except Exception as e:
        raise RuntimeError(f"Invalid surah index for transliteration: {surah}") from e

    verses = chapter.get("verses") if isinstance(chapter, dict) else None
    if verses is None:
        raise RuntimeError("Unexpected chapter format: missing 'verses'")

    try:
        verse = verses[ayah - 1]
    except Exception as e:
        raise RuntimeError(
            f"Invalid ayah index for transliteration: {surah}:{ayah}"
        ) from e

    translit = ""
    if isinstance(verse, dict):
        translit = str(verse.get("transliteration") or "").strip()
    elif isinstance(verse, str):
        translit = verse.strip()

    if not translit:
        raise RuntimeError(f"Transliteration missing for {surah}:{ayah}")

    return translit


def load_surah_meta() -> Dict[int, SurahMeta]:
    raw = json.loads(SURAH_META_PATH.read_text(encoding="utf-8"))
    meta = {
        int(item["number"]): SurahMeta(
            number=int(item["number"]),
            name_en=str(item["name_en"]),
            ayah_count=int(item["ayah_count"]),
            revelation=str(item.get("revelation", "unknown")).lower(),
        )
        for item in raw
    }

    if 2 not in meta or 114 not in meta:
        raise RuntimeError("surah_meta.json must include surah 2 and 114.")

    return meta


def revelation_place_label(revelation: str) -> str:
    r = (revelation or "").lower()
    if r in {"madinah", "madaniyah", "medinan"}:
        return "Madinah"
    if r in {"makkah", "makkiyah", "meccan"}:
        return "Makkah"
    return "Unknown"


def load_state() -> Dict:
    if not STATE_PATH.exists():
        return {
            "surah": 2,
            "ayah": 1,
            "total_verses_read": 0,
            "days_active": 0,
            "last_update_date": None,
        }

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {
        "surah": int(state.get("surah", 2)),
        "ayah": int(state.get("ayah", 1)),
        "total_verses_read": int(state.get("total_verses_read", 0)),
        "days_active": int(state.get("days_active", 0)),
        "last_update_date": state.get("last_update_date"),
    }


def save_state(
    surah: int,
    ayah: int,
    total_verses_read: int,
    days_active: int,
    last_update_date: str,
) -> None:
    STATE_PATH.write_text(
        json.dumps(
            {
                "surah": surah,
                "ayah": ayah,
                "total_verses_read": total_verses_read,
                "days_active": days_active,
                "last_update_date": last_update_date,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def normalize_pointer(
    surah: int, ayah: int, meta: Dict[int, SurahMeta]
) -> Tuple[int, int]:
    while True:
        if surah > 114:
            surah, ayah = 2, 1

        if ayah <= meta[surah].ayah_count:
            return surah, ayah

        ayah -= meta[surah].ayah_count
        surah += 1


def advance_pointer(
    surah: int, ayah: int, steps: int, meta: Dict[int, SurahMeta]
) -> Tuple[int, int]:
    cur_surah, cur_ayah = normalize_pointer(surah, ayah, meta)
    remaining = steps

    while remaining > 0:
        max_ayah = meta[cur_surah].ayah_count
        available = max_ayah - cur_ayah + 1
        take = min(remaining, available)

        remaining -= take
        cur_ayah += take

        if cur_ayah > max_ayah:
            cur_surah += 1
            cur_ayah = 1
            cur_surah, cur_ayah = normalize_pointer(cur_surah, cur_ayah, meta)

    return cur_surah, cur_ayah


def compute_daily_reading(
    start_surah: int, start_ayah: int, count: int, meta: Dict[int, SurahMeta]
) -> Tuple[str, Tuple[int, int]]:
    start_surah, start_ayah = normalize_pointer(start_surah, start_ayah, meta)
    end_surah, end_ayah = advance_pointer(start_surah, start_ayah, count - 1, meta)

    start_name = meta[start_surah].name_en
    end_name = meta[end_surah].name_en

    if start_surah == end_surah:
        if start_ayah == end_ayah:
            line = f"Today's reading: {start_name} {start_surah}:{start_ayah} (1 verse)"
        else:
            line = (
                f"Today's reading: {start_name} {start_surah}:{start_ayah}–{end_ayah} "
                f"({count} verses)"
            )
    else:
        line = (
            f"Today's reading: {start_name} {start_surah}:{start_ayah} → "
            f"{end_name} {end_surah}:{end_ayah} ({count} verses)"
        )

    next_surah, next_ayah = advance_pointer(end_surah, end_ayah, 1, meta)
    return line, (next_surah, next_ayah)


def create_progress_bar(current: int, total: int, length: int = 10) -> str:
    percent = (current / total) * 100 if total > 0 else 0
    filled = int((current / total) * length) if total > 0 else 0
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.1f}% ({current}/{total} verses)"


def fetch_ayah_of_the_day(meta: Dict[int, SurahMeta]) -> str:
    response = requests.get("https://api.tarteel.io/v1/aad/schedule/", timeout=30)
    response.raise_for_status()
    data = response.json()

    surah = int(data["surah"])
    ayah = int(data["ayah"])

    ayah_count = meta[surah].ayah_count
    place = revelation_place_label(meta[surah].revelation)

    transliteration = fetch_transliteration_from_quran_cloud(surah, ayah)
    source_url = f"https://quran.com/{surah}/{ayah}"

    bismillah = (
        '<div align="center">\n\nبِسْمِ ٱللَّٰهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ\n\n</div>\n\n'
        if surah != 9
        else ""
    )

    return (
        f"<sub>_{data['surahNameEnTrans']} • {place} • {ayah_count} Ayat_</sub><br>\n"
        f"**Surah {data['surahNameEn']}** ({surah}:{ayah})\n\n"
        f"{bismillah}"
        f"{data['arabicText']}\n\n"
        f"> _Bismillahir Rahmanir Rahim_\n"
        f">\n"
        f"> _{transliteration}_\n"
        f">\n"
        f"> _*In the name of Allah, the Most Gracious, the Most Merciful*_\n"
        f">\n"
        f"> {data['englishTranslation']}\n\n"
        f"🔗 Source: {source_url}\n\n"
        f"— {data['hijriDate']}H"
    )


def replace_block(
    markdown: str, start_marker: str, end_marker: str, new_content: str
) -> str:
    if start_marker not in markdown or end_marker not in markdown:
        raise RuntimeError(f"Markers not found: {start_marker} / {end_marker}")

    pattern = rf"(^{re.escape(start_marker)})([\s\S]*?)(^{re.escape(end_marker)})"
    new_md, count = re.subn(
        pattern, rf"\1\n{new_content}\n\3", markdown, flags=re.MULTILINE
    )

    if count != 1:
        raise RuntimeError(
            f"Expected exactly 1 replacement for {start_marker}, got {count}."
        )

    return new_md


def main() -> None:
    meta = load_surah_meta()
    state = load_state()
    today = date.today().isoformat()

    days_active = state["days_active"]
    if state["last_update_date"] != today:
        days_active += 1

    reading_line, (next_surah, next_ayah) = compute_daily_reading(
        state["surah"], state["ayah"], DAILY_VERSES, meta
    )

    total_verses_read = state["total_verses_read"] + DAILY_VERSES
    progress_bar = create_progress_bar(total_verses_read, TOTAL_VERSES)
    stats_line = (
        f"📊 **Stats:** {total_verses_read} verses read | {days_active} days active"
    )

    reading_block = f"{reading_line}\n\n{progress_bar}\n\n{stats_line}"
    ayahaday_block = fetch_ayah_of_the_day(meta)

    md = README_PATH.read_text(encoding="utf-8")
    md = replace_block(md, READING_START, READING_END, reading_block)
    md = replace_block(md, AYAHADAY_START, AYAHADAY_END, ayahaday_block)
    README_PATH.write_text(md, encoding="utf-8")

    save_state(next_surah, next_ayah, total_verses_read, days_active, today)


if __name__ == "__main__":
    main()
