from datetime import datetime
from typing import Optional

from user_data.agents import learning_db


class RegimeDetector:
    def __init__(self):
        self._cached_regime: Optional[dict] = None
        self._cached_candle_time: Optional[str] = None

    def update(self, dp) -> dict:
        btc_df = dp.get_pair_dataframe("BTC/EUR", "15m")
        if btc_df is None or len(btc_df) < 100:
            return {
                "regime": "sideways",
                "volatility": "normal",
                "confidence": 0.0,
                "btc_price": 0.0,
            }

        last_candle_time = str(btc_df.iloc[-1]["date"])
        if self._cached_candle_time == last_candle_time and self._cached_regime is not None:
            return self._cached_regime

        close = btc_df["close"]
        btc_price = float(close.iloc[-1])
        ema_20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema_50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])

        if ema_20 > ema_50 * 1.005:
            regime = "bull"
        elif ema_20 < ema_50 * 0.995:
            regime = "bear"
        else:
            regime = "sideways"

        high = btc_df["high"]
        low = btc_df["low"]
        tr = high - low
        atr_14 = float(tr.rolling(14).mean().iloc[-1])
        atr_100 = float(tr.rolling(100).mean().iloc[-1])
        atr_ratio = atr_14 / atr_100 if atr_100 > 0 else 1.0

        if atr_ratio > 1.5:
            volatility = "high"
        elif atr_ratio < 0.7:
            volatility = "low"
        else:
            volatility = "normal"

        ema_spread = abs(ema_20 - ema_50) / ema_50 if ema_50 > 0 else 0
        confidence = min(ema_spread * 100, 1.0)

        result = {
            "regime": regime,
            "volatility": volatility,
            "confidence": round(confidence, 3),
            "btc_price": round(btc_price, 2),
        }

        learning_db.save_regime_snapshot(
            btc_price=btc_price,
            btc_ema_20=ema_20,
            btc_ema_50=ema_50,
            atr_ratio=round(atr_ratio, 4),
            regime=regime,
            confidence=round(confidence, 3),
        )

        self._cached_regime = result
        self._cached_candle_time = last_candle_time
        return result

    def get_current(self) -> dict:
        if self._cached_regime is not None:
            return self._cached_regime
        return {
            "regime": "sideways",
            "volatility": "normal",
            "confidence": 0.0,
            "btc_price": 0.0,
        }
