from __future__ import annotations

import argparse
import csv
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

SERIES = {
    "SSE": {"name": "上证指数", "code": "000001.SH", "secid": "1.000001", "kind": "官方指数"},
    "STAR50": {"name": "科创50", "code": "000688.SH", "secid": "1.000688", "kind": "官方指数"},
    "CHINEXT": {"name": "创业板指", "code": "399006.SZ", "secid": "0.399006", "kind": "官方指数"},
    "CPO": {"name": "CPO概念", "code": "BK1128", "secid": "90.BK1128", "kind": "东方财富概念板块"},
    "PCB": {"name": "PCB", "code": "BK0877", "secid": "90.BK0877", "kind": "东方财富概念板块"},
    "MEMORY": {"name": "存储芯片", "code": "BK1137", "secid": "90.BK1137", "kind": "东方财富概念板块"},
    "SEMI_EQUIP": {"name": "半导体设备", "code": "BK1326", "secid": "90.BK1326", "kind": "东方财富板块"},
    "SEMI_MAT": {"name": "半导体材料", "code": "BK1325", "secid": "90.BK1325", "kind": "东方财富板块"},
}

FIELDS = [
    "年度", "名称", "代码", "口径", "日期", "开盘", "最高", "最低", "收盘",
    "供应商涨跌额", "供应商涨跌幅_pct", "复算涨跌额", "复算涨跌幅_pct",
    "涨跌幅复算差异_bp", "年初至今涨跌幅_pct", "成交量", "成交额", "振幅_pct",
    "换手率_pct", "数据源", "抓取时间_UTC"
]

PARAMS = {
    "ut": "fa5fd1943c7b386f172d6893dbfba10b",
    "fields1": "f1,f2,f3,f4,f5,f6",
    "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
    "klt": "101",
    "fqt": "0",
    "beg": "20231201",
    "end": "20251231",
    "lmt": "100000",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
    "Connection": "close",
}


def request_node(node: str, secid: str):
    url = f"https://{node}.push2his.eastmoney.com/api/qt/stock/kline/get"
    params = dict(PARAMS, secid=secid)
    try:
        response = requests.get(url, params=params, headers=HEADERS, timeout=10)
        response.raise_for_status()
        payload = response.json()
        if payload.get("data") and payload["data"].get("klines"):
            return payload, url
    except Exception:
        return None
    return None


def fetch(secid: str):
    candidates = [str(i) for i in range(1, 100)]
    random.shuffle(candidates)
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = [pool.submit(request_node, node, secid) for node in candidates]
        for future in as_completed(futures):
            result = future.result()
            if result:
                return result
    # final direct-host retries
    for _ in range(4):
        try:
            url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            response = requests.get(url, params=dict(PARAMS, secid=secid), headers=HEADERS, timeout=12)
            response.raise_for_status()
            payload = response.json()
            if payload.get("data") and payload["data"].get("klines"):
                return payload, url
        except Exception:
            pass
    raise RuntimeError("all Eastmoney history nodes failed")


def parse_raw(key: str, cfg: dict, payload: dict, source_url: str):
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for line in payload["data"]["klines"]:
        parts = line.split(",")
        if len(parts) < 11:
            continue
        rows.append({
            "名称": cfg["name"], "代码": cfg["code"], "口径": cfg["kind"],
            "日期": parts[0], "开盘": float(parts[1]), "收盘": float(parts[2]),
            "最高": float(parts[3]), "最低": float(parts[4]), "成交量": float(parts[5]),
            "成交额": float(parts[6]), "振幅_pct": float(parts[7]),
            "供应商涨跌幅_pct": float(parts[8]), "供应商涨跌额": float(parts[9]),
            "换手率_pct": float(parts[10]), "数据源": source_url, "抓取时间_UTC": fetched_at,
        })
    rows.sort(key=lambda row: row["日期"])
    if not rows:
        raise RuntimeError("empty kline data")
    return rows


def build_year(raw_rows: list[dict], year: int):
    prior = [row for row in raw_rows if row["日期"] < f"{year}-01-01"]
    current = [row.copy() for row in raw_rows if f"{year}-01-01" <= row["日期"] <= f"{year}-12-31"]
    if not current:
        raise RuntimeError(f"no rows for {year}")
    base_close = prior[-1]["收盘"] if prior else current[0]["收盘"] - current[0]["供应商涨跌额"]
    previous_close = base_close
    for row in current:
        row["年度"] = year
        row["复算涨跌额"] = row["收盘"] - previous_close
        row["复算涨跌幅_pct"] = (row["收盘"] / previous_close - 1) * 100
        row["涨跌幅复算差异_bp"] = (row["复算涨跌幅_pct"] - row["供应商涨跌幅_pct"]) * 100
        row["年初至今涨跌幅_pct"] = (row["收盘"] / base_close - 1) * 100
        previous_close = row["收盘"]
    info = {
        "year": year,
        "rows": len(current),
        "first_date": current[0]["日期"],
        "last_date": current[-1]["日期"],
        "base_close_previous_year_end": base_close,
        "latest_close": current[-1]["收盘"],
        "year_return_pct": current[-1]["年初至今涨跌幅_pct"],
        "max_abs_recalc_diff_bp": max(abs(row["涨跌幅复算差异_bp"]) for row in current),
    }
    return current, info


def write_csv(path: Path, rows: list[dict]):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", required=True, choices=SERIES.keys())
    parser.add_argument("--attempt", default="0")
    args = parser.parse_args()

    cfg = SERIES[args.series]
    output = Path("job_output")
    output.mkdir(parents=True, exist_ok=True)
    meta = {
        "series_key": args.series,
        "attempt": args.attempt,
        "name": cfg["name"],
        "code": cfg["code"],
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "years": {},
    }
    try:
        payload, source_url = fetch(cfg["secid"])
        raw_rows = parse_raw(args.series, cfg, payload, source_url)
        for year in (2024, 2025):
            rows, info = build_year(raw_rows, year)
            filename = f"{year}_{cfg['code'].replace('.', '_')}_{cfg['name']}.csv"
            write_csv(output / filename, rows)
            meta["years"][str(year)] = info
        meta["source_name"] = payload["data"].get("name")
        meta["source_code"] = payload["data"].get("code")
        meta["source_url"] = source_url
        meta["success"] = True
    except Exception as exc:
        meta["error"] = repr(exc)
    (output / "validation.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
