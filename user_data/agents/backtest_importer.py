import glob
import json
import logging
import os
import zipfile
from datetime import datetime, timedelta

from user_data.agents import learning_db
from user_data.agents.confluence_scorer import score_confluence
from user_data.agents.pattern_aggregator import PatternAggregator

logger = logging.getLogger(__name__)

BACKTEST_DIR = os.path.expanduser("~/Projects/quick-flip/user_data/backtest_results")
KNOWLEDGE_FILE = os.path.expanduser("~/Projects/quick-flip/user_data/data/knowledge.jsonl")
DATA_DIR = os.path.expanduser("~/Projects/quick-flip/user_data/data/bitvavo")


def _load_backtest_trades() -> list[dict]:
    zips = sorted(glob.glob(os.path.join(BACKTEST_DIR, "*.zip")))
    if not zips:
        logger.warning("No backtest zip files found")
        return []

    latest_zip = zips[-1]
    logger.info(f"Loading backtest from {latest_zip}")

    with zipfile.ZipFile(latest_zip) as z:
        json_files = [n for n in z.namelist() if n.endswith(".json") and "config" not in n]
        if not json_files:
            logger.warning("No result JSON found in zip")
            return []
        data = json.loads(z.read(json_files[0]))

    strategies = data.get("strategy", {})
    if not strategies:
        return []

    strategy_name = list(strategies.keys())[0]
    return strategies[strategy_name].get("trades", [])


def _detect_regime_for_trade(pair: str, open_date_str: str) -> str:
    pair_file = pair.replace("/", "_") + "-15m.feather"
    feather_path = os.path.join(DATA_DIR, pair_file)

    btc_feather = os.path.join(DATA_DIR, "BTC_EUR-15m.feather")
    if not os.path.exists(btc_feather):
        return "sideways"

    try:
        import pandas as pd
        df = pd.read_feather(btc_feather)

        open_dt = pd.Timestamp(open_date_str)
        df["date"] = pd.to_datetime(df["date"])
        mask = df["date"] <= open_dt
        if mask.sum() < 50:
            return "sideways"

        df_before = df[mask].tail(50)
        close = df_before["close"]
        ema_20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema_50 = close.ewm(span=50, adjust=False).mean().iloc[-1]

        if ema_20 > ema_50 * 1.005:
            return "bull"
        elif ema_20 < ema_50 * 0.995:
            return "bear"
        return "sideways"
    except Exception as e:
        logger.warning(f"Regime detection failed for {pair}: {e}")
        return "sideways"


def _build_synthetic_row(trade: dict) -> dict:
    return {
        "close": trade.get("close_rate", trade.get("open_rate", 0)),
        "rsi": 50.0,
        "macd": 0.0,
        "macdsignal": 0.0,
        "macdhist": 0.0,
        "volume": 0,
        "bb_upper": 0,
        "bb_lower": 0,
        "bb_middle": 0,
    }


def import_backtest_trades():
    learning_db.init_db()
    trades = _load_backtest_trades()
    if not trades:
        print("No backtest trades found")
        return

    imported = 0
    for i, trade in enumerate(trades):
        bt_id = f"bt_{i+1:03d}"
        pair = trade["pair"]
        open_date = trade["open_date"]
        profit_pct = trade.get("profit_ratio", 0) * 100
        exit_reason = trade.get("exit_reason", "unknown")
        duration_minutes = trade.get("trade_duration", 0)

        regime = _detect_regime_for_trade(pair, open_date)
        regime_dict = {"regime": regime, "volatility": "normal", "confidence": 0.5, "btc_price": 0}

        row = _build_synthetic_row(trade)
        confluence_score, setup_type = score_confluence(row, regime_dict)

        learning_db.save_prediction(
            pair=pair,
            setup_type=setup_type,
            entry_thesis=f"Backtest import: {exit_reason}",
            market_regime=regime,
            confluence_score=confluence_score,
            ai_confidence=0.0,
            conviction_level="backtest",
            what_could_go_wrong="",
            edge_description="",
            source="backtest",
            ft_trade_id=bt_id,
        )

        pred = learning_db.get_prediction_by_trade_id(bt_id)
        if pred:
            learning_db.update_evaluation(
                prediction_id=pred["id"],
                thesis_quality="backtest",
                validation_status="backtest",
                evaluation_notes=f"Backtest: {exit_reason}, duration={duration_minutes}min",
                profit_pct=profit_pct,
                exit_reason=exit_reason,
                duration_minutes=duration_minutes,
            )

        imported += 1

    print(f"Imported {imported} backtest trades")


def import_knowledge():
    if not os.path.exists(KNOWLEDGE_FILE):
        print(f"Knowledge file not found: {KNOWLEDGE_FILE}")
        return

    learning_db.init_db()
    valid_until = (datetime.now() + timedelta(days=7)).isoformat()
    imported = 0

    with open(KNOWLEDGE_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            query = entry.get("query", "")
            answer = entry.get("answer", "")
            if not answer:
                continue

            learning_db.save_knowledge(
                category="research",
                query=query,
                answer=answer,
                source="research",
                valid_until=valid_until,
            )
            imported += 1

    print(f"Imported {imported} knowledge entries")


def main():
    import_backtest_trades()
    import_knowledge()

    aggregator = PatternAggregator()
    aggregator.recalculate()
    print("Pattern aggregation complete")


if __name__ == "__main__":
    main()
