from decimal import Decimal

PLANS = {
    "start": {
        "name": "Start", "price": Decimal("299.90"), "price_label": "299,90",
        "members": 5, "matters": 300, "versions": 1000, "advanced": False,
    },
    "max": {
        "name": "Max", "price": Decimal("599.90"), "price_label": "599,90",
        "members": 20, "matters": 2000, "versions": 5000, "advanced": True,
    },
}
PLAN_CHOICES = [(key, f'{value["name"]} — R$ {value["price_label"]}/mês') for key, value in PLANS.items()]
