import json
from pathlib import Path
import requests
OUT=Path('market_data_output');OUT.mkdir(exist_ok=True)
codes=['000001','000688','399006','BK1128','BK0877','BK1137','BK1326','BK1325']
templates=[
 'https://daxiapi.com/sk/{code}.json',
 'https://daxiapi.com/gn/{code}.json',
 'https://daxiapi.com/gn/{code}',
 'https://quote.eastmoney.com/bk/90.{code}.html',
 'https://quotes.sina.cn/cn/api/jsonp.php/var%20_data=/CN_MarketDataService.getKLineData?symbol={code}&scale=240&ma=no&datalen=300',
]
headers={'User-Agent':'Mozilla/5.0','Accept':'*/*'}
out={}
for code in codes:
 out[code]=[]
 for t in templates:
  u=t.format(code=code)
  try:
   r=requests.get(u,headers=headers,timeout=30,allow_redirects=True)
   out[code].append({'url':u,'status':r.status_code,'content_type':r.headers.get('content-type'),'length':len(r.content),'final_url':r.url,'sample':r.text[:500]})
  except Exception as e:out[code].append({'url':u,'error':repr(e)})
with (OUT/'alternate_probe.json').open('w',encoding='utf-8') as f:json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False,indent=2))
