from pathlib import Path
import json
import re
import requests
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "external"
OUT.mkdir(parents=True, exist_ok=True)

FRED_SERIES = {
    "DFII10": "real_yield_10y",
    "DGS2": "yield_2y",
    "DGS10": "yield_10y",
    "T10YIE": "breakeven_10y",
    "DTWEXBGS": "broad_usd",
    "VIXCLS": "vix",
    "BAMLH0A0HYM2": "hy_oas",
    "DEXCHUS": "usd_cny",
}


def download_fred():
    for series_id, name in FRED_SERIES.items():
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        path = OUT / f"fred_{series_id}.csv"
        path.write_bytes(r.content)

        df = pd.read_csv(path)
        df.columns = ["observation_date", name]
        df["observation_date"] = pd.to_datetime(df["observation_date"])
        df[name] = pd.to_numeric(df[name], errors="coerce")

        # Conservative first version: do not allow same-calendar-day FRED value.
        df["available_date"] = df["observation_date"] + pd.Timedelta(days=1)
        df[["observation_date", "available_date", name]].to_csv(
            OUT / f"{name}.csv", index=False
        )
        path.unlink(missing_ok=True)
        print("FRED:", series_id, "->", name)


def _find_col(columns, fragments):
    norm = {c.lower(): c for c in columns}
    for lc, original in norm.items():
        if all(fragment in lc for fragment in fragments):
            return original
    return None


def download_cftc_gold():
    url = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
    params = {
        "$limit": 50000,
        "$where": "upper(commodity_name)='GOLD'",
        "$order": "report_date_as_yyyy_mm_dd ASC",
    }
    r = requests.get(url, params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError("CFTC query returned no GOLD rows.")

    df = pd.DataFrame(rows)
    date_col = _find_col(df.columns, ["report_date"])
    long_col = _find_col(df.columns, ["m_money", "long"])
    short_col = _find_col(df.columns, ["m_money", "short"])
    oi_col = _find_col(df.columns, ["open_interest", "all"])

    missing = [
        name for name, col in [
            ("report_date", date_col),
            ("managed_money_long", long_col),
            ("managed_money_short", short_col),
        ] if col is None
    ]
    if missing:
        raise RuntimeError(
            f"Could not identify CFTC columns: {missing}. Available columns: {list(df.columns)}"
        )

    out = pd.DataFrame({
        "observation_date": pd.to_datetime(df[date_col]),
        "cftc_mm_long": pd.to_numeric(df[long_col], errors="coerce"),
        "cftc_mm_short": pd.to_numeric(df[short_col], errors="coerce"),
    })
    out["cftc_mm_net"] = out["cftc_mm_long"] - out["cftc_mm_short"]
    if oi_col is not None:
        out["cftc_open_interest"] = pd.to_numeric(df[oi_col], errors="coerce")

    # COT reflects Tuesday positions and is normally published later in the week.
    # +3 calendar days is a conservative approximation for v1; holidays can differ.
    out["available_date"] = out["observation_date"] + pd.Timedelta(days=3)
    out.to_csv(OUT / "cftc_gold_managed_money.csv", index=False)
    print("CFTC: GOLD managed money downloaded.")


if __name__ == "__main__":
    download_fred()
    download_cftc_gold()
