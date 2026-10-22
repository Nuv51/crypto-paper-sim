import pickle, json, numpy as np, pandas as pd
R = pickle.load(open('res.pkl','rb')); P, bt, eq = R['P'], R['bt'], R['eq']
pd.set_option('display.width', 250)
bt['cost'] = bt.fees + bt.slip
print('Costo (comisión+deslizamiento) por bot, USDT:'); print(bt.pivot(index='bot', columns='year', values='cost').round(0).to_string())
print('Total por año', bt.groupby('year').cost.sum().round(0).tolist(), 'comisiones', bt.groupby('year').fees.sum().round(0).tolist())
print('Costo satélites', bt[bt.bot.isin(['v06_grid_eth','v07_grid_eth_gate','v08_trend','v09_trend_gate'])].groupby('year').cost.sum().round(0).tolist(),
      'cap satélites 2000; PnL sat', bt[bt.bot.isin(['v06_grid_eth','v07_grid_eth_gate','v08_trend','v09_trend_gate'])].groupby('year').pnl.sum().round(0).tolist())
# antes de costos de satélites
sat = bt[bt.bot.isin(['v06_grid_eth','v07_grid_eth_gate','v08_trend','v09_trend_gate'])].groupby('year')[['pnl','cost']].sum(); sat['pre']=sat.pnl+sat.cost; print(sat.round(0).T.to_string())
# BTC sharpe/calmar y portafolio
for y in range(2019,2025):
    bars = pd.read_csv(f'data/{y}/tables/bars.csv.gz', usecols=['symbol','ts','close'])
    b = bars[bars.symbol=='BTCUSDT'].set_index('ts').close; b.index=pd.to_datetime(b.index,unit='ms'); d=b.resample('1D').last().pct_change().dropna()
    P.loc[y,'btc_sharpe']=d.mean()/d.std()*np.sqrt(365)
P['calmar']=P.roi/-P.maxdd; P['btc_calmar']=P.btc_roi/-P.btc_dd
print(P[['roi','maxdd','sharpe','btc_roi','btc_dd','btc_sharpe','calmar','btc_calmar']].round(2).to_string())
# meses
allm=[]
for y,s in eq.items():
    s=s.copy(); s.index=pd.to_datetime(s.index,unit='ms'); m=s.resample('MS').last(); m0=pd.concat([pd.Series([10000.0],index=[m.index[0]-pd.offsets.MonthBegin(1)]),m]); r=m0.pct_change().dropna(); allm+=list(r.values)
allm=np.array(allm); print('meses',len(allm),'positivos',int((allm>0).sum()),'peor',allm.min().round(3),'mejor',allm.max().round(3),'media',allm.mean().round(4))
rng=np.random.default_rng(7); sims=[]
for _ in range(10000):
    r=rng.choice(allm,12,replace=True); sims.append(np.prod(1+r)-1)
sims=np.array(sims); print('bootstrap anual (12 meses de los 72): p5',np.percentile(sims,5).round(3),'mediana',np.median(sims).round(3),'p95',np.percentile(sims,95).round(3),'P(<0)',(sims<0).mean().round(3))
# supervivencia: excluidas por "dejó de cotizar" dentro del top-25 potencial
for y in range(2019,2025):
    u=json.load(open(f'/home/claude/crypto-paper-sim/backtest_v2/universe_{y}.json'))
    thr=min(t['cap'] for t in u['top25'])
    caps=json.load(open(f"/home/claude/crypto-paper-sim/backtest_v2/inputs/caps_cmc_{ {2019:'2018-12-30',2020:'2019-12-29',2021:'2020-12-27',2022:'2021-12-26',2023:'2022-12-25',2024:'2023-12-31'}[y]}.json"))['caps_usd']
    cas=[(e['base'],round(caps.get(e['base'],caps.get({'IOTA':'MIOTA'}.get(e['base'],''),0))/1e9,2)) for e in u['excluded'] if 'dejó de cotizar' in e['reason']]
    print(y,'umbral top25 (B)',round(thr/1e9,2),'casualties',cas, 'n<180d', sum('historial' in e['reason'] for e in u['excluded']))
