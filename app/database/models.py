from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.database.session import Base

class Merchant(Base):
    __tablename__ = "merchants"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    transaction_id = Column(String, unique=True, index=True, nullable=False)
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="INR")
    payment_method = Column(String, index=True)  # UPI, CARD, NETBANKING, WALLET
    payment_provider = Column(String)  # HDFC, ICICI, RAZORPAY_GATEWAY, SBI, AXIS
    status = Column(String, index=True)  # SUCCESS, FAILED, ABANDONED
    failure_code = Column(String, index=True, nullable=True)  # BAD_GATEWAY, BANK_TIMEOUT, EXPIRED_CARD, INSUFFICIENT_FUNDS
    device = Column(String)  # MOBILE, DESKTOP, TABLET
    os = Column(String)  # ANDROID, IOS, WINDOWS, MACOS
    country = Column(String, default="IN")
    city = Column(String)
    customer_id = Column(String, index=True)
    subscription_id = Column(String, nullable=True)
    checkout_session_id = Column(String, nullable=True)
    retry_count = Column(Integer, default=0)

class PaymentEvent(Base):
    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    event_type = Column(String, index=True)  # PAYMENT_FAILED, CHECKOUT_ABANDONED, SUB_RENEWAL_FAILED
    transaction_id = Column(String, index=True)
    merchant_id = Column(String, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    details_json = Column(JSON, nullable=True)

class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    incident_code = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    status = Column(String, default="CRITICAL", index=True)  # CRITICAL, WARNING, INVESTIGATING, RESOLVED
    severity = Column(String, default="HIGH")  # HIGH, MEDIUM, LOW
    revenue_at_risk = Column(Float, default=0.0)
    affected_transactions = Column(Integer, default=0)
    baseline_failure_rate = Column(Float, default=0.0)
    current_failure_rate = Column(Float, default=0.0)
    anomaly_score = Column(Float, default=0.0)
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
    root_cause_json = Column(JSON, nullable=True)
    recommendation_json = Column(JSON, nullable=True)

class RecoveryStrategy(Base):
    __tablename__ = "recovery_strategies"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    code = Column(String, unique=True, index=True)  # delayed_retry, alternate_route, recovery_link, mandate_retry, customer_contact
    name = Column(String, nullable=False)
    description = Column(Text)
    expected_recovery_rate = Column(Float)
    risk_score = Column(Float)
    customer_impact = Column(String)  # LOW, MEDIUM, HIGH
    max_transactions = Column(Integer, default=500)
    max_exposure = Column(Float, default=200000.0)
    stop_if_failure_rate_above = Column(Float, default=0.35)

class RecoveryCampaign(Base):
    __tablename__ = "recovery_campaigns"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    campaign_code = Column(String, unique=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id"), nullable=True)
    merchant_id = Column(String, ForeignKey("merchants.id"), index=True)
    strategy_code = Column(String, nullable=False)
    status = Column(String, default="PENDING_APPROVAL", index=True)  # PENDING_APPROVAL, APPROVED, EXECUTING, COMPLETED, HALTED, REJECTED
    total_transactions = Column(Integer, default=0)
    attempted_transactions = Column(Integer, default=0)
    successful_transactions = Column(Integer, default=0)
    failed_transactions = Column(Integer, default=0)
    revenue_exposed = Column(Float, default=0.0)
    revenue_recovered = Column(Float, default=0.0)
    failure_rate = Column(Float, default=0.0)
    stopping_threshold = Column(Float, default=0.35)
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    halted_reason = Column(String, nullable=True)

class RecoveryAttempt(Base):
    __tablename__ = "recovery_attempts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("recovery_campaigns.id"), index=True)
    transaction_id = Column(String, index=True)
    merchant_id = Column(String, index=True)
    status = Column(String, index=True)  # SUCCESS, FAILED, SKIPPED
    amount = Column(Float, nullable=False)
    amount_recovered = Column(Float, default=0.0)
    error_message = Column(String, nullable=True)
    provider_used = Column(String, default="RAZORPAY_TEST")
    executed_at = Column(DateTime, default=datetime.utcnow)
    is_mock = Column(Boolean, default=True)

class RiskPolicy(Base):
    __tablename__ = "risk_policies"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    merchant_id = Column(String, ForeignKey("merchants.id"), unique=True, index=True)
    max_monetary_exposure = Column(Float, default=200000.0)
    max_transaction_count = Column(Integer, default=500)
    max_retry_attempts = Column(Integer, default=3)
    max_failure_rate_threshold = Column(Float, default=0.35)
    require_human_approval_above_exposure = Column(Float, default=100000.0)
    cooldown_period_minutes = Column(Integer, default=20)

class Approval(Base):
    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    campaign_id = Column(Integer, ForeignKey("recovery_campaigns.id"), index=True)
    merchant_id = Column(String, index=True)
    action = Column(String)  # APPROVE, REJECT, MODIFY
    actor = Column(String, default="MERCHANT")
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    actor = Column(String, index=True)  # SYSTEM, AI_AGENT, RISK_GOVERNOR, MERCHANT, RAZORPAY_TEST
    event = Column(String, index=True)
    action = Column(String)
    reason = Column(Text, nullable=True)
    risk_decision = Column(String, nullable=True)  # APPROVED, HUMAN_APPROVAL_REQUIRED, BLOCKED
    provider = Column(String, nullable=True)
    transaction_count = Column(Integer, default=0)
    amount = Column(Float, default=0.0)
    result = Column(String, nullable=True)
    input_data_json = Column(JSON, nullable=True)
    output_data_json = Column(JSON, nullable=True)

class ModelPrediction(Base):
    __tablename__ = "model_predictions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    transaction_id = Column(String, index=True)
    recovery_probability = Column(Float)
    features_json = Column(JSON, nullable=True)
    predicted_at = Column(DateTime, default=datetime.utcnow)
