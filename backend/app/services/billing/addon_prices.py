"""Per-item add-on pricing (services/billing/addon_orders.py). Separate from plans.py:
add-on pricing is per item, not per plan, and future kinds (ai_enhance, print) may price
by size or count rather than flatly — kept here until that shape is known.

Prices are gross (incl. VAT); EXAMPLE until the owner sets real ones (ADDON_EXAMPLE_PRICES).
"""

from app.models import AddonKind
from app.services.billing.plans import CURRENCY, VAT_RATE  # noqa: F401 - re-exported for callers

ADDON_EXAMPLE_PRICES = True

ADDON_PRICES: dict[AddonKind, int] = {
    AddonKind.human_edit: 999,  # per photo, gross cents
}


def addon_price_cents(kind: AddonKind) -> int:
    return ADDON_PRICES[kind]
