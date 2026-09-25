"""The academic catalog: the values a learner profile may use (GET /v1/catalog/academic).

Deliberately small, and made to grow:

- **Codes are permanent.** A code is never deleted, reused or given another meaning. A value
  that should no longer be offered is marked `deprecated`: it is still listed (so a profile
  that has it can show it), still accepted while a profile keeps it unchanged, and no longer
  accepted as a new choice.
- **Every change to this data bumps CATALOG_VERSION.** Clients cache the catalog by version
  (ETag); tests/test_learning.py fails when the content changes and the version does not.
- Names are English display names. The tutor prompt uses them; clients may show their own
  translations, keyed by code.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass

CATALOG_VERSION = 1


@dataclass(frozen=True)
class Entry:
    code: str
    name: str
    deprecated: bool = False


def _entries(*pairs: tuple[str, str]) -> tuple[Entry, ...]:
    return tuple(Entry(code, name) for code, name in pairs)


GRADES = _entries(
    *((f"class_{n}", f"Class {n}") for n in range(6, 13)),
    ("undergraduate", "Undergraduate"),
    ("other", "Other"),
)

BOARDS = _entries(
    ("cbse", "CBSE"),
    ("icse", "ICSE / ISC"),
    ("state", "State board"),
    ("nios", "NIOS"),
    ("ib", "IB"),
    ("cambridge", "Cambridge (IGCSE / A Level)"),
    ("other", "Other"),
)

# Only meaningful with board = "state".
BOARD_STATES = _entries(
    ("andhra_pradesh", "Andhra Pradesh"),
    ("arunachal_pradesh", "Arunachal Pradesh"),
    ("assam", "Assam"),
    ("bihar", "Bihar"),
    ("chhattisgarh", "Chhattisgarh"),
    ("goa", "Goa"),
    ("gujarat", "Gujarat"),
    ("haryana", "Haryana"),
    ("himachal_pradesh", "Himachal Pradesh"),
    ("jharkhand", "Jharkhand"),
    ("karnataka", "Karnataka"),
    ("kerala", "Kerala"),
    ("madhya_pradesh", "Madhya Pradesh"),
    ("maharashtra", "Maharashtra"),
    ("manipur", "Manipur"),
    ("meghalaya", "Meghalaya"),
    ("mizoram", "Mizoram"),
    ("nagaland", "Nagaland"),
    ("odisha", "Odisha"),
    ("punjab", "Punjab"),
    ("rajasthan", "Rajasthan"),
    ("sikkim", "Sikkim"),
    ("tamil_nadu", "Tamil Nadu"),
    ("telangana", "Telangana"),
    ("tripura", "Tripura"),
    ("uttar_pradesh", "Uttar Pradesh"),
    ("uttarakhand", "Uttarakhand"),
    ("west_bengal", "West Bengal"),
    ("andaman_nicobar", "Andaman and Nicobar Islands"),
    ("chandigarh", "Chandigarh"),
    ("dadra_nagar_haveli_daman_diu", "Dadra and Nagar Haveli and Daman and Diu"),
    ("delhi", "Delhi"),
    ("jammu_kashmir", "Jammu and Kashmir"),
    ("ladakh", "Ladakh"),
    ("lakshadweep", "Lakshadweep"),
    ("puducherry", "Puducherry"),
)

# The language the student is taught in at school.
MEDIUMS = _entries(
    ("english", "English"),
    ("hindi", "Hindi"),
    ("assamese", "Assamese"),
    ("bengali", "Bengali"),
    ("gujarati", "Gujarati"),
    ("kannada", "Kannada"),
    ("malayalam", "Malayalam"),
    ("marathi", "Marathi"),
    ("odia", "Odia"),
    ("punjabi", "Punjabi"),
    ("tamil", "Tamil"),
    ("telugu", "Telugu"),
    ("urdu", "Urdu"),
    ("other", "Other"),
)

ACADEMIC_YEARS = _entries(
    ("2025_26", "2025–26"),
    ("2026_27", "2026–27"),
    ("2027_28", "2027–28"),
)

SUBJECTS = _entries(
    ("mathematics", "Mathematics"),
    ("science", "Science"),
    ("physics", "Physics"),
    ("chemistry", "Chemistry"),
    ("biology", "Biology"),
    ("english", "English"),
    ("hindi", "Hindi"),
    ("sanskrit", "Sanskrit"),
    ("social_science", "Social Science"),
    ("history", "History"),
    ("geography", "Geography"),
    ("political_science", "Political Science"),
    ("economics", "Economics"),
    ("accountancy", "Accountancy"),
    ("business_studies", "Business Studies"),
    ("computer_science", "Computer Science"),
    ("environmental_studies", "Environmental Studies"),
    ("psychology", "Psychology"),
)

# Catalog list per learner-profile field (and "subjects" for the subject list).
LISTS: dict[str, tuple[Entry, ...]] = {
    "grades": GRADES,
    "boards": BOARDS,
    "boardStates": BOARD_STATES,
    "mediums": MEDIUMS,
    "academicYears": ACADEMIC_YEARS,
    "subjects": SUBJECTS,
}
FIELD_LISTS = {
    "grade": GRADES,
    "board": BOARDS,
    "board_state": BOARD_STATES,
    "medium": MEDIUMS,
    "academic_year": ACADEMIC_YEARS,
}

_BY_CODE = {id(entries): {entry.code: entry for entry in entries} for entries in LISTS.values()}


def lookup(entries: tuple[Entry, ...], code: str | None) -> Entry | None:
    return _BY_CODE[id(entries)].get(code) if code else None


def as_json() -> dict:
    return {"version": CATALOG_VERSION, **{key: [asdict(e) for e in entries] for key, entries in LISTS.items()}}


def content_hash() -> str:
    """SHA-256 of the catalog's data (not its version): what the version must follow."""
    data = {key: [asdict(e) for e in entries] for key, entries in LISTS.items()}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


ETAG = f'"academic-{CATALOG_VERSION}-{content_hash()[:16]}"'
