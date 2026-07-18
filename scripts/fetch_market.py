import json,re
from pathlib import Path
import requests
OUT=Path('market_data_output');OUT.mkdir(exist_ok=True)
urls=['https://quote.eastmoney.com/bk/90.BK1128.html','https://quote.eastmoney.com/bk/90.BK0877.html']
res={}
for u in urls:
 r=requests.get(u,headers={'User-Agent':'Mozilla/5.0'},timeout=40);t=r.text
 scripts=re.findall(r'<script[^>]+src=["\']([^"\']+)',t)
 needles={}
 for n in ['push2his','kline','klines','__NEXT_DATA__','api/qt','f51','BK1128']:
  pos=[m.start() for m in re.finditer(n,t,re.I)][:20]
  needles[n]=[t[max(0,p-300):p+500] for p in pos]
 res[u]={'status':r.status_code,'length':len(t),'scripts':scripts,'needles':needles}
with (OUT/'quote_page_inspect.json').open('w',encoding='utf-8') as f:json.dump(res,f,ensure_ascii=False,indent=2)
print(json.dumps(res,ensure_ascii=False,indent=2))
