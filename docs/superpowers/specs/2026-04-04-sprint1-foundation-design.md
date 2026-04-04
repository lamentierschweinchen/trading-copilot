# Sprint 1 — Foundation & Data

## Summary

Replace Yahoo Finance with Finnhub for macro data, implement ATR/VWAP indicators end-to-end, add a 24h performance heatmap, and add mini sparkline charts to asset cards. Four features that fix broken data pipelines and add visual richness.

## Features

### 1. Finnhub Macro Data

**Problem:** Yahoo Finance (`yfinance`) is unreliable — market overview strip frequently shows no data.

**Solution:** New `app/services/finnhub.py` replacing `app/services/yahoo.py`.

**API details:**
- Endpoint: `GET https://finnhub.io/api/v1/quote?symbol=X&token=KEY`
- Returns: `{ c: current, d: change, dp: change_pct, h: high, l: low, o: open, pc: prev_close }`
- Free tier: 60 calls/min — we need 7 tickers per session, well within limits
- API key stored in environment variable `FINNHUB_API_KEY`

**Ticker mapping (ETF proxies for free tier compatibility):**

| Label | Finnhub Symbol | Notes |
|-------|---------------|-------|
| S&P 500 | SPY | ETF proxy for ^GSPC |
| Nasdaq | QQQ | ETF proxy for ^NDX |
| Dow | DIA | ETF proxy for ^DJI |
| Gold | GLD | ETF proxy for GC=F |
| Dollar (DXY) | UUP | ETF proxy for DX-Y.NYB |
| US 10Y | TLT | ETF proxy (inverse relationship — note in UI) |
| VIX | VIXY | ETF proxy fallback if VIX index unavailable on free tier |

**Backend changes:**
- New file: `app/services/finnhub.py` with `async fetch_macro_data() -> dict`
- Returns same `dict` format as current `yahoo.py`: `{label: {price, change_pct}}` so `macro_scout.py` continues to build `MacroSnapshot` from it
- Uses `httpx.AsyncClient` with semaphore (max 5 concurrent) to stay under rate limits
- Cache macro data for 5 minutes (same as current yahoo caching)

**Config changes:**
- Replace `MACRO_TICKERS` dict in `app/config.py` with Finnhub ETF symbols
- Add `FINNHUB_API_KEY` to config

**`macro_scout.py` changes:**
- Current code wraps synchronous `yahoo.fetch_macro_data()` in `run_in_executor`. New `finnhub.fetch_macro_data()` is async, so remove the `run_in_executor` wrapper and `await` directly instead.
- `fear_greed.py` is unaffected — continues to work as-is.

**Frontend changes:** None — same data shape, same render functions (`renderMacro()` for the regime banner, `renderMarketOverview()` for the market tiles).

**Files modified:**
- `app/services/finnhub.py` (new)
- `app/services/yahoo.py` (delete)
- `app/config.py` (update ticker mapping, add API key)
- `app/agents/macro_scout.py` (switch import, remove `run_in_executor`, `await` directly)
- `requirements.txt` (remove yfinance, add httpx if not already present)

### 2. Implement ATR & VWAP End-to-End

**Problem:** Frontend has ATR and VWAP indicator pills (added in v2.1), but they always show "N/A" because the backend doesn't compute or return these values.

**What needs to be built:**

**New models in `app/models/schemas.py`:**
```python
class ATRResult(BaseModel):
    value: float   # absolute ATR value
    pct: float     # ATR as percentage of current price
    period: int = 14

class VWAPResult(BaseModel):
    value: float
    price_vs_vwap: str   # "above", "below", "at"
    distance_pct: float  # percentage distance from VWAP
```

**New fields on `TechnicalSnapshot`:**
```python
atr: ATRResult | None = None
vwap: VWAPResult | None = None
```

**New compute functions in `app/indicators/technical.py`:**
- `compute_atr(df, period=14) -> ATRResult` — standard ATR using True Range over rolling window
- `compute_vwap(df) -> VWAPResult` — cumulative (typical_price × volume) / cumulative_volume

**Integration into `analyze_klines()`:**
- Call `compute_atr()` and `compute_vwap()` alongside existing `compute_macd()`, `compute_bollinger()`, `compute_rsi()`
- Pass results into `TechnicalSnapshot` constructor
- Wrap in try/except so failures return None gracefully (frontend handles None → "N/A")
- 200-candle fetch provides sufficient data for ATR (14 period) and VWAP

**Files modified:**
- `app/models/schemas.py` (add `ATRResult`, `VWAPResult` models + fields on `TechnicalSnapshot`)
- `app/indicators/technical.py` (add `compute_atr()`, `compute_vwap()`, integrate into `analyze_klines()`)
- No frontend changes — pills already render ATR/VWAP from `tf.atr` and `tf.vwap`

### 3. Asset Heatmap

**Problem:** No quick visual scan of market performance across all 10 assets. You have to read each card individually.

**Solution:** Horizontal 10-cell heatmap strip between the market overview and the asset cards grid.

**Design:**
- 10 cells in a single row, one per asset
- Each cell shows: symbol (bold) + 24h change percentage
- Background color intensity proportional to change magnitude:
  - Green gradient: `rgba(0, 212, 170, opacity)` where opacity = `min(change_pct * 10, 80)%`
  - Red gradient: `rgba(255, 107, 107, opacity)` for negative changes
  - Neutral (< ±0.1%): `var(--bg-2)` background
- Cells are clickable — smooth-scroll to that asset's card in the grid below
- Responsive: wraps to 5×2 grid on mobile (< 600px)

**Data source:** Uses existing `AssetIntel.change_24h_pct` — no backend changes.

**Frontend changes:**
- New `renderHeatmap(assets)` function in `frontend/index.html`
- Called from the session POST response handler after `renderMarketOverview()`
- New HTML section `#heatmapSection` in the shell between market overview and main content
- CSS for `.heatmap-section`, `.heatmap-grid`, `.heatmap-cell`

### 4. Mini Sparkline Charts

**Problem:** Asset cards show current price and 24h change as numbers, but you can't see the *shape* of the move — was it a sudden spike, a steady grind, a V-recovery?

**Solution:** 32px tall SVG sparkline on each asset card, showing last 24 hours of 1h close prices.

**Backend changes:**
- Add `sparkline_24h: list[float] | None = None` field to `AssetIntel` in `app/models/schemas.py`
- In `app/agents/market_intel.py`, after fetching 1h klines, extract the last 24 close prices and attach to the asset object
- Data is already fetched (200 candles for primary_tf) — just slice the last 24 closes

**Frontend changes:**
- New `buildSparkline(prices, isPositive)` function that returns an SVG string
- SVG uses `viewBox="0 0 200 32"` with `preserveAspectRatio="none"` to stretch to card width
- Line path + area fill with gradient matching sentiment color (green/red)
- Current price dot (circle) at the rightmost point
- Placed between the asset header and the sentiment/bias gauge row
- No chart library — pure inline SVG generation from the price array

**Sparkline rendering logic:**
```
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
  const color = isPositive ? '#00d4aa' : '#ff6b6b';
  // Return SVG with line path, area fill, and end dot
}
```

## Data Flow

```
Session POST → response handler:
  1. Finnhub API → macro dict → macro_scout builds MacroSnapshot → renderMacro() + renderMarketOverview()
  2. Binance 1h klines → analyze_klines() → TechnicalSnapshot (with ATR, VWAP) → renderAssets()
  3. Binance 1h klines → last 24 closes → sparkline_24h on AssetIntel → buildSparkline()
  4. AssetIntel.change_24h_pct → renderHeatmap()
  5. fear_greed API → F&G index (unchanged)
```

## Files Changed

| File | Action | What |
|------|--------|------|
| `app/services/finnhub.py` | Create | Async Finnhub API client returning same dict format as yahoo |
| `app/services/yahoo.py` | Delete | No longer needed |
| `app/config.py` | Modify | Finnhub API key + ETF ticker mapping |
| `app/agents/macro_scout.py` | Modify | Switch import, remove `run_in_executor`, `await` directly |
| `app/models/schemas.py` | Modify | Add `ATRResult`, `VWAPResult` models; add fields to `TechnicalSnapshot`; add `sparkline_24h` to `AssetIntel` |
| `app/indicators/technical.py` | Modify | Add `compute_atr()`, `compute_vwap()`; integrate into `analyze_klines()` |
| `app/agents/market_intel.py` | Modify | Populate `sparkline_24h` from 1h klines |
| `frontend/index.html` | Modify | Heatmap section + renderHeatmap(); sparkline builder + placement in card |
| `requirements.txt` | Modify | Remove yfinance, ensure httpx present |

## What NOT to Change

- Recommendation cards — no changes this sprint (scenarios are Sprint 2)
- Trade tracker, feedback stats — keep as-is
- Sort/filter controls — keep as-is
- Signal emphasis (left border accent) — keep as-is
- `app/services/fear_greed.py` — unaffected by Finnhub migration
- Frontend ATR/VWAP pill rendering — already implemented in v2.1

## Verification

1. Start server: `cd "/Users/ls/Documents/Trading Copilot" && PYTHONPATH=. "./venv/bin/python" -m uvicorn app.main:app --reload --port 8000`
2. Open `http://localhost:8000`
3. Run a session
4. Confirm:
   - Market overview strip loads with real data from Finnhub (SPY, QQQ, UUP, VIXY, etc. displayed as "S&P 500", "Dollar", etc.)
   - Heatmap strip shows all 10 assets with color-coded 24h performance
   - Clicking a heatmap cell scrolls to the corresponding asset card
   - Each asset card has a 32px sparkline showing last 24h price shape
   - Sparkline is green for positive 24h change, red for negative
   - ATR and VWAP indicator pills show real computed values (not "N/A")
   - All existing features still work (recs, trade log, feedback, sort/filter, mobile)
