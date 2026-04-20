import logging
import json
import os
import re
import time
from collections import deque
from datetime import datetime
from pandas import DataFrame
from typing import Optional

from freqtrade.strategy import IStrategy, Trade

import talib.abstract as ta
from technical import qtpylib

logger = logging.getLogger(__name__)

TRADE_JOURNAL = os.path.expanduser(
    "~/Projects/quick-flip/user_data/trade_journal.jsonl"
)
KNOWLEDGE_FILE = os.path.expanduser(
    "~/Projects/quick-flip/user_data/knowledge.jsonl"
)


class QuickFlipStrategy(IStrategy):

    INTERFACE_VERSION = 3
    can_short = False

    minimal_roi = {
        "0": 0.05,
        "60": 0.03,
        "120": 0.02,
        "360": 0.015,
    }

    stoploss = -0.03

    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.025
    trailing_only_offset_is_reached = True

    timeframe = "1h"
    process_only_new_candles = True
    startup_candle_count = 50
    max_open_trades = 2

    # AI config — alleen voor post-trade analyse, NIET in entry-loop
    ai_enabled = False
    ai_model = "google/gemini-2.5-flash-preview"
    ai_cooldown_seconds = 30
    ai_confidence_threshold = 0.7

    # Safety
    daily_loss_limit_eur = 5.0
    research_max_per_day = 3

    def bot_start(self, **kwargs) -> None:
        self._last_ai_call: dict[str, float] = {}
        self._daily_loss = {"date": "", "loss": 0.0}
        self._research_today = {"date": "", "count": 0}
        self._pending_research: list[str] = []

        api_key = self._get_openrouter_key()
        if api_key:
            logger.info("OpenRouter API key loaded")
        else:
            logger.warning("No OpenRouter API key — AI disabled")
            self.ai_enabled = False

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if self._pending_research:
            query = self._pending_research.pop(0)
            self._do_research(query)

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
        if self._daily_loss["date"] != today:
            self._daily_loss = {"date": today, "loss": 0.0}
        if self._daily_loss["loss"] >= self.daily_loss_limit_eur:
            logger.warning(
                f"Daily loss limit reached: €{self._daily_loss['loss']:.2f}"
            )
            return False
        return True

    def _record_loss(self, loss_eur: float):
        today = datetime.now().strftime("%Y-%m-%d")
        if self._daily_loss["date"] != today:
            self._daily_loss = {"date": today, "loss": 0.0}
        if loss_eur > 0:
            self._daily_loss["loss"] += loss_eur

    def _do_research(self, query: str) -> Optional[str]:
        today = datetime.now().strftime("%Y-%m-%d")
        if self._research_today["date"] != today:
            self._research_today = {"date": today, "count": 0}
        if self._research_today["count"] >= self.research_max_per_day:
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
            self._research_today["count"] += 1

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                self._save_knowledge(query, content)
                return content
        except Exception as e:
            logger.warning(f"Research failed: {e}")
        return None

    def _save_knowledge(self, query: str, answer: str):
        try:
            with open(KNOWLEDGE_FILE, "a") as f:
                f.write(json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "query": query,
                    "answer": answer[:500],
                }) + "\n")
        except Exception:
            pass

    def _get_knowledge_context(self) -> str:
        if not os.path.exists(KNOWLEDGE_FILE):
            return ""
        try:
            entries = deque(maxlen=5)
            with open(KNOWLEDGE_FILE) as f:
                for line in f:
                    entries.append(json.loads(line))
            return "\n".join(
                f"- {e['query'][:60]}: {e['answer'][:100]}" for e in entries
            )
        except Exception:
            return ""

    def _parse_ai_response(self, content: str) -> dict:
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0]

        match = re.search(r'\{[^{}]*"confidence"[^{}]*\}', content)
        if not match:
            return {"confidence": 0.5, "reason": "parse_error"}

        try:
            result = json.loads(match.group())
            conf = result.get("confidence", 0.5)
            if isinstance(conf, str):
                conf = float(conf)
            conf = max(0.0, min(1.0, conf))
            result["confidence"] = conf
            return result
        except (json.JSONDecodeError, ValueError):
            return {"confidence": 0.5, "reason": "json_error"}

    def _ask_ai(self, pair: str, dataframe: DataFrame, current_rate: float) -> dict:
        now = time.time()
        last_call = self._last_ai_call.get(pair, 0)
        if now - last_call < self.ai_cooldown_seconds:
            return {"confidence": 0.5, "reason": "cooldown"}

        api_key = self._get_openrouter_key()
        if not api_key:
            return {"confidence": 0.5, "reason": "no_api_key"}

        try:
            import httpx

            last_10 = dataframe.tail(10)
            price_data = {
                "prices": last_10["close"].tolist(),
                "volumes": last_10["volume"].tolist(),
                "rsi": round(float(last_10["rsi"].iloc[-1]), 1),
                "ema_fast": round(float(last_10["ema_fast"].iloc[-1]), 4),
                "ema_slow": round(float(last_10["ema_slow"].iloc[-1]), 4),
                "volume_sma": round(float(last_10["volume_sma"].iloc[-1]), 1),
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
                timeout=5,
            )

            self._last_ai_call[pair] = time.time()

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                result = self._parse_ai_response(content)
                logger.info(f"AI verdict for {pair}: {result}")
                return result
            else:
                logger.warning(f"AI API error: {response.status_code}")
                return {"confidence": 0.5, "reason": "api_error"}

        except Exception as e:
            logger.warning(f"AI call failed: {e}")
            return {"confidence": 0.5, "reason": str(e)[:50]}

    def _get_recent_trades(self, pair: str) -> list:
        if not os.path.exists(TRADE_JOURNAL):
            return []
        trades = []
        try:
            recent_lines = deque(maxlen=200)
            with open(TRADE_JOURNAL) as f:
                for line in f:
                    recent_lines.append(line)
            for line in recent_lines:
                entry = json.loads(line)
                if entry.get("pair") == pair:
                    trades.append(entry)
        except Exception:
            return []
        return trades[-5:]

    def _log_trade(self, trade_data: dict):
        try:
            with open(TRADE_JOURNAL, "a") as f:
                f.write(json.dumps(trade_data) + "\n")
        except Exception as e:
            logger.warning(f"Failed to log trade: {e}")

    def _count_losses(self, pair: str) -> int:
        if not os.path.exists(TRADE_JOURNAL):
            return 0
        count = 0
        try:
            with open(TRADE_JOURNAL) as f:
                for line in f:
                    e = json.loads(line)
                    if (e.get("action") == "closed"
                            and e.get("pair") == pair
                            and e.get("profit_pct", 0) < 0):
                        count += 1
        except Exception:
            pass
        return count

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
            "approved": confidence >= self.ai_confidence_threshold,
        })

        if confidence < self.ai_confidence_threshold:
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

    def confirm_trade_exit(
        self,
        pair: str,
        trade: Trade,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: datetime,
        **kwargs,
    ) -> bool:
        profit_ratio = trade.calc_profit_ratio(rate)
        profit_abs = trade.calc_profit(rate)

        self._log_trade({
            "timestamp": current_time.isoformat(),
            "pair": pair,
            "action": "closed",
            "open_rate": trade.open_rate,
            "close_rate": rate,
            "profit_pct": round(profit_ratio * 100, 2),
            "profit_eur": round(profit_abs, 2),
            "exit_reason": exit_reason,
            "duration_minutes": round(
                (current_time - trade.open_date_utc).total_seconds() / 60, 1
            ),
            "ai_model": self.ai_model,
        })

        if profit_abs < 0:
            self._record_loss(abs(profit_abs))

        loss_count = self._count_losses(pair)
        if loss_count >= 3 and loss_count % 3 == 0:
            self._pending_research.append(
                f"Crypto {pair} heeft {loss_count} keer verlies gegeven op Bitvavo. "
                f"Analyse waarom. Huidige marktcondities, nieuws, technische analyse. "
                f"Moet ik dit pair vermijden of is er een patroon?"
            )

        return True
