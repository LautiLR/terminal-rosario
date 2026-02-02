from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import feedparser
import requests
from datetime import datetime
import time

app = FastAPI()

# Configuración de CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CACHÉ ---
class SimpleCache:
    def __init__(self): self.store = {}
    def get(self, key):
        item = self.store.get(key)
        return item['data'] if item and time.time() < item['expires'] else None
    def set(self, key, data, ttl=300):
        self.store[key] = {'data': data, 'expires': time.time() + ttl}

cache = SimpleCache()

# --- CONSTANTES ---
ADR_MAP = { "GGAL.BA": "GGAL", "YPFD.BA": "YPF", "PAMP.BA": "PAM", "BMA.BA": "BMA", "SUPV.BA": "SUPV", "CEPU.BA": "CEPU", "CRES.BA": "CRESY", "EDN.BA": "EDN", "LOMA.BA": "LOMA", "TECO2.BA": "TEO", "BBAR.BA": "BBAR", "TGS.BA": "TGS", "IRS.BA": "IRS", "TXAR.BA": "TX" }

MARKETS = {
    "merval": ["GGAL.BA", "YPFD.BA", "PAMP.BA", "TXAR.BA", "ALUA.BA", "BMA.BA"],
    "sp500": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"],
    "nasdaq": ["MSFT", "AAPL", "NVDA", "AMZN", "META", "GOOGL", "AVGO"]
}

# --- ENDPOINTS ---

@app.get("/api/global")
def get_global():
    idx = {"merval": "^MERV", "sp500": "^GSPC", "dow": "^DJI"}
    res = {}
    for k, s in idx.items():
        try:
            h = yf.Ticker(s).history(period="1mo")
            if not h.empty:
                curr, prev = h['Close'].iloc[-1], h['Close'].iloc[-2]
                res[k] = {
                    "precio": float(curr),
                    "variacion": float(((curr - prev) / prev) * 100),
                    "history": [{"x": d.strftime('%Y-%m-%d'), "y": round(float(p), 2)} for d, p in zip(h.index, h['Close'])],
                    "moneda": "ARS" if k == "merval" else "USD"
                }
        except: res[k] = None
    
    dol = {}
    try:
        r = requests.get("https://dolarapi.com/v1/dolares", timeout=5).json()
        for d in r:
            if d['casa'] in ['oficial', 'blue', 'bolsa', 'contadoconliqui']:
                dol[d['casa']] = d
    except: pass
    
    return {"indices": res, "dolares": dol}

@app.get("/api/quote/{ticker}")
def get_quote(ticker: str):
    try:
        tk_str = ticker.upper()
        tk = yf.Ticker(tk_str)
        info = tk.info
        hist = tk.history(period="1y")
        
        if hist.empty: raise HTTPException(status_code=404, detail="No data")
        
        price = float(hist['Close'].iloc[-1])
        prev_close = float(tk.fast_info.get('previous_close', price))
        
        # Datos híbridos para ADRs
        target_info = info
        if tk_str in ADR_MAP:
            try:
                adr = yf.Ticker(ADR_MAP[tk_str]).info
                target_info = adr
            except: pass

        return {
            "symbol": tk_str,
            "name": info.get('longName') or info.get('shortName') or tk_str,
            "precio": price,
            "moneda": tk.fast_info.get('currency', 'USD'),
            "rendimiento": {
                "dia": float(((price - prev_close) / prev_close) * 100),
                "semana": 0, "mes": 0, "anio": 0
            },
            "valuacion": {
                "pe": target_info.get('trailingPE'),
                "market_cap": str(target_info.get('marketCap', '-')),
                "beta": target_info.get('beta')
            },
            "dividendos": {
                "yield": (target_info.get('dividendYield') or 0) * 100,
                "currency": "USD" if tk_str in ADR_MAP else "ARS"
            },
            "puntas": {"bid": info.get('bid'), "ask": info.get('ask')}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/movers/{market}/{period}")
def get_movers(market: str, period: str):
    return {"gainers": [], "losers": []}

@app.get("/api/crypto")
def get_crypto():
    return []

@app.get("/api/news/{query}")
def get_news(query: str):
    return []

