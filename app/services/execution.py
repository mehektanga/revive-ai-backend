from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.database.models import (
    RecoveryCampaign, RecoveryAttempt, Transaction, AuditLog, Incident
)
from app.providers.mock_provider import MockPaymentProvider, RazorpayTestProvider

def log_audit_event(
    db: Session,
    actor: str,
    event: str,
    action: str,
    reason: str = None,
    risk_decision: str = None,
    provider: str = None,
    transaction_count: int = 0,
    amount: float = 0.0,
    result: str = None,
    input_data: dict = None,
    output_data: dict = None
) -> AuditLog:
    entry = AuditLog(
        timestamp=datetime.utcnow(),
        actor=actor,
        event=event,
        action=action,
        reason=reason,
        risk_decision=risk_decision,
        provider=provider,
        transaction_count=transaction_count,
        amount=amount,
        result=result,
        input_data_json=input_data,
        output_data_json=output_data
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


class RecoveryExecutor:
    def __init__(self, db: Session):
        self.db = db
        self.provider = RazorpayTestProvider()
        self.mock_provider = MockPaymentProvider()

    def execute_campaign(
        self,
        campaign_id: int,
        batch_limit: int = 500,
        trigger_controlled_failure: bool = False
    ) -> Dict[str, Any]:
        """
        Executes recovery campaign transactions with live progress tracking,
        idempotency safeguards, and automatic halting if failure rate exceeds stopping threshold.
        """
        campaign = self.db.query(RecoveryCampaign).filter(RecoveryCampaign.id == campaign_id).first()
        if not campaign:
            raise ValueError(f"Campaign #{campaign_id} not found")

        if campaign.status not in ["APPROVED", "EXECUTING"]:
            raise ValueError(f"Campaign #{campaign_id} cannot be executed because its status is '{campaign.status}'. Human approval or risk evaluation required.")

        campaign.status = "EXECUTING"
        campaign.started_at = campaign.started_at or datetime.utcnow()
        self.db.commit()

        # Find eligible failed transactions for this merchant
        failed_txs = self.db.query(Transaction).filter(
            Transaction.merchant_id == campaign.merchant_id,
            Transaction.status.in_(["FAILED", "ABANDONED"])
        ).limit(min(batch_limit, campaign.total_transactions or 500)).all()

        # Get existing attempted transaction IDs to enforce duplicate protection
        already_attempted_ids = set(
            a.transaction_id for a in self.db.query(RecoveryAttempt.transaction_id).filter(
                RecoveryAttempt.campaign_id == campaign.id
            ).all()
        )

        attempted_this_run = 0
        success_this_run = 0
        failed_this_run = 0
        recovered_amount_this_run = 0.0
        halted = False
        halt_reason = None

        for idx, tx in enumerate(failed_txs):
            if tx.transaction_id in already_attempted_ids:
                continue

            attempted_this_run += 1
            campaign.attempted_transactions += 1
            campaign.revenue_exposed += tx.amount

            # Controlled failure demonstration for Hackathon Demo:
            # If trigger_controlled_failure is true, after 20 successful retries, force a spike of failures
            # to trigger the automatic stopping threshold (35%).
            if trigger_controlled_failure and attempted_this_run > 20:
                # Force failure rate above 35%
                res = {
                    "success": False,
                    "provider": "SANDBOX / SIMULATED",
                    "amount_recovered": 0.0,
                    "error_message": "SIMULATED_GATEWAY_THROTTLE",
                    "is_mock": True
                }
            else:
                # Normal provider execution
                res = self.mock_provider.retry_payment(
                    transaction_id=tx.transaction_id,
                    amount=tx.amount,
                    payment_method=tx.payment_method or "UPI"
                )

            if res["success"]:
                success_this_run += 1
                campaign.successful_transactions += 1
                recovered_amount_this_run += res["amount_recovered"]
                campaign.revenue_recovered += res["amount_recovered"]
                attempt_status = "SUCCESS"
            else:
                failed_this_run += 1
                campaign.failed_transactions += 1
                attempt_status = "FAILED"

            # Log recovery attempt record
            attempt = RecoveryAttempt(
                campaign_id=campaign.id,
                transaction_id=tx.transaction_id,
                merchant_id=campaign.merchant_id,
                status=attempt_status,
                amount=tx.amount,
                amount_recovered=res.get("amount_recovered", 0.0),
                error_message=res.get("error_message"),
                provider_used=res.get("provider", "SANDBOX / SIMULATED"),
                executed_at=datetime.utcnow(),
                is_mock=res.get("is_mock", True)
            )
            self.db.add(attempt)

            # Check dynamic failure rate stopping condition
            current_fail_rate = campaign.failed_transactions / max(1, campaign.attempted_transactions)
            campaign.failure_rate = round(current_fail_rate, 4)

            # AUTOMATIC SAFETY STOPPING RULE:
            # If at least 25 transactions have been attempted and failure rate exceeds stopping threshold (35%)
            if campaign.attempted_transactions >= 25 and current_fail_rate >= campaign.stopping_threshold:
                halted = True
                campaign.status = "HALTED"
                campaign.completed_at = datetime.utcnow()
                halt_reason = f"AUTOMATIC STOP: Failure rate ({round(current_fail_rate*100, 1)}%) exceeded configured threshold ({round(campaign.stopping_threshold*100, 1)}%)."
                campaign.halted_reason = halt_reason
                
                log_audit_event(
                    db=self.db,
                    actor="SYSTEM",
                    event="RECOVERY_HALTED",
                    action="AUTOMATIC_SAFETY_HALT",
                    reason=halt_reason,
                    risk_decision="BLOCKED",
                    provider=res.get("provider"),
                    transaction_count=campaign.attempted_transactions,
                    amount=campaign.revenue_recovered,
                    result="AUTOMATICALLY_HALTED"
                )
                break

        if not halted and campaign.attempted_transactions >= campaign.total_transactions:
            campaign.status = "COMPLETED"
            campaign.completed_at = datetime.utcnow()
            log_audit_event(
                db=self.db,
                actor="SYSTEM",
                event="RECOVERY_COMPLETED",
                action="CAMPAIGN_FINISHED",
                reason="All target transactions processed",
                provider="SANDBOX / SIMULATED",
                transaction_count=campaign.attempted_transactions,
                amount=campaign.revenue_recovered,
                result="SUCCESS"
            )

        self.db.commit()
        self.db.refresh(campaign)

        # Resolve related incident if campaign recovered significant revenue
        if campaign.incident_id and campaign.revenue_recovered > 50000.0:
            inc = self.db.query(Incident).filter(Incident.id == campaign.incident_id).first()
            if inc and inc.status != "RESOLVED":
                inc.status = "RESOLVED"
                inc.resolved_at = datetime.utcnow()
                self.db.commit()

        return {
            "campaign_id": campaign.id,
            "status": campaign.status,
            "attempted_total": campaign.attempted_transactions,
            "successful_total": campaign.successful_transactions,
            "failed_total": campaign.failed_transactions,
            "revenue_exposed": round(campaign.revenue_exposed, 2),
            "revenue_recovered": round(campaign.revenue_recovered, 2),
            "current_failure_rate": campaign.failure_rate,
            "stopping_threshold": campaign.stopping_threshold,
            "is_halted": halted,
            "halt_reason": halt_reason
        }
