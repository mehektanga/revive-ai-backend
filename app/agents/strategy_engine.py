from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.database.models import Transaction, RiskPolicy

class RecoveryStrategyEngine:
    def __init__(self, db: Session, merchant_id: str = "merchant_demostore"):
        self.db = db
        self.merchant_id = merchant_id

    def generate_strategies(self, revenue_at_risk: float, affected_count: int) -> List[Dict[str, Any]]:
        """
        Generates candidates for recovery strategies with risk scores, recovery estimates, and limits.
        """
        policy = self.db.query(RiskPolicy).filter(RiskPolicy.merchant_id == self.merchant_id).first()
        max_exposure_limit = policy.max_monetary_exposure if policy else 200000.0

        strategies = [
            {
                "code": "delayed_retry",
                "name": "Delayed Smart Retry",
                "description": "Retry UPI/Card transactions after a 20-minute gateway recovery cooldown period.",
                "expected_recovery_rate": 0.39,
                "expected_recovery": round(revenue_at_risk * 0.39, 2),
                "risk_score": 0.12,
                "customer_impact": "LOW",
                "max_transactions": min(affected_count, 500),
                "max_exposure": min(revenue_at_risk * 0.95, max_exposure_limit),
                "stop_if_failure_rate_above": 0.35,
                "recommendation_reason": "Highest expected recovery (₹3.4L estimated) while staying below merchant's ₹2L exposure limit."
            },
            {
                "code": "immediate_retry",
                "name": "Immediate Gateway Retry",
                "description": "Re-submit transactions immediately across primary gateway connection.",
                "expected_recovery_rate": 0.24,
                "expected_recovery": round(revenue_at_risk * 0.24, 2),
                "risk_score": 0.28,
                "customer_impact": "LOW",
                "max_transactions": min(affected_count, 500),
                "max_exposure": min(revenue_at_risk * 0.80, max_exposure_limit),
                "stop_if_failure_rate_above": 0.40,
                "recommendation_reason": "Faster execution, but lower expected recovery due to ongoing bank gateway instability."
            },
            {
                "code": "alternate_route",
                "name": "Alternate Payment Routing",
                "description": "Reroute failed UPI/Card transactions through secondary bank gateway (ICICI/Axis).",
                "expected_recovery_rate": 0.32,
                "expected_recovery": round(revenue_at_risk * 0.32, 2),
                "risk_score": 0.18,
                "customer_impact": "LOW",
                "max_transactions": min(affected_count, 400),
                "max_exposure": min(revenue_at_risk * 0.85, max_exposure_limit),
                "stop_if_failure_rate_above": 0.30,
                "recommendation_reason": "Bypasses primary HDFC node degradation; safe alternate strategy."
            },
            {
                "code": "recovery_link",
                "name": "Dynamic Recovery Payment Link",
                "description": "Send SMS / WhatsApp 1-click Razorpay payment link to affected customers.",
                "expected_recovery_rate": 0.20,
                "expected_recovery": round(revenue_at_risk * 0.20, 2),
                "risk_score": 0.15,
                "customer_impact": "MEDIUM",
                "max_transactions": min(affected_count, 300),
                "max_exposure": min(revenue_at_risk * 0.60, max_exposure_limit),
                "stop_if_failure_rate_above": 0.25,
                "recommendation_reason": "Empowers customers to pay using alternate preferred payment method."
            },
            {
                "code": "customer_contact",
                "name": "Priority Customer Outreach",
                "description": "Trigger personalized email & SMS notification with payment assistance support.",
                "expected_recovery_rate": 0.10,
                "expected_recovery": round(revenue_at_risk * 0.10, 2),
                "risk_score": 0.45,
                "customer_impact": "HIGH",
                "max_transactions": min(affected_count, 100),
                "max_exposure": min(revenue_at_risk * 0.30, max_exposure_limit),
                "stop_if_failure_rate_above": 0.20,
                "recommendation_reason": "High customer touchpoint; reserved for VIP or high basket value transactions."
            }
        ]

        return strategies
