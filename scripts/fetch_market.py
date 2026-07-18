from __future__ import annotations
import csv,json,random,time
from datetime import datetime,timezone
from pathlib import Path
import requests
OUT=Path('market_data_output');OUT.mkdir(exist_ok=True)
SERIES={'上证指数':{'code':'000001.SH','secid':'1.000001','kind':'官方指数'},'PCB':{'code':'BK0877','secid':'90.BK0877','kind':'东方财富概念板块'},'存储芯片':{'code':'BK1137','secid':'90.BK1137','kind':'东方财富概念板块'},'半导体设备':{'code':'BK1326','secid':'90.BK1326','kind':'东方财富板块'},'半导体材料':{'code':'BK1325','secid':'90.BK1325','kind':'东方财富板块'}}
FIELDS=['名称','代码','口径','日期','开盘','最高','最低','收盘','供应商涨跌额','供应商涨跌幅_pct','复算涨跌额','复算涨跌幅_pct','涨跌幅复算差异_bp','年初至今涨跌幅_pct','成交量','成交额','振幅_pct','换手率_pct','数据源']
H={'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/','Accept':'application/json,text/plain,*/*','Connection':'close'}
def fetch(secid):
 p={'secid':secid,'ut':'fa5fd1943c7b386f172d6893dbfba10b','fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61','klt':'101','fqt':'0','beg':'20251201','end':'20260717','lmt':'100000'}
 nodes=list(range(1,100));random.shuffle(nodes);errs=[]
 for n in nodes:
  u=f'https://{n}.push2his.eastmoney.com/api/qt/stock/kline/get'
  try:
   r=requests.get(u,params=p,headers=H,timeout=12);r.raise_for_status();j=r.json()
   if j.get('data') and j['data'].get('klines'):return j,u
   errs.append({'node':n,'status':r.status_code,'sample':r.text[:100]})
  except Exception as e:errs.append({'node':n,'error':repr(e)})
  time.sleep(.25)
 raise RuntimeError(str(errs[-10:]))
def parse(name,cfg,j,u):
 raw=[]
 for line in j['data']['klines']:
  p=line.split(',')
  if len(p)<11:continue
  raw.append({'名称':name,'代码':cfg['code'],'口径':cfg['kind'],'日期':p[0],'开盘':float(p[1]),'收盘':float(p[2]),'最高':float(p[3]),'最低':float(p[4]),'成交量':float(p[5]),'成交额':float(p[6]),'振幅_pct':float(p[7]),'供应商涨跌幅_pct':float(p[8]),'供应商涨跌额':float(p[9]),'换手率_pct':float(p[10]),'数据源':u})
 raw.sort(key=lambda x:x['日期']);prev=None;base=None
 for x in raw:
  if x['日期']<'2026-01-01':base=x['收盘']
  x['复算涨跌额']=None if prev is None else x['收盘']-prev;x['复算涨跌幅_pct']=None if prev is None else (x['收盘']/prev-1)*100;prev=x['收盘']
 y=[x for x in raw if x['日期']>='2026-01-01']
 if not y:raise RuntimeError('no 2026 rows')
 if base is None:base=y[0]['收盘']-y[0]['供应商涨跌额']
 for x in y:
  if x['复算涨跌幅_pct'] is None:x['复算涨跌额']=x['供应商涨跌额'];x['复算涨跌幅_pct']=x['供应商涨跌幅_pct']
  x['涨跌幅复算差异_bp']=(x['复算涨跌幅_pct']-x['供应商涨跌幅_pct'])*100;x['年初至今涨跌幅_pct']=(x['收盘']/base-1)*100
 return y,{'code':cfg['code'],'rows':len(y),'first_date':y[0]['日期'],'last_date':y[-1]['日期'],'last_date_ok':y[-1]['日期']=='2026-07-17','base_close':base,'max_abs_recalc_diff_bp':max(abs(x['涨跌幅复算差异_bp']) for x in y),'source_name':j['data'].get('name'),'source_code':j['data'].get('code'),'node':u}
def write(path,rows):
 with path.open('w',encoding='utf-8-sig',newline='') as f:w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(rows)
def main():
 meta={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'series':{},'errors':{}}
 for name,cfg in SERIES.items():
  try:
   j,u=fetch(cfg['secid']);rows,info=parse(name,cfg,j,u);write(OUT/f"{cfg['code'].replace('.','_')}_{name}.csv",rows);meta['series'][name]=info
  except Exception as e:meta['errors'][name]=repr(e)
 with (OUT/'numbered_nodes_validation.json').open('w',encoding='utf-8') as f:json.dump(meta,f,ensure_ascii=False,indent=2)
 print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
