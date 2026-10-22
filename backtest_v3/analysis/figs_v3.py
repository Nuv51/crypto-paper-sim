"""Gráficas del reporte V3. Corre desde /home/claude/v3/report (necesita ../res_v3.pkl y ../data3)."""
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
R=pickle.load(open('../res_v3.pkl','rb')); V3,RF,V2,bots,EQ,RES=R['V3'],R['RF'],R['V2'],R['bots'],R['EQ'],R['R']
Y=list(range(2019,2025)); x=np.arange(6)
# g1 ROI
fig,ax=plt.subplots(figsize=(8.6,4.1)); w=0.2
for j,(n,v,c) in enumerate([('V3 (con filtro)',V3.roi,BLUE),('V3-ref (sin filtro)',RF.roi,PUR),('V2',V2.roi,GRN),('BTC',V3.btc_roi,MUT)]):
    ax.bar(x+(j-1.5)*w,v,w*0.92,color=c,label=n,zorder=3,linewidth=0)
ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.set_xticks(x); ax.set_xticklabels([f'{y}\nV3 {v:+.0f}%\nref {r:+.0f}%' for y,v,r in zip(Y,V3.roi,RF.roi)],fontsize=8.4)
ax.yaxis.set_major_formatter(pct); ax.grid(axis='x',visible=False); ax.legend(ncol=2,fontsize=8.6,loc='upper right')
title(ax,'ROI anual: V3, su control sin filtro, V2 y BTC','Cada año empieza con 10,000 USDT ficticios el 1 de enero. BTC llega a +302 % en 2020.'); save(fig,'g1_roi')
# g2 caída máxima
fig,ax=plt.subplots(figsize=(8.6,4.0)); w=0.26
for j,(n,v,c) in enumerate([('V3 (con filtro)',V3.maxdd,BLUE),('V3-ref (sin filtro)',RF.maxdd,PUR),('V2',V2.maxdd,GRN)]):
    xs=x+(j-1)*w*1.05; ax.bar(xs,v,w,color=c,label=n,zorder=3,linewidth=0)
ax.axhline(-35,color=RED,lw=1.4,ls='--',zorder=4,label='límite pre-registrado −35 %')
ax.set_ylim(-58,3); ax.set_xticks(x); ax.set_xticklabels([f'{y}\nV3 {a:.0f}%\nref {b:.0f}%\nV2 {c:.0f}%' for y,a,b,c in zip(Y,V3.maxdd,RF.maxdd,V2.maxdd)],fontsize=8.2); ax.yaxis.set_major_formatter(pct); ax.grid(axis='x',visible=False); ax.legend(loc='lower left',ncol=2,fontsize=8.4)
title(ax,'Caída máxima desde el máximo, dentro del año','El filtro casi anula 2022 (−0.5 % contra −31 %), pero en 2021 queda peor que sin filtro.'); save(fig,'g2_dd')
# g3 curvas
fig,axs=plt.subplots(2,3,figsize=(9.8,5.6))
for ax,y in zip(axs.flat,Y):
    for key,c,ls,lw in (('btc',MUT,'--',1.2),(('ref',y),PUR,'-',1.4),(('v3',y),BLUE,'-',1.9)):
        s=EQ[('btc',y)] if key=='btc' else EQ[key]; s=s.copy(); s.index=pd.to_datetime(s.index,unit='ms'); s=(s*(100 if key=='btc' else 1/100)).resample('1D').last()
        ax.plot(s.index,s.values,color=c,ls=ls,lw=lw)
    ax.axhline(100,color=AX,lw=1); ax.set_title(str(y),loc='left',fontsize=10.5,fontweight='bold')
    ax.set_title(f'V3 {V3.roi[y]:+.0f}% · ref {RF.roi[y]:+.0f}%',loc='right',fontsize=8.4,color=SEC)
    ax.xaxis.set_major_locator(md.MonthLocator(bymonth=[1,4,7,10])); ax.xaxis.set_major_formatter(md.DateFormatter('%b')); ax.tick_params(labelsize=8)
fig.legend([plt.Line2D([0],[0],color=BLUE,lw=2),plt.Line2D([0],[0],color=PUR,lw=1.5),plt.Line2D([0],[0],color=MUT,lw=1.3,ls='--')],['V3 (base 100)','V3-ref sin filtro','BTC comprar y mantener'],loc='upper center',ncol=3,fontsize=9,bbox_to_anchor=(0.5,1.02))
fig.tight_layout(); save(fig,'g3_curves')
# g4 costos
fig,ax=plt.subplots(figsize=(8.6,3.9)); w=0.26
for j,(n,v,c) in enumerate([('V3 (con filtro)',V3.cost_pct,BLUE),('V3-ref (sin filtro)',RF.cost_pct,PUR),('V2',V2.cost_pct,GRN)]):
    xs=x+(j-1)*w*1.05; ax.bar(xs,v,w,color=c,label=n,zorder=3,linewidth=0)
ax.axhline(1.0,color=RED,lw=1.4,ls='--',zorder=4,label='límite pre-registrado 1.0 %')
ax.set_xticks(x); ax.set_xticklabels([f'{y}\nV3 {a:.1f}%\nref {b:.1f}%\nV2 {c:.1f}%' for y,a,b,c in zip(Y,V3.cost_pct,RF.cost_pct,V2.cost_pct)],fontsize=8.2); ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v,_:f'{v:.1f}%')); ax.grid(axis='x',visible=False); ax.legend(loc='upper right',ncol=2,fontsize=8.4); ax.set_ylim(0,4.0)
title(ax,'Comisiones + deslizamiento, % del capital inicial','Quitar satélites y estables baja el costo (ref); el filtro lo vuelve a subir al entrar y salir muchas veces (2021: 10 apagados y 10 encendidos).'); save(fig,'g4_costs')
# g5 PnL por grupo V3
grp={'DCA':['w01_dca'],'Carry BTC+ETH':['w02_carry_btc','w03_carry_eth'],'Índice Top-25':['w04_index_cap25']}; cols={'DCA':BLUE,'Carry BTC+ETH':GRN,'Índice Top-25':PUR}
b3=bots[bots['var']=='v3']
G=pd.DataFrame({g:[b3[(b3.year==y)&(b3.bot.isin(bb))].pnl.sum() for y in Y] for g,bb in grp.items()},index=Y)
fig,ax=plt.subplots(figsize=(8.6,4.0)); pos=np.zeros(6); neg=np.zeros(6)
for g in grp:
    v=G[g].values; base=np.where(v>=0,pos,neg); ax.bar(x,v,0.6,bottom=base,color=cols[g],label=g,zorder=3,linewidth=0.6,edgecolor=S); pos+=np.where(v>=0,v,0); neg+=np.where(v<0,v,0)
for xi,t in zip(x,G.sum(axis=1)): ax.text(xi,max(pos[xi],0)+150,f'{t:+,.0f}',ha='center',fontsize=8.8,fontweight='bold')
ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.set_xticks(x); ax.set_xticklabels(Y); ax.grid(axis='x',visible=False); ax.legend(ncol=3,fontsize=8.5,loc='upper right')
ax.yaxis.set_major_formatter(mt.FuncFormatter(lambda v,_:f'{v:,.0f}')); ax.set_ylabel('USDT'); title(ax,'De dónde sale el PnL de V3','El número arriba es el PnL total del portafolio (USDT).'); save(fig,'g5_pnl')
# g6 reserva
V1=R['V1']; fig,axs=plt.subplots(1,2,figsize=(9.2,3.9),sharey=True)
for ax,(y,lab) in zip(axs,((2025,'1 ene – 10 oct 2025'),(2026,'1 ene – 10 oct 2026'))):
    r=RES.loc[f'{y}-cut']; names=['V1 Actual','V1 Dinámico','V1 Indexado','V2 (reserva)','BTC']; vals=[V1[y]['actual'],V1[y]['dinamico'],V1[y]['indexado'],r.roi,r.btc_roi]; cs=[MUT,MUT,MUT,BLUE,ORG]
    ax.bar(range(5),vals,0.62,color=cs,zorder=3,linewidth=0)
    for i,v in enumerate(vals): ax.text(i,v+(1 if v>=0 else -1),f'{v:+.1f}%',ha='center',va='bottom' if v>=0 else 'top',fontsize=8.4,fontweight='bold' if i==3 else 'normal')
    ax.axhline(0,color=AX,lw=1.2,zorder=4); ax.set_xticks(range(5)); ax.set_xticklabels(names,rotation=30,ha='right',fontsize=8.4); ax.yaxis.set_major_formatter(pct); ax.grid(axis='x',visible=False); ax.set_ylim(-38,28)
    ax.set_title(lab,loc='left',fontsize=10.5,fontweight='bold')
fig.suptitle('Reserva: V2 contra los simuladores V1 en el mismo tramo',x=0.01,ha='left',fontsize=11.5,fontweight='bold'); fig.tight_layout(); save(fig,'g6_reserva')
print('figs ok')
