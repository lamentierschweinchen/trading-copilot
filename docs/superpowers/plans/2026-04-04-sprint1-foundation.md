# Sprint 1: Foundation & Data — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Yahoo Finance with Finnhub, implement ATR/VWAP indicators, add a 24h performance heatmap, and add sparkline charts to asset cards.

**Architecture:** Backend-first approach. Fix data sources (Finnhub, ATR/VWAP) before adding frontend features (heatmap, sparklines) that consume that data. Each task produces a working, independently testable change.

**Tech Stack:** Python 3.12, FastAPI, httpx, pandas, Pydantic v2, vanilla JS/HTML/CSS (single-file frontend)

**Spec:** `docs/superpowers/specs/2026-04-04-sprint1-foundation-design.md`

---

## Chunk 1: Backend Data Pipeline

### Task 1: Create Finnhub Service

**Files:**
- Create: `app/services/finnhub.py`

- [ ] **Step 1: Create `app/services/finnhub.py`**

```python
import asyncio
import logging
import time

import httpx
from app.config import settings

logger = logging.getLogger(__name__)

_semaphore = asyncio.Semaphore(5)
_cache: dict = {}
_cache_ttl = 300  # 5 minutes


async def fetch_macro_data() -> dict:
    """
    Fetch macro indicators via Finnhub API.
    Returns dict of label -> {price, change_pct} (same format as old yahoo.py).
    """
    now = time.time()
    if _cache and (now - _cache.get("_ts", 0)) < _cache_ttl:
        return _cache.get("data", {})

    results = {}

    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [
            _fetch_quote(client, label, symbol)
            for label, symbol in settings.MACRO_TICKERS.items()
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

    for resp in responses:
        if isinstance(resp, dict):
            results.update(resp)

    _cache["data"] = results
    _cache["_ts"] = now

    return results


async def _fetch_quote(client: httpx.AsyncClient, label: str, symbol: str) -> dict:
    """Fetch a single quote from Finnhub."""
    async with _semaphore:
        try:
            resp = await client.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": symbol, "token": settings.finnhub_api_key},
            )
            resp.raise_for_status()
            data = resp.json()

            price = data.get("c")  # current price
            change_pct = data.get("dp")  # daily change percentage

            if price is None or price == 0:
                return {label: {"price": None, "change_pct": None}}

            return {label: {"price": round(price, 2), "change_pct": round(change_pct, 3) if change_pct else None}}
        except Exception:
            logger.warning("Failed to fetch Finnhub quote for %s (%s)", label, symbol)
            return {label: {"price": None, "change_pct": None}}
```

- [ ] **Step 2: Verify file parses**

Run: `cd "/Users/ls/Documents/Trading Copilot" && PYTHONPATH=. ./venv/bin/python -c "import app.services.finnhub; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/services/finnhub.py
git commit -m "feat: add Finnhub API service for macro data"
```

### Task 2: Update Config for Finnhub

**Files:**
- Modify: `app/config.py`

- [ ] **Step 1: Update `app/config.py`**

Replace `MACRO_TICKERS` with Finnhub ETF symbols and add `finnhub_api_key`:

```python
# In Settings class, add:
finnhub_api_key: str = ""

# Replace MACRO_TICKERS:
MACRO_TICKERS: ClassVar[dict[str, str]] = {
    "SPX": "SPY",
    "QQQ": "QQQ",
    "DXY": "UUP",
    "US10Y": "TLT",
    "DOW": "DIA",
    "GOLD": "GLD",
    "VIX": "VIXY",
}
```

Remove the `# Macro tickers for yfinance` comment, replace with `# Macro tickers for Finnhub (ETF proxies)`.

- [ ] **Step 2: Add `FINNHUB_API_KEY` to `.env`**

```bash
echo 'FINNHUB_API_KEY=your_key_here' >> .env
```

(User must replace `your_key_here` with their actual key from https://finnhub.io/dashboard)

- [ ] **Step 3: Commit**

```bash
git add app/config.py
git commit -m "feat: update config for Finnhub ETF tickers and API key"
```

### Task 3: Wire Finnhub into Macro Scout

**Files:**
- Modify: `app/agents/macro_scout.py`
- Delete: `app/services/yahoo.py`
- Modify: `requirements.txt`

- [ ] **Step 1: Update `app/agents/macro_scout.py`**

Change line 4 from:
```python
from app.services.yahoo import fetch_macro_data
```
to:
```python
from app.services.finnhub import fetch_macro_data
```

Change lines 15-17 from:
```python
    # yfinance is sync, run in thread; fear_greed is async
    loop = asyncio.get_event_loop()
    macro_task = loop.run_in_executor(None, fetch_macro_data)
```
to:
```python
    # Both are async now
    macro_task = fetch_macro_data()
```

The rest of the function (lines 18-49) stays exactly the same — `asyncio.gather(macro_task, fg_task)` works unchanged since both are now coroutines.

- [ ] **Step 2: Delete `app/services/yahoo.py`**

```bash
rm app/services/yahoo.py
```

- [ ] **Step 3: Remove yfinance from `requirements.txt`**

Remove the line `yfinance==0.2.40` from `requirements.txt`.

- [ ] **Step 4: Verify import chain works**

Run: `cd "/Users/ls/Documents/Trading Copilot" && PYTHONPATH=. ./venv/bin/python -c "from app.agents import macro_scout; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/agents/macro_scout.py requirements.txt
git rm app/services/yahoo.py
git commit -m "feat: switch macro data from Yahoo Finance to Finnhub"
```

### Task 4: Implement ATR & VWAP Models

**Files:**
- Modify: `app/models/schemas.py`

- [ ] **Step 1: Add `ATRResult` and `VWAPResult` models to `app/models/schemas.py`**

Insert after `RSIResult` (after line 93), before `TechnicalSnapshot`:

```python
class ATRResult(BaseModel):
    value: float     # absolute ATR value
    pct: float       # ATR as percentage of current price
    period: int = 14


class VWAPResult(BaseModel):
    value: float
    price_vs_vwap: str    # "above", "below", "at"
    distance_pct: float   # percentage distance from VWAP
```

- [ ] **Step 2: Add fields to `TechnicalSnapshot`**

Add after `rsi: RSIResult` (line 102), before `signal: Signal`:

```python
    atr: ATRResult | None = None
    vwap: VWAPResult | None = None
```

- [ ] **Step 3: Add `sparkline_24h` to `AssetIntel`**

Add after `volume_24h` (line 120), before `scalp_tf`:

```python
    sparkline_24h: list[float] | None = None
```

- [ ] **Step 4: Verify schema loads**

Run: `cd "/Users/ls/Documents/Trading Copilot" && PYTHONPATH=. ./venv/bin/python -c "from app.models.schemas import ATRResult, VWAPResult, TechnicalSnapshot, AssetIntel; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/models/schemas.py
git commit -m "feat: add ATRResult, VWAPResult models and sparkline_24h field"
```

### Task 5: Implement ATR & VWAP Compute Functions

**Files:**
- Modify: `app/indicators/technical.py`

- [ ] **Step 1: Add imports to `app/indicators/technical.py`**

Update the import on line 5-7 to include the new models:

```python
from app.models.schemas import (
    Kline, MACDResult, BollingerResult, RSIResult,
    ATRResult, VWAPResult,
    TechnicalSnapshot, Signal,
)
```

- [ ] **Step 2: Add `compute_atr()` function**

Insert after `compute_rsi()` (after line 111), before `compute_signal()`:

```python
def compute_atr(df: pd.DataFrame, period: int = 14) -> ATRResult:
    """Compute Average True Range."""
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    atr = tr.rolling(window=period).mean().iloc[-1]
    price = float(close.iloc[-1])
    pct = (float(atr) / price) * 100 if price != 0 else 0.0

    return ATRResult(
        value=round(float(atr), 4),
        pct=round(pct, 4),
        period=period,
    )
```

- [ ] **Step 3: Add `compute_vwap()` function**

Insert after `compute_atr()`:

```python
def compute_vwap(df: pd.DataFrame) -> VWAPResult:
    """Compute Volume Weighted Average Price."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    cum_tp_vol = (typical_price * df["volume"]).cumsum()
    cum_vol = df["volume"].cumsum()
    vwap = cum_tp_vol / cum_vol
    vwap_val = float(vwap.iloc[-1])
    price = float(df["close"].iloc[-1])

    distance_pct = ((price - vwap_val) / vwap_val) * 100 if vwap_val != 0 else 0.0
    position = "above" if price > vwap_val * 1.001 else "below" if price < vwap_val * 0.999 else "at"

    return VWAPResult(
        value=round(vwap_val, 4),
        price_vs_vwap=position,
        distance_pct=round(distance_pct, 4),
    )
```

- [ ] **Step 4: Integrate into `analyze_klines()`**

Update `analyze_klines()` (line 175+) to compute ATR and VWAP and pass them to `TechnicalSnapshot`:

```python
def analyze_klines(
    klines: list[Kline], symbol: str, timeframe: str
) -> TechnicalSnapshot:
    """Full technical analysis pipeline for a set of klines."""
    df = klines_to_df(klines)

    macd = compute_macd(df)
    bb = compute_bollinger(df)
    rsi = compute_rsi(df)
    signal, strength = compute_signal(macd, bb, rsi)

    # ATR & VWAP — graceful failure
    atr = None
    vwap = None
    try:
        atr = compute_atr(df)
    except Exception:
        pass
    try:
        vwap = compute_vwap(df)
    except Exception:
        pass

    return TechnicalSnapshot(
        symbol=symbol,
        timeframe=timeframe,
        price=round(float(df["close"].iloc[-1]), 2),
        macd=macd,
        bollinger=bb,
        rsi=rsi,
        atr=atr,
        vwap=vwap,
        signal=signal,
        signal_strength=strength,
    )
```

- [ ] **Step 5: Verify module loads**

Run: `cd "/Users/ls/Documents/Trading Copilot" && PYTHONPATH=. ./venv/bin/python -c "from app.indicators.technical import compute_atr, compute_vwap, analyze_klines; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add app/indicators/technical.py
git commit -m "feat: implement ATR and VWAP compute functions"
```

### Task 6: Populate Sparkline Data in Market Intel

**Files:**
- Modify: `app/agents/market_intel.py`

- [ ] **Step 1: Update `_analyze_asset()` in `app/agents/market_intel.py`**

After computing `primary_tf` (line 39), extract sparkline data from the primary klines. Add before the `return AssetIntel(...)`:

```python
    # Extract last 24 close prices for sparkline (1h candles = 24h)
    sparkline = None
    if primary_klines and len(primary_klines) >= 24:
        sparkline = [float(k.close) for k in primary_klines[-24:]]
```

Then add `sparkline_24h=sparkline` to the `AssetIntel` constructor:

```python
    return AssetIntel(
        symbol=symbol,
        price=primary_tf.price,
        change_24h_pct=change_24h,
        volume_24h=volume_24h,
        sparkline_24h=sparkline,
        scalp_tf=scalp_tf,
        primary_tf=primary_tf,
        confirmation_tf=confirmation_tf,
    )
```

- [ ] **Step 2: Verify module loads**

Run: `cd "/Users/ls/Documents/Trading Copilot" && PYTHONPATH=. ./venv/bin/python -c "from app.agents import market_intel; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/agents/market_intel.py
git commit -m "feat: populate sparkline_24h with last 24 close prices"
```

---

## Chunk 2: Frontend Features

### Task 7: Add Heatmap Section to Frontend

**Files:**
- Modify: `frontend/index.html` (CSS + HTML + JS)

- [ ] **Step 1: Add heatmap CSS**

Insert before the `/* ─── Asset Controls (Sort/Filter) ─── */` comment in the `<style>` block:

```css
/* ─── Heatmap ─── */
.heatmap-section {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-subtle);
  display: none;
}
.heatmap-section.visible { display: block; }
.heatmap-title {
  font-family: var(--font-data);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 8px;
}
.heatmap-grid {
  display: grid;
  grid-template-columns: repeat(10, 1fr);
  gap: 4px;
}
.heatmap-cell {
  border-radius: 4px;
  padding: 8px 4px;
  text-align: center;
  cursor: pointer;
  transition: transform 0.15s, box-shadow 0.15s;
  border: 1px solid transparent;
}
.heatmap-cell:hover {
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}
.heatmap-cell-symbol {
  font-family: var(--font-data);
  font-size: 12px;
  font-weight: 700;
  color: var(--text-0);
}
.heatmap-cell-change {
  font-family: var(--font-data);
  font-size: 11px;
  font-weight: 600;
  margin-top: 2px;
}
@media (max-width: 600px) {
  .heatmap-grid { grid-template-columns: repeat(5, 1fr); }
}
```

- [ ] **Step 2: Add heatmap HTML**

Insert after the market overview `</div>` (after `id="marketOverview"` closing tag), before `<!-- Main Content -->`:

```html
  <!-- Heatmap -->
  <div class="heatmap-section" id="heatmapSection">
    <div class="heatmap-title">24H Performance</div>
    <div class="heatmap-grid" id="heatmapGrid"></div>
  </div>
```

- [ ] **Step 3: Add `renderHeatmap()` JS function**

Insert after `renderMarketOverview()` function, before `renderAssets()`:

```javascript
// ─── Render Heatmap ───
function renderHeatmap(assets) {
  if (!assets || assets.length === 0) return;

  const $heatmap = document.getElementById('heatmapSection');
  const $grid = document.getElementById('heatmapGrid');
  $heatmap.classList.add('visible');

  $grid.innerHTML = assets.map(a => {
    const chg = a.change_24h_pct || 0;
    const absChg = Math.abs(chg);
    const opacity = Math.min(absChg * 12, 80) / 100;
    const color = chg >= 0.1 ? `rgba(0,212,170,${opacity})` :
                  chg <= -0.1 ? `rgba(255,107,107,${opacity})` : 'var(--bg-2)';
    const textColor = chg >= 0.1 ? 'var(--green)' : chg <= -0.1 ? 'var(--red)' : 'var(--text-3)';
    const borderColor = chg >= 0.1 ? `rgba(0,212,170,${opacity * 0.5})` :
                        chg <= -0.1 ? `rgba(255,107,107,${opacity * 0.5})` : 'transparent';

    return `<div class="heatmap-cell" style="background:${color};border-color:${borderColor}"
                 onclick="document.querySelector('.asset-card[data-symbol=\\'${a.symbol}\\']')?.scrollIntoView({behavior:'smooth',block:'center'})">
      <div class="heatmap-cell-symbol">${a.symbol}</div>
      <div class="heatmap-cell-change" style="color:${textColor}">${formatPct(chg)}</div>
    </div>`;
  }).join('');
}
```

- [ ] **Step 4: Add `data-symbol` attribute to asset cards**

In the `renderAssets()` function, find the line that generates the card opening tag:

```javascript
    <div class="asset-card expanded ${signalClass}" onclick="this.classList.toggle('expanded')">
```

Change to:

```javascript
    <div class="asset-card expanded ${signalClass}" data-symbol="${a.symbol}" onclick="this.classList.toggle('expanded')">
```

- [ ] **Step 5: Call `renderHeatmap()` in session handler**

In the `runSession()` function, after `renderMarketOverview(sessionData.macro);` (line 1736), add:

```javascript
    renderHeatmap(sessionData.assets);
```

- [ ] **Step 6: Add `$heatmapSection` to DOM references**

Find where DOM elements are cached (near the top of the script block, look for `const $assetsPanel`) and add:

```javascript
const $heatmapSection = document.getElementById('heatmapSection');
```

- [ ] **Step 7: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add 24h performance heatmap strip"
```

### Task 8: Add Sparkline Charts to Asset Cards

**Files:**
- Modify: `frontend/index.html` (JS only)

- [ ] **Step 1: Add `buildSparkline()` function**

Insert after the `atrDisplay()` function (in the helper functions section), before `// ─── Indicator sentiment classifiers ───`:

```javascript
function buildSparkline(prices, isPositive) {
  if (!prices || prices.length < 2) return '';
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const range = max - min || 1;
  const w = 200, h = 32;
  const points = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * w;
    const y = h - ((p - min) / range) * (h - 4) - 2;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const linePoints = points.join(' L');
  const areaPoints = points.join(' L');
  const lastPoint = points[points.length - 1].split(',');
  const color = isPositive ? '#00d4aa' : '#ff6b6b';
  const gradId = isPositive ? 'sparkGrad-green' : 'sparkGrad-red';

  return `
  <div class="sparkline-container" style="height:32px;margin:4px 0 8px 0">
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="width:100%;height:100%">
      <defs>
        <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.3"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0.02"/>
        </linearGradient>
      </defs>
      <path d="M${areaPoints} L${w},${h} L0,${h} Z" fill="url(#${gradId})"/>
      <path d="M${linePoints}" fill="none" stroke="${color}" stroke-width="1.5"/>
      <circle cx="${lastPoint[0]}" cy="${lastPoint[1]}" r="2.5" fill="${color}"/>
    </svg>
  </div>`;
}
```

- [ ] **Step 2: Insert sparkline into asset card template**

In the `renderAssets()` function, find the card HTML template. After the `</div>` that closes `.asset-header` and before the `<div class="sentiment-row">`, insert the sparkline call:

```javascript
      ${buildSparkline(a.sparkline_24h, (a.change_24h_pct || 0) >= 0)}
```

So the card template section becomes:

```javascript
      </div>  <!-- end .asset-header -->

      ${buildSparkline(a.sparkline_24h, (a.change_24h_pct || 0) >= 0)}

      <div class="sentiment-row">
```

- [ ] **Step 3: Commit**

```bash
git add frontend/index.html
git commit -m "feat: add SVG sparkline charts to asset cards"
```

### Task 9: Verify Full Integration

- [ ] **Step 1: Start the server**

```bash
cd "/Users/ls/Documents/Trading Copilot" && PYTHONPATH=. "./venv/bin/python" -m uvicorn app.main:app --reload --port 8000
```

- [ ] **Step 2: Open http://localhost:8000 and run a session**

Verify:
- Market overview strip loads with data from Finnhub (tiles show prices and % changes)
- Heatmap strip appears with all 10 assets, color-coded by 24h change
- Clicking a heatmap cell scrolls to the corresponding asset card
- Each asset card has a sparkline between header and bias gauge
- Sparklines are green for positive, red for negative changes
- ATR pills show percentage values (e.g., "0.18%"), not "N/A"
- VWAP pills show "Above X.XX%" or "Below X.XX%", not "N/A"
- Sort/filter controls still work
- Recs, trade log, feedback still render correctly

- [ ] **Step 3: Test mobile layout**

Resize browser to < 600px. Verify:
- Heatmap wraps to 5×2 grid
- Asset cards show compact headers, expandable on click
- Sparklines visible inside cards

- [ ] **Step 4: Final commit and push**

```bash
git add -A
git commit -m "v2.2: Sprint 1 — Finnhub, ATR/VWAP, heatmap, sparklines

Complete Sprint 1 foundation features:
- Replace Yahoo Finance with Finnhub for reliable macro data
- Implement ATR and VWAP indicators end-to-end
- Add 24h performance heatmap strip
- Add SVG sparkline charts to asset cards

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"

git push origin main
```
