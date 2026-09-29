from typing import Dict, Any
from sqlalchemy.orm import Session
from app.database.models import RiskPolicy, Transaction, RecoveryCampaign

class RiskGovernor:
    def __init__(self, db: Session, merchant_id: str = "merchant_demostore"):
        self.db = db
        self.merchant_id = merchant_id

    def evaluate_campaign_plan(
        self,
        strategy_code: str,
        requested_transactions: int,
        requested_exposure: float,
        customer_impact: str = "LOW"
    ) -> Dict[str, Any]:
        """
        Evaluates a proposed recovery campaign against merchant risk policy limits.
        Deterministic enforcement: No AI logic can override these financial safeguards.
        """
        policy = self.db.query(RiskPolicy).filter(RiskPolicy.merchant_id == self.merchant_id).first()

        max_exposure = policy.max_monetary_exposure if policy else 200000.0
        max_tx_count = policy.max_transaction_count if policy else 500
        human_approval_thresh = policy.require_human_approval_above_exposure if policy else 100000.0
        stopping_thresh = policy.max_failure_rate_threshold if policy else 0.35

        policy_checks = {
            "within_max_exposure": requested_exposure <= max_exposure,
            "within_max_transactions": requested_transactions <= max_tx_count,
            "below_human_approval_threshold": requested_exposure <= human_approval_thresh and customer_impact != "HIGH"
        }

        # Decision Logic
        if not policy_checks["within_max_exposure"]:
            return {
                "decision": "BLOCKED",
                "reason": f"Requested monetary exposure (₹{requested_exposure:,.2f}) exceeds merchant policy limit of ₹{max_exposure:,.2f}.",
                "max_exposure": max_exposure,
                "requested_exposure": requested_exposure,
                "max_transactions": max_tx_count,
                "requested_transactions": requested_transactions,
                "stopping_threshold": stopping_thresh,
                "policy_checks": policy_checks
            }

        if not policy_checks["within_max_transactions"]:
            return {
                "decision": "BLOCKED",
                "reason": f"Requested transaction count ({requested_transactions}) exceeds merchant policy limit of {max_tx_count} transactions.",
                "max_exposure": max_exposure,
                "requested_exposure": requested_exposure,
                "max_transactions": max_tx_count,
                "requested_transactions": requested_transactions,
                "stopping_threshold": stopping_thresh,
                "policy_checks": policy_checks
            }

        if not policy_checks["below_human_approval_threshold"]:
            return {
                "decision": "HUMAN_APPROVAL_REQUIRED",
                "reason": f"Proposed exposure ₹{requested_exposure:,.2f} exceeds auto-execution limit of ₹{human_approval_thresh:,.2f}. Merchant approval required.",
                "max_exposure": max_exposure,
                "requested_exposure": requested_exposure,
                "max_transactions": max_tx_count,
                "requested_transactions": requested_transactions,
                "stopping_threshold": stopping_thresh,
                "policy_checks": policy_checks
            }

        return {
            "decision": "APPROVED",
            "reason": f"Action evaluated successfully. Proposed exposure ₹{requested_exposure:,.2f} is within ₹{max_exposure:,.2f} policy limit.",
            "max_exposure": max_exposure,
            "requested_exposure": requested_exposure,
            "max_transactions": max_tx_count,
            "requested_transactions": requested_transactions,
            "stopping_threshold": stopping_thresh,
            "policy_checks": policy_checks
        }
