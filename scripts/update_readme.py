from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, Tuple

import requests

# Paths
README_PATH = Path("README.md")
STATE_PATH = Path("state.json")
SURAH_META_PATH = Path("data/surah_meta.json")

# Markers
READING_START = "<!-- READING:START -->"
READING_END = "<!-- READING:END -->"
AYAHADAY_START = "<!-- AYAHADAY:START -->"
AYAHADAY_END = "<!-- AYAHADAY:END -->"

# Constants
TOTAL_VERSES = 6229  # Al-Baqarah to An-Nas (excluding Al-Fatihah)
DAILY_VERSES = 30


@dataclass(frozen=True)
class SurahMeta:
    number: int
    name_en: str
    ayah_count: int


def load_surah_meta() -> Dict[int, SurahMeta]:

    raw = json.loads(SURAH_META_PATH.read_text(encoding="utf-8"))
    meta = {
        int(item["number"]): SurahMeta(
            number=int(item["number"]),
            name_en=str(item["name_en"]),
            ayah_count=int(item["ayah_count"]),
        )
        for item in raw
    }

    if 2 not in meta or 114 not in meta:
        raise RuntimeError("surah_meta.json must include surah 2 and 114.")

    return meta


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
            line = f"Today's reading: {start_name} {start_surah}:{start_ayah}–{end_ayah} ({count} verses)"
    else:
        line = f"Today's reading: {start_name} {start_surah}:{start_ayah} → {end_name} {end_surah}:{end_ayah} ({count} verses)"

    next_surah, next_ayah = advance_pointer(end_surah, end_ayah, 1, meta)
    return line, (next_surah, next_ayah)


def create_progress_bar(current: int, total: int, length: int = 10) -> str:

    percent = (current / total) * 100 if total > 0 else 0
    filled = int((current / total) * length) if total > 0 else 0
    bar = "█" * filled + "░" * (length - filled)
    return f"[{bar}] {percent:.1f}% ({current}/{total} verses)"


def fetch_ayah_of_the_day() -> str:

    response = requests.get("https://api.tarteel.io/v1/aad/schedule/", timeout=30)
    response.raise_for_status()
    data = response.json()

    return (
        f"<sub>_{data['surahNameEnTrans']}_</sub><br>\n"
        f"**Surah {data['surahNameEn']}** ({data['surah']}: {data['ayah']})\n\n"
        f"{data['arabicText']}\n\n"
        f"> {data['englishTranslation']}\n\n"
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
    ayahaday_block = fetch_ayah_of_the_day()

    md = README_PATH.read_text(encoding="utf-8")
    md = replace_block(md, READING_START, READING_END, reading_block)
    md = replace_block(md, AYAHADAY_START, AYAHADAY_END, ayahaday_block)
    README_PATH.write_text(md, encoding="utf-8")

    save_state(next_surah, next_ayah, total_verses_read, days_active, today)


if __name__ == "__main__":
    main()
