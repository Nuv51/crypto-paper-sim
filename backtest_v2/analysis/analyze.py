import json, sys, importlib
import numpy as np, pandas as pd
sys.path.insert(0, '/home/claude/crypto-paper-sim')
from sim.gates import btc_vol_gate
YEARS = range(2019, 2025)
CAP0 = 10000.0
H = 3_600_000

def load(y):
    d = f'data/{y}/tables/'
    return (pd.read_csv(d + 'equity.csv.gz'), pd.read_csv(d + 'trades.csv.gz'), pd.read_csv(d + 'events.csv.gz'),
            pd.read_csv(d + 'bots.csv.gz'), json.load(open(f'data/{y}/summary.json')))

def maxdd(s):
    s = np.asarray(s, float); return float((s / np.maximum.accumulate(s) - 1).min())

def slip_bps(cfg, bot_id, sym):
    b = {x['id']: x for x in cfg.BOTS}[bot_id]
    if sym.endswith('~PERP'):
        return b.get('params', {}).get('perp_slip_bps', 2.0)
    m = b.get('slippage_map_bps') or {}
    return m.get(sym, b.get('slippage_bps', 5))

res, botrows, port = {}, [], {}
btc_close = {}
for y in YEARS:
    eq, tr, ev, bots, sm = load(y)
    cfg = importlib.import_module(f'config_v2_{y}')
    caps = {b['id']: b['capital_pct'] * CAP0 for b in cfg.BOTS}
    idle = CAP0 - sum(caps.values())
    w = eq.pivot(index='ts', columns='bot_id', values='equity')
    tot = w.sum(axis=1) + idle
    bars = pd.read_csv(f'data/{y}/tables/bars.csv.gz', usecols=['symbol', 'ts', 'open', 'close'])
    btc = bars[bars.symbol == 'BTCUSDT'].set_index('ts')
    btc_open0 = btc.open.iloc[0]
    btc_eq = btc.close / btc_open0
    btc_close[y] = btc.close
    # EW buy&hold of the index symbols (no costs)
    syms = list(cfg.INDEX_SYMBOLS)
    ew = np.mean([bars[bars.symbol == s].set_index('ts').close.reindex(btc.index).ffill() / bars[bars.symbol == s].open.iloc[0] for s in syms if (bars.symbol == s).any()], axis=0)
    daily = tot.copy(); daily.index = pd.to_datetime(daily.index, unit='ms'); d = daily.resample('1D').last().pct_change().dropna()
    sharpe = float(d.mean() / d.std() * np.sqrt(365)) if d.std() > 0 else None
    tr = tr[tr.reason != 'funding'].copy()      # las filas de funding no son operaciones: no pagan comisión ni deslizamiento
    tr['slip'] = [n * slip_bps(cfg, b, s) / 1e4 for n, b, s in zip(tr.notional, tr.bot_id, tr.symbol)]
    fees = tr.groupby('bot_id').fee.sum(); slip = tr.groupby('bot_id').slip.sum()
    last = w.iloc[-1]
    for b in cfg.BOTS:
        i = b['id']; s = w[i]
        botrows.append(dict(year=y, bot=i, capital=caps[i], final=last[i], pnl=last[i] - caps[i], roi=(last[i] / caps[i] - 1) * 100,
                            maxdd=maxdd(s) * 100, fees=fees.get(i, 0.0), slip=slip.get(i, 0.0), n=int((tr.bot_id == i).sum()),
                            status=bots.set_index('bot_id').loc[i, 'status']))
    # gate-on fraction (approx; warm-up from previous year's BTC when available)
    prev = btc_close.get(y - 1)
    cl = pd.concat([prev, btc.close]) if prev is not None else btc.close
    g = btc_vol_gate(cl.to_numpy(float), cl.index.to_numpy(np.int64), 14, 0.40)[-len(btc):]
    port[y] = dict(pnl=float(tot.iloc[-1] - CAP0), roi=float((tot.iloc[-1] / CAP0 - 1) * 100), maxdd=maxdd(tot) * 100, sharpe=sharpe,
                   fees=float(fees.sum()), slip=float(slip.sum()), idle=idle, btc_roi=float((btc_eq.iloc[-1] - 1) * 100), btc_dd=maxdd(btc_eq) * 100,
                   eth_roi=sm['eth_roi'], ew_roi=float((ew[-1] - 1) * 100), ew_dd=maxdd(ew) * 100, gate_on=float(g.mean()), n_trades=int(len(tr)),
                   n_index=len(syms), eq=tot, events=ev)
bt = pd.DataFrame(botrows)
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
P = pd.DataFrame({y: {k: v for k, v in d.items() if k not in ('eq', 'events')} for y, d in port.items()}).T
print(P.round(2).to_string())
print()
print(bt.pivot(index='bot', columns='year', values='pnl').round(0).to_string())
print(bt.pivot(index='bot', columns='year', values='roi').round(1).to_string())
print(bt.pivot(index='bot', columns='year', values='maxdd').round(1).to_string())
print(bt.pivot(index='bot', columns='year', values='status').to_string())
bt.to_csv('bots_by_year.csv', index=False); P.to_csv('portfolio_by_year.csv')
# criteria
c1 = (P.maxdd >= -40).all(); c2 = (P.roi > 0).sum() >= 4; costs = (P.fees + P.slip) / CAP0 * 100
c3 = (costs < 1.5).all(); c4 = ((P.maxdd > P.btc_dd).sum() >= 5)
print('\nC1', c1, P.maxdd.round(1).tolist()); print('C2', c2, P.roi.round(1).tolist()); print('C3', c3, costs.round(2).tolist(), 'solo comisiones', (P.fees/CAP0*100).round(2).tolist())
print('C4', c4, 'port', P.maxdd.round(1).tolist(), 'btc', P.btc_dd.round(1).tolist())
tw = []
for typ, a, b in (('grid', 'v06_grid_eth', 'v07_grid_eth_gate'), ('trend', 'v08_trend', 'v09_trend_gate')):
    for y in YEARS:
        pa = bt[(bt.year == y) & (bt.bot == a)].pnl.iloc[0]; pb = bt[(bt.year == y) & (bt.bot == b)].pnl.iloc[0]
        tw.append(dict(type=typ, year=y, A=pa, B=pb, diff=pb - pa))
tw = pd.DataFrame(tw); print(); print(tw.round(1).to_string())
print('C5 pooled B-A', tw['diff'].sum().round(1), 'B wins', int((tw['diff'] > 0).sum()), 'ties', int((tw['diff'] == 0).sum()), 'of', len(tw))
sat = bt[bt.bot.isin(['v06_grid_eth', 'v07_grid_eth_gate', 'v08_trend', 'v09_trend_gate'])]
print('C6 worst satellite roi', sat.roi.min().round(1), sat.loc[sat.roi.idxmin(), ['year', 'bot']].tolist())
chain = np.prod(1 + P.roi / 100) - 1; print('chained', round(chain * 100, 1), 'btc chained', round((np.prod(1 + P.btc_roi / 100) - 1) * 100, 1))
core = bt[bt.bot.isin(['v01_dca', 'v02_carry_btc', 'v03_carry_eth', 'v04_stable', 'v05_index_cap25'])].groupby('year').pnl.sum()
satp = sat.groupby('year').pnl.sum(); print('\nPnL nucleo', core.round(0).tolist(), 'satelites', satp.round(0).tolist())
import pickle; pickle.dump(dict(P=P, bt=bt, tw=tw, eq={y: port[y]['eq'] for y in YEARS}, ev={y: port[y]['events'] for y in YEARS}), open('res.pkl', 'wb'))
