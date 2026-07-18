from __future__ import annotations

import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests

URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
OUT = Path("market_data_output")
OUT.mkdir(exist_ok=True)

SERIES = {
    "上证指数": {"code": "000001.SH", "secid": "1.000001", "kind": "官方指数"},
    "科创50": {"code": "000688.SH", "secid": "1.000688", "kind": "官方指数"},
    "创业板指": {"code": "399006.SZ", "secid": "0.399006", "kind": "官方指数"},
    "CPO概念": {"code": "BK1128", "secid": "90.BK1128", "kind": "东方财富概念板块"},
    "PCB": {"code": "BK0877", "secid": "90.BK0877", "kind": "东方财富概念板块"},
    "存储芯片": {"code": "BK1137", "secid": "90.BK1137", "kind": "东方财富概念板块"},
    "半导体设备": {"code": "BK1326", "secid": "90.BK1326", "kind": "东方财富行业/概念板块"},
    "半导体材料": {"code": "BK1325", "secid": "90.BK1325", "kind": "东方财富行业/概念板块"},
}

FIELDS1 = "f1,f2,f3,f4,f5,f6"
FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
}


def fetch(secid: str) -> dict:
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": FIELDS1,
        "fields2": FIELDS2,
        "klt": "101",
        "fqt": "0",
        "beg": "20251201",
        "end": "20260717",
        "lmt": "100000",
    }
    last_error = None
    for attempt in range(6):
        try:
            r = requests.get(URL, params=params, headers=HEADERS, timeout=30)
            r.raise_for_status()
            payload = r.json()
            if payload.get("data") and payload["data"].get("klines"):
                return payload
            last_error = RuntimeError(f"empty payload: {payload}")
        except Exception as exc:
            last_error = exc
        time.sleep(2 ** attempt)
    raise RuntimeError(f"failed {secid}: {last_error}")


def parse_rows(name: str, cfg: dict, payload: dict) -> list[dict]:
    rows = []
    for line in payload["data"]["klines"]:
        parts = line.split(",")
        if len(parts) < 11:
            raise RuntimeError(f"unexpected kline {name}: {line}")
        date, open_, close, high, low, volume, amount, amplitude, pct, change, turnover = parts[:11]
        rows.append({
            "名称": name,
            "代码": cfg["code"],
            "口径": cfg["kind"],
            "日期": date,
            "开盘": float(open_),
            "收盘": float(close),
            "最高": float(high),
            "最低": float(low),
            "成交量": float(volume),
            "成交额": float(amount),
            "振幅_pct": float(amplitude),
            "供应商涨跌幅_pct": float(pct),
            "供应商涨跌额": float(change),
            "换手率_pct": float(turnover),
            "数据源": URL,
        })
    rows.sort(key=lambda x: x["日期"])
    prev_close = None
    base_close = None
    for row in rows:
        if row["日期"] < "2026-01-01":
            base_close = row["收盘"]
        if prev_close is None:
            row["复算涨跌额"] = None
            row["复算涨跌幅_pct"] = None
        else:
            row["复算涨跌额"] = row["收盘"] - prev_close
            row["复算涨跌幅_pct"] = (row["收盘"] / prev_close - 1) * 100
        prev_close = row["收盘"]
    if base_close is None:
        raise RuntimeError(f"{name} missing 2025 year-end baseline")
    ytd = [r for r in rows if r["日期"] >= "2026-01-01"]
    if not ytd or ytd[-1]["日期"] != "2026-07-17":
        raise RuntimeError(f"{name} latest date is {ytd[-1]['日期'] if ytd else 'NONE'}, expected 2026-07-17")
    for row in ytd:
        row["年初至今涨跌幅_pct"] = (row["收盘"] / base_close - 1) * 100
        row["涨跌幅复算差异_bp"] = None if row["复算涨跌幅_pct"] is None else (row["复算涨跌幅_pct"] - row["供应商涨跌幅_pct"]) * 100
    return ytd


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = [
        "名称", "代码", "口径", "日期", "开盘", "最高", "最低", "收盘",
        "供应商涨跌额", "供应商涨跌幅_pct", "复算涨跌额", "复算涨跌幅_pct",
        "涨跌幅复算差异_bp", "年初至今涨跌幅_pct", "成交量", "成交额",
        "振幅_pct", "换手率_pct", "数据源"
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    all_rows = []
    meta = {"generated_at_utc": datetime.utcnow().isoformat() + "Z", "series": {}}
    for name, cfg in SERIES.items():
        payload = fetch(cfg["secid"])
        rows = parse_rows(name, cfg, payload)
        all_rows.extend(rows)
        safe = cfg["code"].replace(".", "_")
        write_csv(OUT / f"{safe}_{name}.csv", rows)
        diffs = [abs(r["涨跌幅复算差异_bp"]) for r in rows if r["涨跌幅复算差异_bp"] is not None]
        meta["series"][name] = {
            "code": cfg["code"],
            "rows": len(rows),
            "first_date": rows[0]["日期"],
            "last_date": rows[-1]["日期"],
            "max_abs_recalc_diff_bp": max(diffs) if diffs else None,
            "source_name": payload["data"].get("name"),
            "source_code": payload["data"].get("code"),
        }
    all_rows.sort(key=lambda r: (r["日期"], r["名称"]))
    write_csv(OUT / "all_2026_ytd_daily.csv", all_rows)
    with (OUT / "validation.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
