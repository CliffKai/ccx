#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch complete 2026 YTD daily data for seven requested A-share series.

No interpolation or synthetic market rows are used. Direct Eastmoney requests are
supplemented with Jina Reader proxy requests because some cloud IP ranges are
blocked by the upstream host.
"""
from __future__ import annotations

import csv
import json
import math
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAW_BEGIN = "20251201"
OUTPUT_BEGIN = "20260101"
END = "20260717"
OUT_DIR = Path(__file__).resolve().parent / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FIELDS1 = "f1,f2,f3,f4,f5,f6"
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
BASE_PATH = "push2his.eastmoney.com/api/qt/stock/kline/get"

@dataclass(frozen=True)
class Series:
    name: str
    code: str
    secids: tuple[str, ...]
    definition: str

SERIES = [
    Series("上证指数", "000001.SH", ("1.000001",), "上海证券综合指数"),
    Series("科创50指数", "000688.SH", ("1.000688",), "上证科创板50成份指数"),
    Series("创业板指", "399006.SZ", ("0.399006",), "创业板指数"),
    Series("CPO概念", "BK1128", ("90.BK1128",), "东方财富CPO概念板块指数"),
    Series("PCB概念", "BK0877", ("90.BK0877",), "东方财富PCB概念板块指数"),
    Series("存储芯片概念", "BK1137", ("90.BK1137",), "东方财富存储芯片概念板块指数"),
    Series("半导体材料设备指数", "931743.CSI", ("2.931743", "1.931743", "0.931743"), "中证半导体材料设备主题指数"),
]

HEADERS = [
    "日期", "名称", "代码", "secid", "昨收", "开盘", "最高", "最低", "收盘",
    "涨跌额", "日涨跌幅(%)", "成交量", "成交额(元)", "振幅(%)", "换手率(%)",
    "年初至今涨跌幅(%)", "2025年末归一化=100", "数据源"
]


def parse_json_bytes(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", errors="replace").lstrip("\ufeff")
    # Direct API responses are plain JSON. Jina Reader may wrap the payload in
    # Markdown metadata or code fences; find and decode the first valid object.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    starts = [m.start() for m in re.finditer(r"\{", text)]
    decoder = json.JSONDecoder()
    for pos in starts:
        try:
            obj, _ = decoder.raw_decode(text[pos:])
            if isinstance(obj, dict) and ("data" in obj or "rc" in obj):
                return obj
        except Exception:
            continue
    raise ValueError("no Eastmoney JSON object in response: " + text[:500].replace("\n", " "))


def fetch_json(url: str, retries: int = 3) -> dict[str, Any]:
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                    "Accept": "application/json,text/plain,text/markdown,*/*",
                    "Referer": "https://quote.eastmoney.com/",
                    "Connection": "close",
                    "X-Return-Format": "text",
                },
            )
            with urllib.request.urlopen(req, timeout=35) as r:
                raw = r.read()
            return parse_json_bytes(raw)
        except Exception as exc:
            last = exc
            time.sleep(2 ** i)
    raise RuntimeError(f"request failed: {url}; last={last!r}")


def candidate_urls(secid: str) -> list[str]:
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": FIELDS1,
        "fields2": FIELDS2,
        "klt": "101",
        "fqt": "0",
        "beg": RAW_BEGIN,
        "end": END,
        "lmt": "1000",
    }
    query = urllib.parse.urlencode(params)
    target_http = f"http://{BASE_PATH}?{query}"
    target_https = f"https://{BASE_PATH}?{query}"
    return [
        "https://r.jina.ai/" + target_http,
        "https://r.jina.ai/" + target_https,
        target_https,
        target_http,
    ]


def number(s: Any) -> float | int | None:
    if s in ("", "-", "null", "None", None):
        return None
    x = float(s)
    return int(x) if math.isfinite(x) and x.is_integer() else x


def fetch_series(spec: Series) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    errors: list[str] = []
    for secid in spec.secids:
        for url in candidate_urls(secid):
            try:
                obj = fetch_json(url)
                data = obj.get("data")
                if not data or not data.get("klines"):
                    raise ValueError(f"empty data: rc={obj.get('rc')}, data={data!r}")
                parsed: list[dict[str, Any]] = []
                for line in data["klines"]:
                    p = line.split(",")
                    if len(p) < 11:
                        raise ValueError(f"bad kline row: {line}")
                    parsed.append({
                        "date": p[0], "open": number(p[1]), "close": number(p[2]),
                        "high": number(p[3]), "low": number(p[4]), "volume": number(p[5]),
                        "amount": number(p[6]), "amplitude": number(p[7]), "pct_change": number(p[8]),
                        "change": number(p[9]), "turnover": number(p[10]),
                    })
                parsed.sort(key=lambda x: x["date"])
                meta = {
                    "requested_name": spec.name, "api_name": data.get("name"),
                    "requested_code": spec.code, "api_code": data.get("code"),
                    "secid": secid, "definition": spec.definition,
                    "source_url": url, "records_raw": len(parsed),
                }
                return parsed, meta
            except Exception as exc:
                errors.append(f"{secid} via {url}: {exc!r}")
    raise RuntimeError(spec.name + " failed; " + " | ".join(errors))


def build_rows(spec: Series, raw: list[dict[str, Any]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    previous_close: float | int | None = None
    prev_by_date: dict[str, float | int | None] = {}
    for r in raw:
        prev_by_date[r["date"]] = previous_close
        previous_close = r["close"]
    baseline = [r for r in raw if r["date"] < OUTPUT_BEGIN and r["close"] is not None]
    if not baseline:
        raise RuntimeError(f"{spec.name}: missing 2025 year-end baseline")
    base_close = float(baseline[-1]["close"])
    rows: list[dict[str, Any]] = []
    for r in raw:
        if not (OUTPUT_BEGIN <= r["date"] <= END):
            continue
        close = float(r["close"])
        pre_close = prev_by_date[r["date"]]
        if pre_close is None and r["change"] is not None:
            pre_close = close - float(r["change"])
        rows.append({
            "日期": r["date"], "名称": spec.name, "代码": spec.code, "secid": meta["secid"],
            "昨收": pre_close, "开盘": r["open"], "最高": r["high"], "最低": r["low"], "收盘": r["close"],
            "涨跌额": r["change"], "日涨跌幅(%)": r["pct_change"], "成交量": r["volume"],
            "成交额(元)": r["amount"], "振幅(%)": r["amplitude"], "换手率(%)": r["turnover"],
            "年初至今涨跌幅(%)": round((close / base_close - 1) * 100, 8),
            "2025年末归一化=100": round(close / base_close * 100, 8), "数据源": meta["source_url"],
        })
    meta.update({
        "baseline_date": baseline[-1]["date"], "baseline_close": base_close,
        "records_2026": len(rows), "first_date_2026": rows[0]["日期"] if rows else None,
        "last_date_2026": rows[-1]["日期"] if rows else None,
    })
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    all_rows: list[dict[str, Any]] = []
    metadata: list[dict[str, Any]] = []
    rows_by_name: dict[str, list[dict[str, Any]]] = {}
    for spec in SERIES:
        print(f"Fetching {spec.name}...", flush=True)
        raw, meta = fetch_series(spec)
        rows = build_rows(spec, raw, meta)
        if not rows:
            raise RuntimeError(f"{spec.name}: no 2026 rows")
        rows_by_name[spec.name] = rows
        metadata.append(meta)
        all_rows.extend(rows)
        write_csv(OUT_DIR / f"{spec.name}.csv", rows)
        print(f"  {len(rows)} rows, {rows[0]['日期']}..{rows[-1]['日期']}, secid={meta['secid']}, source={meta['source_url']}")

    reference_dates = [r["日期"] for r in rows_by_name["上证指数"]]
    ref_set = set(reference_dates)
    validation: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requested_period": [OUTPUT_BEGIN, END], "reference_series": "上证指数",
        "reference_count": len(reference_dates), "series": {}, "all_complete": True,
    }
    for spec in SERIES:
        dates = [r["日期"] for r in rows_by_name[spec.name]]
        missing, extra = sorted(ref_set - set(dates)), sorted(set(dates) - ref_set)
        duplicates = sorted({d for d in dates if dates.count(d) > 1})
        ok = not missing and not extra and not duplicates and dates == sorted(dates)
        validation["series"][spec.name] = {
            "count": len(dates), "first": dates[0], "last": dates[-1],
            "missing_vs_reference": missing, "extra_vs_reference": extra,
            "duplicate_dates": duplicates, "complete": ok,
        }
        validation["all_complete"] = validation["all_complete"] and ok

    expected = {
        "上证指数": (3764.1547, -3.0460),
        "科创50指数": (1715.4044, -7.1186),
        "创业板指": (3428.6298, -7.1450),
    }
    validation["cross_check_20260717"] = {}
    for name, (exp_close, exp_pct) in expected.items():
        row = next(r for r in rows_by_name[name] if r["日期"] == END)
        close_ok = abs(float(row["收盘"]) - exp_close) < 0.0002
        pct_ok = abs(float(row["日涨跌幅(%)"]) - exp_pct) < 0.02
        validation["cross_check_20260717"][name] = {
            "eastmoney_close": row["收盘"], "tushare_close": exp_close, "close_match": close_ok,
            "eastmoney_pct": row["日涨跌幅(%)"], "tushare_pct": exp_pct, "pct_match": pct_ok,
        }
        validation["all_complete"] = validation["all_complete"] and close_ok and pct_ok

    all_rows.sort(key=lambda r: (r["日期"], r["名称"]))
    write_csv(OUT_DIR / "all_series_long.csv", all_rows)
    close_maps = {name: {r["日期"]: r["收盘"] for r in rows} for name, rows in rows_by_name.items()}
    wide_headers = ["日期"] + [s.name for s in SERIES]
    with (OUT_DIR / "close_wide.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=wide_headers)
        w.writeheader()
        for d in reference_dates:
            row = {"日期": d}
            row.update({s.name: close_maps[s.name].get(d) for s in SERIES})
            w.writerow(row)

    payload = {"metadata": metadata, "validation": validation, "headers": HEADERS, "rows": all_rows}
    (OUT_DIR / "all_series.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    if not validation["all_complete"]:
        raise SystemExit("Completeness/cross-check validation failed")

if __name__ == "__main__":
    main()
