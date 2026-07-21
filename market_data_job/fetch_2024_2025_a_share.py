#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch complete 2024 and 2025 daily data for seven requested A-share series.

Outputs are raw/derived CSV and JSON files. No interpolation or synthetic rows.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT = Path("market_data_job/output_2024_2025")
OUT.mkdir(parents=True, exist_ok=True)

BASE = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
PROXY = "https://r.jina.ai/http://push2his.eastmoney.com/api/qt/stock/kline/get"
FIELDS = [
    "日期", "名称", "代码", "secid", "年份", "昨收", "开盘", "最高", "最低", "收盘",
    "涨跌额", "日涨跌幅(%)", "成交量", "成交额(元)", "振幅(%)", "换手率(%)",
    "年初至今涨跌幅(%)", "上年末归一化=100", "数据源"
]

@dataclass(frozen=True)
class Spec:
    name: str
    code: str
    secids: tuple[str, ...]

SPECS = [
    Spec("上证指数", "000001", ("1.000001",)),
    Spec("科创50指数", "000688", ("1.000688",)),
    Spec("创业板指", "399006", ("0.399006",)),
    Spec("CPO概念", "BK1128", ("90.BK1128",)),
    Spec("PCB概念", "BK0877", ("90.BK0877",)),
    Spec("存储芯片概念", "BK1137", ("90.BK1137",)),
    Spec("半导体材料设备指数", "931743", ("2.931743", "1.931743", "0.931743")),
]


def request_text(url: str, attempts: int = 4) -> str:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://quote.eastmoney.com/",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            last = exc
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"request failed: {url}; last={last!r}")


def extract_payload(text: str) -> dict[str, Any]:
    text = text.lstrip("\ufeff").strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and obj.get("data"):
            return obj
    except Exception:
        pass

    decoder = json.JSONDecoder()
    starts = []
    for marker in ('{"rc"', '{"data"', '{\n  "rc"', '{\n  "data"'):
        p = text.find(marker)
        if p >= 0:
            starts.append(p)
    starts.extend(i for i, ch in enumerate(text) if ch == "{")
    seen = set()
    for pos in starts:
        if pos in seen:
            continue
        seen.add(pos)
        try:
            obj, _ = decoder.raw_decode(text[pos:])
        except Exception:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("data"), dict) and obj["data"].get("klines"):
            return obj
    raise RuntimeError("could not locate Eastmoney JSON payload")


def make_url(endpoint: str, secid: str) -> str:
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "0",
        "beg": "20231201",
        "end": "20251231",
        "lmt": "1000",
        "_": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
    }
    return endpoint + "?" + urllib.parse.urlencode(params)


def normalize_date(s: str) -> str:
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10]


def num(x: str) -> float | int | None:
    x = x.strip()
    if not x or x == "-":
        return None
    try:
        v = float(x)
        return int(v) if v.is_integer() else v
    except ValueError:
        return None


def fetch_series(spec: Spec) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    for secid in spec.secids:
        for endpoint in (PROXY, BASE):
            url = make_url(endpoint, secid)
            try:
                text = request_text(url)
                payload = extract_payload(text)
                data = payload.get("data") or {}
                klines = data.get("klines") or []
                if not klines:
                    raise RuntimeError("empty klines")
                parsed: list[dict[str, Any]] = []
                for line in klines:
                    parts = line.split(",")
                    if len(parts) < 11:
                        continue
                    parsed.append({
                        "date": normalize_date(parts[0]),
                        "open": num(parts[1]),
                        "close": num(parts[2]),
                        "high": num(parts[3]),
                        "low": num(parts[4]),
                        "volume": num(parts[5]),
                        "amount": num(parts[6]),
                        "amplitude": num(parts[7]),
                        "pct": num(parts[8]),
                        "change": num(parts[9]),
                        "turnover": num(parts[10]),
                    })
                parsed.sort(key=lambda r: r["date"])
                if not parsed:
                    raise RuntimeError("no parseable rows")
                meta = {
                    "requested_name": spec.name,
                    "api_name": data.get("name"),
                    "api_code": data.get("code"),
                    "secid": secid,
                    "source_url": url,
                    "raw_count": len(parsed),
                    "raw_first": parsed[0]["date"],
                    "raw_last": parsed[-1]["date"],
                }
                return parsed, meta, payload
            except Exception as exc:
                errors.append(f"{secid} via {endpoint}: {exc!r}")
    raise RuntimeError(spec.name + " failed; " + " | ".join(errors))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] = FIELDS) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def wide_csv(path: Path, dates: list[str], series_rows: dict[str, list[dict[str, Any]]], value_field: str) -> None:
    names = [s.name for s in SPECS]
    maps = {name: {r["日期"]: r[value_field] for r in rows} for name, rows in series_rows.items()}
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["日期"] + names)
        for d in dates:
            w.writerow([d] + [maps[n].get(d) for n in names])


def main() -> None:
    all_rows: list[dict[str, Any]] = []
    by_year: dict[int, dict[str, list[dict[str, Any]]]] = {2024: {}, 2025: {}}
    metadata: dict[str, Any] = {}
    raw_payloads: dict[str, Any] = {}

    for spec in SPECS:
        print(f"Fetching {spec.name}...", flush=True)
        raw, meta, payload = fetch_series(spec)
        metadata[spec.name] = meta
        raw_payloads[spec.name] = payload
        close_by_date = {r["date"]: r["close"] for r in raw if r["close"] is not None}

        for year in (2024, 2025):
            baseline_candidates = [(d, c) for d, c in close_by_date.items() if d < f"{year}-01-01"]
            if not baseline_candidates:
                raise RuntimeError(f"{spec.name}: missing baseline for {year}")
            baseline_date, baseline_close = max(baseline_candidates, key=lambda x: x[0])
            raw_year = [r for r in raw if f"{year}-01-01" <= r["date"] <= f"{year}-12-31"]
            if not raw_year:
                raise RuntimeError(f"{spec.name}: no rows for {year}")
            out_rows: list[dict[str, Any]] = []
            previous_close = baseline_close
            for r in raw_year:
                close = r["close"]
                if close is None:
                    raise RuntimeError(f"{spec.name} {r['date']}: missing close")
                row = {
                    "日期": r["date"],
                    "名称": spec.name,
                    "代码": spec.code,
                    "secid": meta["secid"],
                    "年份": year,
                    "昨收": previous_close,
                    "开盘": r["open"],
                    "最高": r["high"],
                    "最低": r["low"],
                    "收盘": close,
                    "涨跌额": r["change"],
                    "日涨跌幅(%)": r["pct"],
                    "成交量": r["volume"],
                    "成交额(元)": r["amount"],
                    "振幅(%)": r["amplitude"],
                    "换手率(%)": r["turnover"],
                    "年初至今涨跌幅(%)": round((float(close) / float(baseline_close) - 1) * 100, 8),
                    "上年末归一化=100": round(float(close) / float(baseline_close) * 100, 8),
                    "数据源": meta["source_url"],
                }
                if row["最高"] is not None and row["最低"] is not None and row["最高"] < row["最低"]:
                    raise RuntimeError(f"{spec.name} {r['date']}: high < low")
                out_rows.append(row)
                previous_close = close
            by_year[year][spec.name] = out_rows
            all_rows.extend(out_rows)
            metadata[spec.name][f"baseline_{year}"] = {"date": baseline_date, "close": baseline_close}
            metadata[spec.name][f"count_{year}"] = len(out_rows)
            metadata[spec.name][f"first_{year}"] = out_rows[0]["日期"]
            metadata[spec.name][f"last_{year}"] = out_rows[-1]["日期"]
            write_csv(OUT / f"{year}_{spec.name}.csv", out_rows)
        write_csv(OUT / f"2024_2025_{spec.name}.csv", by_year[2024][spec.name] + by_year[2025][spec.name])

    validation: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_source": "Eastmoney historical K-line via Jina AI reader proxy",
        "series_count": len(SPECS),
        "years": {},
    }
    for year in (2024, 2025):
        reference = [r["日期"] for r in by_year[year]["上证指数"]]
        ref_set = set(reference)
        yv: dict[str, Any] = {"reference_count": len(reference), "series": {}}
        for spec in SPECS:
            rows = by_year[year][spec.name]
            dates = [r["日期"] for r in rows]
            duplicates = sorted({d for d in dates if dates.count(d) > 1})
            ds = set(dates)
            item = {
                "count": len(rows),
                "first": dates[0],
                "last": dates[-1],
                "missing_vs_reference": sorted(ref_set - ds),
                "extra_vs_reference": sorted(ds - ref_set),
                "duplicate_dates": duplicates,
                "strictly_increasing": dates == sorted(dates) and len(dates) == len(set(dates)),
            }
            item["complete"] = not item["missing_vs_reference"] and not item["extra_vs_reference"] and not duplicates and item["strictly_increasing"]
            yv["series"][spec.name] = item
        yv["all_complete"] = all(v["complete"] for v in yv["series"].values())
        validation["years"][str(year)] = yv
        wide_csv(OUT / f"{year}_收盘宽表.csv", reference, by_year[year], "收盘")
        wide_csv(OUT / f"{year}_涨跌幅宽表.csv", reference, by_year[year], "日涨跌幅(%)")
        wide_csv(OUT / f"{year}_归一化宽表.csv", reference, by_year[year], "上年末归一化=100")

    validation["all_complete"] = all(validation["years"][str(y)]["all_complete"] for y in (2024, 2025))
    all_rows.sort(key=lambda r: (r["年份"], r["日期"], [s.name for s in SPECS].index(r["名称"])))
    write_csv(OUT / "all_series_long_2024_2025.csv", all_rows)
    (OUT / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "raw_payloads.json").write_text(json.dumps(raw_payloads, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2), flush=True)
    if not validation["all_complete"]:
        raise SystemExit("Completeness validation failed")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(1)
