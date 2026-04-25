import logging
import os
import sys
from datetime import datetime, timedelta
from pandas import DataFrame
from typing import Optional

_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from freqtrade.enums import CandleType
from freqtrade.strategy import IStrategy, Trade, IntParameter, DecimalParameter

import numpy as np
import talib.abstract as ta
from technical import qtpylib

from user_data.agents import learning_db
from user_data.agents.regime_detector import RegimeDetector
from user_data.agents.confluence_scorer import score_confluence
from user_data.agents.pre_trade_gatekeeper import PreTradeGatekeeper
from user_data.agents.post_trade_analyzer import PostTradeAnalyzer
from user_data.agents.pattern_aggregator import PatternAggregator

logger = logging.getLogger(__name__)


class QuickFlipStrategy(IStrategy):

    INTERFACE_VERSION = 3
    can_short = False

    minimal_roi = {
        "0": 0.18,
    }

    stoploss = -0.06

    trailing_stop = False
    use_custom_stoploss = True

    timeframe = "15m"
    process_only_new_candles = True
    startup_candle_count = 50
    max_open_trades = 8

    # Hyperopt parameter spaces
    buy_rsi_lower = IntParameter(20, 35, default=30, space="buy")
    buy_rsi_upper = IntParameter(65, 72, default=70, space="buy")
    buy_ema_fast = IntParameter(5, 15, default=8, space="buy")
    buy_ema_slow = IntParameter(15, 40, default=21, space="buy")
    buy_bb_window = IntParameter(15, 30, default=20, space="buy")
    buy_volume_mult = DecimalParameter(0.9, 1.5, decimals=1, default=1.0, space="buy")

    sell_rsi_exit = IntParameter(55, 75, default=65, space="sell")
    sell_rsi_high = IntParameter(65, 75, default=70, space="sell")

    # Safety
    daily_loss_limit_eur = 10.0

    def bot_start(self, **kwargs) -> None:
        self._daily_loss = {"date": "", "loss": 0.0}
        self._last_pattern_date = ""

        learning_db.init_db()
        self.learning_db = learning_db
        self.regime_detector = RegimeDetector()
        self.confluence_scorer = score_confluence
        self.gatekeeper = PreTradeGatekeeper()
        self.post_analyzer = PostTradeAnalyzer()
        self.pattern_aggregator = PatternAggregator()

        cleaned = Trade.session.query(Trade).filter(
            Trade.is_open.is_(True), Trade.amount == 0.0
        ).all()
        for t in cleaned:
            logger.warning(f"Removing ghost trade: {t.pair} (id={t.id}, amount=0)")
            Trade.session.delete(t)
        if cleaned:
            Trade.session.commit()
            logger.info(f"Cleaned {len(cleaned)} ghost trades on startup")

        logger.info("Agent team initialized: LearningDB, RegimeDetector, ConfluenceScorer, Gatekeeper, Analyzer, Aggregator")

    def informative_pairs(self):
        return [("BTC/EUR", "15m", CandleType.SPOT)]

    def bot_loop_start(self, current_time: datetime, **kwargs) -> None:
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

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for period in range(5, 16):
            dataframe[f"ema_{period}"] = ta.EMA(dataframe, timeperiod=period)
        for period in range(15, 41):
            dataframe[f"ema_{period}"] = ta.EMA(dataframe, timeperiod=period)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["volume_sma"] = ta.SMA(dataframe["volume"], timeperiod=20)
        dataframe["volume_mean_20"] = dataframe["volume_sma"]

        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        for window in range(15, 31):
            bb = qtpylib.bollinger_bands(dataframe["close"], window=window, stds=2)
            dataframe[f"bb_lower_{window}"] = bb["lower"]
            dataframe[f"bb_middle_{window}"] = bb["mid"]
            dataframe[f"bb_upper_{window}"] = bb["upper"]

        dataframe["bb_upper"] = dataframe["bb_upper_20"]
        dataframe["bb_lower"] = dataframe["bb_lower_20"]
        dataframe["bb_middle"] = dataframe["bb_middle_20"]

        dataframe["atr_10"] = ta.ATR(dataframe, timeperiod=10)

        st_period, st_mult = 10, 3.0
        hl2 = (dataframe["high"] + dataframe["low"]) / 2
        st_atr = ta.ATR(dataframe, timeperiod=st_period)
        upper_arr = (hl2 + st_mult * st_atr).to_numpy().copy()
        lower_arr = (hl2 - st_mult * st_atr).to_numpy().copy()
        close_arr = dataframe["close"].to_numpy()
        supertrend = np.zeros(len(dataframe))
        direction = np.ones(len(dataframe))
        for i in range(1, len(dataframe)):
            if lower_arr[i] < lower_arr[i - 1] and close_arr[i - 1] >= lower_arr[i - 1]:
                lower_arr[i] = lower_arr[i - 1]
            if upper_arr[i] > upper_arr[i - 1] and close_arr[i - 1] <= upper_arr[i - 1]:
                upper_arr[i] = upper_arr[i - 1]
            if direction[i - 1] == 1:
                if close_arr[i] < lower_arr[i]:
                    direction[i] = -1
                    supertrend[i] = upper_arr[i]
                else:
                    direction[i] = 1
                    supertrend[i] = lower_arr[i]
            else:
                if close_arr[i] > upper_arr[i]:
                    direction[i] = 1
                    supertrend[i] = lower_arr[i]
                else:
                    direction[i] = -1
                    supertrend[i] = upper_arr[i]
        dataframe["supertrend"] = supertrend
        dataframe["supertrend_dir"] = direction

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

    def custom_stoploss(
        self, pair: str, trade: Trade, current_time: datetime,
        current_rate: float, current_profit: float, after_fill: bool,
        **kwargs,
    ) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty or "atr_10" not in dataframe.columns:
            return self.stoploss

        atr = dataframe["atr_10"].iloc[-1]
        if atr <= 0:
            return self.stoploss

        multiplier = 1.5 if current_profit >= 0.02 else 2.5
        atr_stop = (atr * multiplier) / current_rate
        return max(-atr_stop, self.stoploss)

    def custom_exit(
        self, pair: str, trade: Trade, current_time: datetime,
        current_rate: float, current_profit: float, **kwargs,
    ) -> Optional[str]:
        if current_profit < 0.01:
            return None

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty or "supertrend_dir" not in dataframe.columns:
            return None

        if dataframe["supertrend_dir"].iloc[-1] == -1:
            return "supertrend_reversal"

        return None

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
            logger.warning(f"Gatekeeper error, fail-closed: {e}")
            return False

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
                    learning_db.update_prediction_trade_id(pred["id"], str(trade.id))
            except Exception as e:
                logger.warning(f"Failed to link prediction to trade: {e}")
            return

        if order.ft_order_side != "sell":
            return

        profit_abs = trade.calc_profit(order.safe_price)

        logger.info(
            f"Trade closed: {pair} profit=€{profit_abs:.2f} "
            f"exit={trade.exit_reason or 'unknown'}"
        )

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
