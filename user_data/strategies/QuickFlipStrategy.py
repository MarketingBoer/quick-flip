import numpy as np
import pandas as pd
import logging
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pandas import DataFrame
from typing import Optional

from freqtrade.strategy import IStrategy, Trade

import talib.abstract as ta
from technical import qtpylib

logger = logging.getLogger(__name__)


class QuickFlipStrategy(IStrategy):

    INTERFACE_VERSION = 3
    can_short = False

    minimal_roi = {
        "0": 0.03,
        "30": 0.02,
        "60": 0.015,
        "120": 0.01,
        "360": 0.005,
    }

    stoploss = -0.05

    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.02
    trailing_only_offset_is_reached = True

    timeframe = "5m"
    process_only_new_candles = True
    startup_candle_count = 50

    max_open_trades = 3
    stake_amount = "unlimited"

    # Paths
    trade_journal_path = os.path.expanduser(
        "~/Projects/quick-flip/user_data/trade_journal.jsonl"
    )
    knowledge_path = os.path.expanduser(
        "~/Projects/quick-flip/user_data/knowledge.jsonl"
    )

    # AI config
    ai_enabled = True
    ai_model = "google/gemini-2.5-flash-preview"
    ai_cooldown_seconds = 30
    _last_ai_call = 0

    # Safety: daily loss limit
    daily_loss_limit_eur = 10.0
    _daily_loss_tracker = {"date": "", "loss": 0.0}

    # Research cooldown (max 3x per dag)
    _research_calls_today = {"date": "", "count": 0}
    research_max_per_day = 3

    def _get_openrouter_key(self) -> Optional[str]:
        secrets_path = os.path.expanduser("~/.secrets")
        if not os.path.exists(secrets_path):
            return None
        with open(secrets_path) as f:
            for line in f:
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.strip().split("=", 1)[1].strip('"').strip("'")
        return None

    def _check_daily_loss(self) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_loss_tracker["date"] != today:
            self._daily_loss_tracker = {"date": today, "loss": 0.0}

        if self._daily_loss_tracker["loss"] >= self.daily_loss_limit_eur:
            logger.warning(
                f"Daily loss limit reached: €{self._daily_loss_tracker['loss']:.2f}"
            )
            return False
        return True

    def _record_loss(self, loss_eur: float):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_loss_tracker["date"] != today:
            self._daily_loss_tracker = {"date": today, "loss": 0.0}
        if loss_eur > 0:
            self._daily_loss_tracker["loss"] += loss_eur

    def _do_research(self, query: str) -> Optional[str]:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._research_calls_today["date"] != today:
            self._research_calls_today = {"date": today, "count": 0}
        if self._research_calls_today["count"] >= self.research_max_per_day:
            return None

        api_key = self._get_openrouter_key()
        if not api_key:
            return None

        try:
            import httpx

            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "google/gemini-2.5-flash-preview",
                    "messages": [{"role": "user", "content": query}],
                    "max_tokens": 300,
                    "temperature": 0.2,
                },
                timeout=15,
            )

            self._research_calls_today["count"] += 1

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                self._save_knowledge(query, content)
                return content
        except Exception as e:
            logger.warning(f"Research failed: {e}")
        return None

    def _save_knowledge(self, query: str, answer: str):
        try:
            with open(self.knowledge_path, "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "query": query,
                    "answer": answer[:500],
                }) + "\n")
        except Exception:
            pass

    def _get_knowledge_context(self) -> str:
        if not os.path.exists(self.knowledge_path):
            return ""
        try:
            entries = []
            with open(self.knowledge_path) as f:
                for line in f:
                    entries.append(json.loads(line))
            recent = entries[-5:]
            return "\n".join(
                f"- {e['query']}: {e['answer'][:100]}" for e in recent
            )
        except Exception:
            return ""

    def _ask_ai(self, pair: str, dataframe: DataFrame, current_rate: float) -> dict:
        now = time.time()
        if now - self._last_ai_call < self.ai_cooldown_seconds:
            return {"confidence": 0.5, "reason": "cooldown"}

        api_key = self._get_openrouter_key()
        if not api_key:
            logger.warning("No OpenRouter API key found in ~/.secrets")
            return {"confidence": 0.5, "reason": "no_api_key"}

        try:
            import httpx

            last_10 = dataframe.tail(10)
            price_data = {
                "prices": last_10["close"].tolist(),
                "volumes": last_10["volume"].tolist(),
                "rsi": round(last_10["rsi"].iloc[-1], 1),
                "ema_fast": round(last_10["ema_fast"].iloc[-1], 4),
                "ema_slow": round(last_10["ema_slow"].iloc[-1], 4),
                "volume_sma": round(last_10["volume_sma"].iloc[-1], 1),
                "current_rate": current_rate,
            }

            recent_trades = self._get_recent_trades(pair)
            knowledge = self._get_knowledge_context()

            prompt = f"""Je bent een crypto trading analist op Bitvavo (NL exchange).

MISSIE:
- Dit is een GROEIPROJECT. We beginnen klein (€46) en laten kennis en kapitaal samen groeien.
- Elke trade is een leermoment. Bescherm het kapitaal ALTIJD — verlies vermijden is belangrijker dan winst pakken.
- De eigenaar zal af en toe bijstorten als de bot bewezen slim handelt.
- Later upgraden we naar slimmere AI-modellen. Jij bent fase 1: bewijs dat je consistent kunt zijn.
- Doel nu: een paar euro per dag. €10/maand is al een succes. Niet hebberig zijn. Geduld > snelheid.

EXCHANGE KENNIS:
- Bitvavo fees: 0.20% maker/taker (roundtrip 0.40%)
- Minimum order: €5 (check minOrderInQuoteAsset per market)
- Ons kapitaal: ~€46, max 3 open trades, ~€15 per positie
- Doel: momentum trades, snel in/uit, 1-3% winst per trade
- Bij twijfel: NIET kopen. Fees vreten kleine winsten op.
- Liever 1 goede trade per dag dan 10 matige trades.

GELEERDE KENNIS:
{knowledge if knowledge else "Nog geen opgebouwde kennis."}

MARKTDATA:
Pair: {pair}
Laatste 10 candles (5min): {json.dumps(price_data)}

EERDERE TRADES (leer hiervan):
{json.dumps(recent_trades) if recent_trades else "Geen eerdere trades."}

OPDRACHT: Beoordeel of dit een goede entry is.
Antwoord ALLEEN met dit JSON object:
{{"confidence": 0.0-1.0, "reason": "max 20 woorden"}}

REGELS:
- confidence >= 0.7 = kopen (sterk momentum + volume bevestiging)
- confidence 0.3-0.7 = overslaan (niet overtuigend genoeg)
- confidence < 0.3 = vermijden (bearish signalen)
- Wees STRENG. Met 0.40% fees moet de verwachte move > 1% zijn.
- RSI > 70 = overbought = NIET kopen. RSI < 30 = oversold = potentiële bounce.
- Volume spike + EMA crossover = sterkste signaal.
- Als eerdere trades op dit pair verlies gaven: extra voorzichtig."""

            response = httpx.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.ai_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 100,
                    "temperature": 0.1,
                },
                timeout=10,
            )

            self._last_ai_call = time.time()

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                content = content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0]
                result = json.loads(content)
                logger.info(f"AI verdict for {pair}: {result}")
                return result
            else:
                logger.warning(f"AI API error: {response.status_code}")
                return {"confidence": 0.5, "reason": "api_error"}

        except Exception as e:
            logger.warning(f"AI call failed: {e}")
            return {"confidence": 0.5, "reason": str(e)[:50]}

    def _get_recent_trades(self, pair: str) -> list:
        if not os.path.exists(self.trade_journal_path):
            return []
        trades = []
        try:
            with open(self.trade_journal_path) as f:
                for line in f:
                    entry = json.loads(line)
                    if entry.get("pair") == pair:
                        trades.append(entry)
        except Exception:
            return []
        return trades[-5:]

    def _log_trade(self, trade_data: dict):
        try:
            with open(self.trade_journal_path, "a") as f:
                f.write(json.dumps(trade_data) + "\n")
        except Exception as e:
            logger.warning(f"Failed to log trade: {e}")

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=8)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=21)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["volume_sma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        bollinger = qtpylib.bollinger_bands(dataframe["close"], window=20, stds=2)
        dataframe["bb_lower"] = bollinger["lower"]
        dataframe["bb_middle"] = bollinger["mid"]
        dataframe["bb_upper"] = bollinger["upper"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema_fast"] > dataframe["ema_slow"])
                & (dataframe["rsi"] < 70)
                & (dataframe["rsi"] > 30)
                & (dataframe["macdhist"] > 0)
                & (dataframe["volume"] > dataframe["volume_sma"])
                & (dataframe["close"] < dataframe["bb_middle"])
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["ema_fast"] < dataframe["ema_slow"])
                & (dataframe["rsi"] > 70)
            )
            | (
                (dataframe["macdhist"] < 0)
                & (dataframe["rsi"] > 65)
            ),
            "exit_long",
        ] = 1
        return dataframe

    def confirm_trade_entry(
        self,
        pair: str,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        current_time: datetime,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> bool:
        if not self._check_daily_loss():
            logger.warning("Trade blocked: daily loss limit reached")
            return False

        if not self.ai_enabled:
            return True

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return True

        ai_result = self._ask_ai(pair, dataframe, rate)
        confidence = ai_result.get("confidence", 0.5)

        self._log_trade({
            "timestamp": current_time.isoformat(),
            "pair": pair,
            "action": "entry_check",
            "rate": rate,
            "ai_confidence": confidence,
            "ai_reason": ai_result.get("reason", ""),
            "approved": confidence >= 0.6,
        })

        if confidence < 0.6:
            logger.info(
                f"AI rejected {pair}: confidence={confidence}, "
                f"reason={ai_result.get('reason')}"
            )
            return False

        logger.info(
            f"AI approved {pair}: confidence={confidence}, "
            f"reason={ai_result.get('reason')}"
        )
        return True

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        return None

    def custom_trade_info(self, trade: Trade, current_time: datetime, **kwargs):
        if trade.is_open:
            return
        profit_eur = trade.realized_profit if hasattr(trade, 'realized_profit') else 0
        self._log_trade({
            "timestamp": current_time.isoformat(),
            "pair": trade.pair,
            "action": "closed",
            "open_rate": trade.open_rate,
            "close_rate": trade.close_rate,
            "profit_pct": round(trade.profit_ratio * 100, 2) if trade.profit_ratio else 0,
            "profit_eur": round(profit_eur, 2),
            "duration_minutes": (
                current_time - trade.open_date_utc
            ).total_seconds() / 60 if trade.open_date_utc else 0,
            "ai_model": self.ai_model,
        })

        if profit_eur < 0:
            self._record_loss(abs(profit_eur))

        loss_count = 0
        try:
            with open(self.trade_journal_path) as f:
                for line in f:
                    e = json.loads(line)
                    if (e.get("action") == "closed"
                            and e.get("pair") == trade.pair
                            and e.get("profit_pct", 0) < 0):
                        loss_count += 1
        except Exception:
            pass

        if loss_count >= 3 and loss_count % 3 == 0:
            self._do_research(
                f"Crypto {trade.pair} heeft {loss_count} keer verlies gegeven. "
                f"Analyse waarom. Huidige marktcondities, nieuws, technische analyse. "
                f"Moet ik dit pair vermijden of is er een patroon?"
            )
