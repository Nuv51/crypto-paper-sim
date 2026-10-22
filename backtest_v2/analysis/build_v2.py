import base64, html, re, pickle, pandas as pd, numpy as np
R=pickle.load(open('../res.pkl','rb')); P,bt,tw=R['P'],R['bt'],R['tw']
css=re.search(r'<style>(.*?)</style>',open('/home/claude/analysis/report_full.html').read(),re.S).group(1)
Y=list(range(2019,2025))
BTCS=[1.27,2.25,0.97,-1.34,2.34,1.68]
def fig(n,alt,cap=''):
    b=base64.b64encode(open(f'fig/{n}.png','rb').read()).decode()
    return f'<figure class="fig"><img src="data:image/png;base64,{b}" alt="{html.escape(alt)}">{f"<figcaption>{cap}</figcaption>" if cap else ""}</figure>'
def tone(v): return 'pos' if v>0.05 else 'neg' if v<-0.05 else 'neu'
def cell(v,d=1,suf='%',sign=True):
    if v is None or (isinstance(v,float) and np.isnan(v)): return '<td class="num neu">—</td>'
    return f'<td class="num {tone(v)}">{v:+,.{d}f}{suf}</td>' if sign else f'<td class="num">{v:,.{d}f}{suf}</td>'
# tabla por año
rows=''
for i,y in enumerate(Y):
    r=P.loc[y]
    rows+=f'<tr><th scope="row">{y}</th>{cell(r.roi)}<td class="num neg">{r.maxdd:.1f}%</td><td class="num">{r.sharpe:.2f}</td>{cell(r.btc_roi)}<td class="num neg">{r.btc_dd:.1f}%</td><td class="num">{BTCS[i]:.2f}</td>{cell(r.eth_roi)}{cell(r.ew_roi)}<td class="num">{int(r.n_index)}</td></tr>'
yeartable=f'<div class="tw"><table><thead><tr><th>Año</th><th>ROI V2</th><th>Caída máx. V2</th><th>Sharpe V2</th><th>ROI BTC</th><th>Caída máx. BTC</th><th>Sharpe BTC</th><th>ROI ETH</th><th>Índice igual peso*</th><th>Monedas en índice</th></tr></thead><tbody>{rows}</tbody></table></div><p class="sm">*Sin costos. ROI y caída máxima sobre los 10,000 completos (el efectivo no asignado cuenta). Sharpe diario anualizado sin tasa libre. Cada año se corre aparte, empezando el 1 de enero.</p>'
# PnL por bot
NMB={'v01_dca':'DCA BTC+ETH','v02_carry_btc':'Carry BTC','v03_carry_eth':'Carry ETH','v04_stable':'Estables (peg)','v05_index_cap25':'Índice Top-25 (trimestral)','v06_grid_eth':'Grid ETH · A (sin interruptor)','v07_grid_eth_gate':'Grid ETH · B (con interruptor)','v08_trend':'Tendencia · A','v09_trend_gate':'Tendencia · B'}
pv=bt.pivot(index='bot',columns='year',values='pnl'); rows=''
for b in NMB:
    rows+=f'<tr><th scope="row">{NMB[b]}</th>'+''.join(cell(pv.loc[b,y] if y in pv.columns and not np.isnan(pv.loc[b,y]) else None,0,'') for y in Y)+f'<td class="num">{pv.loc[b].sum():+,.0f}</td></tr>'
rows+='<tr><th scope="row">Total portafolio</th>'+''.join(cell(P.loc[y,'pnl'],0,'') for y in Y)+f'<td class="num"><b>{P.pnl.sum():+,.0f}</b></td></tr>'
pnltable=f'<div class="tw"><table><thead><tr><th>PnL en USDT</th>'+''.join(f'<th>{y}</th>' for y in Y)+'<th>Suma</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
# criterios
CR=[('C1','Caída máxima ≤ 40 % cada año','−43.9 % (2019) y −45.0 % (2021); los otros cuatro entre −16.8 % y −33.8 %',0),
('C2','ROI > 0 en ≥ 4 de 6 años','5 de 6 (solo 2022 negativo)',1),
('C3','Comisiones + deslizamiento < 1.5 % del capital por año','1.4 % a 2.5 %; solo 2024 cumple (1.36 %); solo comisiones: 1.05 % a 1.85 %',0),
('C4','Caída máxima menor que la de BTC en ≥ 5 de 6 años','6 de 6',1),
('C5','El interruptor aporta: B − A > 0 y B gana ≥ 8 de 12','Suma +23 USDT; B gana 4, empata 2, pierde 6',0),
('C6','Ningún satélite pierde > 25 % de su capital','Peor caso −21.8 %',1)]
crow=''.join(f'<tr><th scope="row">{c}</th><td>{d}</td><td>{e}</td><td class="{"pos" if ok else "neg"}"><b>{"✓ Cumple" if ok else "✗ No cumple"}</b></td></tr>' for c,d,e,ok in CR)
crit=f'<div class="tw"><table><thead><tr><th>#</th><th>Criterio fijado antes de correr</th><th>Resultado</th><th></th></tr></thead><tbody>{crow}</tbody></table></div>'
# V1 vs V2
v1rows=''.join(f'<tr><th scope="row">{a}</th><td>{b}</td>{cell(c)}{cell(d)}{cell(c-d,0," pp")}</tr>' for a,b,c,d in [
 ('V1 Actual (1 h)','1 ene–10 oct 2025',-10.7,20.5),('V1 Dinámico (15 min)','1 ene–10 oct 2025',-30.0,20.5),('V1 Indexado','1 ene–10 oct 2025',-3.2,20.5),
 ('V1 Actual (1 h)','1 ene–10 oct 2026',-10.1,-5.3),('V1 Dinámico (15 min)','1 ene–10 oct 2026',-18.6,-5.3),('V1 Indexado','1 ene–10 oct 2026',-4.1,-5.3)]+
 [('V2 low cost',f'año {y}',P.loc[y,'roi'],P.loc[y,'btc_roi']) for y in Y])
v1table=f'<div class="tw"><table><thead><tr><th>Simulador</th><th>Periodo</th><th>ROI</th><th>BTC</th><th>ROI − BTC</th></tr></thead><tbody>{v1rows}</tbody></table></div>'
n_ok=sum(c[3] for c in CR)
BODY=f'''
<title>Simulador en frío 2019-2024 V2</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>{css}</style>
<div class="page">
<header class="hero">
<span class="eyebrow">Trading Bots · Simulador en frío 2019-2024 V2 · Reestructurado low cost</span>
<h1>Gana en 5 de 6 años, pero es sobre todo beta del mercado y cumple {n_ok} de 6 criterios</h1>
<p class="lead">Seis corridas independientes (una por año, 10,000 USDT ficticios cada 1 de enero), criterios fijados antes de correr y dinero ficticio. La estructura low cost cae menos que BTC y no pierde mucho en el año malo, pero no controla la caída máxima ni los costos, y el interruptor de volatilidad no aporta.</p>
<div class="tiles">
<div class="tile"><div class="k">Años con ROI positivo</div><div class="v"><span class="pos">5</span> de 6</div><div class="k">solo 2022 negativo</div></div>
<div class="tile"><div class="k">ROI encadenado</div><div class="v"><span class="pos">+468%</span></div><div class="k">BTC: +2,428 %</div></div>
<div class="tile"><div class="k">Peor caída del año</div><div class="v"><span class="neg">−45.0%</span></div><div class="k">2021 · BTC −54.7 %</div></div>
<div class="tile"><div class="k">Criterios cumplidos</div><div class="v">{n_ok} de 6</div><div class="k">C2, C4 y C6</div></div>
</div>
</header>

<section id="resumen"><h2>Resumen ejecutivo</h2>
<ul class="k">
<li><b>Ganó en 5 de 6 años:</b> +1.9 %, +128 %, +89 %, −32 %, +42 % y +33 %. Cayó menos que BTC en los 6 años (en 2022 perdió la mitad: −32 % contra −64 %).</li>
<li><b>Pero captura poco del alza.</b> En 2020, 2023 y 2024 obtuvo menos de la mitad del ROI de BTC. El encadenado es +468 % contra +2,428 %. Superó a BTC en ROI solo en 2021 y 2022, y en Sharpe solo en 2021.</li>
<li><b>El resultado es el mercado.</b> El índice Top-25 y el DCA explican casi todo el PnL (y casi toda la caída: el índice llegó a −62 % a −70 % de caída propia en 2019-2022). El carry y las estables dan estabilidad, no volumen.</li>
<li><b>Los satélites restan.</b> Los 4 bots de grid y tendencia pierden en 4 de 6 años. Antes de costos suman +321 USDT en seis años; los costos suman 788 y el neto queda en −467.</li>
<li><b>El interruptor de volatilidad no discrimina.</b> BTC superó 40 % de volatilidad el 75 % de los días (99 % en 2021), así que casi siempre estuvo encendido. Los gemelos con y sin interruptor difieren por ruido.</li>
<li><b>Los topes duros funcionaron:</b> ningún satélite perdió más de 21.8 % de su capital.</li>
<li><b>¿Mejor que V1?</b> No se puede afirmar: V1 se midió en 2025-2026 (1 ene–10 oct) y V2 en 2019-2024. Está mejor diseñado (menos rotación, límites duros), pero el rendimiento no está demostrado en igualdad de condiciones.</li>
</ul>
<div class="box"><b>Conclusión.</b> V2 confirma el diagnóstico de V1: lo que aporta valor es exposición al mercado con costo bajo y gestión de riesgo; lo que pretendía aportar “edge” (satélites e interruptor) no lo demuestra. La prueba limpia que queda es el paper trading en vivo (desde el 16 de octubre de 2026) y la comparación directa en 2025-2026, que está reservada en el pre-registro.</div>
</section>

<section id="criterios"><h2>1. Qué se probó y cómo salió</h2>
<p>La estructura V2 es un solo simulador con núcleo de bajo costo (DCA 20 %, carry BTC y ETH 20 %, estables 10 %, índice Top-25 con rebalanceo trimestral 30 %) y cuatro satélites de 5 % cada uno (grid ETH y tendencia, cada uno con gemelo con y sin interruptor de volatilidad), con tope de pérdida acumulada de 20 % y presupuesto de rotación mensual. Las hipótesis y los seis criterios numéricos se escribieron y se subieron al repositorio antes de correr.</p>
{crit}
<p class="sm">Un criterio incumplido se reporta como incumplido. No se movió ningún parámetro después de ver resultados.</p>
</section>

<section id="anual"><h2>2. Resultados por año</h2>
{fig("g1_roi","ROI anual de V2 contra BTC, ETH e índice de igual peso, 2019 a 2024")}
{yeartable}
{fig("g2_curves","Curva de capital base 100 de V2 contra BTC en cada año","V2 amortigua las caídas (2022) y se queda corto en los rallies (2020, 2023, 2024).")}
</section>

<section id="riesgo"><h2>3. Riesgo: cae menos que BTC, pero cruza el límite dos veces</h2>
{fig("g3_dd","Caída máxima de V2 y de BTC en cada año con el límite de −40 por ciento")}
<ul class="k">
<li>Cae menos que BTC los 6 años (C4 cumplido), con 5 a 34 puntos de diferencia, pero en 2019 (−43.9 %) y 2021 (−45.0 %) pasa el límite de −40 % (C1 incumplido).</li>
<li>El Sharpe de V2 supera al de BTC solo en 2021 (1.37 contra 0.97); la caída más chica no se traduce en mejor relación riesgo-retorno.</li>
<li>La caída viene del propio índice (−62 % a −70 % en cuatro años) y del DCA (−46 % a −57 % en 2019, 2021 y 2022): es 50 % del capital en beta de cripto sin protección.</li>
</ul>
</section>

<section id="pnl"><h2>4. De dónde sale el resultado</h2>
{fig("g4_pnl","PnL en USDT por grupo de bots y año")}
{pnltable}
<ul class="k">
<li><b>Núcleo = beta.</b> Índice más DCA producen el PnL en los años buenos y también la pérdida de 2022.</li>
<li><b>Carry y estables aportan poco volumen</b> (carry BTC de 0 a +229 y carry ETH de −17 a +176 según el año, ROI de 0 a +23 % sobre su capital; estables entre 0 y +13). En 2022 el carry BTC no operó: el funding no cumplió el umbral de entrada.</li>
<li><b>2019 sin carry y 2023 sin estables:</b> Binance Futures solo ofrece historial desde 2020 y Binance dejó de listar USDC, TUSD y USDP contra USDT en marzo de 2023. Ese capital quedó en efectivo y cuenta en el ROI.</li>
</ul>
</section>

<section id="costos"><h2>5. Costos y satélites</h2>
{fig("g6_costs","Costos del año por grupo de bots y límite pre-registrado","Comisiones más deslizamiento estimado con los niveles de liquidez de cada moneda.")}
{fig("g5_sat","Satélites: ganancia antes de costos, costos y neto por año; y diferencia entre gemelos","")}
<ul class="k">
<li><b>Costos de 136 a 245 USDT por año</b> (1.4 % a 2.5 % del capital; solo comisiones 1.05 % a 1.85 %): C3 incumplido en 5 de 6 años (solo 2024 cumple).</li>
<li><b>Los satélites concentran los costos:</b> 86 a 161 USDT por año sobre 2,000 de capital, más de lo que ganan antes de costos. <b>El carry es barato:</b> 5 a 34 USDT por año por bot (9 % a 12 % de su ganancia bruta en 2020, 2021 y 2024; más en 2022-2023, cuando operó poco), y rindió +256, +404, −17, +55 y +129 USDT (2020-2024) con caída máxima de 3 % o menos.</li>
<li><b>En 2019 las estables</b> gastaron 88 USDT en costos sobre una ganancia bruta de ~101 (neto +13): con comisión de 0.1 % por operación el umbral de 0.30 % deja poco margen.</li>
<li><b>Los límites duros sí protegen:</b> el tope de pérdida retiró a la tendencia (al menos a uno de los gemelos) en 2019, 2023 y 2024, con pérdidas cercanas a −20 %, y el presupuesto de rotación pausó a los satélites con frecuencia (4× el capital agotado en pocos días en enero de 2021). Es protección, no rentabilidad.</li>
</ul>
</section>

<section id="gate"><h2>6. El interruptor de volatilidad (hipótesis H2)</h2>
{fig("g7_gate","Porcentaje de días con el interruptor encendido por año")}
<p>Con el umbral pre-registrado (volatilidad de BTC a 14 días mayor que 40 % anualizada) el interruptor estuvo encendido entre 48 % y 99 % de los días. En 2021 los gemelos fueron idénticos. La diferencia entre gemelos (grid: +56, −27, 0, −46, +80, −34 USDT; tendencia: −3, −94, 0, +30, +69, −7) cambia de signo sin patrón. Cambiar el umbral con estos datos sería ajustar a la muestra, por eso no se hizo; una hipótesis nueva solo se puede probar hacia adelante.</p>
</section>

<section id="v1"><h2>7. ¿Mejor que V1?</h2>
<div class="warn"><b>No son comparables en ROI absoluto.</b> V1 se midió del 1 de enero al 10 de octubre de 2025 y 2026 (mercado plano o bajista); V2, en años completos de 2019 a 2024, con cuatro años de BTC +94 % a +302 %. La referencia justa es el ROI frente a BTC en cada periodo, y solo como patrón.</div>
{fig("g8_vs_btc","ROI menos ROI de BTC en puntos porcentuales para V1 y V2")}
{v1table}
<ul class="k">
<li><b>Mejor diseñado:</b> V1 perdió en los 6 resultados (3 simuladores × 2 años), con la causa raíz en el costo de operar (85 % de la variación del ROI). V2 elimina las familias de costo alto (market making, ML, breakout) y pone topes duros; su peor año fue −32 %, con BTC −64 %.</li>
<li><b>No demostrado en rendimiento:</b> el simulador indexado de V1, lo más parecido al núcleo de V2, rindió −3.2 % y −4.1 % en un mercado plano; V2 no se ha corrido en esos periodos.</li>
<li><b>Prueba justa pendiente:</b> correr V2 sobre 2025 y 2026 (reserva del pre-registro, una sola vez y sin cambios) y compararlo con V1 en el mismo tramo.</li>
</ul>
</section>

<section id="estadistica"><h2>8. Orientación estadística (no es prueba)</h2>
{fig("g9_boot","Distribución de los 72 retornos mensuales de V2 y de años posibles remuestreando esos meses")}
<p>En 72 meses, 40 fueron positivos; la media mensual es +3.0 %, el peor mes −14.9 % y el mejor +36.7 %. Remuestreando años de 12 meses de esos 72: percentil 5 = −27 %, mediana +33 %, percentil 95 = +150 %, y 22 % de probabilidad de un año negativo. Todo depende de 2020-2021, y seis años son un solo ciclo de mercado.</p>
</section>

<section id="recomendaciones"><h2>9. Recomendaciones</h2>
<ol class="rec">
<li><b>No usar dinero real con estas reglas.</b> Hay criterios incumplidos y los datos ya se vieron.</li>
<li><b>Correr V2 en 2025 y 2026 (la reserva).</b> Es la comparación directa con V1: mismos periodos, mismos benchmarks, una sola corrida sin cambios.</li>
<li><b>Quitar o reducir mucho los satélites.</b> Perdieron en 4 de 6 años y los costos superan lo que ganan antes de costos. Si se conservan, con un tope de capital muy bajo.</li>
<li><b>Reducir la caída del núcleo con una hipótesis nueva</b> (menos peso en el índice o un filtro de tendencia sobre el núcleo), pre-registrada y probada solo hacia adelante.</li>
<li><b>Mantener el carry y darle más peso:</b> fue lo más consistente (positivo en 8 de 10 bot-años, caída ≤ 3 %, costos bajos). Su límite es el volumen: aporta 1-2 % de ROI al año.</li>
<li><b>No ajustar el interruptor con estos datos.</b> Si se quiere un régimen, definirlo antes y evaluarlo en vivo.</li>
<li><b>Poner V2 en paper trading en vivo</b> como cuarto simulador: es la única prueba que ya no está contaminada.</li>
</ol>
</section>

<section id="limites"><h2>10. Límites y sesgos</h2>
<ul class="k">
<li><b>Contaminación:</b> conocemos la historia 2019-2024, y V2 y el umbral de 40 % salieron del análisis de 2025-2026. Sirve para ver si la estructura sobrevive a otro ciclo, no como evidencia limpia.</li>
<li><b>Supervivencia:</b> exigir cotizar todo el año deja fuera a quienes dejaron de cotizar o cambiaron de símbolo. En 2024, MATIC (cambió a POL) y XMR (deslistada) habrían entrado al Top-25. En 2019-2021 no hubo excluidas de este tipo.</li>
<li><b>Universo 2019 de 15 monedas</b> (pocas tenían 180 días de historial en Binance).</li>
<li><b>Carry con datos de Binance Futures:</b> comisión y funding distintos a KuCoin; sin historial antes de 2020.</li>
<li><b>Deslizamiento por nivel de liquidez actual,</b> no la real de 2019-2020. Sin impuestos. Arbitraje XRP no evaluado.</li>
<li><b>Fallo técnico del primer intento:</b> 2021 falló por ~41 horas sin velas en Binance. Se corrigió solo el código (arranque por fecha, ventana del interruptor por hora), se repitieron las seis corridas con el mismo código y se anotó en el pre-registro. Se habían visto los ROI de los otros cinco años sin analizar.</li>
</ul>
<div class="two">
<div class="card"><h3>Para tu perfil</h3><p class="sm">Pre-registrar hipótesis y criterios numéricos, usar gemelos A/B para aislar un efecto, medir costos y reportar lo que falla sin reinterpretarlo son habilidades de roles cuantitativos, de riesgo y de estrategia.</p></div>
<div class="card"><h3>Para la disciplina</h3><p class="sm">Ya vimos 2019 a 2026: cualquier ajuste sobre esos datos es ajustar a la muestra. La paciencia aquí es esperar a que el vivo acumule datos nuevos antes de cambiar nada.</p></div>
</div>
<p class="sm">Datos y código: repositorio Nuv51/crypto-paper-sim (pre-registro BACKTEST_V2_2019_2024.md, resultados BACKTEST_V2_2019_2024_RESULTADOS.md, rama backtest-v2, análisis en backtest_v2/analysis).</p>
</section>
</div>
'''
full=f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body>{BODY}</body></html>'
open('report_v2.html','w').write(full); print(len(full)/1e6,'MB')
