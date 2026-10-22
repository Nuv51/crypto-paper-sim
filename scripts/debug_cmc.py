import re, json, sys, requests
r = requests.get("https://coinmarketcap.com/historical/20181230/", headers={"User-Agent": "Mozilla/5.0 (compatible; research)"}, timeout=60)
t = r.text
print("HTTP", r.status_code, "bytes", len(t))
print("tags: table", t.count("<table"), "tr", t.count("<tr"), "tbody", t.count("<tbody"))
m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
def tree(n, d=0, key="root"):
    pad = "  " * d
    if isinstance(n, dict):
        print(f"{pad}{key}: dict({len(n)}) keys={list(n)[:12]}")
        if d < 4:
            for k, v in list(n.items())[:14]:
                tree(v, d + 1, k)
    elif isinstance(n, list):
        print(f"{pad}{key}: list({len(n)}) first={type(n[0]).__name__ if n else None}")
        if n and d < 4:
            tree(n[0], d + 1, key + "[0]")
    else:
        print(f"{pad}{key}: {type(n).__name__} {str(n)[:60]!r}")
if m:
    data = json.loads(m.group(1)); tree(data)
for kw in ("Bitcoin", "BTC"):
    for mm in list(re.finditer(kw, t))[:2]:
        print("---", kw, "contexto:", t[max(0, mm.start() - 300): mm.start() + 500].replace("\n", " ")[:800])
i = t.find("<tr")
print("--- primer <tr>:", t[i:i + 1500].replace("\n", " "))
