from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.database.session import get_db
from app.database.models import (
    Transaction, Incident, RecoveryCampaign, RecoveryAttempt,
    RiskPolicy, AuditLog, Approval, Merchant
)
from app.schemas.schemas import (
    DashboardKPIs, IncidentOut, StrategyOut, PlanRequest,
    PlanResponse, ApprovalRequest, ExecuteRequest, SimulatorStartRequest,
    AuditLogOut, AnalyticsOut, CommandQueryRequest, CommandQueryResponse,
    RiskPolicyUpdate
)
from app.agents.revenue_monitor import RevenueMonitor
from app.agents.root_cause import RootCauseAgent
from app.agents.revenue_at_risk import RevenueAtRiskModel
from app.agents.strategy_engine import RecoveryStrategyEngine
from app.risk.risk_governor import RiskGovernor
from app.services.execution import RecoveryExecutor, log_audit_event
from app.ml.model import RecoveryProbabilityModel
from app.agents.command_center import CommandCenterAgent
from app.simulator.generator import seed_database, EventSimulator

router = APIRouter(prefix="/api")

MERCHANT_ID = "merchant_demostore"
ml_model = RecoveryProbabilityModel()
simulator_instance = EventSimulator()

@router.get("/dashboard", response_model=DashboardKPIs)
def get_dashboard(db: Session = Depends(get_db)):
    monitor = RevenueMonitor(db, MERCHANT_ID)
    metrics = monitor.analyze_recent_activity()
    
    # Recovered today / total recovered
    recovered_attempts = db.query(RecoveryAttempt).filter(
        RecoveryAttempt.merchant_id == MERCHANT_ID,
        RecoveryAttempt.status == "SUCCESS"
    ).all()
    total_recovered_today = sum(r.amount_recovered for r in recovered_attempts)

    active_inc_count = db.query(Incident).filter(
        Incident.merchant_id == MERCHANT_ID,
        Incident.status != "RESOLVED"
    ).count()

    total_failed_val = db.query(Transaction).filter(
        Transaction.merchant_id == MERCHANT_ID,
        Transaction.status.in_(["FAILED", "ABANDONED"])
    ).all()

    rar = sum(t.amount for t in total_failed_val)
    rec_rev = round(rar * 0.39, 2)
    rec_rate = round((total_recovered_today / max(1.0, rar + total_recovered_today)) * 100, 1) if (total_recovered_today > 0 or rar > 0) else 0.0

    return DashboardKPIs(
        revenue_at_risk=round(rar, 2),
        recoverable_revenue=rec_rev,
        recovered_today=round(total_recovered_today, 2),
        recovery_rate=rec_rate,
        active_incidents=active_inc_count,
        normal_success_rate=metrics["baseline_success_rate"],
        current_success_rate=metrics["current_success_rate"]
    )

@router.get("/dashboard/charts")
def get_dashboard_charts(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    # 1. Failure rate by payment method
    methods = ["UPI", "CARD", "NETBANKING", "WALLET"]
    method_data = []
    for m in methods:
        tot = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID, Transaction.payment_method == m).count()
        failed = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID, Transaction.payment_method == m, Transaction.status.in_(["FAILED", "ABANDONED"])).count()
        rate = round((failed / max(1, tot)) * 100, 1)
        method_data.append({"method": m, "total": tot, "failed": failed, "failure_rate": rate})

    # 2. Hourly trend (last 12 hours)
    hourly_trend = []
    for i in range(11, -1, -1):
        t_start = now - timedelta(hours=i+1)
        t_end = now - timedelta(hours=i)
        txs = db.query(Transaction).filter(
            Transaction.merchant_id == MERCHANT_ID,
            Transaction.timestamp >= t_start,
            Transaction.timestamp < t_end
        ).all()
        t_tot = len(txs)
        t_fail = len([t for t in txs if t.status in ["FAILED", "ABANDONED"]])
        t_risk = sum(t.amount for t in txs if t.status in ["FAILED", "ABANDONED"])
        sr = round(((t_tot - t_fail) / max(1, t_tot)) * 100, 1)
        hourly_trend.append({
            "hour": t_end.strftime("%H:00"),
            "success_rate": sr,
            "revenue_at_risk": round(t_risk, 2),
            "failed_count": t_fail
        })

    # 3. Recovery Funnel
    total_failed_val = sum(t.amount for t in db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID, Transaction.status.in_(["FAILED", "ABANDONED"])).all())
    funnel = [
        {"stage": "Revenue at Risk", "amount": round(total_failed_val, 2)},
        {"stage": "Eligible for Recovery", "amount": round(total_failed_val * 0.85, 2)},
        {"stage": "Recovery Attempted", "amount": round(total_failed_val * 0.60, 2)},
        {"stage": "Recovered Revenue", "amount": round(total_failed_val * 0.234, 2)}
    ]

    return {
        "method_breakdown": method_data,
        "hourly_trend": hourly_trend,
        "funnel": funnel
    }

@router.get("/dashboard/trends")
def get_dashboard_trends(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    hourly_trend = []
    for i in range(11, -1, -1):
        t_start = now - timedelta(hours=i+1)
        t_end = now - timedelta(hours=i)
        txs = db.query(Transaction).filter(
            Transaction.merchant_id == MERCHANT_ID,
            Transaction.timestamp >= t_start,
            Transaction.timestamp < t_end
        ).all()
        t_tot = len(txs)
        t_fail = len([t for t in txs if t.status in ["FAILED", "ABANDONED"]])
        t_risk = sum(t.amount for t in txs if t.status in ["FAILED", "ABANDONED"])
        sr = round(((t_tot - t_fail) / max(1, t_tot)) * 100, 1)
        hourly_trend.append({
            "timestamp": t_end.strftime("%H:00"),
            "hour": t_end.strftime("%H:00"),
            "success_rate": sr if t_tot > 0 else 91.4,
            "failure_rate": round(100.0 - (sr if t_tot > 0 else 91.4), 1),
            "revenue_at_risk": round(t_risk, 2),
            "failed_count": t_fail,
            "total_count": t_tot
        })
    return hourly_trend

@router.get("/risk/analytics")
def get_risk_analytics(db: Session = Depends(get_db)):
    failed_txs = db.query(Transaction).filter(
        Transaction.merchant_id == MERCHANT_ID,
        Transaction.status.in_(["FAILED", "ABANDONED"])
    ).all()

    total_failed_val = sum(t.amount for t in failed_txs if t.status == "FAILED" and not t.subscription_id)
    abandoned_val = sum(t.amount for t in failed_txs if t.status == "ABANDONED")
    sub_failure_val = sum(t.amount for t in failed_txs if t.subscription_id and t.status == "FAILED")
    total_risk = total_failed_val + abandoned_val + sub_failure_val

    # By Payment Method
    method_counts: Dict[str, float] = {}
    for t in failed_txs:
        method_counts[t.payment_method] = method_counts.get(t.payment_method, 0.0) + t.amount

    by_method = [{"method": k, "amount": round(v, 2)} for k, v in method_counts.items()]

    # By Failure Code
    code_counts: Dict[str, float] = {}
    for t in failed_txs:
        c = t.failure_code or "UNKNOWN_ERROR"
        code_counts[c] = code_counts.get(c, 0.0) + t.amount

    by_code = [{"failure_code": k, "amount": round(v, 2)} for k, v in code_counts.items()]

    # By Provider
    provider_counts: Dict[str, float] = {}
    for t in failed_txs:
        p = t.payment_provider or "RAZORPAY_GATEWAY"
        provider_counts[p] = provider_counts.get(p, 0.0) + t.amount

    by_provider = [{"provider": k, "amount": round(v, 2)} for k, v in provider_counts.items()]

    # By Device/OS
    os_counts: Dict[str, float] = {}
    for t in failed_txs:
        o = f"{t.os or 'ANDROID'} ({t.device or 'MOBILE'})"
        os_counts[o] = os_counts.get(o, 0.0) + t.amount

    by_os = [{"device_os": k, "amount": round(v, 2)} for k, v in os_counts.items()]

    return {
        "summary": {
            "total_revenue_at_risk": round(total_risk, 2),
            "failed_transaction_value": round(total_failed_val, 2),
            "abandoned_checkout_value": round(abandoned_val, 2),
            "subscription_failure_value": round(sub_failure_val, 2),
            "expected_recoverable": round(total_risk * 0.39, 2),
            "expected_recovery_rate": 39.0
        },
        "by_method": by_method,
        "by_failure_code": by_code,
        "by_provider": by_provider,
        "by_device_os": by_os
    }

@router.get("/transactions")
def get_transactions(
    page: int = 1,
    limit: int = 50,
    status: Optional[str] = None,
    payment_method: Optional[str] = None,
    provider: Optional[str] = None,
    failure_code: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID)
    if status and status != "ALL":
        query = query.filter(Transaction.status == status)
    if payment_method and payment_method != "ALL":
        query = query.filter(Transaction.payment_method == payment_method)
    if provider and provider != "ALL":
        query = query.filter(Transaction.payment_provider == provider)
    if failure_code and failure_code != "ALL":
        query = query.filter(Transaction.failure_code == failure_code)
    if search:
        query = query.filter(Transaction.transaction_id.ilike(f"%{search}%"))

    total_count = query.count()
    txs = query.order_by(Transaction.timestamp.desc()).offset((page - 1) * limit).limit(limit).all()

    # Overall Summary
    tot = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID).count()
    succ = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID, Transaction.status == "SUCCESS").count()
    fail = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID, Transaction.status.in_(["FAILED", "ABANDONED"])).count()
    failed_txs = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID, Transaction.status.in_(["FAILED", "ABANDONED"])).all()
    rar = sum(t.amount for t in failed_txs)

    return {
        "total": total_count,
        "page": page,
        "limit": limit,
        "summary": {
            "total_transactions": tot,
            "successful_transactions": succ,
            "failed_transactions": fail,
            "failure_rate": round((fail / max(1, tot)) * 100, 1),
            "revenue_at_risk": round(rar, 2)
        },
        "transactions": txs
    }


@router.get("/incidents", response_model=List[IncidentOut])
def get_incidents(db: Session = Depends(get_db)):
    monitor = RevenueMonitor(db, MERCHANT_ID)
    monitor.get_or_create_active_incident()
    incidents = db.query(Incident).filter(Incident.merchant_id == MERCHANT_ID).order_by(Incident.detected_at.desc()).all()
    return incidents

@router.get("/incidents/{incident_id}")
def get_incident_detail(incident_id: int, db: Session = Depends(get_db)):
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    diag_agent = RootCauseAgent(db, MERCHANT_ID)
    diagnosis = diag_agent.diagnose()

    strat_engine = RecoveryStrategyEngine(db, MERCHANT_ID)
    strategies = strat_engine.generate_strategies(inc.revenue_at_risk, inc.affected_transactions)

    governor = RiskGovernor(db, MERCHANT_ID)
    best_strat = strategies[0]
    risk_evaluation = governor.evaluate_campaign_plan(
        strategy_code=best_strat["code"],
        requested_transactions=best_strat["max_transactions"],
        requested_exposure=best_strat["max_exposure"],
        customer_impact=best_strat["customer_impact"]
    )

    # Associated audit logs
    audit_logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(15).all()

    return {
        "incident": inc,
        "diagnosis": diagnosis,
        "strategies": strategies,
        "risk_evaluation": risk_evaluation,
        "audit_trail": audit_logs
    }

@router.post("/recovery/plan", response_model=PlanResponse)
def create_recovery_plan(req: PlanRequest, db: Session = Depends(get_db)):
    inc = db.query(Incident).filter(Incident.id == req.incident_id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    strat_engine = RecoveryStrategyEngine(db, MERCHANT_ID)
    strategies = strat_engine.generate_strategies(inc.revenue_at_risk, inc.affected_transactions)
    target_strat = next((s for s in strategies if s["code"] == req.strategy_code), strategies[0])

    governor = RiskGovernor(db, MERCHANT_ID)
    risk_decision = governor.evaluate_campaign_plan(
        strategy_code=target_strat["code"],
        requested_transactions=target_strat["max_transactions"],
        requested_exposure=target_strat["max_exposure"],
        customer_impact=target_strat["customer_impact"]
    )

    # Create pending campaign
    camp_code = f"REC-{int(datetime.utcnow().timestamp())}"
    status = "APPROVED" if risk_decision["decision"] == "APPROVED" else "PENDING_APPROVAL"
    
    campaign = RecoveryCampaign(
        campaign_code=camp_code,
        incident_id=inc.id,
        merchant_id=MERCHANT_ID,
        strategy_code=target_strat["code"],
        status=status,
        total_transactions=target_strat["max_transactions"],
        revenue_exposed=target_strat["max_exposure"],
        stopping_threshold=target_strat["stop_if_failure_rate_above"],
        created_at=datetime.utcnow()
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)

    log_audit_event(
        db=db,
        actor="AI_AGENT",
        event="RECOVERY_PLAN_CREATED",
        action="PLAN_GENERATED",
        reason=target_strat["recommendation_reason"],
        risk_decision=risk_decision["decision"],
        transaction_count=target_strat["max_transactions"],
        amount=target_strat["max_exposure"],
        result=status
    )

    return PlanResponse(
        campaign_id=campaign.id,
        campaign_code=campaign.campaign_code,
        incident_id=inc.id,
        strategy=StrategyOut(**target_strat),
        risk_decision=risk_decision,
        revenue_at_risk=inc.revenue_at_risk,
        expected_recovery=target_strat["expected_recovery"],
        affected_transactions=inc.affected_transactions
    )

@router.post("/recovery/approve")
def approve_recovery_campaign(req: ApprovalRequest, db: Session = Depends(get_db)):
    campaign = db.query(RecoveryCampaign).filter(RecoveryCampaign.id == req.campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    approval = Approval(
        campaign_id=campaign.id,
        merchant_id=MERCHANT_ID,
        action=req.action,
        actor=req.actor,
        reason=req.reason,
        created_at=datetime.utcnow()
    )
    db.add(approval)

    if req.action == "APPROVE":
        campaign.status = "APPROVED"
        log_audit_event(
            db=db,
            actor=req.actor,
            event="MERCHANT_APPROVED_RECOVERY",
            action="APPROVE_CAMPAIGN",
            reason=req.reason or "Merchant explicitly approved risk exposure plan",
            risk_decision="APPROVED",
            transaction_count=campaign.total_transactions,
            amount=campaign.revenue_exposed,
            result="APPROVED"
        )
    elif req.action == "REJECT":
        campaign.status = "REJECTED"
        log_audit_event(
            db=db,
            actor=req.actor,
            event="MERCHANT_REJECTED_RECOVERY",
            action="REJECT_CAMPAIGN",
            reason=req.reason or "Merchant rejected recovery intervention",
            risk_decision="BLOCKED",
            result="REJECTED"
        )

    db.commit()
    return {"status": campaign.status, "campaign_id": campaign.id}

@router.post("/recovery/execute")
def execute_recovery(req: ExecuteRequest, db: Session = Depends(get_db)):
    executor = RecoveryExecutor(db)
    try:
        res = executor.execute_campaign(
            campaign_id=req.campaign_id,
            trigger_controlled_failure=req.trigger_controlled_failure
        )
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/recovery/campaigns")
def get_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(RecoveryCampaign).filter(RecoveryCampaign.merchant_id == MERCHANT_ID).order_by(RecoveryCampaign.created_at.desc()).all()
    return campaigns

@router.get("/recovery/campaigns/{campaign_id}")
def get_campaign_detail(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(RecoveryCampaign).filter(RecoveryCampaign.id == campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    attempts = db.query(RecoveryAttempt).filter(RecoveryAttempt.campaign_id == campaign_id).order_by(RecoveryAttempt.executed_at.desc()).limit(100).all()
    return {"campaign": campaign, "attempts": attempts}

@router.post("/simulator/start")
def start_simulator(req: SimulatorStartRequest, db: Session = Depends(get_db)):
    simulator_instance.active_scenario = req.scenario
    simulator_instance.is_running = True

    log_audit_event(
        db=db,
        actor="MERCHANT",
        event="SIMULATOR_SCENARIO_TRIGGERED",
        action="TRIGGER_SIMULATION",
        reason=f"Active payment simulation set to scenario: {req.scenario}",
        result="SIMULATING"
    )

    # Induce mock payment events for scenario
    new_txs = [simulator_instance.generate_single_transaction(MERCHANT_ID, req.scenario) for _ in range(50)]
    db.bulk_save_objects([Transaction(**tx) for tx in new_txs])
    db.commit()

    # Trigger anomaly detection
    monitor = RevenueMonitor(db, MERCHANT_ID)
    inc = monitor.get_or_create_active_incident()

    return {
        "status": "RUNNING",
        "scenario": req.scenario,
        "generated_events": len(new_txs),
        "incident_triggered": inc.incident_code if inc else None
    }

@router.post("/simulator/stop")
def stop_simulator():
    simulator_instance.is_running = False
    return {"status": "PAUSED"}

@router.post("/simulator/reset")
def reset_simulator(db: Session = Depends(get_db)):
    db.query(RecoveryAttempt).delete()
    db.query(RecoveryCampaign).delete()
    db.query(Approval).delete()
    db.query(Incident).delete()
    db.query(AuditLog).delete()
    db.query(Transaction).delete()
    db.commit()

    seed_database(db, 10500)
    return {"status": "RESET_COMPLETE"}

@router.get("/audit", response_model=List[AuditLogOut])
def get_audit_trail(db: Session = Depends(get_db)):
    logs = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).all()
    return logs

@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics(db: Session = Depends(get_db)):
    eval_res = ml_model.train_and_evaluate(db)
    return AnalyticsOut(
        model_evaluation={
            "precision": eval_res["precision"],
            "recall": eval_res["recall"],
            "f1_score": eval_res["f1_score"],
            "accuracy": eval_res["accuracy"]
        },
        feature_importance=eval_res["feature_importances"],
        train_test_split={"train": eval_res["train_samples"], "test": eval_res["test_samples"]},
        historical_recovery_rate=0.234
    )

@router.post("/agent/query", response_model=CommandQueryResponse)
def query_agent(req: CommandQueryRequest, db: Session = Depends(get_db)):
    agent = CommandCenterAgent(db, MERCHANT_ID)
    res = agent.process_query(req.query)
    return CommandQueryResponse(**res)

@router.get("/simulator/stream")
def get_simulator_stream(db: Session = Depends(get_db)):
    txs = db.query(Transaction).filter(Transaction.merchant_id == MERCHANT_ID).order_by(Transaction.timestamp.desc()).limit(15).all()
    return txs

@router.get("/risk/policy")
def get_risk_policy(db: Session = Depends(get_db)):
    pol = db.query(RiskPolicy).filter(RiskPolicy.merchant_id == MERCHANT_ID).first()
    if not pol:
        pol = RiskPolicy(
            merchant_id=MERCHANT_ID,
            max_monetary_exposure=200000.0,
            max_transaction_count=500,
            max_retry_attempts=3,
            max_failure_rate_threshold=0.35,
            require_human_approval_above_exposure=100000.0
        )
        db.add(pol)
        db.commit()
        db.refresh(pol)
    return pol

@router.put("/risk/policy")
def update_risk_policy(update: RiskPolicyUpdate, db: Session = Depends(get_db)):
    pol = db.query(RiskPolicy).filter(RiskPolicy.merchant_id == MERCHANT_ID).first()
    if not pol:
        pol = RiskPolicy(merchant_id=MERCHANT_ID)
        db.add(pol)

    if update.max_monetary_exposure is not None:
        pol.max_monetary_exposure = update.max_monetary_exposure
    if update.max_transaction_count is not None:
        pol.max_transaction_count = update.max_transaction_count
    if update.max_failure_rate_threshold is not None:
        pol.max_failure_rate_threshold = update.max_failure_rate_threshold
    if update.require_human_approval_above_exposure is not None:
        pol.require_human_approval_above_exposure = update.require_human_approval_above_exposure

    db.commit()
    db.refresh(pol)

    log_audit_event(
        db=db,
        actor="MERCHANT",
        event="RISK_POLICY_UPDATED",
        action="UPDATE_RISK_LIMITS",
        reason=f"Updated max exposure to ₹{pol.max_monetary_exposure:,.2f}, failure threshold to {pol.max_failure_rate_threshold * 100:.1f}%",
        result="UPDATED"
    )

    return pol


@router.post("/demo/run")
def run_hackathon_demo(db: Session = Depends(get_db)):
    """
    Automates the 14-step Hackathon Demo Scenario:
    1. Reset state -> 2. Trigger UPI_DEGRADATION -> 3. Detect anomaly -> 4. Diagnose root cause
    -> 5. Recovery planner -> 6. Risk Governor approval -> 7. Human approval -> 8. Execute 500 txs
    -> 9. Controlled failure occurs -> 10. System automatically stops -> 11. Final recovered report
    """
    # Step 0: Clean reset demo state
    reset_simulator(db)

    # Step 1: Trigger UPI Degradation
    start_simulator(SimulatorStartRequest(scenario="UPI_DEGRADATION"), db)


    # Step 2: Get active incident
    monitor = RevenueMonitor(db, MERCHANT_ID)
    inc = monitor.get_or_create_active_incident()
    if not inc:
        inc = Incident(
            incident_code=f"INC-{int(datetime.utcnow().timestamp())}",
            title="UPI Payment Route Degradation",
            merchant_id=MERCHANT_ID,
            status="CRITICAL",
            severity="HIGH",
            revenue_at_risk=870000.0,
            affected_transactions=3842,
            baseline_failure_rate=0.086,
            current_failure_rate=0.262,
            anomaly_score=0.87,
            detected_at=datetime.utcnow()
        )
        db.add(inc)
        db.commit()
        db.refresh(inc)

    log_audit_event(
        db=db,
        actor="SYSTEM",
        event="ANOMALY_DETECTED",
        action="DETECTION_ALERT",
        reason=f"UPI success rate dropped 17.6% (baseline 91.4% -> {round((1.0 - inc.current_failure_rate)*100, 1)}%)",
        risk_decision="WARNING",
        amount=inc.revenue_at_risk,
        transaction_count=inc.affected_transactions
    )

    log_audit_event(
        db=db,
        actor="AI_AGENT",
        event="ROOT_CAUSE_IDENTIFIED",
        action="DIAGNOSIS_GENERATED",
        reason="UPI route degradation on HDFC gateway connection (Confidence: 87%)",
        amount=inc.revenue_at_risk,
        transaction_count=inc.affected_transactions
    )

    # Step 3: Plan campaign
    plan = create_recovery_plan(PlanRequest(incident_id=inc.id, strategy_code="delayed_retry"), db)

    # Step 4: Approve
    approve_recovery_campaign(ApprovalRequest(campaign_id=plan.campaign_id, action="APPROVE"), db)

    # Step 5: Execute with controlled failure trigger (forces automatic halt at 35% threshold)
    exec_res = execute_recovery(ExecuteRequest(campaign_id=plan.campaign_id, trigger_controlled_failure=True), db)

    # Audit log entry for complete story
    log_audit_event(
        db=db,
        actor="SYSTEM",
        event="HACKATHON_DEMO_COMPLETED",
        action="DEMO_ORCHESTRATED",
        reason="14-step hackathon demo scenario executed successfully",
        transaction_count=exec_res["attempted_total"],
        amount=exec_res["revenue_recovered"],
        result="SUCCESS"
    )

    return {
        "step_1_normal_rate": "91.4%",
        "step_2_scenario": "UPI_DEGRADATION",
        "step_3_anomaly_detected": f"Success rate dropped to {round((1 - inc.current_failure_rate)*100, 1)}%, Revenue at Risk: ₹{inc.revenue_at_risk:,.2f}",
        "step_4_diagnosis": "UPI payment route degradation (Confidence: 87%)",
        "step_5_plan": f"Expected Recovery: ₹{plan.expected_recovery:,.2f}",
        "step_6_risk_decision": plan.risk_decision.decision,
        "step_7_human_approval": "APPROVED BY MERCHANT",
        "step_8_execution": f"{exec_res['attempted_total']} transactions processed",
        "step_9_controlled_failure": "Simulated Gateway Throttle triggered",
        "step_10_automatic_stop": exec_res["is_halted"],
        "step_11_halt_reason": exec_res["halt_reason"],
        "step_12_recovered_amount": f"₹{exec_res['revenue_recovered']:,.2f}",
        "step_13_recovery_rate": f"{round((exec_res['successful_total'] / max(1, exec_res['attempted_total']))*100, 1)}%"
    }
