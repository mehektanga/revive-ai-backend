from abc import ABC, abstractmethod
from typing import Dict, Any

class PaymentProvider(ABC):
    @abstractmethod
    def retry_payment(self, transaction_id: str, amount: float, payment_method: str) -> Dict[str, Any]:
        """Attempt payment retry/recovery."""
        pass

    @abstractmethod
    def create_recovery_link(self, transaction_id: str, amount: float, customer_id: str) -> Dict[str, Any]:
        """Create recovery payment link."""
        pass

    @abstractmethod
    def is_sandbox(self) -> bool:
        """Returns True if operating in Sandbox/Mock mode."""
        pass
