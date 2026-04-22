import logging
from collections import defaultdict

from user_data.agents import learning_db

logger = logging.getLogger(__name__)


class PatternAggregator:
    def recalculate(self) -> None:
        rows = learning_db.get_predictions_for_aggregation()
        if not rows:
            logger.info("PatternAggregator: no completed trades to aggregate")
            return

        groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for r in rows:
            key = (r["setup_type"], r["pair"], r["market_regime"] or "unknown")
            groups[key].append(r["profit_pct"])

        for (setup_type, pair, market_regime), profits in groups.items():
            total = len(profits)
            wins = sum(1 for p in profits if p > 0)
            losses = sum(1 for p in profits if p <= 0)
            win_rate = (wins / total * 100) if total > 0 else 0
            avg_profit = sum(profits) / total if total > 0 else 0
            rating = self._calculate_rating(total, win_rate, avg_profit)

            learning_db.upsert_pattern(
                setup_type=setup_type,
                pair=pair,
                market_regime=market_regime,
                total_trades=total,
                wins=wins,
                losses=losses,
                win_rate=round(win_rate, 2),
                avg_profit_pct=round(avg_profit, 4),
                rating=rating,
            )

        logger.info(f"PatternAggregator: recalculated {len(groups)} patterns from {len(rows)} trades")

    def get_rating(self, setup_type: str, pair: str, market_regime: str) -> str:
        rating = learning_db.get_pattern_rating(setup_type, pair, market_regime)
        if rating != "NEUTRAL":
            return rating

        rating = learning_db.get_pattern_rating(setup_type, pair, "unknown")
        if rating != "NEUTRAL":
            return rating

        rating = learning_db.get_pattern_rating(setup_type, "", market_regime)
        if rating != "NEUTRAL":
            return rating

        return "NEUTRAL"

    @staticmethod
    def _calculate_rating(total: int, win_rate: float, avg_profit: float) -> str:
        if total < 10:
            return "NEUTRAL"
        if win_rate > 60 and avg_profit > 0.5:
            return "SEEK"
        if win_rate < 40 or avg_profit < -1.0:
            return "AVOID"
        return "NEUTRAL"
