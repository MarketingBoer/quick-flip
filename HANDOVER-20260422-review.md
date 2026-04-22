# HANDOVER — QuickFlip Zelflerend Trading Systeem (Review-update)

**Datum:** 2026-04-22
**Sessie:** Plan review + fixes (geen implementatie)

---

## Stap 1 — Projectcontext

**Project:** QuickFlip — AI crypto trading bot die zelflerend wordt
**Waarom:** De bot draait rule-based en leert niets van trades. Eigenaar wil dat de bot na elke trade slimmer wordt.
**Eindresultaat:** Een team van 5 agents (Markt Scout, Analist, Beslisser, Leraar, Boekhouder) die communiceren via een gedeelde SQLite database. De bot start met 12 maanden backtest-ervaring (~300 trades) en leert daarna door bij elke live trade.

## Stap 2 — Huidige staat

```
AFGEROND:
- Implementatieplan v2 geschreven en 3x gereviewed (bug-hunter, ai-engineer, Grok)
- Plan review sessie: 10 issues gevonden en allemaal verwerkt in het plan
- MEMORY.md gecorrigeerd (verkeerde config-waarden: 1h→15m, €14→€10)

BEZIG:
- Niets — plan is klaar, implementatie nog niet begonnen

GEBLOKKEERD:
- Niets

NOG NIET BEGONNEN:
- Stap 1-11 van het implementatieplan (geschatte doorlooptijd: 2-3 sessies)
- Eerste stap: backup strategie + agents/ directory aanmaken
```

## Stap 3 — Beslissingen

**Beslissing:** 12 maanden data + 30 pairs voor backtest (was: 6 maanden + 15 pairs)
**Waarom:** Met 6 maanden + 15 pairs leverde de backtest slechts 79 trades op. Te weinig voor betrouwbare SEEK/AVOID ratings. 12 maanden + 30 pairs levert ~300 trades.
**Risico als dit veranderd wordt:** Minder data = minder betrouwbare patronen, langere leertijd live.

**Beslissing:** Grok 4.20 voor Beslisser, Sonnet 4.6 voor Leraar
**Waarom:** Eigenaar vertrouwt Grok voor marktanalyse. Sonnet voor evaluatie/lessen (goedkoper, betrouwbare JSON output). ~$13/maand.

**Beslissing:** Agents communiceren via SQLite, niet via elkaars context
**Waarom:** Context-overloop voorkomen. Elke agent krijgt schone context per aanroep. Database groeit onbeperkt, agents blijven scherp.

## Stap 4 — Waar alles staat

```
BESTANDEN:
- Implementatieplan      → ~/.claude/plans/we-moeten-deze-2-parsed-cosmos.md
- Review-fix plan        → ~/.claude/plans/compiled-yawning-bunny.md
- Huidige strategie      → ~/Projects/quick-flip/user_data/strategies/QuickFlipStrategy.py
- Bestaande backtest     → ~/Projects/quick-flip/user_data/backtest_results/backtest-result-2026-04-21_23-56-45.zip (79 trades, oud)
- Knowledge entries      → ~/Projects/quick-flip/user_data/knowledge.jsonl (15 entries, oud format)
- Vorige handover        → ~/Projects/quick-flip/HANDOVER-20260422.md
- Research rapport       → ~/Projects/quick-flip/research/ai-trading-tools-rapport-2026-04-22.md

REPOS:
- ~/Projects/quick-flip/ → master → 5a1ad6b4

CONFIGS / CREDENTIALS:
- API keys → ~/.secrets (OPENROUTER_API_KEY) + user_data/config.json (Bitvavo)
- Freqtrade config → user_data/config.json
- Systemd service → ~/.config/systemd/user/quickflip.service

EXTERNE SYSTEMEN:
- OpenRouter API → openrouter.ai (Grok 4.20 + Sonnet 4.6 beschikbaar, geverifieerd)
- Bitvavo exchange → via Freqtrade CCXT
- REST API → localhost:8080 (user: quickflip)
```

## Stap 5 — Exacte volgende stap

1. `cd ~/Projects/quick-flip && cp user_data/strategies/QuickFlipStrategy.py user_data/strategies/QuickFlipStrategy.py.bak-pre-agents`
2. `mkdir -p user_data/agents && touch user_data/agents/__init__.py`
3. Begin met `user_data/agents/learning_db.py` — het SQLite schema met 4 tabellen (predictions, patterns, regime_snapshots, knowledge) + WAL mode + indexes + CRUD functies. Dit is de fundering waar alle agents op leunen.

## Stap 6 — Bekende risico's en valkuilen

- **Grok JSON betrouwbaarheid:** Grok levert niet altijd schone JSON. De openrouter_client.py moet robuuste JSON parsing hebben met fallback.
- **Backtest importer complexiteit:** De importer moet historische candle data laden per trade om confluence score en regime te berekenen. Dit is complexer dan een simpele CSV-import.
- **OpenRouter credits:** Waren recent bijna op. Zorg dat er genoeg credits staan voor implementatie + testen.
- **PORTAL spam in journal data:** Bij import van knowledge.jsonl opletten dat er geen PORTAL-gerelateerde rommel meegaat.
- **NIET doen:** De bestaande safety functies (`_check_daily_loss`, `_record_loss`, `daily_loss_limit_eur`) verwijderen — die staan expliciet als BEHOUDEN in het plan.

## Stap 7 — Open vragen

- Geen blokkerende vragen. Plan is klaar voor implementatie.

## Stap 8 — MemPalace diary + git
