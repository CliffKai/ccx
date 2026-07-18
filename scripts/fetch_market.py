import json,re
from pathlib import Path
import requests
OUT=Path('market_data_output');OUT.mkdir(exist_ok=True)
u='https://quote.eastmoney.com/newstatic/build/bk2.js'
r=requests.get(u,headers={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/bk/90.BK1128.html'},timeout=60)
t=r.text
patterns=['push2his','push2','kline/get','api/qt','stock/kline','fields2','f51','quotekchart']
out={'status':r.status_code,'length':len(t),'url':r.url,'hits':{}}
for n in patterns:
 ps=[m.start() for m in re.finditer(re.escape(n),t,re.I)][:50]
 out['hits'][n]=[t[max(0,p-600):p+1200] for p in ps]
with (OUT/'bk2_js_inspect.json').open('w',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False,indent=2))
