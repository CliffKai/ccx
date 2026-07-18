#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import csv, json, math, re, time, urllib.parse, urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RAW_BEGIN, OUTPUT_BEGIN, END = "20251201", "20260101", "20260717"
END_ISO = "2026-07-17"
OUT = Path(__file__).resolve().parent / "output"
OUT.mkdir(parents=True, exist_ok=True)
F1 = "f1,f2,f3,f4,f5,f6"
F2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
API_PATH = "push2his.eastmoney.com/api/qt/stock/kline/get"

@dataclass(frozen=True)
class Spec:
    name: str
    code: str
    secids: tuple[str, ...]
    definition: str

SPECS = [
    Spec("上证指数", "000001.SH", ("1.000001",), "上海证券综合指数"),
    Spec("科创50指数", "000688.SH", ("1.000688",), "上证科创板50成份指数"),
    Spec("创业板指", "399006.SZ", ("0.399006",), "创业板指数"),
    Spec("CPO概念", "BK1128", ("90.BK1128",), "东方财富CPO概念板块指数"),
    Spec("PCB概念", "BK0877", ("90.BK0877",), "东方财富PCB概念板块指数"),
    Spec("存储芯片概念", "BK1137", ("90.BK1137",), "东方财富存储芯片概念板块指数"),
    Spec("半导体材料设备指数", "931743.CSI", ("2.931743", "1.931743", "0.931743"), "中证半导体材料设备主题指数"),
]

COLS = ["日期","名称","代码","secid","昨收","开盘","最高","最低","收盘","涨跌额","日涨跌幅(%)","成交量","成交额(元)","振幅(%)","换手率(%)","年初至今涨跌幅(%)","2025年末归一化=100","数据源"]


def iso(key: str) -> str:
    return f"{key[:4]}-{key[4:6]}-{key[6:8]}"


def num(x: Any):
    if x in (None, "", "-", "null", "None"): return None
    v = float(x)
    return int(v) if math.isfinite(v) and v.is_integer() else v


def decode_json(raw: bytes) -> dict[str, Any]:
    text = raw.decode("utf-8", "replace").lstrip("\ufeff")
    try:
        o = json.loads(text)
        if isinstance(o, dict): return o
    except Exception: pass
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text):
        try:
            o, _ = dec.raw_decode(text[m.start():])
            if isinstance(o, dict) and ("data" in o or "rc" in o): return o
        except Exception: pass
    raise ValueError("No API JSON: " + text[:400].replace("\n", " "))


def get(url: str) -> dict[str, Any]:
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent":"Mozilla/5.0 AppleWebKit/537.36 Chrome/124 Safari/537.36",
                "Accept":"application/json,text/plain,text/markdown,*/*",
                "Referer":"https://quote.eastmoney.com/", "Connection":"close"})
            with urllib.request.urlopen(req, timeout=35) as r: return decode_json(r.read())
        except Exception as e:
            last = e; time.sleep(2 ** attempt)
    raise RuntimeError(f"{last!r}")


def urls(secid: str) -> list[str]:
    q = urllib.parse.urlencode({"secid":secid,"ut":"fa5fd1943c7b386f172d6893dbfba10b","fields1":F1,"fields2":F2,"klt":"101","fqt":"0","beg":RAW_BEGIN,"end":END,"lmt":"1000","_":"20260718140000"})
    http = f"http://{API_PATH}?{q}"; https = f"https://{API_PATH}?{q}"
    return ["https://r.jina.ai/"+http, "https://r.jina.ai/"+https, https, http]


def fetch(spec: Spec):
    errors=[]
    for sid in spec.secids:
        for url in urls(sid):
            try:
                data = get(url).get("data")
                if not data or not data.get("klines"): raise ValueError(f"empty {data!r}")
                rows=[]
                for line in data["klines"]:
                    p=line.split(",")
                    if len(p)<11: raise ValueError(line)
                    rows.append({"key":p[0].replace("-",""),"open":num(p[1]),"close":num(p[2]),"high":num(p[3]),"low":num(p[4]),"volume":num(p[5]),"amount":num(p[6]),"amplitude":num(p[7]),"pct":num(p[8]),"change":num(p[9]),"turnover":num(p[10])})
                rows.sort(key=lambda r:r["key"])
                print(f"  API {data.get('name')} {data.get('code')}: {len(rows)} raw rows, {iso(rows[0]['key'])}..{iso(rows[-1]['key'])}, {url}", flush=True)
                return rows, {"requested_name":spec.name,"api_name":data.get("name"),"requested_code":spec.code,"api_code":data.get("code"),"secid":sid,"definition":spec.definition,"source_url":url,"records_raw":len(rows)}
            except Exception as e: errors.append(f"{sid} {url}: {e!r}")
    raise RuntimeError(spec.name+" failed; "+" | ".join(errors))


def transform(spec: Spec, raw, meta):
    prev=None; prevmap={}
    for r in raw: prevmap[r["key"]]=prev; prev=r["close"]
    base=[r for r in raw if r["key"]<OUTPUT_BEGIN and r["close"] is not None]
    if not base: raise RuntimeError(spec.name+": no 2025 baseline")
    b=float(base[-1]["close"]); out=[]
    for r in raw:
        if not (OUTPUT_BEGIN<=r["key"]<=END): continue
        c=float(r["close"]); pc=prevmap[r["key"]]
        if pc is None and r["change"] is not None: pc=c-float(r["change"])
        out.append({"日期":iso(r["key"]),"名称":spec.name,"代码":spec.code,"secid":meta["secid"],"昨收":pc,"开盘":r["open"],"最高":r["high"],"最低":r["low"],"收盘":r["close"],"涨跌额":r["change"],"日涨跌幅(%)":r["pct"],"成交量":r["volume"],"成交额(元)":r["amount"],"振幅(%)":r["amplitude"],"换手率(%)":r["turnover"],"年初至今涨跌幅(%)":round((c/b-1)*100,8),"2025年末归一化=100":round(c/b*100,8),"数据源":meta["source_url"]})
    meta.update({"baseline_date":iso(base[-1]["key"]),"baseline_close":b,"records_2026":len(out),"first_date_2026":out[0]["日期"] if out else None,"last_date_2026":out[-1]["日期"] if out else None})
    return out


def write_csv(path, rows, fields=COLS):
    with open(path,"w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)


def main():
    by={}; metas=[]; allrows=[]
    for s in SPECS:
        print("Fetching "+s.name+"...", flush=True)
        raw,m=fetch(s); rows=transform(s,raw,m)
        if not rows: raise RuntimeError(s.name+": no 2026 rows after normalization")
        by[s.name]=rows; metas.append(m); allrows.extend(rows); write_csv(OUT/(s.name+".csv"),rows)
        print(f"  OUTPUT {len(rows)} rows, {rows[0]['日期']}..{rows[-1]['日期']}",flush=True)

    ref=[r["日期"] for r in by["上证指数"]]; refset=set(ref)
    val={"generated_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds"),"requested_period":[iso(OUTPUT_BEGIN),iso(END)],"reference_series":"上证指数","reference_count":len(ref),"series":{},"all_complete":True}
    for s in SPECS:
        ds=[r["日期"] for r in by[s.name]]; miss=sorted(refset-set(ds)); extra=sorted(set(ds)-refset); dup=sorted({d for d in ds if ds.count(d)>1}); ok=(not miss and not extra and not dup and ds==sorted(ds))
        val["series"][s.name]={"count":len(ds),"first":ds[0],"last":ds[-1],"missing_vs_reference":miss,"extra_vs_reference":extra,"duplicate_dates":dup,"complete":ok}; val["all_complete"] &= ok
    checks={"上证指数":(3764.1547,-3.0460),"科创50指数":(1715.4044,-7.1186),"创业板指":(3428.6298,-7.1450)}; val["cross_check_20260717"]={}
    for name,(ec,ep) in checks.items():
        r=next(x for x in by[name] if x["日期"]==END_ISO); co=abs(float(r["收盘"])-ec)<0.0002; po=abs(float(r["日涨跌幅(%)"])-ep)<0.02
        val["cross_check_20260717"][name]={"eastmoney_close":r["收盘"],"tushare_close":ec,"close_match":co,"eastmoney_pct":r["日涨跌幅(%)"],"tushare_pct":ep,"pct_match":po}; val["all_complete"] &= co and po
    allrows.sort(key=lambda r:(r["日期"],r["名称"])); write_csv(OUT/"all_series_long.csv",allrows)
    maps={n:{r["日期"]:r["收盘"] for r in rs} for n,rs in by.items()}; wh=["日期"]+[s.name for s in SPECS]
    with open(OUT/"close_wide.csv","w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=wh); w.writeheader()
        for d in ref: w.writerow({"日期":d,**{s.name:maps[s.name].get(d) for s in SPECS}})
    payload={"metadata":metas,"validation":val,"headers":COLS,"rows":allrows}; (OUT/"all_series.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8"); (OUT/"validation.json").write_text(json.dumps(val,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(val,ensure_ascii=False,indent=2))
    if not val["all_complete"]: raise SystemExit("Completeness/cross-check validation failed")

if __name__=="__main__": main()
