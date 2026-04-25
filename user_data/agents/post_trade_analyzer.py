import logging
from typing import Optional

from user_data.agents import learning_db
from user_data.agents.openrouter_client import call_llm, CallLimitExceeded

logger = logging.getLogger(__name__)


class PostTradeAnalyzer:
    def analyze(self, trade) -> None:
        try:
            self._analyze_inner(trade)
        except Exception as e:
            logger.error(f"PostTradeAnalyzer exception: {e}", exc_info=True)

    def _analyze_inner(self, trade) -> None:
        ft_trade_id = str(trade.id)
        prediction = learning_db.get_prediction_by_trade_id(ft_trade_id)
        if prediction is None:
            logger.info(f"No prediction found for trade {ft_trade_id}, skipping analysis")
            return

        pair = trade.pair
        profit_pct = (trade.close_profit or 0) * 100
        exit_reason = str(getattr(trade, "exit_reason", "unknown"))
        open_date = str(getattr(trade, "open_date", ""))
        close_date = str(getattr(trade, "close_date", ""))
        duration_minutes = 0.0
        if hasattr(trade, "open_date") and hasattr(trade, "close_date") and trade.close_date and trade.open_date:
            try:
                delta = trade.close_date - trade.open_date
                duration_minutes = delta.total_seconds() / 60
            except Exception:
                pass

        entry_thesis = prediction.get("entry_thesis", "Geen thesis beschikbaar")
        setup_type = prediction.get("setup_type", "unknown")
        market_regime = prediction.get("market_regime", "unknown")
        confluence_score = prediction.get("confluence_score", 0)

        step1_prompt = f"""Beoordeel de kwaliteit van deze entry thesis ZONDER het resultaat te kennen.

Pair: {pair}
Setup type: {setup_type}
Marktregime: {market_regime}
Confluence score: {confluence_score}
Entry thesis: {entry_thesis}

Was de redenering goed? Antwoord in JSON:
{{"thesis_quality": "goed" of "matig" of "slecht", "reasoning": "korte uitleg"}}"""

        try:
            step1_result = call_llm(step1_prompt, tier="analysis")
        except CallLimitExceeded:
            logger.info("PostTradeAnalyzer: daily call limit reached, skipping")
            return

        thesis_quality = step1_result.get("thesis_quality", "matig")

        step2_prompt = f"""Nu het resultaat:

Pair: {pair}
Setup type: {setup_type}
Entry thesis: {entry_thesis}
Thesis kwaliteit (zonder resultaat): {thesis_quality}

Resultaat:
- Profit: {profit_pct:.2f}%
- Exit reden: {exit_reason}
- Duur: {duration_minutes:.0f} minuten

Wat verklaart het verschil tussen de thesis en het resultaat?
Antwoord in JSON:
{{"validation_status": "correct" of "wrong" of "partial", "evaluation_notes": "korte analyse", "lesson": "de belangrijkste les voor toekomstige trades op {pair} met setup {setup_type}"}}"""

        try:
            step2_result = call_llm(step2_prompt, tier="analysis")
        except CallLimitExceeded:
            logger.info("PostTradeAnalyzer: daily call limit reached at step 2, saving partial")
            learning_db.update_evaluation(
                prediction_id=prediction["id"],
                thesis_quality=thesis_quality,
                validation_status="partial",
                evaluation_notes="Analyse incompleet door call limiet",
                profit_pct=profit_pct,
                exit_reason=exit_reason,
                duration_minutes=duration_minutes,
            )
            return

        validation_status = step2_result.get("validation_status", "partial")
        evaluation_notes = step2_result.get("evaluation_notes", "")
        lesson = step2_result.get("lesson", "")

        learning_db.update_evaluation(
            prediction_id=prediction["id"],
            thesis_quality=thesis_quality,
            validation_status=validation_status,
            evaluation_notes=evaluation_notes,
            profit_pct=profit_pct,
            exit_reason=exit_reason,
            duration_minutes=duration_minutes,
        )

        if lesson:
            learning_db.save_knowledge(
                category="post_trade_learning",
                query=f"{pair} {setup_type} {market_regime}",
                answer=f"[{pair}] [{setup_type}] [{market_regime}] profit={profit_pct:.2f}%: {lesson}",
                source="post_trade_learning",
                valid_until=None,
            )

        logger.info(
            f"PostTradeAnalyzer {pair}: quality={thesis_quality}, "
            f"status={validation_status}, profit={profit_pct:.2f}%"
        )
