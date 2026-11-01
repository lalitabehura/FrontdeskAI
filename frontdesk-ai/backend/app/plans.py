"""Subscription plans and their limits. Edit here to change pricing/limits."""
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_monthly_usd: int
    conversations_per_month: int
    max_members: int
    features: tuple[str, ...]

    @property
    def stripe_price_id(self) -> str | None:
        s = get_settings()
        return {"starter": s.stripe_price_starter, "growth": s.stripe_price_growth,
                "pro": s.stripe_price_pro}.get(self.key)


PLANS: dict[str, Plan] = {
    "starter": Plan("starter", "Starter", 29, 300, 2,
                    ("Website chat assistant", "Lead capture", "Online booking", "Email reminders")),
    "growth": Plan("growth", "Growth", 79, 1500, 5,
                   ("Everything in Starter", "Birthday & anniversary wishes", "Team inbox", "CSV export")),
    "pro": Plan("pro", "Pro", 199, 6000, 15,
                ("Everything in Growth", "Priority support", "Higher limits")),
}
TRIAL_PLAN = "growth"  # trials get Growth limits

ACTIVE_STATUSES = {"trialing", "active", "past_due"}  # past_due keeps working during Stripe's retry window


def plan_for(key: str | None) -> Plan:
    return PLANS.get(key or TRIAL_PLAN, PLANS[TRIAL_PLAN])
