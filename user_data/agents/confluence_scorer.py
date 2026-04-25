from typing import Optional


WEIGHTS = {
    "ema": 0.20,
    "rsi": 0.20,
    "macd": 0.20,
    "volume": 0.15,
    "bb": 0.10,
    "regime": 0.15,
}


def score_confluence(row, regime: dict) -> tuple[float, str]:
    ema_score = _score_ema(row)
    rsi_score = _score_rsi(row)
    macd_score = _score_macd(row)
    volume_score = _score_volume(row)
    bb_score = _score_bb(row)
    regime_score = _score_regime(regime)

    total = (
        ema_score * WEIGHTS["ema"]
        + rsi_score * WEIGHTS["rsi"]
        + macd_score * WEIGHTS["macd"]
        + volume_score * WEIGHTS["volume"]
        + bb_score * WEIGHTS["bb"]
        + regime_score * WEIGHTS["regime"]
    )

    scores = {
        "ema": ema_score,
        "rsi": rsi_score,
        "macd": macd_score,
        "volume": volume_score,
        "bb": bb_score,
        "regime": regime_score,
    }

    setup_type = _classify_setup(scores, total, regime)

    return round(total, 2), setup_type


def _score_ema(row) -> float:
    try:
        close = float(row["close"])
        ema_short = float(row.get("ema_short", row.get("ema_8", 0)))
        ema_long = float(row.get("ema_long", row.get("ema_21", 0)))
        if ema_short == 0 or ema_long == 0:
            return 50.0
        if close > ema_short > ema_long:
            spread = (ema_short - ema_long) / ema_long * 100
            return min(50 + spread * 10, 100)
        elif close < ema_short < ema_long:
            return max(50 - abs(ema_short - ema_long) / ema_long * 1000, 0)
        return 50.0
    except (KeyError, TypeError, ZeroDivisionError):
        return 50.0


def _score_rsi(row) -> float:
    try:
        rsi = float(row.get("rsi", 50))
        if rsi < 30:
            return 90.0
        elif rsi < 35:
            return 80.0
        elif rsi < 45:
            return 65.0
        elif rsi > 70:
            return 20.0
        elif rsi > 65:
            return 35.0
        return 50.0
    except (TypeError, ValueError):
        return 50.0


def _score_macd(row) -> float:
    try:
        macd = float(row.get("macd", 0))
        macdsignal = float(row.get("macdsignal", 0))
        macdhist = float(row.get("macdhist", 0))
        score = 50.0
        if macd > macdsignal:
            score += 20
        else:
            score -= 20
        if macdhist > 0:
            score += 15
        else:
            score -= 15
        return max(0, min(score, 100))
    except (TypeError, ValueError):
        return 50.0


def _score_volume(row) -> float:
    try:
        volume = float(row.get("volume", 0))
        volume_mean = float(row.get("volume_mean_20", row.get("volume_mean", 0)))
        if volume_mean == 0:
            return 50.0
        ratio = volume / volume_mean
        if ratio > 2.0:
            return 95.0
        elif ratio > 1.5:
            return 80.0
        elif ratio > 1.0:
            return 60.0
        elif ratio > 0.5:
            return 40.0
        return 20.0
    except (TypeError, ValueError, ZeroDivisionError):
        return 50.0


def _score_bb(row) -> float:
    try:
        close = float(row["close"])
        bb_upper = float(row.get("bb_upper", row.get("bb_upperband", 0)))
        bb_lower = float(row.get("bb_lower", row.get("bb_lowerband", 0)))
        bb_middle = float(row.get("bb_middle", row.get("bb_middleband", 0)))
        if bb_upper == 0 or bb_lower == 0:
            return 50.0
        bb_range = bb_upper - bb_lower
        if bb_range == 0:
            return 50.0
        position = (close - bb_lower) / bb_range
        if position <= 0.1:
            return 90.0
        elif position <= 0.3:
            return 70.0
        elif position >= 0.9:
            return 20.0
        elif position >= 0.7:
            return 35.0
        return 50.0
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 50.0


def _score_regime(regime: dict) -> float:
    r = regime.get("regime", "sideways")
    v = regime.get("volatility", "normal")
    score = 50.0
    if r == "bull":
        score += 30
    elif r == "bear":
        score -= 30
    if v == "high":
        score -= 10
    elif v == "low":
        score += 5
    return max(0, min(score, 100))


def _classify_setup(scores: dict, total: float, regime: dict) -> str:
    r = regime.get("regime", "sideways")

    ema_positive = scores["ema"] > 60
    macd_positive = scores["macd"] > 60
    bull = r == "bull"
    rsi_oversold = scores["rsi"] >= 80
    bb_low = scores["bb"] >= 70
    volume_high = scores["volume"] >= 80

    signal_bullish = total > 55
    regime_bearish = r == "bear"

    if ema_positive and macd_positive and bull:
        return "trend_follow"

    if rsi_oversold and bb_low:
        return "mean_reversion"

    if volume_high and (macd_positive or ema_positive):
        return "momentum_breakout"

    if signal_bullish and regime_bearish:
        return "counter_trend"

    dominant = sum(1 for s in scores.values() if s > 65)
    if total > 75 and dominant >= 3:
        return "full_confluence"

    if 40 <= total <= 60 and dominant <= 1:
        return "weak_signal"

    if total > 60:
        return "trend_follow"
    if total < 40:
        return "counter_trend"

    return "weak_signal"
