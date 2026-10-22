"""Análisis de V3 (BACKTEST_V3.md). Corre desde una carpeta con data3/<variante>-<año>/ (rama backtest-v3) y datar/<año>/ (rama backtest-v2-reserva).
  python analyze_v3.py <carpeta_datos> <ruta_repo>
Escribe portfolio_v3.csv, bots_v3.csv, reserva_v2.csv y res_v3.pkl en la carpeta actual."""
import importlib, json, pickle, sys
import numpy as np, pandas as pd

DATA = sys.argv[1] if len(sys.argv) > 1 else '.'
REPO = sys.argv[2] if len(sys.argv) > 2 else '/home/claude/crypto-paper-sim'
sys.path.insert(0, REPO)
CAP0 = 10000.0
YEARS = range(2019, 2025)


def maxdd(s):
    s = np.asarray(s, float)
    return float((s / np.maximum.accumulate(s) - 1).min())


def slip_bps(cfg, bot_id, sym):
    b = {x['id']: x for x in cfg.BOTS}[bot_id]
    if sym.endswith('~PERP'):
        return b.get('params', {}).get('perp_slip_bps', 2.0)
    m = b.get('slippage_map_bps') or {}
    return m.get(sym, b.get('slippage_bps', 5))


def run(path, cfgname, year, cut_ms=None):
    d = f'{DATA}/{path}/tables/'
    eq = pd.read_csv(d + 'equity.csv.gz'); tr = pd.read_csv(d + 'trades.csv.gz'); bars = pd.read_csv(d + 'bars.csv.gz', usecols=['symbol', 'ts', 'open', 'close'])
    cfg = importlib.import_module(f'{cfgname}_{year}')
    caps = {b['id']: b['capital_pct'] * CAP0 for b in cfg.BOTS}
    idle = CAP0 - sum(caps.values())
    w = eq.pivot(index='ts', columns='bot_id', values='equity')
    tot = w.sum(axis=1) + idle
    btc = bars[bars.symbol == 'BTCUSDT'].set_index('ts')
    if cut_ms:
        tot = tot[tot.index < cut_ms]; w = w.loc[tot.index]; btc = btc[btc.index < cut_ms]; tr = tr[tr.ts < cut_ms] if 'ts' in tr else tr
    btc_eq = btc.close / btc.open.iloc[0]
    daily = tot.copy(); daily.index = pd.to_datetime(daily.index, unit='ms'); dd = daily.resample('1D').last().pct_change().dropna()
    sharpe = float(dd.mean() / dd.std() * np.sqrt(365)) if dd.std() > 0 else float('nan')
    tr = tr[tr.reason != 'funding'].copy()
    tr['slip'] = [n * slip_bps(cfg, b, s) / 1e4 for n, b, s in zip(tr.notional, tr.bot_id, tr.symbol)]
    fees = tr.groupby('bot_id').fee.sum(); slip = tr.groupby('bot_id').slip.sum()
    last = w.iloc[-1]
    rows = [dict(bot=b['id'], year=year, capital=caps[b['id']], final=last[b['id']], pnl=last[b['id']] - caps[b['id']],
                 maxdd=maxdd(w[b['id']]) * 100, fees=fees.get(b['id'], 0.0), slip=slip.get(b['id'], 0.0), n=int((tr.bot_id == b['id']).sum())) for b in cfg.BOTS]
    roi = float((tot.iloc[-1] / CAP0 - 1) * 100); mdd = maxdd(tot) * 100
    P = dict(roi=roi, maxdd=mdd, calmar=roi / abs(mdd) if mdd else float('nan'), sharpe=sharpe, fees=float(fees.sum()), slip=float(slip.sum()),
             cost_pct=float((fees.sum() + slip.sum()) / CAP0 * 100), idle=idle, btc_roi=float((btc_eq.iloc[-1] - 1) * 100), btc_dd=maxdd(btc_eq) * 100,
             n_trades=int(len(tr)))
    return P, rows, tot, btc_eq


# ---------- principal 2019-2024: V3 vs V3-ref ----------
PV, BV, EQ = {}, [], {}
for var in ('v3', 'ref'):
    cn = 'config_v3' if var == 'v3' else 'config_v3ref'
    for y in YEARS:
        P, rows, tot, be = run(f'data3/{var}-{y}', cn, y)
        PV[(var, y)] = P; EQ[(var, y)] = tot; EQ[('btc', y)] = be
        BV += [dict(r, var=var) for r in rows]
V3 = pd.DataFrame({y: PV[('v3', y)] for y in YEARS}).T
RF = pd.DataFrame({y: PV[('ref', y)] for y in YEARS}).T
V2 = pd.read_csv(f'{REPO}/backtest_v2/analysis/portfolio_by_year.csv', index_col=0)
V2['cost_pct'] = (V2.fees + V2.slip) / CAP0 * 100
bots = pd.DataFrame(BV)
pd.set_option('display.width', 250); pd.set_option('display.max_columns', 30)
cols = ['roi', 'maxdd', 'sharpe', 'calmar', 'cost_pct', 'n_trades']
print('V3\n', V3[cols + ['btc_roi', 'btc_dd']].round(2).to_string()); print('\nV3-ref\n', RF[cols].round(2).to_string()); print('\nV2\n', V2[['roi', 'maxdd', 'sharpe', 'cost_pct']].round(2).to_string())
V3.to_csv('portfolio_v3.csv'); RF.to_csv('portfolio_v3ref.csv'); bots.to_csv('bots_v3.csv', index=False)

# fracción del tiempo con filtro encendido (SMA200 de BTC, cierre diario 23:00 UTC), con el año previo como calentamiento cuando existe
btc_all = {}
for y in YEARS:
    b = pd.read_csv(f'{DATA}/data3/v3-{y}/tables/bars.csv.gz', usecols=['symbol', 'ts', 'close']); btc_all[y] = b[b.symbol == 'BTCUSDT'].set_index('ts').close
gate_on = {}
for y in YEARS:
    if y - 1 not in btc_all:
        gate_on[y] = np.nan; continue
    s = pd.concat([btc_all[y - 1], btc_all[y]]); s.index = pd.to_datetime(s.index, unit='ms')
    dcl = s.resample('1D').last().dropna()
    on = (dcl.shift(1) > dcl.shift(1).rolling(200).mean().shift(0)).astype(float)  # cierre de ayer vs media de los 200 cierres previos incluyendo ayer: equivalente al diseño
    gate_on[y] = float(on[on.index.year == y].mean())
print('\nfiltro encendido (fracción de días):', {y: round(v, 2) if v == v else None for y, v in gate_on.items()})

# ---------- criterios ----------
cost = V3.cost_pct
D1 = bool((V3.maxdd >= -35).all()); D2 = int((V3.roi > 0).sum()) >= 4; D3 = bool((cost < 1.0).all()); D4 = int((V3.maxdd > V3.btc_dd).sum()) >= 5
d5a = int((V3.maxdd > RF.maxdd).sum()); d5b = int((V3.calmar > RF.calmar).sum()); D5 = d5a >= 4 and d5b >= 4
d6a = int((V3.maxdd > V2.maxdd.values).sum()); d6b = int((cost.values < V2.cost_pct.values).sum()); D6 = d6a >= 4 and d6b == 6
print('\nD1', D1, V3.maxdd.round(1).tolist()); print('D2', D2, V3.roi.round(1).tolist()); print('D3', D3, cost.round(2).tolist())
print('D4', D4, 'V3', V3.maxdd.round(1).tolist(), 'BTC', V3.btc_dd.round(1).tolist())
print('D5', D5, f'caída V3<ref en {d5a}/6 · Calmar V3>ref en {d5b}/6')
print('D6', D6, f'caída V3<V2 en {d6a}/6 · costos V3<V2 en {d6b}/6')
ch = lambda r: (np.prod(1 + r / 100) - 1) * 100
print('\nencadenado V3', round(ch(V3.roi), 1), 'ref', round(ch(RF.roi), 1), 'V2', round(ch(V2.roi), 1), 'BTC', round(ch(V3.btc_roi), 1))
print('\nPnL por bot (USDT)'); print(bots.pivot_table(index=['var', 'bot'], columns='year', values='pnl').round(0).to_string())
print('\ncostos por bot'); print(bots.assign(c=bots.fees + bots.slip).pivot_table(index=['var', 'bot'], columns='year', values='c').round(0).to_string())

# ---------- reserva V2 2025-2026 ----------
V1 = {2025: dict(actual=-10.7, dinamico=-30.0, indexado=-3.2, btc=20.5), 2026: dict(actual=-10.1, dinamico=-18.6, indexado=-4.1, btc=-5.3)}
RR = {}; RB = []
for y in (2025, 2026):
    full = run(f'datar/{y}', 'config_v2', y)
    RR[(y, 'full')] = full[0]; RB += full[1]
    if y == 2025:
        cut = int(pd.Timestamp('2025-10-11', tz='UTC').timestamp() * 1000)
        RR[(y, 'cut')] = run(f'datar/{y}', 'config_v2', y, cut)[0]
    else:
        RR[(y, 'cut')] = full[0]
R = pd.DataFrame({f'{k[0]}{"-"+k[1]}': v for k, v in RR.items()}).T
print('\nReserva V2\n', R[['roi', 'maxdd', 'sharpe', 'cost_pct', 'btc_roi', 'btc_dd', 'n_trades']].round(2).to_string())
R.to_csv('reserva_v2.csv')
rb = pd.DataFrame(RB); rb['c'] = rb.fees + rb.slip; rb.to_csv('reserva_v2_bots.csv', index=False)
print('\nReserva V2 · PnL por bot'); print(rb.pivot(index='bot', columns='year', values='pnl').round(0).to_string())
print('\nReserva V2 · costos por bot'); print(rb.pivot(index='bot', columns='year', values='c').round(0).to_string())
for y in (2025, 2026):
    p = rb[rb.year == y].set_index('bot')
    print(y, 'B-A grid', round(p.loc['v07_grid_eth_gate', 'pnl'] - p.loc['v06_grid_eth', 'pnl'], 1), 'B-A trend', round(p.loc['v09_trend_gate', 'pnl'] - p.loc['v08_trend', 'pnl'], 1),
          'peor satélite %', round(((p.loc[['v06_grid_eth', 'v07_grid_eth_gate', 'v08_trend', 'v09_trend_gate'], 'pnl'] / p.loc[['v06_grid_eth', 'v07_grid_eth_gate', 'v08_trend', 'v09_trend_gate'], 'capital']) * 100).min(), 1))
pickle.dump(dict(V3=V3, RF=RF, V2=V2, bots=bots, gate_on=gate_on, R=R, V1=V1, EQ=EQ,
                 crit=dict(D1=D1, D2=D2, D3=D3, D4=D4, D5=D5, D6=D6, d5=(d5a, d5b), d6=(d6a, d6b))), open('res_v3.pkl', 'wb'))
