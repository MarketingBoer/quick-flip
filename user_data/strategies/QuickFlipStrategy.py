import logging
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timedelta
from pandas import DataFrame
from typing import Optional

from freqtrade.enums import CandleType
from freqtrade.strategy import IStrategy, Trade, IntParameter, DecimalParameter

import talib.abstract as ta
from technical import qtpylib

from user_data.agents import learning_db
from user_data.agents.openrouter_client import CallLimitExceeded
from user_data.agents.regime_detector import RegimeDetector
from user_data.agents.confluence_scorer import score_confluence
from user_data.agents.pre_trade_gatekeeper import PreTradeGatekeeper
from user_data.agents.post_trade_analyzer import PostTradeAnalyzer
from user_data.agents.pattern_aggregator import PatternAggregator

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

    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 50
    max_open_trades = 2

    # Hyperopt parameter spaces
    buy_rsi_lower = IntParameter(20, 35, default=30, space="buy")
    buy_rsi_upper = IntParameter(65, 72, default=70, space="buy")
    buy_ema_fast = IntParameter(5, 15, default=8, space="buy")
    buy_ema_slow = IntParameter(15, 40, default=21, space="buy")
    buy_bb_window = IntParameter(15, 30, default=20, space="buy")
    buy_volume_mult = DecimalParameter(0.9, 1.5, decimals=1, default=1.0, space="buy")

    sell_rsi_exit = IntParameter(55, 75, default=65, space="sell")
    sell_rsi_high = IntParameter(65, 75, default=70, space="sell")

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
        self._last_pattern_date = ""

        learning_db.init_db()
        self.learning_db = learning_db
        self.regime_detector = RegimeDetector()
        self.confluence_scorer = score_confluence
        self.gatekeeper = PreTradeGatekeeper()
        self.post_analyzer = PostTradeAnalyzer()
        self.pattern_aggregator = PatternAggregator()
        logger.info("Agent team initialized: LearningDB, RegimeDetector, ConfluenceScorer, Gatekeeper, Analyzer, Aggregator")

        api_key = self._get_openrouter_key()
        if api_key:
            logger.info("OpenRouter API key loaded")
        else:
            logger.warning("No OpenRouter API key — AI disabled")
            self.ai_enabled = False

    def informative_pairs(self):
        return [("BTC/EUR", "15m", CandleType.SPOT)]

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
        if self._pending_research:
            query = self._pending_research.pop(0)
            self._do_research(query)

        try:
            self.regime_detector.update(self.dp)
        except Exception as e:
            logger.warning(f"Regime detector update failed: {e}")

        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_pattern_date != today:
            self._last_pattern_date = today
            try:
                self.pattern_aggregator.recalculate()
                logger.info("Daily pattern recalculation complete")
            except Exception as e:
                logger.warning(f"Pattern recalculation failed: {e}")
            try:
                learning_db.expire_knowledge()
                logger.info("Daily knowledge expiry check complete")
            except Exception as e:
                logger.warning(f"Knowledge expiry check failed: {e}")

    def _get_openrouter_key(self) -> Optional[str]:
        secrets_path = os.path.expanduser("~/.secrets")
        if not os.path.exists(secrets_path):
            return None
        with open(secrets_path) as f:
            for line in f:
                line = line.strip().removeprefix("export ")
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip('"').strip("'")
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
        for period in range(5, 16):
            dataframe[f"ema_{period}"] = ta.EMA(dataframe, timeperiod=period)
        for period in range(15, 41):
            dataframe[f"ema_{period}"] = ta.EMA(dataframe, timeperiod=period)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["volume_sma"] = ta.SMA(dataframe["volume"], timeperiod=20)

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        for window in range(15, 31):
            bb = qtpylib.bollinger_bands(dataframe["close"], window=window, stds=2)
            dataframe[f"bb_lower_{window}"] = bb["lower"]
            dataframe[f"bb_middle_{window}"] = bb["mid"]
            dataframe[f"bb_upper_{window}"] = bb["upper"]

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_fast = dataframe[f"ema_{self.buy_ema_fast.value}"]
        ema_slow = dataframe[f"ema_{self.buy_ema_slow.value}"]
        bb_upper = dataframe[f"bb_upper_{self.buy_bb_window.value}"]

        regime = self.regime_detector.get_current()
        scores = []
        setup_types = []
        for _, row in dataframe.iterrows():
            s, st = self.confluence_scorer(row, regime)
            scores.append(s)
            setup_types.append(st)
        dataframe["confluence_score"] = scores
        dataframe["setup_type"] = setup_types

        dataframe.loc[
            (
                (ema_fast > ema_slow)
                & (dataframe["rsi"] < self.buy_rsi_upper.value)
                & (dataframe["rsi"] > self.buy_rsi_lower.value)
                & (dataframe["macdhist"] > 0)
                & (dataframe["volume"] > dataframe["volume_sma"] * self.buy_volume_mult.value)
                & (dataframe["close"] < bb_upper)
                & (dataframe["volume"] > 0)
            ),
            "enter_long",
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        ema_fast = dataframe[f"ema_{self.buy_ema_fast.value}"]
        ema_slow = dataframe[f"ema_{self.buy_ema_slow.value}"]

        dataframe.loc[
            (
                (ema_fast < ema_slow)
                & (dataframe["rsi"] > self.sell_rsi_high.value)
            )
            | (
                (dataframe["macdhist"] < 0)
                & (dataframe["rsi"] > self.sell_rsi_exit.value)
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

        min_exit_value = rate * amount * (1 + self.stoploss)
        if min_exit_value < 5.5:
            logger.warning(
                f"Skipping {pair}: position after stoploss (€{min_exit_value:.2f}) "
                f"would be below Bitvavo minimum order (€5)"
            )
            return False

        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if not dataframe.empty and "confluence_score" in dataframe.columns:
                last_row = dataframe.iloc[-1]
                confluence_score = float(last_row.get("confluence_score", 50))
                setup_type = str(last_row.get("setup_type", "weak_signal"))
            else:
                confluence_score = 50.0
                setup_type = "weak_signal"

            regime = self.regime_detector.get_current()
            approved = self.gatekeeper.evaluate(
                pair=pair,
                setup_type=setup_type,
                confluence_score=confluence_score,
                regime=regime,
            )
            if not approved:
                logger.info(f"Gatekeeper rejected {pair} ({setup_type}, score={confluence_score})")
                return False
        except Exception as e:
            logger.warning(f"Gatekeeper error, fail-open: {e}")

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
        return True

    def order_filled(
        self, pair: str, trade: Trade, order, current_time: datetime, **kwargs
    ) -> None:
        if order.ft_order_side == "buy":
            try:
                pred = learning_db.get_prediction_by_pair_time(
                    pair, (current_time - timedelta(minutes=30)).isoformat()
                )
                if pred:
                    learning_db.update_prediction_trade_id(pred["id"], str(trade.trade_id))
            except Exception as e:
                logger.warning(f"Failed to link prediction to trade: {e}")
            return

        if order.ft_order_side != "sell":
            return

        profit_ratio = trade.calc_profit_ratio(order.safe_price)
        profit_abs = trade.calc_profit(order.safe_price)

        self._log_trade({
            "timestamp": current_time.isoformat(),
            "pair": pair,
            "action": "closed",
            "open_rate": trade.open_rate,
            "close_rate": order.safe_price,
            "profit_pct": round(profit_ratio * 100, 2),
            "profit_eur": round(profit_abs, 2),
            "exit_reason": trade.exit_reason or "unknown",
            "duration_minutes": round(
                (current_time - trade.open_date_utc).total_seconds() / 60, 1
            ),
            "ai_model": self.ai_model,
        })

        if profit_abs < 0:
            self._record_loss(abs(profit_abs))

        try:
            self.post_analyzer.analyze(trade)
        except Exception as e:
            logger.warning(f"Post-trade analysis failed: {e}")

        try:
            self.pattern_aggregator.recalculate()
        except Exception as e:
            logger.warning(f"Pattern recalculation after trade failed: {e}")

        loss_count = self._count_losses(pair)
        if loss_count >= 3 and loss_count % 3 == 0:
            self._pending_research.append(
                f"Crypto {pair} heeft {loss_count} keer verlies gegeven op Bitvavo. "
                f"Analyse waarom. Huidige marktcondities, nieuws, technische analyse. "
                f"Moet ik dit pair vermijden of is er een patroon?"
            )
