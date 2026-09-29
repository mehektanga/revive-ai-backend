import os
import random
import uuid
from typing import Dict, Any
from app.providers.base import PaymentProvider

class RazorpayTestProvider(PaymentProvider):
    def __init__(self):
        self.key_id = os.getenv("RAZORPAY_KEY_ID", "")
        self.key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")

    def is_sandbox(self) -> bool:
        return False

    def retry_payment(self, transaction_id: str, amount: float, payment_method: str) -> Dict[str, Any]:
        # If active keys exist, call Razorpay SDK
        if self.key_id and self.key_secret:
            try:
                import razorpay
                client = razorpay.Client(auth=(self.key_id, self.key_secret))
                # Razorpay test mode payment order creation / retry
                order = client.order.create({
                    "amount": int(amount * 100),
                    "currency": "INR",
                    "receipt": f"rcpt_{transaction_id[:10]}",
                    "notes": {"retry_for": transaction_id}
                })
                return {
                    "success": True,
                    "provider": "RAZORPAY_TEST_MODE",
                    "order_id": order.get("id"),
                    "amount_recovered": amount,
                    "is_mock": False
                }
            except Exception as e:
                return {
                    "success": False,
                    "provider": "RAZORPAY_TEST_MODE",
                    "error": str(e),
                    "amount_recovered": 0.0,
                    "is_mock": False
                }
        
        # Fallback to sandbox simulation if key missing
        return MockPaymentProvider().retry_payment(transaction_id, amount, payment_method)

    def create_recovery_link(self, transaction_id: str, amount: float, customer_id: str) -> Dict[str, Any]:
        return MockPaymentProvider().create_recovery_link(transaction_id, amount, customer_id)


class MockPaymentProvider(PaymentProvider):
    def is_sandbox(self) -> bool:
        return True

    def retry_payment(self, transaction_id: str, amount: float, payment_method: str) -> Dict[str, Any]:
        # Realistic recovery rate simulation for sandbox retries (~70% success in sandbox demo)
        success = random.random() < 0.70
        return {
            "success": success,
            "provider": "SANDBOX / SIMULATED",
            "reference_id": f"sandbox_{uuid.uuid4().hex[:10]}",
            "amount_recovered": amount if success else 0.0,
            "error_message": None if success else "SANDBOX_SIMULATED_REJECTION",
            "is_mock": True
        }

    def create_recovery_link(self, transaction_id: str, amount: float, customer_id: str) -> Dict[str, Any]:
        link_id = f"plink_{uuid.uuid4().hex[:12]}"
        return {
            "success": True,
            "provider": "SANDBOX / SIMULATED",
            "payment_link_id": link_id,
            "short_url": f"https://rzp.sandbox.test/{link_id}",
            "amount": amount,
            "is_mock": True
        }
