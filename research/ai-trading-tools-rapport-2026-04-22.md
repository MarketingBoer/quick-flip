# QuickFlip — AI Trading Tools & Strategieën Research Rapport

**Datum:** 2026-04-22
**Onderzocht door:** Claude Code (Opus 4.6) + 2 research agents + Grok 4.20
**Doel:** Welke GitHub-repos, YouTube-setups en tools hebben toegevoegde waarde voor QuickFlip?

---

## 1. Huidige QuickFlip Setup

| Parameter | Waarde |
|-----------|--------|
| Platform | Freqtrade v2026.3 |
| Exchange | Bitvavo (EU, spot) |
| Strategie | Rule-based: EMA / RSI / MACD / BB / Volume |
| Timeframe | 1h candles |
| Trades | 2 simultaan × €14 |
| Stoploss | -3% |
| Daily loss limit | €5 |
| Budget gereserveerd | €40 |
| AI component | Gemini Flash — post-trade analyse |
| Knowledge base | 15 entries (marktcondities, per-munt analyse, correlaties) |
| Status | LIVE sinds 2026-04-20, eerste trade EDU/EUR op 2026-04-21 |
| Service | systemd `quickflip.service` (24/7) |
| CLI | `quickflip start/stop/status/logs/journal/knowledge/kill` |

---

## 2. Onderzochte GitHub Repositories

### 2.1 NostalgiaForInfinity
- **URL:** https://github.com/iterativv/NostalgiaForInfinity
- **Wat:** Populairste community Freqtrade-strategie. 22K commits, 515 releases, v17.3 (april 2026)
- **Technisch:** Vereist 5m candles, 6-12 simultane trades, 40-80 paren, USDT/USDC stablecoin paren
- **Bitvavo:** Wordt ondersteund volgens wiki, maar setup is incompatibel met QuickFlip (5m vs 1h, veel trades vs 2 trades, hoge stakes vs €14)
- **Verdict:** NIET BRUIKBAAR in huidige setup. Wel nuttig als referentie voor indicator-combinaties
- **Actie:** Geen

### 2.2 roman-rr/trading-skills
- **URL:** https://github.com/roman-rr/trading-skills
- **Wat:** Claude Code crypto signals plugin. 17 triggers × 44 algoritmes × 3 AI experts. Gratis in beta
- **Technisch:** Alleen Hyperliquid perpetuals (niet spot). Output: entry/SL/TP/leverage/confidence per signal
- **Community:** 20 stars, 19 commits. Geen backtests gepubliceerd, geen user reviews gevonden
- **Verdict:** OVERSLAAN. Onbewezen beta, perps-only, niet voor Bitvavo spot
- **Actie:** Geen

### 2.3 agiprolabs/claude-trading-skills
- **URL:** https://github.com/agiprolabs/claude-trading-skills
- **Wat:** 62 crypto/DeFi skills voor Claude Code. MIT licentie
- **Technisch:** Sterk Solana-gericht (PumpFun, Jito, Raydium). Gratis API's (CoinGecko, DeFiLlama, DexScreener)
- **Skills:** LP math, impermanent loss, MEV analyse, whale tracking, on-chain analyse, technische indicatoren
- **Community:** 14 stars, 4 commits. Beperkt onderhoud
- **Verdict:** OVERSLAAN. Te Solana-specifiek, weinig overlap met Bitvavo spot trading
- **Actie:** Geen

### 2.4 Byte-Ventures/claude-trader
- **URL:** https://github.com/Byte-Ventures/claude-trader
- **Wat:** Experimenteel crypto trading framework met AI trade analyse
- **Technisch:** Exact dezelfde indicatoren als QuickFlip:
  - RSI (25% gewicht)
  - MACD (25%)
  - Bollinger Bands (20%)
  - EMA Crossover (15%)
  - Volume (15%)
  - Trade wanneer score >= 60 (of <= -60 voor sells)
- **AI systeem:** 3 reviewer-agents (Pro / Neutraal / Tegenstander) + rechter-agent voor finaal besluit
- **Safety:** Kill switch, circuit breaker (geel/rood/zwart), dagelijkse verlieslimieten, Fear & Greed index
- **Exchanges:** Alleen Coinbase + Kraken (geen Bitvavo)
- **Licentie:** AGPL-3.0 (alle wijzigingen moeten gedeeld worden)
- **Community:** 261 commits, 34 releases, actief onderhouden
- **Verdict:** NIET INSTALLEREN (verkeerde exchange, AGPL), maar de CODE LEZEN voor:
  1. Confluence scoring systeem (indicator gewichten + drempel)
  2. 3-reviewer AI architectuur
  3. Circuit breaker patronen
- **Actie:** Confluence scoring patroon overnemen in QuickFlip strategie

### 2.5 hugoguerrap/crypto-claude-desk
- **URL:** https://github.com/hugoguerrap/crypto-claude-desk
- **Wat:** Multi-agent crypto intelligence platform. 7 agents, 83 MCP tools. MIT licentie
- **Agents:**
  - Market-Monitor (Haiku) — live prijzen, volume, funding rates
  - Technical-Analyst (Sonnet) — 38 indicatoren
  - News-Sentiment (Sonnet) — nieuwsanalyse
  - Risk-Specialist (Sonnet) — volatiliteit, risico
  - Portfolio-Manager (Opus) — EXECUTE/WAIT/REJECT besluiten
  - Learning-Agent (Opus) — voorspellingen, post-mortem
  - System-Builder (Opus) — genereert nieuwe MCP servers
- **Leermechanisme:** Bij trade-opening: agents leggen voorspellingen vast. Bij sluiting: NL-evaluatie van predictions vs werkelijkheid. Bouwt setup win-rates op (SEEK >60%, AVOID <40%)
- **Architectuur:** Zero-code orchestratie via CLAUDE.md (geen Python state machine). Model-tiering bespaart 40-60% tokens
- **Status:** Paper trading only, niet production-ready
- **Verdict:** NIET INSTALLEREN voor live trading, maar het LEERMECHANISME is het meest waardevolle concept:
  1. Predictions tracking bij elke trade
  2. NL-evaluatie achteraf
  3. Win-rates per setup type
- **Actie:** Learning-agent concept overnemen voor QuickFlip/Hermes

### 2.6 atilaahmettaner/tradingview-mcp
- **URL:** https://github.com/atilaahmettaner/tradingview-mcp
- **Wat:** TradingView MCP server voor Claude Code. 2.1K stars, MIT licentie, actief onderhouden
- **Features:** Backtesting voor RSI, MACD, BB, Supertrend, EMA, Donchian. Sharpe/Calmar metrics. Multi-exchange screening
- **Exchanges:** Binance, KuCoin, Bybit (geen Bitvavo, maar cross-exchange data is bruikbaar)
- **Verdict:** INSTALLEREN — directe waarde voor strategie-validatie naast Freqtrade's eigen backtester
- **Actie:** Toevoegen aan Claude Code MCP configuratie

### 2.7 CoinGecko MCP Server
- **URL:** https://docs.coingecko.com/docs/mcp-server
- **Wat:** Officiële CoinGecko MCP server. 15K+ coins, realtime prijzen, on-chain analytics
- **Setup:** JSON config in settings.json, geen API key nodig (free tier)
- **Verdict:** INSTALLEREN — drop-in marktdata bron voor Claude Code sessies
- **Actie:** Toevoegen aan Claude Code MCP configuratie (5 minuten)

### 2.8 FreqAI (ingebouwd in Freqtrade)
- **URL:** https://www.freqtrade.io/en/stable/freqai/
- **Wat:** ML-laag ingebouwd in Freqtrade. LightGBM, XGBoost, PyTorch
- **Hoe:** Inject ML features in `populate_indicators()` + retrain cadence config. Config-driven, geen Python nodig tenzij custom models
- **Verdict:** LATER — pas nuttig na 50-100 trades met genoeg trainingsdata
- **Actie:** Bookmarken voor evaluatie na 4 weken live trading

### 2.9 Freqtrade + Bitvavo bekende issues
- `clientOrderId` parameter errors (GitHub issue #10942)
- NoneType arithmetic errors (issue #9560, #6166)
- Mitigatie: regenereer API keys bij Nonce errors

---

## 3. Onderzochte YouTube Video's

### 3.1 "Architect Algorithm" — AI als trade gatekeeper (jouw video)
- **URL:** https://youtu.be/Av0M0p2_W0A
- **Maker:** Onbekend
- **Concept:** AI-laag bovenop bestaande algo strategie. Elke trade wordt door AI gevalideerd VOOR executie
- **Hoe het werkt:**
  - Core strategie ("Vigorous") neemt 20-30 trades/dag op EUR/USD M1
  - Bij elk entry-signal: AI analyseert meerdere timeframes (daily, 1h, M15, M1)
  - AI checkt nieuws + geplande events via MetaTrader 5
  - AI geeft go/no-go + confidence score (bijv. 0.38 = nee, 0.65 = ja)
  - Alleen traden bij voldoende confidence
- **Resultaten:** 398 trades, 87% winrate (was 65-70% zonder AI), profit factor 4.15, 9% gain, 2% drawdown
- **Beperking:** AI-component kan niet worden gebacktest (realtime inputs)
- **RELEVANTIE VOOR QUICKFLIP: HOOG** — Dit is het model. Gemini Flash omzetten van post-trade reviewer naar pre-trade gatekeeper

### 3.2 "AI Trading Team With Claude Code in 14 min"
- **URL:** https://www.youtube.com/watch?v=HfEu7XPUnAU
- **Concept:** 5 parallelle research agents: technisch / fundamenteel / sentiment / risico / thesis
- **Output:** Investment thesis met composite score, entry zone, SL, 3x TP, position sizing, risk matrix
- **Hoe:** Slash-commands in Claude Code. Discovery fase → 5 agents parallel → synthese rapport
- **Installatie:** Skills folder unzippen in workspace, of repo-based install
- **RELEVANTIE VOOR QUICKFLIP: MEDIUM** — Het multi-agent research concept past bij Hermes (perplexity-researcher + flash-seo + opus-reviewer als pre-trade pipeline)

### 3.3 "How To Use Claude Code for Trading (Like a Quant)"
- **URL:** https://www.youtube.com/watch?v=EUSXhJNwRqI
- **Concept:** Hidden Markov Model (7 regimes) op hourly data. Detecteert bull/crash/chop met confidence
- **Hoe:** HMM getraind op ~11.000-17.000 hourly samples (returns, range, volume/volatility)
- **Parameters:** 2.5x leverage, entry na meerdere bevestigingen, exit bij regime-flip, 48u cooldown na exit
- **Resultaten:** ~3x portfolio growth in één run, 65% return, 63% alpha, 41% max drawdown in backtest
- **Iteratie:** Run backtests → prompt AI om regels aan te scherpen → herhaal
- **RELEVANTIE VOOR QUICKFLIP: HOOG** — Regime-detectie is wat QuickFlip mist. Je handelt nu blind in elke marktconditie. Een simpele variant (BTC trend als markt-proxy) zou slechte trades voorkomen

### 3.4 "ULTIMATE Claude Code Trading Assistant" + TradingView
- **URL:** https://www.youtube.com/watch?v=vTkZK8PK114
- **Concept:** Claude Code + TradingView desktop integratie. 78 tools
- **Features:**
  1. Automatische morning briefs (watchlist → NL-samenvatting met conviction levels)
  2. Deep-dive second opinions (multi-timeframe analyse per symbol)
  3. Strategie-import vanuit YouTube-transcripts (URL → strategie → indicators op chart)
- **Setup:** 6-staps installer via terminal, ~5 minuten. TradingView desktop app vereist
- **RELEVANTIE VOOR QUICKFLIP: MEDIUM** — TradingView MCP is bruikbaar voor analyse. Morning briefs concept past bij Hermes cron-taken

### 3.5 "Full AI Trading Bot Using Claude Code (Insane Results)"
- **URL:** https://www.youtube.com/watch?v=tsCI72TWzsg
- **Concept:** Claude Code + Telegram + Hyperliquid. Plain English trade executie
- **Features:**
  - Multi-trade executie via chat ("open 5x long BTC $10, short DOGE $5, set 3% SL + 8% TP")
  - Portfolio dashboards met equity curves, win rates, funding income
  - Funding rate scanner (assets met hoge annualized yields)
  - Copy-trading: screenshots van top-wallets (Hyperdash) → AI analyseert + plaatst trades
- **Security:** Lokaal draaien, withdrawal permissions disabled, alle acties gelogd
- **Automatisering:** TradingView webhooks → auto-executie bij signal
- **RELEVANTIE VOOR QUICKFLIP: LAAG** — Hyperliquid perps, niet Bitvavo spot. Maar het Telegram-integratie concept is al beschikbaar via Hermes

---

## 4. Rode draad — Wat succesvolle setups gemeen hebben

Alle onderzochte succesvolle trading setups delen drie patronen:

### Patroon A: AI als pre-trade gatekeeper (niet post-trade reviewer)
De Architect-video laat het duidelijkst zien: winrate steeg van 65-70% naar 87% door AI VOOR elke trade te laten beslissen. QuickFlip doet dit nu andersom — Gemini Flash reviewt pas NA de trade.

### Patroon B: Regime-awareness (niet blind handelen in elke markt)
De Quant-video gebruikt een Hidden Markov Model om marktregimes te detecteren. Simpelere variant: niet handelen in sideways/bearish markt. QuickFlip heeft dit niet.

### Patroon C: Confluence scoring (niet alles-of-niets)
De claude-trader repo laat zien hoe je indicatoren gewichten geeft en een drempel instelt. QuickFlip's huidige logica is binair (alle condities moeten waar zijn), niet gewogen.

---

## 5. Beoordelingen

### Claude's beoordeling
Voor een bot met 1 trade en €40 budget is nu tooling toevoegen premature optimalisatie. De bot moet eerst draaien en data genereren. Backtesting op historische data is het hoogste ROI-gedrag. Na 50-100 trades: FreqAI of betere scoring evalueren.

**Maar:** De pre-trade gatekeeper (Patroon A) en regime-detectie (Patroon B) zijn geen "extra tooling" — het zijn verbeteringen aan de bestaande strategie die de kwaliteit van elke trade verhogen. Die zijn wél nu relevant.

### Grok's beoordeling (HQ-Grok, x-ai/grok-4.20)
> "Nu die repos gaan installeren of integreren is de kar voor het paard spannen. QuickFlip heeft 1 trade. Dat is statistisch lawaai."

Grok adviseert:
1. Confluence scoring uit claude-trader overnemen (enig repo dat direct relevant is)
2. Serieuze backtesting op exacte setup (2023-2025, 1h Bitvavo data)
3. Structured trade logging (JSON/SQLite) + Gemini review elke 10 trades
4. Geen multi-agent systemen, geen FreqAI, geen externe tools

> "Focus de komende 3-4 weken op 20-30 trades met de huidige strategie + confluence scoring + keiharde backtesting. Alles daarboven is nu ego."

---

## 6. Actieplan — Prioriteit

### NU doen (verhoogt kwaliteit van elke trade)

| # | Actie | Bron | Effort | Impact |
|---|-------|------|--------|--------|
| 1 | **Backtesting** op 2023-2025 1h data met exacte parameters | Freqtrade built-in | 2-3 uur | Valideert of strategie überhaupt een edge heeft |
| 2 | **Gemini Flash pre-trade gatekeeper** inbouwen | Architect-video concept | 3-4 uur | Winrate verbetering (65→87% in Architect case) |
| 3 | **Regime-filter** toevoegen (BTC > 20-EMA daily = long OK) | Quant-video concept | 30 min | Voorkomt trades in bear/sideways markt |
| 4 | **Confluence scoring** met gewichten i.p.v. binaire logica | claude-trader repo | 1-2 uur | Fijnmaziger entry-beslissingen |

### OVER 2-4 WEKEN (na genoeg data)

| # | Actie | Bron | Trigger |
|---|-------|------|---------|
| 5 | Trade logger + Gemini 10-trade reviews | Grok advies | Na 20+ trades |
| 6 | FreqAI ML-laag evalueren | Freqtrade docs | Na 50-100 trades |
| 7 | TradingView MCP installeren | tradingview-mcp repo | Wanneer backtesting nodig is buiten Freqtrade |
| 8 | CoinGecko MCP installeren | CoinGecko docs | Wanneer marktdata in Claude sessies nodig is |

### BOOKMARKEN (niet nu, mogelijk later)

| Repo | Waarom bewaren | Wanneer relevant |
|------|---------------|-----------------|
| crypto-claude-desk | Learning-agent architectuur | Als je trade-learning wilt bouwen in Hermes |
| NostalgiaForInfinity | Indicator-combinaties referentie | Als je naar 5m candles wilt overstappen |
| FreqAI docs | ML-laag voor Freqtrade | Na 50-100 trades met genoeg data |
| agiprolabs/claude-trading-skills | DeFi/on-chain analyse | Als je naast Bitvavo ook DeFi wilt |

---

## 7. Bronnen

### GitHub Repositories
- https://github.com/iterativv/NostalgiaForInfinity
- https://github.com/roman-rr/trading-skills
- https://github.com/agiprolabs/claude-trading-skills
- https://github.com/Byte-Ventures/claude-trader
- https://github.com/hugoguerrap/crypto-claude-desk
- https://github.com/atilaahmettaner/tradingview-mcp
- https://docs.coingecko.com/docs/mcp-server
- https://github.com/freqtrade/freqtrade-strategies
- https://www.freqtrade.io/en/stable/freqai/

### YouTube Video's
- https://youtu.be/Av0M0p2_W0A — Architect Algorithm (AI gatekeeper, 87% winrate)
- https://www.youtube.com/watch?v=HfEu7XPUnAU — AI Trading Team in 14 min
- https://www.youtube.com/watch?v=EUSXhJNwRqI — Trading Like a Quant (HMM regime detection)
- https://www.youtube.com/watch?v=vTkZK8PK114 — ULTIMATE Trading Assistant + TradingView
- https://www.youtube.com/watch?v=tsCI72TWzsg — AI Trading Bot + Telegram (Insane Results)

### Freqtrade + Bitvavo Issues
- https://github.com/freqtrade/freqtrade/issues/10942 — clientOrderId error
- https://github.com/freqtrade/freqtrade/issues/9560 — NoneType error
- https://github.com/freqtrade/freqtrade/issues/6166 — NoneType multiplication error
