import logging
from datetime import datetime
from typing import Optional

from user_data.agents import learning_db
from user_data.agents.openrouter_client import call_llm, CallLimitExceeded

logger = logging.getLogger(__name__)


class PreTradeGatekeeper:
    def evaluate(
        self,
        pair: str,
        setup_type: str,
        confluence_score: float,
        regime: dict,
    ) -> bool:
        try:
            return self._evaluate_inner(pair, setup_type, confluence_score, regime)
        except Exception as e:
            logger.warning(f"Gatekeeper exception, fail-open: {e}")
            return True

    def _evaluate_inner(
        self,
        pair: str,
        setup_type: str,
        confluence_score: float,
        regime: dict,
    ) -> bool:
        market_regime = regime.get("regime", "sideways")
        rating = learning_db.get_pattern_rating(setup_type, pair, market_regime)

        if rating == "AVOID":
            logger.info(f"Gatekeeper BLOCK {pair} {setup_type}: AVOID rating in DB")
            return False

        if rating == "SEEK" and confluence_score > 70:
            logger.info(f"Gatekeeper PASS {pair} {setup_type}: SEEK + score {confluence_score}")
            return True

        knowledge = learning_db.get_relevant_knowledge(pair=pair, setup_type=setup_type, limit=5)
        history = learning_db.get_pair_history(pair, setup_type, limit=3)

        lessons_text = "\n".join(
            f"- {k['answer']}" for k in knowledge
        ) if knowledge else "Geen relevante lessen."

        history_text = "\n".join(
            f"- {h.get('created_at', '?')}: profit={h.get('profit_pct', '?')}%, "
            f"exit={h.get('exit_reason', '?')}, quality={h.get('thesis_quality', '?')}"
            for h in history
        ) if history else "Geen eerdere trades."

        prompt = f"""Beoordeel deze trade entry:

Pair: {pair}
Setup type: {setup_type}
Confluence score: {confluence_score}
Marktregime: {market_regime}
Volatiliteit: {regime.get('volatility', 'normal')}
BTC prijs: {regime.get('btc_price', 'onbekend')}
Pattern rating: {rating}

Relevante lessen:
{lessons_text}

Laatste 3 trades op dit pair/setup:
{history_text}

Antwoord in JSON:
{{"decision": "go" of "no_go", "confidence": 0.0-1.0, "conviction": "high"/"medium"/"low", "thesis": "korte uitleg waarom wel/niet", "risk": "wat kan misgaan", "edge": "waar zit de edge"}}"""

        try:
            result = call_llm(prompt, tier="decision")
        except CallLimitExceeded:
            logger.info("Gatekeeper: daily call limit reached, fail-open")
            return True

        decision = result.get("decision", "go")
        confidence = float(result.get("confidence", 0.5))
        conviction = result.get("conviction", "medium")
        thesis = result.get("thesis", "")
        risk = result.get("risk", "")
        edge = result.get("edge", "")

        learning_db.save_prediction(
            pair=pair,
            setup_type=setup_type,
            entry_thesis=thesis,
            market_regime=market_regime,
            confluence_score=confluence_score,
            ai_confidence=confidence,
            conviction_level=conviction,
            what_could_go_wrong=risk,
            edge_description=edge,
            source="live",
        )

        approved = decision == "go"
        logger.info(
            f"Gatekeeper {'PASS' if approved else 'BLOCK'} {pair} {setup_type}: "
            f"confidence={confidence}, conviction={conviction}"
        )
        return approved
