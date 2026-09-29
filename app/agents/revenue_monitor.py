from datetime import datetime, timedelta
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func, case
from app.database.models import Transaction, Incident

class RevenueMonitor:
    def __init__(self, db: Session, merchant_id: str = "merchant_demostore"):
        self.db = db
        self.merchant_id = merchant_id

    def analyze_recent_activity(self, lookback_minutes: int = 120) -> Dict[str, Any]:
        """
        Calculates recent payment success/failure rates compared to a 7-day baseline.
        Identifies anomalies and revenue at risk.
        """
        now = datetime.utcnow()
        recent_window_start = now - timedelta(minutes=lookback_minutes)
        baseline_window_start = now - timedelta(days=7)

        # Baseline stats (past 7 days excluding last 2 hours)
        baseline_query = self.db.query(
            func.count(Transaction.id).label("total"),
            func.sum(case((Transaction.status == "FAILED", 1), else_=0)).label("failed"),
            func.sum(case((Transaction.status == "ABANDONED", 1), else_=0)).label("abandoned")
        ).filter(
            Transaction.merchant_id == self.merchant_id,
            Transaction.timestamp >= baseline_window_start,
            Transaction.timestamp < recent_window_start
        ).first()

        b_total = (baseline_query.total or 1) if baseline_query else 1
        b_failed = ((baseline_query.failed or 0) + (baseline_query.abandoned or 0)) if baseline_query else 0
        baseline_failure_rate = b_failed / max(1, b_total)
        baseline_success_rate = 1.0 - baseline_failure_rate

        # Recent stats (last lookback_minutes)
        recent_txs = self.db.query(Transaction).filter(
            Transaction.merchant_id == self.merchant_id,
            Transaction.timestamp >= recent_window_start
        ).all()

        r_total = len(recent_txs)
        if r_total == 0:
            return {
                "anomaly_detected": False,
                "current_success_rate": 0.914,
                "baseline_success_rate": 0.914,
                "current_failure_rate": 0.086,
                "baseline_failure_rate": 0.086,
                "revenue_at_risk": 0.0,
                "affected_transactions": 0,
                "anomaly_score": 0.0,
                "severity": "NORMAL"
            }

        failed_txs = [t for t in recent_txs if t.status in ["FAILED", "ABANDONED"]]
        r_failed = len(failed_txs)
        current_failure_rate = r_failed / r_total
        current_success_rate = 1.0 - current_failure_rate

        revenue_at_risk = sum(t.amount for t in failed_txs)
        affected_count = len(failed_txs)

        # Anomaly score calculation
        failure_rate_diff = current_failure_rate - baseline_failure_rate
        anomaly_score = round(max(0.0, min(1.0, failure_rate_diff * 4.0)), 2)

        anomaly_detected = (current_failure_rate > (baseline_failure_rate + 0.08)) and (affected_count >= 10)
        
        severity = "LOW"
        if anomaly_score > 0.70:
            severity = "CRITICAL"
        elif anomaly_score > 0.40:
            severity = "HIGH"
        elif anomaly_score > 0.20:
            severity = "MEDIUM"

        return {
            "anomaly_detected": anomaly_detected,
            "current_success_rate": round(current_success_rate, 4),
            "baseline_success_rate": round(baseline_success_rate, 4),
            "current_failure_rate": round(current_failure_rate, 4),
            "baseline_failure_rate": round(baseline_failure_rate, 4),
            "revenue_at_risk": round(revenue_at_risk, 2),
            "affected_transactions": affected_count,
            "anomaly_score": anomaly_score,
            "severity": severity,
            "recent_total_transactions": r_total,
            "recent_failed_transactions": r_failed
        }

    def get_or_create_active_incident(self) -> Dict[str, Any]:
        """Gets active incident or creates one if anomaly detected."""
        existing = self.db.query(Incident).filter(
            Incident.merchant_id == self.merchant_id,
            Incident.status.in_(["CRITICAL", "WARNING", "INVESTIGATING"])
        ).first()

        metrics = self.analyze_recent_activity()

        if existing:
            existing.revenue_at_risk = metrics["revenue_at_risk"]
            existing.affected_transactions = metrics["affected_transactions"]
            existing.current_failure_rate = metrics["current_failure_rate"]
            existing.anomaly_score = metrics["anomaly_score"]
            self.db.commit()
            return existing

        if metrics["anomaly_detected"]:
            inc_code = f"INC-{int(datetime.utcnow().timestamp())}"
            new_inc = Incident(
                incident_code=inc_code,
                title="UPI Payment Degradation" if metrics["severity"] in ["HIGH", "CRITICAL"] else "Payment Failure Spike",
                merchant_id=self.merchant_id,
                status="CRITICAL" if metrics["severity"] == "CRITICAL" else "WARNING",
                severity=metrics["severity"],
                revenue_at_risk=metrics["revenue_at_risk"],
                affected_transactions=metrics["affected_transactions"],
                baseline_failure_rate=metrics["baseline_failure_rate"],
                current_failure_rate=metrics["current_failure_rate"],
                anomaly_score=metrics["anomaly_score"],
                detected_at=datetime.utcnow()
            )
            self.db.add(new_inc)
            self.db.commit()
            self.db.refresh(new_inc)
            return new_inc

        return None
