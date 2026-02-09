from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, List

import requests


README_PATH = Path("README.md")
STATE_PATH = Path("state.json")
SURAH_META_PATH = Path("data/surah_meta.json")

READING_START = "<!-- READING:START -->"
READING_END = "<!-- READING:END -->"

AYAHADAY_START = "<!-- AYAHADAY:START -->"
AYAHADAY_END = "<!-- AYAHADAY:END -->"


@dataclass(frozen=True)
class SurahMeta:
    number: int
    name_en: str
    ayah_count: int


def load_surah_meta() -> Dict[int, SurahMeta]:
    raw = json.loads(SURAH_META_PATH.read_text(encoding="utf-8"))
    meta: Dict[int, SurahMeta] = {}
    for item in raw:
        s = SurahMeta(
            number=int(item["number"]),
            name_en=str(item["name_en"]),
            ayah_count=int(item["ayah_count"]),
        )
        meta[s.number] = s

    if 2 not in meta or 114 not in meta:
        raise RuntimeError("surah_meta.json must include surah 2 and 114.")
    return meta


def load_state() -> Dict[str, int]:
    if not STATE_PATH.exists():
        return {"surah": 2, "ayah": 1}

    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {"surah": int(state["surah"]), "ayah": int(state["ayah"])}


def save_state(surah: int, ayah: int) -> None:
    STATE_PATH.write_text(
        json.dumps({"surah": surah, "ayah": ayah}, indent=2) + "\n",
        encoding="utf-8",
    )


def normalize_pointer(
    surah: int, ayah: int, meta: Dict[int, SurahMeta]
) -> Tuple[int, int]:
    while True:
        if surah > 114:
            surah = 2
            ayah = 1

        max_ayah = meta[surah].ayah_count
        if ayah <= max_ayah:
            return surah, ayah

        ayah -= max_ayah
        surah += 1


def advance_pointer(
    surah: int,
    ayah: int,
    steps: int,
    meta: Dict[int, SurahMeta],
) -> Tuple[int, int]:
    cur_surah, cur_ayah = normalize_pointer(surah, ayah, meta)
    remaining = steps

    while remaining > 0:
        max_ayah = meta[cur_surah].ayah_count
        available_in_surah = max_ayah - cur_ayah + 1

        take = remaining if remaining <= available_in_surah else available_in_surah
        remaining -= take
        cur_ayah += take

        if cur_ayah > max_ayah:
            cur_surah += 1
            cur_ayah = 1
            cur_surah, cur_ayah = normalize_pointer(cur_surah, cur_ayah, meta)

    return cur_surah, cur_ayah


def compute_daily_reading(
    start_surah: int,
    start_ayah: int,
    count: int,
    meta: Dict[int, SurahMeta],
) -> Tuple[str, Tuple[int, int]]:
    start_surah, start_ayah = normalize_pointer(start_surah, start_ayah, meta)

    end_surah, end_ayah = advance_pointer(start_surah, start_ayah, count - 1, meta)

    start_name = meta[start_surah].name_en
    end_name = meta[end_surah].name_en

    if (start_surah, start_ayah) == (end_surah, end_ayah):
        line = f"Today’s reading: {start_name} {start_surah}:{start_ayah} (1 verse)"
    elif start_surah == end_surah:
        line = f"Today’s reading: {start_name} {start_surah}:{start_ayah}–{end_ayah} ({count} verses)"
    else:
        line = (
            f"Today’s reading: {start_name} {start_surah}:{start_ayah} → "
            f"{end_name} {end_surah}:{end_ayah} ({count} verses)"
        )

    next_surah, next_ayah = advance_pointer(end_surah, end_ayah, 1, meta)
    return line, (next_surah, next_ayah)


def fetch_ayah_of_the_day() -> str:
    url = "https://api.tarteel.io/v1/aad/schedule/"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    j = r.json()

    template = (
        f"<sub>_{j['surahNameEnTrans']}_</sub><br>\n"
        f"**Surah {j['surahNameEn']}** ({j['surah']}: {j['ayah']})\n\n"
        f"> {j['englishTranslation']}\n\n"
        f"— {j['hijriDate']}H"
    )
    return template


def replace_block(
    markdown: str, start_marker: str, end_marker: str, new_content: str
) -> str:
    if start_marker not in markdown or end_marker not in markdown:
        raise RuntimeError(f"Markers not found: {start_marker} / {end_marker}")

    pattern = (
        r"(^" + re.escape(start_marker) + r")"
        r"([\s\S]*?)"
        r"(^" + re.escape(end_marker) + r")"
    )

    def repl(m: re.Match) -> str:
        return f"{m.group(1)}\n{new_content}\n{m.group(3)}"

    new_md, n = re.subn(pattern, repl, markdown, flags=re.MULTILINE)
    if n != 1:
        raise RuntimeError(
            f"Expected exactly 1 block replacement for {start_marker}, got {n}."
        )
    return new_md


def main() -> None:
    meta = load_surah_meta()
    state = load_state()

    reading_line, (next_surah, next_ayah) = compute_daily_reading(
        start_surah=state["surah"],
        start_ayah=state["ayah"],
        count=30,
        meta=meta,
    )

    ayahaday_block = fetch_ayah_of_the_day()

    md = README_PATH.read_text(encoding="utf-8")

    md = replace_block(md, READING_START, READING_END, reading_line)
    md = replace_block(md, AYAHADAY_START, AYAHADAY_END, ayahaday_block)

    README_PATH.write_text(md, encoding="utf-8")

    save_state(next_surah, next_ayah)


if __name__ == "__main__":
    main()
