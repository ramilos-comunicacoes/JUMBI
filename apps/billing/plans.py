from decimal import Decimal

PLANS = {
    "start": {"name": "Start", "price": Decimal("89.90"), "price_label": "89,90", "members": 3, "matters": 100, "versions": 200, "advanced": False},
    "max": {"name": "Max", "price": Decimal("199.90"), "price_label": "199,90", "members": 15, "matters": 1000, "versions": 2000, "advanced": True},
}
PLAN_CHOICES = [(key, f'{value["name"]} — R$ {value["price_label"]}/mês') for key, value in PLANS.items()]
