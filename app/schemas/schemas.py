from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime

class MerchantBase(BaseModel):
    id: str
    name: str
    email: str

class TransactionBase(BaseModel):
    transaction_id: str
    merchant_id: str
    timestamp: datetime
    amount: float
    currency: str = "INR"
    payment_method: str
    payment_provider: str
    status: str
    failure_code: Optional[str] = None
    device: Optional[str] = None
    os: Optional[str] = None
    country: str = "IN"
    city: Optional[str] = None
    customer_id: str
    subscription_id: Optional[str] = None
    checkout_session_id: Optional[str] = None
    retry_count: int = 0

    class Config:
        from_attributes = True

class PaymentEventCreate(BaseModel):
    event_type: str
    transaction_id: str
    merchant_id: str
    details_json: Optional[Dict[str, Any]] = None

class IncidentOut(BaseModel):
    id: int
    incident_code: str
    title: str
    merchant_id: str
    status: str
    severity: str
    revenue_at_risk: float
    affected_transactions: int
    baseline_failure_rate: float
    current_failure_rate: float
    anomaly_score: float
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    root_cause_json: Optional[Dict[str, Any]] = None
    recommendation_json: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

class StrategyOut(BaseModel):
    code: str
    name: str
    description: str
    expected_recovery: float
    expected_recovery_rate: float
    risk_score: float
    customer_impact: str
    max_transactions: int
    max_exposure: float
    stop_if_failure_rate_above: float
    recommendation_reason: Optional[str] = None

class PlanRequest(BaseModel):
    incident_id: int
    strategy_code: str

class RiskDecision(BaseModel):
    decision: str  # APPROVED, HUMAN_APPROVAL_REQUIRED, BLOCKED
    reason: str
    max_exposure: float
    requested_exposure: float
    max_transactions: int
    requested_transactions: int
    stopping_threshold: float
    policy_checks: Dict[str, bool]

class PlanResponse(BaseModel):
    campaign_id: int
    campaign_code: str
    incident_id: int
    strategy: StrategyOut
    risk_decision: RiskDecision
    revenue_at_risk: float
    expected_recovery: float
    affected_transactions: int

class ApprovalRequest(BaseModel):
    campaign_id: int
    action: str  # APPROVE, REJECT, MODIFY
    actor: str = "MERCHANT"
    reason: Optional[str] = None
    modified_exposure: Optional[float] = None
    modified_transactions: Optional[int] = None

class ExecuteRequest(BaseModel):
    campaign_id: int
    trigger_controlled_failure: bool = False

class SimulatorStartRequest(BaseModel):
    scenario: str = "UPI_DEGRADATION"  # NORMAL, UPI_DEGRADATION, CARD_FAILURE_SPIKE, CHECKOUT_ABANDONMENT, SUBSCRIPTION_FAILURE, PROVIDER_OUTAGE, RANDOM_MIXED_FAILURE
    tpm: int = 60  # transactions per minute

class AuditLogOut(BaseModel):
    id: int
    timestamp: datetime
    actor: str
    event: str
    action: str
    reason: Optional[str] = None
    risk_decision: Optional[str] = None
    provider: Optional[str] = None
    transaction_count: int
    amount: float
    result: Optional[str] = None
    input_data_json: Optional[Dict[str, Any]] = None
    output_data_json: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True

class DashboardKPIs(BaseModel):
    revenue_at_risk: float
    recoverable_revenue: float
    recovered_today: float
    recovery_rate: float
    successful_retries: int = 0
    active_incidents: int
    normal_success_rate: float
    current_success_rate: float

class AnalyticsOut(BaseModel):
    model_evaluation: Dict[str, Any]
    feature_importance: List[Dict[str, Any]]
    train_test_split: Dict[str, int]
    confusion_matrix: Optional[Dict[str, int]] = None
    historical_recovery_rate: float

class CommandQueryRequest(BaseModel):
    query: str

class CommandQueryResponse(BaseModel):
    query: str
    answer: str
    sql_tool_used: Optional[str] = None
    data: Optional[Any] = None

class RiskPolicyUpdate(BaseModel):
    max_monetary_exposure: Optional[float] = None
    max_transaction_count: Optional[int] = None
    max_failure_rate_threshold: Optional[float] = None
    require_human_approval_above_exposure: Optional[float] = None

