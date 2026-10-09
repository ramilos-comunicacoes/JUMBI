"""Stable, validated practice-area codes shared by platform and legal screens."""
from django.core.exceptions import ValidationError


PRACTICE_AREAS = (
    ("civil", "Direito Civil"), ("familia", "Família e Sucessões"),
    ("trabalhista", "Direito Trabalhista"), ("previdenciario", "Direito Previdenciário"),
    ("consumidor", "Direito do Consumidor"), ("criminal", "Direito Criminal"),
    ("tributario", "Direito Tributário"), ("empresarial", "Direito Empresarial"),
    ("contratual", "Direito Contratual"), ("imobiliario", "Direito Imobiliário"),
    ("administrativo", "Direito Administrativo"), ("constitucional", "Direito Constitucional"),
    ("ambiental", "Direito Ambiental"), ("digital", "Direito Digital e Proteção de Dados"),
    ("saude", "Direito da Saúde"), ("bancario", "Direito Bancário"),
    ("eleitoral", "Direito Eleitoral"), ("agrario", "Direito Agrário"),
    ("internacional", "Direito Internacional"), ("propriedade-intelectual", "Propriedade Intelectual"),
    ("transito", "Direito de Trânsito"), ("militar", "Direito Militar"),
    ("desportivo", "Direito Desportivo"), ("educacional", "Direito Educacional"),
    ("outros", "Outras áreas jurídicas"),
)
PRACTICE_AREA_LABELS = dict(PRACTICE_AREAS)


def validate_practice_areas(value):
    if not isinstance(value, list) or any(not isinstance(code, str) or code not in PRACTICE_AREA_LABELS for code in value):
        raise ValidationError("Escolha áreas jurídicas válidas do catálogo.")
    if len(value) != len(set(value)):
        raise ValidationError("Uma área jurídica não pode aparecer duas vezes.")


def practice_area_choices(organization):
    selected = getattr(organization, "practice_areas", []) or []
    return [(code, label) for code, label in PRACTICE_AREAS if code in selected]


def practice_area_values(code):
    """Accept both the new code and the corresponding historical label."""
    return [code, PRACTICE_AREA_LABELS.get(code, code)]
