"""Sondeo de red para el observatorio de mercado (fases 1-3): ¿qué fuentes públicas alcanza GitHub Actions?
Solo lectura, sin llaves. Escribe probe_market_results.json (estado HTTP, tamaño, tipo y primeras líneas)."""
import json
import time

import requests

NOW = int(time.time() * 1000)
H = 3_600_000
UA = {"User-Agent": "Mozilla/5.0 (compatible; crypto-paper-sim research probe; +https://github.com/Nuv51/crypto-paper-sim)"}
TESTS = {
    # fase 1 · flujo de órdenes y derivados
    "binance_klines_taker_field": "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=3",
    "binance_depth": "https://data-api.binance.vision/api/v3/depth?symbol=BTCUSDT&limit=100",
    "binance_aggtrades": "https://data-api.binance.vision/api/v3/aggTrades?symbol=BTCUSDT&limit=5",
    "okx_open_interest": "https://www.okx.com/api/v5/public/open-interest?instType=SWAP&instId=BTC-USDT-SWAP",
    "okx_oi_volume_hist": "https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=1D",
    "okx_long_short_ratio": "https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1D",
    "okx_taker_volume": "https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1D",
    "okx_liquidations": "https://www.okx.com/api/v5/public/liquidation-orders?instType=SWAP&uly=BTC-USDT&state=filled",
    "okx_books": "https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=20",
    "okx_funding_hist_long": "https://www.okx.com/api/v5/public/funding-rate-history?instId=ETH-USDT-SWAP&limit=100",
    "kucoin_contracts_active": "https://api-futures.kucoin.com/api/v1/contracts/active",
    "kucoin_fut_open_interest": "https://api-futures.kucoin.com/api/v1/contracts/XBTUSDTM",
    "deribit_dvol": f"https://www.deribit.com/api/v2/public/get_volatility_index_data?currency=BTC&start_timestamp={NOW - 72 * H}&end_timestamp={NOW}&resolution=3600",
    "deribit_options_summary": "https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option",
    "coinbase_ticker_btcusd": "https://api.exchange.coinbase.com/products/BTC-USD/ticker",
    "defillama_stablecoins": "https://stablecoins.llama.fi/stablecoins?includePrices=false",
    "defillama_stablecoin_chart": "https://stablecoins.llama.fi/stablecoincharts/all?stablecoin=1",
    "coingecko_global": "https://api.coingecko.com/api/v3/global",
    "blockchain_com_chart": "https://api.blockchain.info/charts/n-transactions?timespan=30days&format=json",
    "mempool_fees": "https://mempool.space/api/v1/fees/recommended",
    # fase 2 · anuncios y calendario
    "binance_announcements": "https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&catalogId=48&pageNo=1&pageSize=5",
    "okx_announcements": "https://www.okx.com/api/v5/support/announcements?annType=announcements-new-listings",
    "kucoin_announcements": "https://api.kucoin.com/api/v3/announcements?annType=new-listings&lang=en_US&pageSize=5",
    "coinbase_status_blog_rss": "https://www.coinbase.com/blog/rss",
    "fed_fomc_calendar": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
    "bls_cpi_schedule": "https://www.bls.gov/schedule/news_release/cpi.htm",
    "fed_ics_calendar": "https://www.federalreserve.gov/newsevents/calendar.htm",
    # fase 3 · noticias y redes
    "rss_coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "rss_cointelegraph": "https://cointelegraph.com/rss",
    "rss_decrypt": "https://decrypt.co/feed",
    "rss_theblock": "https://www.theblock.co/rss.xml",
    "rss_bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
    "rss_cryptoslate": "https://cryptoslate.com/feed/",
    "gdelt_doc": "https://api.gdeltproject.org/api/v2/doc/doc?query=bitcoin&mode=artlist&maxrecords=5&format=json",
    "cryptopanic_public": "https://cryptopanic.com/api/free/v1/posts/?public=true",
    "reddit_json": "https://www.reddit.com/r/CryptoCurrency/new.json?limit=5",
    "reddit_rss": "https://www.reddit.com/r/CryptoCurrency/new/.rss?limit=5",
    "reddit_old_rss": "https://old.reddit.com/r/Bitcoin/new/.rss",
    "bluesky_search": "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=bitcoin&limit=5",
    "stocktwits_btc": "https://api.stocktwits.com/api/2/streams/symbol/BTC.X.json",
    "telegram_public_preview": "https://t.me/s/whale_alert_io",
    "hackernews_algolia": "https://hn.algolia.com/api/v1/search_by_date?query=bitcoin&tags=story&hitsPerPage=3",
}
out = {}
for name, url in TESTS.items():
    t0 = time.time()
    try:
        r = requests.get(url, timeout=25, headers=UA)
        body = r.text
        out[name] = {"status": r.status_code, "ms": int((time.time() - t0) * 1000), "bytes": len(body),
                     "ctype": r.headers.get("content-type", "")[:60], "head": body[:240].replace("\n", " ")}
    except Exception as e:
        out[name] = {"status": None, "error": f"{type(e).__name__}: {e}"[:300]}
    print(name, out[name].get("status"), out[name].get("bytes", ""), out[name].get("error", ""), flush=True)
with open("probe_market_results.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
