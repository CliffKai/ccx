from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT = Path("market_data_output")
OUT.mkdir(exist_ok=True)
HOSTS = [
    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
    "https://push2his.eastmoney.com/api/qt/stock/kline/get",
]
SERIES = {
    "上证指数": {"code": "000001.SH", "secid": "1.000001", "kind": "官方指数"},
    "科创50": {"code": "000688.SH", "secid": "1.000688", "kind": "官方指数"},
    "创业板指": {"code": "399006.SZ", "secid": "0.399006", "kind": "官方指数"},
    "CPO概念": {"code": "BK1128", "secid": "90.BK1128", "kind": "东方财富概念板块"},
    "PCB": {"code": "BK0877", "secid": "90.BK0877", "kind": "东方财富概念板块"},
    "存储芯片": {"code": "BK1137", "secid": "90.BK1137", "kind": "东方财富概念板块"},
    "半导体设备": {"code": "BK1326", "secid": "90.BK1326", "kind": "东方财富板块"},
    "半导体材料": {"code": "BK1325", "secid": "90.BK1325", "kind": "东方财富板块"},
}
FIELDS = [
    "名称", "代码", "口径", "日期", "开盘", "最高", "最低", "收盘",
    "供应商涨跌额", "供应商涨跌幅_pct", "复算涨跌额", "复算涨跌幅_pct",
    "涨跌幅复算差异_bp", "年初至今涨跌幅_pct", "成交量", "成交额",
    "振幅_pct", "换手率_pct", "数据源"
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
    "Accept": "application/json,text/plain,*/*",
}


def fetch(secid: str) -> tuple[dict, str]:
    params = {
        "secid": secid,
        "ut": "fa5fd1943c7b386f172d6893dbfba10b",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101", "fqt": "0", "beg": "20251201", "end": "20260717", "lmt": "100000",
    }
    errors = []
    for url in HOSTS:
        for attempt in range(3):
            try:
                r = requests.get(url, params=params, headers=HEADERS, timeout=25)
                r.raise_for_status()
                payload = r.json()
                if payload.get("data") and payload["data"].get("klines"):
                    return payload, url
                errors.append({"url": r.url, "status": r.status_code, "body": r.text[:500]})
            except Exception as exc:
                errors.append({"url": url, "error": repr(exc)})
            time.sleep(1 + attempt)
    raise RuntimeError(json.dumps(errors, ensure_ascii=False))


def parse(name: str, cfg: dict, payload: dict, source_url: str) -> tuple[list[dict], dict]:
    raw = []
    for line in payload["data"]["klines"]:
        p = line.split(",")
        if len(p) < 11:
            continue
        raw.append({
            "名称": name, "代码": cfg["code"], "口径": cfg["kind"], "日期": p[0],
            "开盘": float(p[1]), "收盘": float(p[2]), "最高": float(p[3]), "最低": float(p[4]),
            "成交量": float(p[5]), "成交额": float(p[6]), "振幅_pct": float(p[7]),
            "供应商涨跌幅_pct": float(p[8]), "供应商涨跌额": float(p[9]), "换手率_pct": float(p[10]),
            "数据源": source_url,
        })
    raw.sort(key=lambda x: x["日期"])
    prev_close = None
    last_2025_close = None
    for r in raw:
        if r["日期"] < "2026-01-01":
            last_2025_close = r["收盘"]
        if prev_close is None:
            r["复算涨跌额"] = None
            r["复算涨跌幅_pct"] = None
        else:
            r["复算涨跌额"] = r["收盘"] - prev_close
            r["复算涨跌幅_pct"] = (r["收盘"] / prev_close - 1) * 100
        prev_close = r["收盘"]
    ytd = [r for r in raw if r["日期"] >= "2026-01-01"]
    if not ytd:
        raise RuntimeError("no 2026 rows")
    if last_2025_close is None:
        first = ytd[0]
        last_2025_close = first["收盘"] - first["供应商涨跌额"]
    for r in ytd:
        if r["复算涨跌幅_pct"] is None:
            r["复算涨跌额"] = r["供应商涨跌额"]
            r["复算涨跌幅_pct"] = r["供应商涨跌幅_pct"]
        r["涨跌幅复算差异_bp"] = (r["复算涨跌幅_pct"] - r["供应商涨跌幅_pct"]) * 100
        r["年初至今涨跌幅_pct"] = (r["收盘"] / last_2025_close - 1) * 100
    diffs = [abs(r["涨跌幅复算差异_bp"]) for r in ytd]
    info = {
        "code": cfg["code"], "rows": len(ytd), "first_date": ytd[0]["日期"], "last_date": ytd[-1]["日期"],
        "last_date_ok": ytd[-1]["日期"] == "2026-07-17", "base_close": last_2025_close,
        "max_abs_recalc_diff_bp": max(diffs), "source_name": payload["data"].get("name"),
        "source_code": payload["data"].get("code"), "source_market": payload["data"].get("market"),
    }
    return ytd, info


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    all_rows = []
    meta = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "series": {}, "errors": {}}
    for name, cfg in SERIES.items():
        try:
            payload, source_url = fetch(cfg["secid"])
            rows, info = parse(name, cfg, payload, source_url)
            write_csv(OUT / f"{cfg['code'].replace('.', '_')}_{name}.csv", rows)
            all_rows.extend(rows)
            meta["series"][name] = info
        except Exception as exc:
            meta["errors"][name] = repr(exc)
    all_rows.sort(key=lambda r: (r["日期"], r["名称"]))
    if all_rows:
        write_csv(OUT / "all_2026_ytd_daily.csv", all_rows)
    with (OUT / "validation.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
