"""Reporte HTML/PDF de V3. Corre desde /home/claude/v3/report (necesita ../res_v3.pkl, fig/*.png y el css de /home/claude/analysis/report_full.html)."""
import base64, html, re, pickle, numpy as np, pandas as pd
R=pickle.load(open('../res_v3.pkl','rb')); V3,RF,V2,bots,RES,V1,GO=R['V3'],R['RF'],R['V2'],R['bots'],R['R'],R['V1'],R['gate_on']
css=re.search(r'<style>(.*?)</style>',open('/home/claude/analysis/report_full.html').read(),re.S).group(1)
Y=list(range(2019,2025))
def fig(n,alt,cap=''):
    b=base64.b64encode(open(f'fig/{n}.png','rb').read()).decode()
    return f'<figure class="fig"><img src="data:image/png;base64,{b}" alt="{html.escape(alt)}">{f"<figcaption>{cap}</figcaption>" if cap else ""}</figure>'
def tone(v): return 'pos' if v>0.05 else 'neg' if v<-0.05 else 'neu'
def cell(v,d=1,suf='%'):
    if v is None or (isinstance(v,float) and np.isnan(v)): return '<td class="num neu">—</td>'
    return f'<td class="num {tone(v)}">{v:+,.{d}f}{suf}</td>'
ch=lambda r:(np.prod(1+np.asarray(r)/100)-1)*100
# tabla por año
rows=''
for y in Y:
    a,b,c=V3.loc[y],RF.loc[y],V2.loc[y]
    g=GO[y]; gt='n/d' if g!=g else f'{g*100:.0f} %'
    rows+=f'<tr><th scope="row">{y}</th>{cell(a.roi)}<td class="num neg">{a.maxdd:.1f}%</td><td class="num">{a.cost_pct:.2f}%</td>{cell(b.roi)}<td class="num neg">{b.maxdd:.1f}%</td><td class="num">{b.cost_pct:.2f}%</td>{cell(c.roi)}<td class="num neg">{c.maxdd:.1f}%</td>{cell(a.btc_roi)}<td class="num">{gt}</td></tr>'
rows+=f'<tr><th scope="row">Encadenado</th>{cell(ch(V3.roi),0)}<td></td><td></td>{cell(ch(RF.roi),0)}<td></td><td></td>{cell(ch(V2.roi),0)}<td></td>{cell(ch(V3.btc_roi),0)}<td></td></tr>'
yeartable=f'<div class="tw"><table><thead><tr><th rowspan="2">Año</th><th colspan="3">V3 (con filtro)</th><th colspan="3">V3-ref (sin filtro)</th><th colspan="2">V2</th><th>BTC</th><th rowspan="2">Días con filtro encendido</th></tr><tr><th>ROI</th><th>Caída máx.</th><th>Costos</th><th>ROI</th><th>Caída máx.</th><th>Costos</th><th>ROI</th><th>Caída máx.</th><th>ROI</th></tr></thead><tbody>{rows}</tbody></table></div><p class="sm">ROI y caída máxima sobre los 10,000 completos (el efectivo no asignado cuenta: 50 % en 2019 por falta de carry). Costos = comisiones + deslizamiento estimado, % del capital inicial. “Días con filtro”: BTC sobre su media de 200 días; 2019 no se calculó (sin año previo en las tablas).</p>'
# PnL por bot V3
NMB={'w01_dca':'DCA BTC+ETH','w02_carry_btc':'Carry BTC','w03_carry_eth':'Carry ETH','w04_index_cap25':'Índice Top-25 (trimestral)'}
b3=bots[bots['var']=='v3']; pv=b3.pivot(index='bot',columns='year',values='pnl'); rows=''
for b in NMB:
    rows+=f'<tr><th scope="row">{NMB[b]}</th>'+''.join(cell(pv.loc[b,y] if not np.isnan(pv.loc[b,y]) else None,0,'') for y in Y)+f'<td class="num">{np.nansum(pv.loc[b]):+,.0f}</td></tr>'
tot3=(V3.roi/100*10000); totr=(RF.roi/100*10000)
rows+='<tr><th scope="row">Total V3</th>'+''.join(cell(tot3[y],0,'') for y in Y)+f'<td class="num"><b>{tot3.sum():+,.0f}</b></td></tr>'
rows+='<tr><th scope="row">Total V3-ref (sin filtro)</th>'+''.join(cell(totr[y],0,'') for y in Y)+f'<td class="num"><b>{totr.sum():+,.0f}</b></td></tr>'
pnltable=f'<div class="tw"><table><thead><tr><th>PnL en USDT</th>'+''.join(f'<th>{y}</th>' for y in Y)+'<th>Suma</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
# criterios
c=R['crit']; d5=c['d5']; d6=c['d6']
CR=[('D1','Caída máx. de V3 ≤ 35 % cada año',f'−47.3 % en 2021; los otros cinco entre −0.5 % y −29.1 %',c['D1']),
('D2','ROI de V3 > 0 en ≥ 4 de 6 años','4 de 6 (2019 −3.2 % y 2022 −0.4 %)',c['D2']),
('D3','Costos < 1.0 % del capital cada año','Solo 2019 (0.50 %) y 2022 (0.68 %) cumplen; 2021 llega a 3.38 %',c['D3']),
('D4','Caída máx. menor que BTC en ≥ 5 de 6 años','6 de 6',c['D4']),
('D5','El filtro aporta: caída V3 < ref en ≥ 4 de 6 y Calmar V3 > ref en ≥ 4 de 6',f'Caída menor en {d5[0]} de 6, pero Calmar mayor solo en {d5[1]} de 6',c['D5']),
('D6','Mejor que V2: caída V3 < V2 en ≥ 4 de 6 y costos V3 < V2 en los 6',f'Caída menor en {d6[0]} de 6; costos menores en {d6[1]} de 6 (2021 es mayor)',c['D6'])]
crow=''.join(f'<tr><th scope="row">{a}</th><td>{b}</td><td>{e}</td><td class="{"pos" if ok else "neg"}"><b>{"✓ Cumple" if ok else "✗ No cumple"}</b></td></tr>' for a,b,e,ok in CR)
crit=f'<div class="tw"><table><thead><tr><th>#</th><th>Criterio fijado antes de correr</th><th>Resultado</th><th></th></tr></thead><tbody>{crow}</tbody></table></div>'
n_ok=sum(x[3] for x in CR)
# reserva
r25,r26=RES.loc['2025-cut'],RES.loc['2026-cut']; f25=RES.loc['2025-full']
v1rows=''.join(f'<tr><th scope="row">{a}</th><td>{b}</td>{cell(v)}</tr>' for a,b,v in [
 ('V1 Actual','1 ene–10 oct 2025',V1[2025]['actual']),('V1 Dinámico','1 ene–10 oct 2025',V1[2025]['dinamico']),('V1 Indexado','1 ene–10 oct 2025',V1[2025]['indexado']),('V2 (reserva)','1 ene–10 oct 2025',r25.roi),('BTC','1 ene–10 oct 2025',V1[2025]['btc']),
 ('V1 Actual','1 ene–10 oct 2026',V1[2026]['actual']),('V1 Dinámico','1 ene–10 oct 2026',V1[2026]['dinamico']),('V1 Indexado','1 ene–10 oct 2026',V1[2026]['indexado']),('V2 (reserva)','1 ene–10 oct 2026',r26.roi),('BTC','1 ene–10 oct 2026',V1[2026]['btc'])])
v1table=f'<div class="tw"><table><thead><tr><th>Simulador</th><th>Tramo</th><th>ROI</th></tr></thead><tbody>{v1rows}</tbody></table></div>'
BODY=f'''
<title>Simulador en frío V3 y reserva V2</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{css}</style>
<div class="page">
<header class="hero">
<span class="eyebrow">Trading Bots · Simulador en frío V3 · Núcleo con filtro de tendencia + reserva V2 2025-2026</span>
<h1>El filtro de tendencia protege en 2022 pero cuesta casi todo el rendimiento: V3 cumple {n_ok} de 6 criterios</h1>
<p class="lead">Doce corridas (V3 y su control sin filtro, 2019-2024), criterios fijados antes de correr y dinero ficticio. Quitar satélites y estables sí bajó costos y caídas; el filtro SMA200 casi elimina 2022 (−0.4 % contra −30 %), pero deja fuera los rallies, repite entradas y salidas en 2021 y empeora la caída ese año.</p>
<div class="tiles">
<div class="tile"><div class="k">Criterios cumplidos V3</div><div class="v">{n_ok} de 6</div><div class="k">D2 y D4</div></div>
<div class="tile"><div class="k">ROI encadenado 2019-2024</div><div class="v"><span class="pos">{ch(V3.roi):+.0f}%</span></div><div class="k">sin filtro {ch(RF.roi):+.0f} % · V2 {ch(V2.roi):+.0f} % · BTC {ch(V3.btc_roi):+,.0f} %</div></div>
<div class="tile"><div class="k">Peor caída V3</div><div class="v"><span class="neg">−47.3%</span></div><div class="k">2021 · sin filtro −44.9 %</div></div>
<div class="tile"><div class="k">Peor año (2022)</div><div class="v"><span class="pos">−0.4%</span></div><div class="k">sin filtro −29.7 % · BTC −64.2 %</div></div>
</div>
</header>

<section id="resumen"><h2>Resumen ejecutivo</h2>
<ul class="k">
<li><b>V3 incumple 4 de 6 criterios.</b> Caída máxima (D1, −47 % en 2021), costos (D3), filtro (D5) y mejora frente a V2 (D6). Cumple consistencia (D2, 4 de 6 años positivos) y caída menor que BTC (D4, 6 de 6).</li>
<li><b>El filtro hace lo que promete, pero cuesta demasiado.</b> Reduce la caída máxima en 5 de 6 años y en 2022 se queda casi todo el año en efectivo (el filtro estuvo apagado todo el año). Pero el ROI encadenado cae de +{ch(RF.roi):.0f} % (sin filtro) a +{ch(V3.roi):.0f} %, y el Calmar (retorno entre caída) empeora en 4 de 6 años.</li>
<li><b>2021 es el caso adverso:</b> el filtro se apagó recién el 20 de mayo (después del desplome) y se encendió y apagó 10 veces; cada reinicio recompra el índice y paga costos (216 USDT solo en el índice). Resultado: caída −47 % (peor que sin filtro) y costos de 3.4 % del capital.</li>
<li><b>Lo que sí funcionó fue quitar lo que no aportaba.</b> V3 sin filtro (V3-ref) tiene menos caída que V2 en los 6 años (−45 % a −14 % frente a −45 % a −17 %), costos de 0.3 % a 1.1 % (V2: 1.4 % a 2.5 %) y ROI encadenado +{ch(RF.roi):.0f} % frente a +{ch(V2.roi):.0f} % de V2. Ojo: esto no era un criterio del pre-registro y se ve después de los datos; es una comparación de ablación, no evidencia nueva.</li>
<li><b>Reserva V2 en 2025-2026</b> (corrida única, carry de KuCoin): hasta el 10 de octubre, +{r25.roi:.1f} % en 2025 y {r26.roi:.1f} % en 2026, contra −10.7 % / −10.1 % de V1 Actual, −30.0 % / −18.6 % de V1 Dinámico y −3.2 % / −4.1 % de V1 Indexado. Cayó menos que BTC en ambos (−18 % y −20 % contra −31 % y −40 %).</li>
</ul>
<div class="box"><b>Conclusión.</b> Según el pre-registro (§6), el filtro no pasa a vivo porque D5 falla: la candidata para paper trading es V3-ref (núcleo sin filtro, sin satélites ni estables, con carry 40 %). Su problema sin resolver sigue siendo la caída del beta: −43 % en 2019 y −45 % en 2021. Un filtro lento de 200 días no lo resuelve; cualquier otra idea (menos peso en beta, otro filtro) se pre-registra y se prueba solo hacia adelante.</div>
</section>

<section id="criterios"><h2>1. Qué se probó y cómo salió</h2>
<p>V3 es el núcleo de V2 sin satélites ni estables: DCA 20 %, índice Top-25 30 % (ambos con filtro de tendencia: solo invierten cuando BTC cierra sobre su media de 200 días), carry BTC 25 %, carry ETH 15 % y 10 % en efectivo. V3-ref es idéntico sin el filtro; sirve para aislar su efecto. Hipótesis y criterios se subieron al repositorio antes de correr (BACKTEST_V3.md).</p>
{crit}
<p class="sm">Un criterio incumplido se reporta como incumplido. No se movió ningún parámetro. Los umbrales de D1 y D3 se eligieron conociendo el resultado de V2, y los años ya se habían visto: esto es una prueba de coherencia, no validación fuera de muestra.</p>
</section>

<section id="anual"><h2>2. Resultados por año</h2>
{fig("g1_roi","ROI anual de V3, V3-ref, V2 y BTC")}
{yeartable}
{fig("g3_curves","Curvas de capital base 100 de V3, V3-ref y BTC por año","En 2022 el filtro deja a V3 plano; en 2021 la curva azul se aplana de mayo a agosto y sigue sin recuperar.")}
</section>

<section id="riesgo"><h2>3. Riesgo</h2>
{fig("g2_dd","Caída máxima por año de V3, V3-ref y V2 con el límite de −35 por ciento")}
<ul class="k">
<li>El filtro mejora la caída en 2019 (−29 % contra −43 %), 2020, 2022, 2023 y 2024, pero 2021 es −47 % contra −45 %.</li>
<li>En 2019 hay 50 % del capital sin trabajar (sin carry) y aun así V3 pierde −3.2 %: el filtro compra tarde y vende tarde, con costos del 0.5 %.</li>
<li>Los Sharpe de 2022 (−2.8) no significan mucho: el portafolio estuvo plano (−0.4 % con volatilidad casi nula).</li>
</ul>
</section>

<section id="costos"><h2>4. Costos</h2>
{fig("g4_costs","Comisiones y deslizamiento por año de V3, V3-ref y V2 con el límite de 1 por ciento")}
<ul class="k">
<li><b>Sin filtro (ref):</b> de 0.3 % a 1.1 %; quitar los cuatro satélites y las estables elimina la mayor parte del costo de V2. Solo 2021 pasa de 1.0 % (1.11 %).</li>
<li><b>Con filtro:</b> 0.5 % a 3.4 %. Cada vez que el filtro se apaga se vende todo; al encenderse se recompra el índice entero. En 2021 el índice pagó 216 USDT.</li>
</ul>
</section>

<section id="pnl"><h2>5. De dónde sale el resultado</h2>
{fig("g5_pnl","PnL en USDT por grupo de bots y año de V3")}
{pnltable}
<ul class="k">
<li><b>Sigue siendo beta.</b> El índice y el DCA producen casi todo el PnL (en 2020, 7,000 de 7,533). El filtro les quita entre la mitad (2020) y tres cuartas partes (2021) del PnL, y evita la pérdida de 2022.</li>
<li><b>El carry duplicó su aporte</b> (2020 +512, 2021 +808, 2022 −35, 2023 +110, 2024 +257 USDT) pero sigue siendo 0-8 % del capital total al año. En 2022 el carry BTC no operó y el ETH perdió 35.</li>
</ul>
</section>

<section id="reserva"><h2>6. Reserva: V2 en 2025 y 2026 frente a V1</h2>
{fig("g6_reserva","ROI de los simuladores V1, de V2 y de BTC en 1 de enero a 10 de octubre de 2025 y 2026")}
{v1table}
<ul class="k">
<li><b>Frente a V1, V2 es mejor</b> en el mismo tramo: +{r25.roi:.1f} % contra −3.2 % a −30.0 % en 2025 y {r26.roi:.1f} % contra −4.1 % a −18.6 % en 2026. Probablemente por menos operaciones, topes duros y el índice trimestral (la causa principal de V1 era el costo), aunque aquí no se aisló cada pieza.</li>
<li><b>Frente a BTC no:</b> en 2025 gana la mitad (+{r25.roi:.1f} % contra +20.5 %); en 2026 lo supera (−0.7 % contra −5.3 %, con una caída máx. de −20 % contra −40 %).</li>
<li><b>Año 2025 completo:</b> {f25.roi:+.1f} % (BTC {f25.btc_roi:+.1f} %), caída máx. {f25.maxdd:.1f} % (BTC {f25.btc_dd:.1f} %). Entre el 10 de octubre y el 31 de diciembre perdió 15 puntos de ROI.</li>
<li><b>Criterios (C1-C4, C6):</b> C1 ✓ (caída ≤ 40 %); C3 ✗ en 2025 ({r25.cost_pct:.2f} % al corte, {f25.cost_pct:.2f} % el año) y ✓ en 2026 (1.28 %); C4 ✓ (cae menos que BTC en ambos); C6 ✓ (peor satélite −20.1 %). C5 (reportado): el interruptor con B − A = +56 USDT en 2025 y +35 en 2026, con ganancia en 3 de 4 comparaciones, pequeño y con pocos datos.</li>
<li><b>El carry apenas operó</b> en 2025-2026 con datos de KuCoin: +2 y 0 USDT (BTC), −2 y −1 (ETH), con costos de 28-32 USDT en 2025. Con el funding actual, ponerle 40 % del capital a carry (V3) significaría capital ocioso.</li>
</ul>
</section>

<section id="recomendaciones"><h2>7. Recomendaciones</h2>
<ol class="rec">
<li><b>Descartar el filtro SMA200 tal como está.</b> D5 falla: protege el año malo pero cuesta rendimiento y repite operaciones en mercados laterales. No se ajusta la ventana con estos datos (sería sobreajuste).</li>
<li><b>Llevar V3-ref a paper trading en vivo</b> (núcleo sin filtro, sin satélites ni estables) junto a los simuladores actuales, sin tocarlos. Es la única prueba no contaminada. Antes hay que decidir el peso del carry, porque en 2025-2026 casi no opera.</li>
<li><b>Atacar la caída del beta con una hipótesis nueva, pre-registrada y solo hacia adelante</b> (menos peso en índice/DCA, o un filtro de volatilidad en lugar de tendencia). No con más backtests sobre 2019-2026.</li>
<li><b>Revisar el carry en vivo:</b> medir cuánto funding cobra realmente en KuCoin y Binance antes de darle 40 % del capital.</li>
</ol>
</section>

<section id="limites"><h2>8. Límites y sesgos</h2>
<ul class="k">
<li><b>Contaminación:</b> estructura, pesos (20/30/25/15/10) y umbrales salen de mirar 2019-2026. V3 no es validación fuera de muestra.</li>
<li><b>Ablación post hoc:</b> la comparación V3-ref contra V2 no estaba en los criterios y se hizo después de ver los datos.</li>
<li><b>Supervivencia, carry con datos de Binance en 2020-2024, liquidez constante, sin impuestos:</b> como en V2.</li>
<li><b>Un solo valor del filtro</b> (200 días), el convencional, sin probar otros.</li>
<li><b>El filtro empieza apagado si no hay historial</b> (no ocurrió); en 2019 el cálculo de días encendidos no se hizo.</li>
</ul>
<div class="two">
<div class="card"><h3>Para tu perfil</h3><p class="sm">Pre-registrar, usar un control (V3-ref) para aislar el efecto del filtro y reportar un resultado negativo sin maquillarlo es el tipo de rigor que se valora en roles cuantitativos y de riesgo. La ablación (quitar piezas para ver qué aportan) también.</p></div>
<div class="card"><h3>Para la disciplina</h3><p class="sm">Una regla que evita el peor año se siente como una victoria, pero un año no la valida: aquí el mismo filtro empeoró 2021. La tentación ahora es afinar la ventana hasta que “funcione”; no hacerlo es la parte difícil.</p></div>
</div>
<p class="sm">Datos y código: repositorio Nuv51/crypto-paper-sim (pre-registro BACKTEST_V3.md, resultados BACKTEST_V3_RESULTADOS.md, ramas backtest-v3 y backtest-v2-reserva, análisis en backtest_v3/analysis).</p>
</section>
</div>
'''
open('report_v3.html','w').write(f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>{BODY}</body></html>'); print('ok')
