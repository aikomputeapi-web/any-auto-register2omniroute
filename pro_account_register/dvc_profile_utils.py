from __future__ import annotations

"""Utilities for selecting candidate profiles from the pointclickcare dataset."""

from dataclasses import dataclass
from pathlib import Path
import json
import random
import re
from typing import Iterable


MALE_FIRST_NAMES = {
    "adam", "alan", "andrew", "anthony", "arthur", "ben", "benjamin", "bernard",
    "brian", "bruce", "calvin", "carlos", "charles", "christopher", "daniel",
    "david", "dean", "donald", "douglas", "edward", "edwin", "eugene", "frank",
    "fred", "george", "gerald", "glen", "gregory", "harold", "henry", "ian",
    "james", "jeff", "jeffrey", "jerome", "jim", "jimmy", "joe", "john",
    "johnny", "jose", "joseph", "joshua", "juan", "keith", "kenneth", "kevin",
    "larry", "leonard", "lester", "liam", "louis", "mario", "mark", "martin",
    "matthew", "michael", "miguel", "mohamed", "nathan", "nicholas", "oscar",
    "paul", "peter", "philip", "randy", "raul", "raymond", "richard", "robert",
    "roger", "ronald", "samuel", "scott", "sean", "shawn", "stephen", "steven",
    "thomas", "timothy", "victor", "vincent", "walter", "william",
}


@dataclass(frozen=True)
class ProfileRecord:
    line_no: int
    first_name: str
    last_name: str
    address: str
    city: str
    state: str
    zip_code: str
    dob: str
    ssn: str

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def normalized_first_name(self) -> str:
        return re.sub(r"[^a-z]", "", self.first_name.lower())


def parse_profile_line(line: str, line_no: int) -> ProfileRecord:
    parts = [part.strip() for part in str(line or "").split("|")]
    if len(parts) < 8:
        raise ValueError(f"Unexpected dataset format on line {line_no}: {line!r}")
    return ProfileRecord(
        line_no=line_no,
        first_name=parts[0],
        last_name=parts[1],
        address=parts[2],
        city=parts[3],
        state=parts[4],
        zip_code=parts[5],
        dob=parts[6],
        ssn=parts[7],
    )


def load_profiles(dataset_path: str | Path) -> list[ProfileRecord]:
    path = Path(dataset_path)
    if not path.exists():
        raise FileNotFoundError(f"Dataset not found: {path}")

    records: list[ProfileRecord] = []
    for idx, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        records.append(parse_profile_line(line, idx))
    return records


def is_male_profile(profile: ProfileRecord) -> bool:
    first = profile.normalized_first_name
    if not first:
        return False
    return first in MALE_FIRST_NAMES


def filter_male_profiles(profiles: Iterable[ProfileRecord]) -> list[ProfileRecord]:
    return [p for p in profiles if is_male_profile(p)]


def load_used_lines(used_path: str | Path) -> set[int]:
    path = Path(used_path)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {int(x) for x in data if str(x).isdigit()}
        if isinstance(data, dict) and "used_lines" in data and isinstance(data["used_lines"], list):
            return {int(x) for x in data["used_lines"] if str(x).isdigit()}
    except Exception:
        pass
    return set()


def save_used_line(used_path: str | Path, line_no: int) -> None:
    """Add a single line to the used lines set and persist."""
    used = load_used_lines(used_path)
    used.add(line_no)
    save_used_lines(used_path, used)


def save_used_lines(used_path: str | Path, used_lines: Iterable[int]) -> None:
    path = Path(used_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "used_lines": sorted({int(x) for x in used_lines}),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def choose_random_unused_male_profile(
    dataset_path: str | Path,
    used_path: str | Path = "registration_results/dvc_used_lines.json",
    seed: int | None = None,
) -> ProfileRecord:
    profiles = filter_male_profiles(load_profiles(dataset_path))
    if not profiles:
        raise RuntimeError("No male profiles found in dataset")

    used = load_used_lines(used_path)
    candidates = [p for p in profiles if p.line_no not in used]
    if not candidates:
        raise RuntimeError("No unused male profiles remaining")

    rng = random.Random(seed)
    chosen = rng.choice(candidates)
    used.add(chosen.line_no)
    save_used_lines(used_path, used)
    return chosen
