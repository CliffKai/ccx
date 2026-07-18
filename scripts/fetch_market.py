from __future__ import annotations
import csv, json, os, random, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import requests

SERIES = {
    "BK1137": {"name": "存储芯片", "code": "BK1137", "secid": "90.BK1137", "kind": "东方财富概念板块"},
    "BK1326": {"name": "半导体设备", "code": "BK1326", "secid": "90.BK1326", "kind": "东方财富板块"},
    "BK1325": {"name": "半导体材料", "code": "BK1325", "secid": "90.BK1325", "kind": "东方财富板块"},
}
FIELDS = ["名称","代码","口径","日期","开盘","最高","最低","收盘","供应商涨跌额","供应商涨跌幅_pct","复算涨跌额","复算涨跌幅_pct","涨跌幅复算差异_bp","年初至今涨跌幅_pct","成交量","成交额","振幅_pct","换手率_pct","数据源"]
PARAMS = {"ut":"fa5fd1943c7b386f172d6893dbfba10b","fields1":"f1,f2,f3,f4,f5,f6","fields2":"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61","klt":"101","fqt":"0","beg":"20251201","end":"20260717","lmt":"100000"}


def request_node(node: int, secid: str, nonce: str):
    url = f"https://{node}.push2his.eastmoney.com/api/qt/stock/kline/get"
    headers = {
        "User-Agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17 Safari/605.1.15",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
        ]),
        "Referer": "https://quote.eastmoney.com/",
        "Accept": "application/json,text/plain,*/*",
        "Connection": "close",
    }
    params = dict(PARAMS, secid=secid, cb=f"jQuery{nonce}", _=nonce)
    try:
        r = requests.get(url, params=params, headers=headers, timeout=12)
        r.raise_for_status()
        text = r.text.strip()
        if text.startswith("jQuery"):
            text = text[text.find("(")+1:text.rfind(")")]
        payload = json.loads(text)
        if payload.get("data") and payload["data"].get("klines"):
            return payload, url
    except Exception:
        return None
    return None


def fetch(secid: str, shard: int):
    nodes = list(range(1, 100))
    random.Random(20260718 + shard * 1009).shuffle(nodes)
    nonce = f"{2026071800000 + shard}{random.randint(1000,9999)}"
    with ThreadPoolExecutor(max_workers=24) as pool:
        futures = [pool.submit(request_node, n, secid, nonce + str(n)) for n in nodes]
        for future in as_completed(futures):
            result = future.result()
            if result:
                return result
    raise RuntimeError("all numbered nodes failed")


def parse(cfg, payload, source_url):
    rows = []
    for line in payload["data"]["klines"]:
        p = line.split(",")
        if len(p) < 11:
            continue
        rows.append({
            "名称": cfg["name"], "代码": cfg["code"], "口径": cfg["kind"], "日期": p[0],
            "开盘": float(p[1]), "收盘": float(p[2]), "最高": float(p[3]), "最低": float(p[4]),
            "成交量": float(p[5]), "成交额": float(p[6]), "振幅_pct": float(p[7]),
            "供应商涨跌幅_pct": float(p[8]), "供应商涨跌额": float(p[9]), "换手率_pct": float(p[10]),
            "数据源": source_url,
        })
    rows.sort(key=lambda x: x["日期"])
    prev = None
    base = None
    for row in rows:
        if row["日期"] < "2026-01-01":
            base = row["收盘"]
        row["复算涨跌额"] = None if prev is None else row["收盘"] - prev
        row["复算涨跌幅_pct"] = None if prev is None else (row["收盘"] / prev - 1) * 100
        prev = row["收盘"]
    ytd = [r for r in rows if r["日期"] >= "2026-01-01"]
    if not ytd:
        raise RuntimeError("no 2026 rows")
    if base is None:
        base = ytd[0]["收盘"] - ytd[0]["供应商涨跌额"]
    for row in ytd:
        if row["复算涨跌幅_pct"] is None:
            row["复算涨跌额"] = row["供应商涨跌额"]
            row["复算涨跌幅_pct"] = row["供应商涨跌幅_pct"]
        row["涨跌幅复算差异_bp"] = (row["复算涨跌幅_pct"] - row["供应商涨跌幅_pct"]) * 100
        row["年初至今涨跌幅_pct"] = (row["收盘"] / base - 1) * 100
    info = {
        "code": cfg["code"], "rows": len(ytd), "first_date": ytd[0]["日期"], "last_date": ytd[-1]["日期"],
        "last_date_ok": ytd[-1]["日期"] == "2026-07-17", "base_close": base,
        "max_abs_recalc_diff_bp": max(abs(r["涨跌幅复算差异_bp"]) for r in ytd),
        "source_name": payload["data"].get("name"), "source_code": payload["data"].get("code"), "node": source_url,
    }
    if len(ytd) != 129 or not info["last_date_ok"]:
        raise RuntimeError(f"incomplete series: {info}")
    return ytd, info


def write_csv(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def probe():
    target = os.environ["TARGET"]
    shard = int(os.environ.get("SHARD", "0"))
    cfg = SERIES[target]
    out = Path("attempt_output")
    out.mkdir(exist_ok=True)
    meta = {"target": target, "shard": shard, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "success": False}
    try:
        payload, url = fetch(cfg["secid"], shard)
        rows, info = parse(cfg, payload, url)
        write_csv(out / f"{target}_{cfg['name']}.csv", rows)
        meta.update({"success": True, "info": info})
    except Exception as exc:
        meta["error"] = repr(exc)
    with (out / f"{target}_{shard}.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(json.dumps(meta, ensure_ascii=False, indent=2))


def aggregate():
    attempts = Path("attempts")
    output = Path("market_data_output")
    output.mkdir(exist_ok=True)
    summary = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "series": {}, "errors": {}}
    for target, cfg in SERIES.items():
        candidates = []
        for meta_path in attempts.rglob(f"{target}_*.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("success"):
                    candidates.append((meta, meta_path))
            except Exception:
                pass
        if not candidates:
            summary["errors"][cfg["name"]] = "no successful probe artifact"
            continue
        meta, meta_path = candidates[0]
        csvs = list(meta_path.parent.glob(f"{target}_*.csv"))
        if not csvs:
            summary["errors"][cfg["name"]] = "successful metadata without CSV"
            continue
        dest = output / f"{cfg['code']}_{cfg['name']}.csv"
        dest.write_bytes(csvs[0].read_bytes())
        summary["series"][cfg["name"]] = meta["info"]
    existing = list(output.glob("*.csv"))
    individual = [p for p in existing if p.name != "all_2026_ytd_daily.csv"]
    all_rows = []
    for path in individual:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            all_rows.extend(list(csv.DictReader(f)))
    all_rows.sort(key=lambda r: (r["日期"], r["名称"]))
    if all_rows:
        write_csv(output / "all_2026_ytd_daily.csv", all_rows)
    summary["individual_csv_count"] = len(individual)
    summary["all_rows"] = len(all_rows)
    with (output / "final_missing_validation.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "aggregate":
        aggregate()
    else:
        probe()
