"""
Download a reproducible sample of NYC 311 service requests created in 2023.

Source: NYC Open Data, dataset erm2-nwe9 (Socrata API).
The full year is ~3.2M rows. We take the first ROWS_PER_DAY rows of EVERY day
(ordered by unique_key), which gives ~290k rows spread evenly over the year
(seasonality and every agency stay represented) and is identical on every run.

Idempotent: if data/raw/nyc311_2023_sample.csv exists, nothing is downloaded.

Run:  python -m project_b.download
"""

from __future__ import annotations

import datetime as dt
import io
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
RAW_FILE = RAW_DIR / "nyc311_2023_sample.csv"
API = "https://data.cityofnewyork.us/resource/erm2-nwe9.csv"
ROWS_PER_DAY = 800

COLUMNS = [
    "unique_key", "created_date", "closed_date", "agency", "agency_name",
    "complaint_type", "descriptor", "location_type", "incident_zip",
    "incident_address", "street_name", "city", "status", "due_date",
    "resolution_description", "resolution_action_updated_date",
    "community_board", "borough", "x_coordinate_state_plane",
    "y_coordinate_state_plane", "open_data_channel_type", "latitude", "longitude",
]


def _fetch_day(day: dt.date) -> pd.DataFrame:
    nxt = day + dt.timedelta(days=1)
    params = {
        "$select": ",".join(COLUMNS),
        "$where": f"created_date >= '{day}T00:00:00' AND created_date < '{nxt}T00:00:00'",
        "$order": "unique_key",
        "$limit": str(ROWS_PER_DAY),
    }
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                # read everything as text: type inference is part of profiling
                return pd.read_csv(io.BytesIO(r.read()), dtype=str, keep_default_na=False)
        except Exception:  # noqa: BLE001 — network hiccups, retry
            time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to download {day}")


def download(force: bool = False) -> Path:
    if RAW_FILE.exists() and not force:
        print(f"[download] {RAW_FILE.name} exists — skipping")
        return RAW_FILE
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    days = [dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(365)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        frames = list(pool.map(_fetch_day, days))
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(RAW_FILE, index=False)
    print(f"[download] wrote {len(df):,} rows -> {RAW_FILE}")
    return RAW_FILE


def load_raw() -> pd.DataFrame:
    """Everything as strings; empty string = missing (like the API delivers it)."""
    return pd.read_csv(download(), dtype=str, keep_default_na=False)


if __name__ == "__main__":
    download()
