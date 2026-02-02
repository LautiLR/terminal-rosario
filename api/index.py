from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import feedparser
import requests
from datetime import datetime
import time

app = FastAPI(title="Terminal Rosario API", version="13.1")

# --- MIDDLEWARE (Solo una vez y arriba) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CACHÉ SIMPLE ---
class SimpleCache:
    def __init__(self): self.store = {}
    def get(self, key): 
        item = self.store.get(key)
        return item['data'] if item and time.time() < item['expires'] else None
    def set(self, key, data, ttl=300): self.store[key] = {'data': data, 'expires': time.time() + ttl}

cache = SimpleCache()

# --- MAPEOS Y LISTAS ---
ADR_MAP = { "GGAL.BA": "GGAL", "YPFD.BA": "YPF", "PAMP.BA": "PAM", "BMA.BA": "BMA", "SUPV.BA": "SUPV", "CEPU.BA": "CEPU", "CRES.BA": "CRESY", "EDN.BA": "EDN", "LOMA.BA": "LOMA", "TECO2.BA": "TEO", "BBAR.BA": "BBAR", "TGS.BA": "TGS", "IRS.BA": "IRS", "TXAR.BA": "TX" }
MARKETS = {
    "merval": ["GGAL.BA", "YPFD.BA", "PAMP.BA", "TXAR.BA", "ALUA.BA", "BMA.BA", "CRES.BA", "EDN.BA", "CEPU.BA", "SUPV.BA", "TECO2.BA", "TGNO4.BA", "TRAN.BA", "VALO.BA", "BYMA.BA", "COME.BA", "MIRG.BA"],
    "sp500": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B", "LLY", "V", "JPM", "XOM", "WMT", "MA", "PG", "JNJ", "HD", "CVX", "MRK", "ABBV", "KO", "PEP"],
    "nasdaq": ["MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "COST", "PEP", "NFLX", "AMD", "ADBE", "QCOM", "TXN", "INTC", "AMGN", "HON", "INTU", "SBUX"]
}
CRYPTO_LIST = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "AVAX-USD", "TRX-USD", "DOT-USD", "LINK-USD", "MATIC-USD", "LTC-USD", "BCH-USD"]
SECTORS = { "XLE": "Energía", "XLF": "Finanzas", "XLK": "Tecnología", "XLV": "Salud", "XLI": "Industrial", "XLP": "Consumo Básico", "XLY": "Consumo Discrec.", "XLU": "Utilities", "XLB": "Materiales", "XLRE": "Real Estate", "XLC": "Comunicación" }
DIVIDEND_STOCKS = ["KO", "JPM", "XOM", "CVX", "JNJ", "PG", "PEP", "ABBV", "MO", "VZ", "T", "O", "MMM", "IBM", "CSCO", "YPFD.BA", "TXAR.BA", "PAMP.BA", "BBAR.BA", "LOMA.BA", "GGAL.BA", "BMA.BA"]

# --- AUXILIARES ---
def formato_millones(n): 
    if not n: return "-"
    return f"{n/1e12:.2f}T" if n>=1e12 else (f"{n/1e9:.2f}B" if n>=1e9 else (f"{n/1e6:.2f}M" if n>=1e6 else f"{n:,.0f}"))

# --- ENDPOINTS ---

@app.get("/api/global")
def get_global():
    c = cache.get("global")
    if c: return c
    idx = {"merval": "^MERV", "sp500": "^GSPC", "dow": "^DJI"}
    res = {}
    for k,s in idx.items():
        try:
            h = yf.Ticker(s).history(period="1mo")
            if not h.empty:
                curr, prev = h['Close'].iloc[-1], h['Close'].iloc[-2]
                res[k] = {"precio": curr, "variacion": ((curr-prev)/prev)*100, "history": [{"x":d.strftime('%Y-%m-%d'),"y":round(p,2)} for d,p in zip(h.index, h['Close'])], "moneda": "ARS" if k=="merval" else "USD"}
        except: res[k] = None
    dol = {}
    try:
        r = requests.get("https://dolarapi.com/v1/dolares", timeout=2).json()
        for d in r: 
            if d['casa'] in ['oficial','blue','bolsa','contadoconliqui']: dol[d['casa']] = d
    except: pass
    final = {"indices": res, "dolares": dol}
    cache.set("global", final, 300)
    return final

@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    try:
        tk_str = ticker.upper()
        tk = yf.Ticker(tk_str)
        fst = tk.fast_info
        p = fst['last_price']
        
        h = tk.history(period="1y")
        def perf(d): return ((p - h['Close'].iloc[-(d+1)])/h['Close'].iloc[-(d+1)])*100 if len(h)>d else 0

        info = tk.info
        name = info.get('longName') or info.get('shortName') or tk_str
        
        # Estrategia Híbrida: Si es ADR, buscamos fundamentales en USA
        target_info = info
        div_curr = fst['currency']
        
        if tk_str in ADR_MAP:
            try:
                adr = yf.Ticker(ADR_MAP[tk_str]).info
                target_info = adr
                div_curr = "USD"
            except: pass

        raw_yield = target_info.get('dividendYield') or 0
        # Ajuste de porcentaje: si es 0.03 -> 3%, si ya es 3.0 -> 3%
        final_yield = raw_yield * 100 if raw_yield < 1 else raw_yield

        return {
            "symbol": tk_str,
            "name": name,
            "precio": p,
            "moneda": fst['currency'],
            "rendimiento": {"dia": ((p - fst['previous_close']) / fst['previous_close']) * 100, "semana": perf(5), "mes": perf(21), "anio": perf(250)},
            "valuacion": {
                "pe": target_info.get('trailingPE'),
                "forward_pe": target_info.get('forwardPE'),
                "peg": target_info.get('pegRatio'),
                "beta": target_info.get('beta'),
                "market_cap": formato_millones(target_info.get('marketCap'))
            },
            "dividendos": {
                "yield": final_yield,
                "ex_date": datetime.fromtimestamp(target_info['exDividendDate']).strftime('%d/%m/%Y') if target_info.get('exDividendDate') else None,
                "currency": div_curr
            },
            "puntas": {"bid": info.get('bid'), "ask": info.get('ask')}
        }
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/dividend-hub")
def get_dividend_hub(skip: int = 0, limit: int = 5):
    batch = DIVIDEND_STOCKS[skip : skip + limit]
    results = []
    for t in batch:
        try:
            tk = yf.Ticker(t)
            info = tk.info
            raw_yield = info.get('dividendYield') or 0
            curr = tk.fast_info['currency']
            
            if t in ADR_MAP:
                try:
                    adr = yf.Ticker(ADR_MAP[t]).info
                    raw_yield = adr.get('dividendYield') or raw_yield
                    curr = "USD"
                except: pass
            
            if raw_yield > 0:
                results.append({
                    "symbol": t,
                    "name": info.get('shortName', t),
                    "yield": raw_yield * 100 if raw_yield < 1 else raw_yield,
                    "price": tk.fast_info['last_price'],
                    "currency": curr
                })
        except: continue
    return {"data": results, "has_more": (skip + limit) < len(DIVIDEND_STOCKS), "next_skip": skip + limit}

@app.get("/api/movers/{market}/{period}")
def get_movers(market: str, period: str):
    lst = MARKETS.get(market, MARKETS['sp500'])
    dias = {'1d':1, '5d':5, '1mo':21, '1y':250}.get(period, 1)
    res = []
    try:
        dt = yf.download(lst, period="2y", group_by='ticker', progress=False)
        for t in lst:
            try:
                h = dt[t]['Close'].dropna()
                if len(h) > dias:
                    c, p = h.iloc[-1], h.iloc[-(dias+1)]
                    res.append({"symbol": t, "change": ((c-p)/p)*100, "price": c})
            except: continue
        res.sort(key=lambda x: x['change'], reverse=True)
        return {"gainers": res[:5], "losers": sorted(res[-5:], key=lambda x: x['change'])}
    except: return {"gainers": [], "losers": []}

@app.get("/api/groups")
def get_groups():
    res = []
    tickers = list(SECTORS.keys())
    try:
        data = yf.download(tickers, period="2y", group_by='ticker', progress=False)
        for t in tickers:
            try:
                h = data[t]['Close'].dropna()
                curr = h.iloc[-1]
                def cv(d): return ((curr - h.iloc[-(d+1)])/h.iloc[-(d+1)])*100 if len(h)>d else 0
                res.append({"symbol": t, "name": SECTORS[t], "dia": ((curr - h.iloc[-2]) / h.iloc[-2]) * 100, "semana": cv(5), "mes": cv(21), "anio": cv(250)})
            except: continue
        res.sort(key=lambda x: x['dia'], reverse=True)
        return res
    except: return []

@app.get("/api/crypto")
def get_crypto():
    res = []
    try:
        d = yf.download(CRYPTO_LIST, period="1mo", group_by='ticker', progress=False)
        for t in CRYPTO_LIST:
            try:
                h = d[t]['Close'].dropna()
                c, p = h.iloc[-1], h.iloc[-2]
                res.append({"symbol": t.replace("-USD",""), "price": c, "change": ((c-p)/p)*100, "history": [{"x":x.strftime('%Y-%m-%d'),"y":round(y,2)} for x,y in zip(h.index, h)]})
            except: continue
        return res
    except: return []

@app.get("/api/news/{query}")
def get_news(query: str):
    try:
        f = feedparser.parse(f"https://news.google.com/rss/search?q={query.replace('.BA','')}+finanzas+when:7d&hl=es-419&gl=AR&ceid=AR:es-419")
        return [{"titulo":e.title, "link":e.link, "fuente":e.source.get('title'), "fecha":e.published[:16]} for e in f.entries[:10]]
    except: return []
