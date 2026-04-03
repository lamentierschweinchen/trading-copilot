# Trading Copilot

Multi-agent crypto trading assistant. Spins up specialized agents to analyze macro conditions, technical indicators, and leverage positioning, then synthesizes trade recommendations via Claude.

## Architecture

```
┌─────────────────────────────────────────────┐
│              POST /session                   │
│         (runs full analysis cycle)           │
└──────────────────┬──────────────────────────┘
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
┌─────────┐  ┌──────────┐  ┌──────────────┐
│  Macro   │  │  Market  │  │   Leverage   │
│  Scout   │  │  Intel   │  │   Context    │
│          │  │          │  │              │
│ yfinance │  │ Binance  │  │ Binance FAPI │
│ F&G API  │  │ klines   │  │ funding rate │
│          │  │ MACD/BB/ │  │ open interest│
│ → regime │  │ RSI      │  │              │
└────┬─────┘  └────┬─────┘  └──────┬───────┘
     │             │               │
     └─────────────┼───────────────┘
                   ▼
          ┌────────────────┐
          │  Synthesizer   │
          │  (Claude API)  │
          │                │
          │  confluence    │
          │  reasoning →   │
          │  recommendations│
          └───────┬────────┘
                  │
                  ▼
          ┌────────────────┐
          │ Feedback Loop  │
          │ (JSON on disk) │
          │                │
          │ logs trades,   │
          │ tracks P&L,    │
          │ feeds stats    │
          │ back to synth  │
          └────────────────┘
```

## Quick Start

```bash
# Clone and cd into project
cd trading-copilot

# Create virtualenv
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set your Anthropic API key
cp .env.example .env
# Edit .env and add your key

# Run the server
uvicorn app.main:app --reload --port 8000
```

## API Endpoints

### Core

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/session` | Run full analysis — all agents fire, returns recommendations |
| `GET` | `/macro` | Macro regime only (cached 30 min) |
| `GET` | `/assets?symbols=BTC,ETH` | Technical analysis for specific assets |
| `GET` | `/leverage?symbols=BTC,ETH` | Funding rates & open interest |

### Trade Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/trades?open_only=true` | List trade logs |
| `POST` | `/trades/{id}/resolve` | Close a trade with outcome |
| `GET` | `/feedback` | Performance statistics |

### Example: Run a Session

```bash
# Full session (all top-10 assets)
curl -X POST http://localhost:8000/session

# Specific assets only
curl -X POST "http://localhost:8000/session?symbols=BTC,ETH,SOL"
```

### Example: Resolve a Trade

```bash
curl -X POST http://localhost:8000/trades/abc123/resolve \
  -H "Content-Type: application/json" \
  -d '{"outcome": "target_hit", "exit_price": 72500.0, "notes": "Clean breakout"}'
```

## Data Sources (all free, no API keys except Anthropic)

- **Binance Public API** — klines, 24h stats, funding rates, open interest
- **yfinance** — SPX, QQQ, DXY, US10Y
- **Alternative.me** — Crypto Fear & Greed Index
- **Anthropic API** — Synthesizer brain (requires API key)

## Indicators

- **MACD** (12/26/9) — trend direction and momentum
- **Bollinger Bands** (20, 2σ) — volatility and mean reversion
- **RSI** (14) — overbought/oversold conditions

## Feedback Loop

Every recommendation is auto-logged. When you resolve trades, the system tracks:
- Win rate overall and per-asset
- Conviction accuracy (are high-conviction trades actually better?)
- Macro alignment performance (do trades aligned with macro regime win more?)

This data feeds into future Synthesizer calls as context.

## Config

Edit `app/config.py` to:
- Add/remove tracked assets
- Change timeframes (default: 1h primary, 4h confirmation)
- Adjust kline history depth
