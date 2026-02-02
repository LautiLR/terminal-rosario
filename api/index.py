from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import feedparser
import requests
from datetime import datetime
import time

app = FastAPI(title="Terminal Rosario API", version="13.0 RC")

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

# --- CONFIGURACIÓN ---
ADR_MAP = { "GGAL.BA": "GGAL", "YPFD.BA": "YPF", "PAMP.BA": "PAM", "BMA.BA": "BMA", "SUPV.BA": "SUPV", "CEPU.BA": "CEPU", "CRES.BA": "CRESY", "EDN.BA": "EDN", "LOMA.BA": "LOMA", "TECO2.BA": "TEO", "BBAR.BA": "BBAR", "TGS.BA": "TGS", "IRS.BA": "IRS", "TXAR.BA": "TX" }

MARKETS = {
    "merval": ["GGAL.BA", "YPFD.BA", "PAMP.BA", "TXAR.BA", "ALUA.BA", "BMA.BA", "CRES.BA", "EDN.BA", "CEPU.BA", "SUPV.BA", "TECO2.BA", "TGNO4.BA", "TRAN.BA", "VALO.BA", "BYMA.BA", "COME.BA", "MIRG.BA"],
    "sp500": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META", "BRK-B", "LLY", "V", "JPM", "XOM", "WMT", "MA", "PG", "JNJ", "HD", "CVX", "MRK", "ABBV", "KO", "PEP"],
    "nasdaq": ["MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "AVGO", "TSLA", "COST", "PEP", "NFLX", "AMD", "ADBE", "QCOM", "TXN", "INTC", "AMGN", "HON", "INTU", "SBUX"]
}

CRYPTO_LIST = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "AVAX-USD", "TRX-USD", "DOT-USD", "LINK-USD", "MATIC-USD", "LTC-USD", "BCH-USD", "UNI7083-USD", "ATOM-USD", "XLM-USD", "ETC-USD", "HBAR-USD"]
SECTORS = { "XLE": "Energía", "XLF": "Finanzas", "XLK": "Tecnología", "XLV": "Salud", "XLI": "Industrial", "XLP": "Consumo Básico", "XLY": "Consumo Discrec.", "XLU": "Utilities", "XLB": "Materiales", "XLRE": "Real Estate", "XLC": "Comunicación" }
DIVIDEND_STOCKS = ["KO", "JPM", "XOM", "CVX", "JNJ", "PG", "PEP", "ABBV", "MO", "VZ", "T", "O", "MMM", "IBM", "CSCO", "YPFD.BA", "TXAR.BA", "PAMP.BA", "BBAR.BA", "LOMA.BA", "GGAL.BA", "BMA.BA"]

# --- AUXILIARES ---
def formato_millones(n): return f"{n/1e12:.2f}T" if n>=1e12 else (f"{n/1e9:.2f}B" if n>=1e9 else (f"{n/1e6:.2f}M" if n>=1e6 else f"{n:,.0f}")) if n else "-"
def calcular_beta(t): return None 

# --- ENDPOINTS ---

@app.get("/api/global")
def get_global():
    c = cache.get("global"); 
    if c: return c
    idx = {"merval": "^MERV", "sp500": "^GSPC", "dow": "^DJI"}
    res = {}
    for k,s in idx.items():
        try:
            h = yf.Ticker(s).history(period="3mo")
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

@app.get("/api/movers/{market}/{period}")
def get_movers(market: str, period: str):
    key = f"mov_{market}_{period}"
    c = cache.get(key); 
    if c: return c
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
        
        # 1. Ordenamos de MAYOR a MENOR (Descendente)
        res.sort(key=lambda x: x['change'], reverse=True) 
        
        # 2. Gainers: Los primeros 5 (positivos altos)
        gainers = res[:5]

        # 3. Losers: Los últimos 5 (que serán los negativos o los más bajos)
        # Tomamos los últimos 5 y los reordenamos de MENOR a MAYOR para que el más rojo quede primero
        raw_losers = res[-5:]
        losers = sorted(raw_losers, key=lambda x: x['change']) # Ascendente (ej: -5%, -3%, -1%)

        final = {"gainers": gainers, "losers": losers}
        cache.set(key, final, 600)
        return final
    except: return {"gainers": [], "losers": []}

@app.get("/api/groups")
def get_groups():
    c = cache.get("groups"); 
    if c: return c
    res = []
    tickers = list(SECTORS.keys())
    try:
        data = yf.download(tickers, period="2y", group_by='ticker', progress=False)
        for t in tickers:
            try:
                h = data[t]['Close'].dropna(); curr = h.iloc[-1]
                def cv(d): return ((curr - h.iloc[-(d+1)])/h.iloc[-(d+1)])*100 if len(h)>d else 0
                res.append({"symbol": t, "name": SECTORS[t], "dia": ((curr - h.iloc[-2]) / h.iloc[-2]) * 100, "semana": cv(5), "mes": cv(21), "anio": cv(250)})
            except: continue
        res.sort(key=lambda x: x['dia'], reverse=True)
        cache.set("groups", res, 3600)
        return res
    except: return []

# --- REEMPLAZA ESTA FUNCIÓN EN main.py ---

@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    try:
        tk = ticker.upper()
        local_ticker = yf.Ticker(tk)
        
        # 1. OBTENER PRECIO Y RENDIMIENTO (Siempre del local)
        # Usamos fast_info porque es lo más rápido y fiable para precios en tiempo real
        fst = local_ticker.fast_info
        try:
            p = fst['last_price']
        except:
            raise HTTPException(404, detail="Ticker no encontrado")
            
        h = local_ticker.history(period="1y")
        def perf(d): 
            return ((p - h['Close'].iloc[-(d+1)])/h['Close'].iloc[-(d+1)])*100 if len(h)>d else 0

        # Info básica local (solo para Nombre y Tipo)
        local_info = local_ticker.info
        quote_type = local_info.get('quoteType', 'EQUITY')
        name = local_info.get('longName') or local_info.get('shortName') or tk

        # 2. INICIALIZAR VARIABLES DE FUNDAMENTALES (En nulo por defecto)
        pe = None
        fwd_pe = None
        peg = None
        mkt_cap = None
        beta = None
        div_yield = None
        div_curr = fst['currency']
        ex_date = None
        
        # Puntas (Bid/Ask) - Preferimos local para operar, pero si no hay, nulo.
        bid = local_info.get('bid')
        ask = local_info.get('ask')

        # 3. LÓGICA DE FUENTE DE DATOS ("La Estrategia Híbrida")
        
        if tk in ADR_MAP:
            # === ES UNA EMPRESA ARGENTINA CON ADR ===
            # Buscamos los fundamentales en EE.UU. DIRECTAMENTE.
            try:
                adr_sym = ADR_MAP[tk]
                adr = yf.Ticker(adr_sym)
                adr_info = adr.info
                
                # Extraemos la data "limpia" de Wall Street
                # ... dentro del bloque if tk in ADR_MAP: ...
                
                pe = adr_info.get('trailingPE')
                fwd_pe = adr_info.get('forwardPE')
                peg = adr_info.get('pegRatio') or adr_info.get('trailingPegRatio')
                mkt_cap = adr_info.get('marketCap')
                beta = adr_info.get('beta')
                
                # Dividendos (siempre mejor la info en USD)
                div_yield = adr_info.get('dividendYield')
                ex_date = adr_info.get('exDividendDate')
                div_curr = "USD"
                
                # A veces el nombre está mejor formateado en el ADR
                if not name: name = adr_info.get('longName')
                
            except Exception as e:
                print(f"Error buscando ADR {adr_sym}: {e}")
                # Si falla USA, quedamos con todo en None (mejor que mostrar basura)
        
        else:
            # === ES LOCAL PURA (Ej: VALO.BA) O CRYPTO ===
            # No nos queda otra que usar la data local
            pe = local_info.get('trailingPE')
            fwd_pe = local_info.get('forwardPE')
            peg = local_info.get('pegRatio') or local_info.get('trailingPegRatio')
            mkt_cap = local_info.get('marketCap')
            beta = local_info.get('beta') # Rara vez existe en local, pero probamos
            div_yield = local_info.get('dividendYield')
            ex_date = local_info.get('exDividendDate')

        # --- RESPUESTA JSON FINAL ---
        return {
            "symbol": tk,
            "type": quote_type,
            "name": name,
            "moneda": fst['currency'], # Moneda del PRECIO (ARS)
            "precio": p,
            "pre_market": local_info.get('preMarketPrice'), # Pre local (raro) o null
            "post_market": local_info.get('postMarketPrice'),
            "rendimiento": {
                "dia": ((p - fst['previous_close']) / fst['previous_close']) * 100, 
                "semana": perf(5), 
                "mes": perf(21), 
                "anio": perf(250)
            },
            "valuacion": { 
                "pe": pe, 
                "forward_pe": fwd_pe, 
                "peg": peg, 
                "beta": beta, 
                "market_cap": formato_millones(mkt_cap) # Formateamos el número grande
            },
            "dividendos": { 
                "yield": (div_yield or 0) * 100, 
                "ex_date": datetime.fromtimestamp(ex_date).strftime('%d/%m/%Y') if ex_date else None, 
                "currency": div_curr 
            },
            "puntas": { "bid": bid, "ask": ask },
            "arbitraje": None
        }
    except Exception as e: 
        print(f"Error critico en {ticker}: {e}")
        raise HTTPException(500, detail=str(e))
@app.get("/api/dividend-hub")
def get_divs(skip: int=0, limit: int=5):
    batch = DIVIDEND_STOCKS[skip:skip+limit]; res=[]
    for t in batch:
        try:
            tk=yf.Ticker(t); i=tk.info; y=i.get('dividendYield',0); c=tk.fast_info['currency']
            if t in ADR_MAP: 
                try: a=yf.Ticker(ADR_MAP[t]).info; y=a.get('dividendYield',0); c="USD"
                except:pass
            if y and y>0.005: res.append({"symbol":t,"name":i.get('shortName',t),"yield":y*100,"ex_date":datetime.fromtimestamp(i.get('exDividendDate',0)).strftime('%d/%m/%Y') if i.get('exDividendDate') else "-","price":tk.fast_info['last_price'],"currency":c})
        except: continue
    return {"data":res, "has_more":(skip+limit)<len(DIVIDEND_STOCKS), "next_skip":skip+limit}

@app.get("/api/crypto")
def get_crypto():
    c = cache.get("crypto"); 
    if c: return c
    res=[]
    try:
        d = yf.download(CRYPTO_LIST, period="3mo", group_by='ticker', progress=False) # 3 meses para gráfico lindo
        for t in CRYPTO_LIST:
            try:
                h=d[t]['Close'].dropna(); c,p=h.iloc[-1],h.iloc[-2]
                ch=[{"x":x.strftime('%Y-%m-%d'),"y":round(y,4)} for x,y in zip(h.index, h)]
                res.append({"symbol":t.replace("-USD",""),"full_symbol":t,"price":c,"change":((c-p)/p)*100,"history":ch})
            except: continue
        cache.set("crypto", res, 300)
        return res
    except: return []

@app.get("/api/news/{query}")
def get_news(query: str):
    try:
        f = feedparser.parse(f"https://news.google.com/rss/search?q={query.replace('.BA','')}+finanzas+when:7d&hl=es-419&gl=AR&ceid=AR:es-419")
        return [{"titulo":e.title,"link":e.link,"fuente":e.source.get('title'),"fecha":e.published[:16]} for e in f.entries[:10]]
    except: return []