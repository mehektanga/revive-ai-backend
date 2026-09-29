import random
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.database.models import Merchant, Transaction, PaymentEvent, RiskPolicy

MERCHANT_ID = "merchant_demostore"
MERCHANT_NAME = "DemoStore Payments"
MERCHANT_EMAIL = "operations@demostore.com"

PAYMENT_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
METHOD_WEIGHTS = [0.60, 0.25, 0.10, 0.05]

PROVIDERS = ["HDFC", "ICICI", "SBI", "AXIS", "RAZORPAY_GATEWAY"]
DEVICES = ["MOBILE", "DESKTOP", "TABLET"]
DEVICE_WEIGHTS = [0.75, 0.20, 0.05]

OS_LIST = ["ANDROID", "IOS", "WINDOWS", "MACOS"]
OS_WEIGHTS = [0.65, 0.20, 0.10, 0.05]

CITIES = ["Mumbai", "Bengaluru", "Delhi", "Hyderabad", "Pune", "Chennai"]

FAILURE_CODES = {
    "UPI": ["UPI_BANK_TIMEOUT", "INVALID_UPI_ID", "USER_ABORTED", "PSP_APP_ERROR", "INSUFFICIENT_FUNDS"],
    "CARD": ["3DS_AUTHENTICATION_FAILED", "EXPIRED_CARD", "INSUFFICIENT_FUNDS", "CARD_BLOCKED", "BANK_GATEWAY_ERROR"],
    "NETBANKING": ["BANK_SERVER_DOWN", "SESSION_TIMEOUT", "AUTH_FAILED"],
    "WALLET": ["WALLET_INSUFFICIENT_BALANCE", "TOKEN_EXPIRED"]
}

class EventSimulator:
    def __init__(self):
        self.active_scenario = "NORMAL"
        self.is_running = False
        self.tpm = 60

    def generate_single_transaction(
        self,
        merchant_id: str = MERCHANT_ID,
        scenario: str = "NORMAL",
        timestamp: datetime = None
    ) -> Dict[str, Any]:
        if not timestamp:
            timestamp = datetime.utcnow()

        method = random.choices(PAYMENT_METHODS, weights=METHOD_WEIGHTS)[0]
        provider = random.choice(PROVIDERS)
        device = random.choices(DEVICES, weights=DEVICE_WEIGHTS)[0]
        os_type = random.choices(OS_LIST, weights=OS_WEIGHTS)[0]
        city = random.choice(CITIES)
        cust_id = f"cust_{random.randint(10000, 99999)}"

        # Default normal success probability = 91.4%
        success_prob = 0.914
        failure_code = None

        if scenario == "UPI_DEGRADATION" and method == "UPI":
            # Degradation: UPI success drops significantly (~35% fail rate)
            success_prob = 0.635
        elif scenario == "CARD_FAILURE_SPIKE" and method == "CARD":
            success_prob = 0.450
        elif scenario == "CHECKOUT_ABANDONMENT" and device == "MOBILE":
            success_prob = 0.500
        elif scenario == "SUBSCRIPTION_FAILURE":
            success_prob = 0.550
        elif scenario == "PROVIDER_OUTAGE" and provider == "HDFC":
            success_prob = 0.200
        elif scenario == "RANDOM_MIXED_FAILURE":
            success_prob = 0.720

        is_success = random.random() < success_prob
        status = "SUCCESS" if is_success else "FAILED"

        if not is_success:
            if scenario == "CHECKOUT_ABANDONMENT" and random.random() < 0.4:
                status = "ABANDONED"
            failure_code = random.choice(FAILURE_CODES.get(method, ["UNKNOWN_ERROR"]))

        # Amount distribution (normal e-commerce ₹200 to ₹15,000)
        amount = round(random.uniform(250.0, 8500.0), 2)

        tx_id = f"pay_{uuid.uuid4().hex[:14]}"
        sub_id = f"sub_{uuid.uuid4().hex[:10]}" if random.random() < 0.2 else None
        chk_id = f"chk_{uuid.uuid4().hex[:10]}" if status == "ABANDONED" else None

        return {
            "transaction_id": tx_id,
            "merchant_id": merchant_id,
            "timestamp": timestamp,
            "amount": amount,
            "currency": "INR",
            "payment_method": method,
            "payment_provider": provider,
            "status": status,
            "failure_code": failure_code,
            "device": device,
            "os": os_type,
            "country": "IN",
            "city": city,
            "customer_id": cust_id,
            "subscription_id": sub_id,
            "checkout_session_id": chk_id,
            "retry_count": 0
        }

def seed_database(db: Session, num_transactions: int = 10500):
    """Seed initial merchant, risk policy, and historical transaction dataset."""
    # Check if merchant exists
    existing_merchant = db.query(Merchant).filter(Merchant.id == MERCHANT_ID).first()
    if not existing_merchant:
        merchant = Merchant(
            id=MERCHANT_ID,
            name=MERCHANT_NAME,
            email=MERCHANT_EMAIL,
            created_at=datetime.utcnow() - timedelta(days=30)
        )
        db.add(merchant)

        # Risk Policy
        policy = RiskPolicy(
            merchant_id=MERCHANT_ID,
            max_monetary_exposure=200000.0,  # ₹2 Lakhs
            max_transaction_count=500,
            max_retry_attempts=3,
            max_failure_rate_threshold=0.35,
            require_human_approval_above_exposure=100000.0,
            cooldown_period_minutes=20
        )
        db.add(policy)
        db.commit()

    # Check transaction count
    count = db.query(Transaction).count()
    if count >= num_transactions:
        print(f"Database already seeded with {count} transactions.")
        return

    print(f"Seeding database with {num_transactions} synthetic transactions...")
    sim = EventSimulator()
    now = datetime.utcnow()
    
    # 1. Historical normal transactions (Days -30 to -1, ~9,500 transactions)
    tx_list = []
    historical_count = num_transactions - 1000
    for i in range(historical_count):
        days_ago = random.uniform(1.0, 30.0)
        tx_time = now - timedelta(days=days_ago)
        tx_data = sim.generate_single_transaction(
            merchant_id=MERCHANT_ID,
            scenario="NORMAL",
            timestamp=tx_time
        )
        tx_list.append(Transaction(**tx_data))

    # 2. Recent transactions in last 24 hours (with simulated UPI Degradation incident, ~1,000 transactions)
    for i in range(1000):
        minutes_ago = random.uniform(0, 1440) # 24 hours
        tx_time = now - timedelta(minutes=minutes_ago)
        # Induce UPI degradation in the last 2 hours (120 mins)
        scenario = "UPI_DEGRADATION" if minutes_ago <= 120 else "NORMAL"
        tx_data = sim.generate_single_transaction(
            merchant_id=MERCHANT_ID,
            scenario=scenario,
            timestamp=tx_time
        )
        tx_list.append(Transaction(**tx_data))

    # Bulk insert in batches
    batch_size = 2000
    for i in range(0, len(tx_list), batch_size):
        db.bulk_save_objects(tx_list[i:i+batch_size])
        db.commit()

    print(f"Successfully seeded {len(tx_list)} transactions into database.")
