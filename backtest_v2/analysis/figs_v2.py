import pickle, numpy as np, pandas as pd, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt, matplotlib.ticker as mt, matplotlib.dates as md
import warnings; warnings.filterwarnings('ignore')
S='#fcfcfb';INK='#0b0b0b';SEC='#52514e';MUT='#898781';GRID='#e1e0d9';AX='#c3c2b7'
BLUE='#2a78d6';ORG='#eb6834';GRN='#1baf7a';PUR='#6250d6';RED='#e34948'
plt.rcParams.update({'figure.facecolor':S,'axes.facecolor':S,'savefig.facecolor':S,'font.family':'DejaVu Sans','font.size':10,'text.color':INK,
 'axes.edgecolor':AX,'axes.labelcolor':SEC,'xtick.color':SEC,'ytick.color':SEC,'axes.spines.top':False,'axes.spines.right':False,'axes.grid':True,
 'grid.color':GRID,'grid.linewidth':0.7,'axes.axisbelow':True,'legend.frameon':False})
def save(f,n): f.savefig(f'fig/{n}.png',dpi=170,bbox_inches='tight'); plt.close(f)
def title(ax,t,sub=None):
    ax.set_title(t,loc='left',fontsize=11.5,fontweight='bold',color=INK,pad=18 if sub else 8)
    if sub: ax.text(0,1.02,sub,transform=ax.transAxes,fontsize=8.8,color=SEC,va='bottom')
pct=mt.FuncFormatter(lambda v,_:f'{v:.0f}%')
R=pickle.load(open('../res.pkl','rb')); P,bt,tw,EQ=R['P'],R['bt'],R['tw'],R['eq']
Y=list(range(2019,2025)); x=np.arange(6)
# F1 ROI por año
fig,ax=plt.subplots(figsize=(8.6,4.1)); w=0.2
ser=[('V2 low cost',P.roi,BLUE),('BTC',P.btc_roi,MUT),('ETH',P.eth_roi,PUR),('Índice igual peso (sin costos)',P.ew_roi,GRN)]
for j,(n,v,c) in enumerate(ser):
    xs=x+(j-1.5)*w; ax.bar(xs,v,w*0.92,color=c,label=n,zorder=3,linewidth=0)
ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.set_xticks(x); ax.set_xticklabels([f'{y}\nV2 {v:+.0f}%\nBTC {b:+.0f}%' for y,v,b in zip(Y,P.roi,P.btc_roi)],fontsize=8.4); ax.yaxis.set_major_formatter(pct); ax.grid(axis='x',visible=False)
ax.legend(ncol=2,fontsize=8.6,loc='upper right'); title(ax,'ROI anual: V2 contra comprar y mantener','Cada año empieza con 10,000 USDT ficticios el 1 de enero. ETH llega a +470 % en 2020.')
save(fig,'g1_roi')
# F2 curvas
fig,axs=plt.subplots(2,3,figsize=(9.8,5.6))
for ax,y in zip(axs.flat,Y):
    s=EQ[y].copy(); s.index=pd.to_datetime(s.index,unit='ms'); d=(s/10000*100).resample('1D').last()
    b=pd.read_csv(f'../data/{y}/tables/bars.csv.gz',usecols=['symbol','ts','open','close']); b=b[b.symbol=='BTCUSDT']; o=b.open.iloc[0]
    c=b.set_index('ts').close/o*100; c.index=pd.to_datetime(c.index,unit='ms'); c=c.resample('1D').last()
    ax.plot(c.index,c.values,color=MUT,lw=1.3,ls='--'); ax.plot(d.index,d.values,color=BLUE,lw=1.8)
    ax.axhline(100,color=AX,lw=1); ax.set_title(str(y),loc='left',fontsize=10.5,fontweight='bold')
    ax.set_title(f'V2 {d.values[-1]-100:+.0f}%  ·  BTC {c.values[-1]-100:+.0f}%',loc='right',fontsize=8.4,color=SEC)
    ax.xaxis.set_major_locator(md.MonthLocator(bymonth=[1,4,7,10])); ax.xaxis.set_major_formatter(md.DateFormatter('%b')); ax.tick_params(labelsize=8)
    if y>2020: ax.set_yscale('log') if False else None
fig.legend([plt.Line2D([0],[0],color=BLUE,lw=2),plt.Line2D([0],[0],color=MUT,lw=1.5,ls='--')],['V2 (base 100)','BTC comprar y mantener (base 100)'],loc='upper center',ncol=2,fontsize=9,bbox_to_anchor=(0.5,1.02))
fig.tight_layout(); save(fig,'g2_curves')
# F3 caída máxima
fig,ax=plt.subplots(figsize=(8.6,3.9)); w=0.36
for j,(n,v,c) in enumerate((('V2 low cost',P.maxdd,BLUE),('BTC',P.btc_dd,MUT))):
    xs=x+(j-.5)*w*1.05; ax.bar(xs,v,w,color=c,label=n,zorder=3,linewidth=0)
    for xi,vi in zip(xs,v): ax.text(xi,vi-1.2,f'{vi:.0f}%',ha='center',va='top',fontsize=8.6,fontweight='bold' if j==0 else 'normal',color=INK)
ax.axhline(-40,color=RED,lw=1.4,ls='--',zorder=4); ax.text(5.45,-41,'límite pre-registrado −40 %',ha='right',va='top',fontsize=8.5,color=RED)
ax.set_ylim(-75,3); ax.set_xticks(x); ax.set_xticklabels(Y); ax.yaxis.set_major_formatter(pct); ax.grid(axis='x',visible=False); ax.legend(loc='lower left',ncol=2,fontsize=8.6)
title(ax,'Caída máxima desde el máximo, dentro del año','V2 cae menos que BTC los 6 años, pero cruza el límite de −40 % en 2019 y 2021.')
save(fig,'g3_dd')
# F4 PnL por grupo
grp={'DCA':['v01_dca'],'Carry':['v02_carry_btc','v03_carry_eth'],'Estables':['v04_stable'],'Índice Top-25':['v05_index_cap25'],'4 satélites':['v06_grid_eth','v07_grid_eth_gate','v08_trend','v09_trend_gate']}
cols={'DCA':BLUE,'Carry':GRN,'Estables':'#e0b441','Índice Top-25':PUR,'4 satélites':RED}
G=pd.DataFrame({g:[bt[(bt.year==y)&(bt.bot.isin(b))].pnl.sum() for y in Y] for g,b in grp.items()},index=Y)
fig,ax=plt.subplots(figsize=(8.6,4.2)); pos=np.zeros(6); neg=np.zeros(6)
for g in grp:
    v=G[g].values; base=np.where(v>=0,pos,neg); ax.bar(x,v,0.6,bottom=base,color=cols[g],label=g,zorder=3,linewidth=0.6,edgecolor=S)
    pos+=np.where(v>=0,v,0); neg+=np.where(v<0,v,0)
for xi,t in zip(x,G.sum(axis=1)): ax.text(xi,max(pos[xi],0)+300,f'{t:+,.0f}',ha='center',fontsize=8.8,fontweight='bold')
ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.set_xticks(x); ax.set_xticklabels(Y); ax.grid(axis='x',visible=False); ax.legend(ncol=3,fontsize=8.5,loc='upper right')
ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v,_:f'{v:,.0f}')); ax.set_ylabel('USDT')
title(ax,'De dónde sale el PnL del año','Índice y DCA concentran el resultado; el número arriba es el PnL total del portafolio.')
save(fig,'g4_pnl'); G.to_csv('pnl_by_group.csv')
# F5 satélites: bruto, costos, neto + gemelos
sat=['v06_grid_eth','v07_grid_eth_gate','v08_trend','v09_trend_gate']
S5=bt[bt.bot.isin(sat)].groupby('year')[['pnl','fees','slip']].sum(); S5['cost']=S5.fees+S5.slip; S5['gross']=S5.pnl+S5.cost
fig,axs=plt.subplots(1,2,figsize=(9.8,3.9),gridspec_kw={'width_ratios':[1.15,1]})
ax=axs[0]; w=0.27
for j,(n,v,c) in enumerate((('Antes de costos',S5.gross,GRN),('Costos',-S5.cost,RED),('Neto',S5.pnl,BLUE))):
    xs=x+(j-1)*w; ax.bar(xs,v,w*0.92,color=c,label=n,zorder=3,linewidth=0)
ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.set_xticks(x); ax.set_xticklabels(Y,fontsize=9); ax.grid(axis='x',visible=False); ax.legend(fontsize=8.4,ncol=3,loc='lower center',bbox_to_anchor=(0.5,-0.3))
title(ax,'Satélites (suma de 4): bruto, costos y neto','USDT; capital total de satélites 2,000'); 
ax=axs[1]; w=0.38
for j,(t,c) in enumerate((('grid',BLUE),('trend',ORG))):
    v=tw[tw.type==t].set_index('year')['diff']; xs=x+(j-.5)*w*1.05; ax.bar(xs,v.values,w,color=c,zorder=3,linewidth=0,label='Grid ETH' if t=='grid' else 'Tendencia')
ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.set_xticks(x); ax.set_xticklabels(Y,fontsize=9); ax.grid(axis='x',visible=False); ax.legend(fontsize=8.4,ncol=2,loc='lower center',bbox_to_anchor=(0.5,-0.3))
title(ax,'Gemelo con interruptor menos sin interruptor','USDT por año; positivo = el interruptor ayudó')
fig.tight_layout(); save(fig,'g5_sat')
# F6 costos por grupo vs límite
C6=pd.DataFrame({g:[(bt[(bt.year==y)&(bt.bot.isin(b))].fees+bt[(bt.year==y)&(bt.bot.isin(b))].slip).sum() for y in Y] for g,b in grp.items()},index=Y)
fig,ax=plt.subplots(figsize=(8.6,3.9)); bot=np.zeros(6)
for g in grp: ax.bar(x,C6[g].values,0.6,bottom=bot,color=cols[g],label=g,zorder=3,linewidth=0.6,edgecolor=S); bot+=C6[g].values
ax.axhline(150,color=RED,lw=1.4,ls='--',zorder=4,label='límite pre-registrado: 150 USDT (1.5 %)')
for xi,t in zip(x,bot): ax.text(xi,t+8,f'{t:,.0f}',ha='center',fontsize=8.8,fontweight='bold')
ax.set_xticks(x); ax.set_xticklabels(Y); ax.grid(axis='x',visible=False); ax.legend(ncol=3,fontsize=8.2,loc='upper left'); ax.set_ylabel('USDT'); ax.set_ylim(0,330)
title(ax,'Costos del año (comisiones + deslizamiento) por grupo','Los 4 satélites concentran los costos; el carry paga poco.')
save(fig,'g6_costs'); C6.to_csv('costs_by_group.csv')
# F7 interruptor encendido
fig,ax=plt.subplots(figsize=(8.0,3.3)); v=P.gate_on*100
ax.bar(x,v,0.55,color=BLUE,zorder=3,linewidth=0)
for xi,vi in zip(x,v): ax.text(xi,vi+2,f'{vi:.0f}%',ha='center',fontsize=9,fontweight='bold')
ax.set_ylim(0,112); ax.set_xticks(x); ax.set_xticklabels(Y); ax.yaxis.set_major_formatter(pct); ax.grid(axis='x',visible=False)
title(ax,'Porcentaje de días con el interruptor encendido','Volatilidad de BTC a 14 días > 40 % anualizada. Casi siempre encendido: no distingue regímenes.')
save(fig,'g7_gate')
# F8 vs BTC: V1 y V2
labels=['V1\nactual\n2025','V1\ndinám.\n2025','V1\nindexado\n2025','V1\nactual\n2026','V1\ndinám.\n2026','V1\nindexado\n2026']+[f'V2\n\n{y}' for y in Y]
roi=[-10.7,-30.0,-3.2,-10.1,-18.6,-4.1]+list(P.roi.values); btc=[20.5]*3+[-5.3]*3+list(P.btc_roi.values)
d=np.array(roi)-np.array(btc); col=[ORG]*6+[BLUE]*6
fig,ax=plt.subplots(figsize=(9.4,4.0)); xs=np.arange(12)
ax.bar(xs,d,0.62,color=col,zorder=3,linewidth=0)
for xi,vi in zip(xs,d): ax.text(xi,vi+(3 if vi>=0 else -3),f'{vi:+.0f}',ha='center',va='bottom' if vi>=0 else 'top',fontsize=8.6,fontweight='bold')
ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.axvline(5.5,color=AX,lw=1,ls=':'); ax.set_xticks(xs); ax.set_xticklabels(labels,fontsize=7.6); ax.grid(axis='x',visible=False)
ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v,_:f'{v:+.0f}')); ax.set_ylim(-215,62)
ax.text(2.5,50,'V1 · 1 ene–10 oct',ha='center',fontsize=8.6,color=ORG,fontweight='bold'); ax.text(8.5,50,'V2 · años completos',ha='center',fontsize=8.6,color=BLUE,fontweight='bold')
title(ax,'ROI menos ROI de BTC, en puntos porcentuales','Periodos y mercados distintos: sirve para ver el patrón, no para declarar ganador.')
save(fig,'g8_vs_btc')
# F9 meses y bootstrap
allm=[]
for y,s in EQ.items():
    s=s.copy(); s.index=pd.to_datetime(s.index,unit='ms'); m=s.resample('MS').last(); m0=pd.concat([pd.Series([10000.0],index=[m.index[0]-pd.offsets.MonthBegin(1)]),m]); allm+=list(m0.pct_change().dropna().values)
allm=np.array(allm)*100; rng=np.random.default_rng(7); sims=np.array([(np.prod(1+rng.choice(allm,12)/100)-1)*100 for _ in range(10000)])
fig,axs=plt.subplots(1,2,figsize=(9.8,3.7))
ax=axs[0]; ax.hist(allm,bins=np.arange(-16,40,2),color=BLUE,zorder=3,linewidth=0.6,edgecolor=S); ax.axvline(0,color=AX,lw=1.2)
title(ax,'72 retornos mensuales de V2','40 positivos · media +3.0 % · peor −14.9 %'); ax.xaxis.set_major_formatter(pct); ax.set_ylabel('meses')
ax=axs[1]; ax.hist(sims,bins=np.arange(-60,260,10),color=PUR,zorder=3,linewidth=0.6,edgecolor=S); ax.axvline(0,color=AX,lw=1.2)
for q,l in ((5,'p5'),(50,'mediana'),(95,'p95')):
    v=np.percentile(sims,q); ax.axvline(v,color=RED,lw=1,ls='--'); ax.text(v,ax.get_ylim()[1]*0.93,f'{l} {v:+.0f}%',rotation=90,fontsize=8,va='top',ha='right',color=RED)
title(ax,'Años posibles remuestreando esos meses','12 meses al azar, 10,000 veces. P(año < 0) ≈ 22 %'); ax.xaxis.set_major_formatter(pct)
fig.tight_layout(); save(fig,'g9_boot')
print('ok', P.gate_on.round(2).tolist(), round((sims<0).mean(),3))
