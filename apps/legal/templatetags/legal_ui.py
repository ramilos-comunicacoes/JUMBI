from django import template

register = template.Library()


@register.filter
def column_at(columns, index):
    """Keep mobile record labels aligned with the server-rendered table header."""
    try:
        return columns[int(index)]
    except (IndexError, TypeError, ValueError):
        return ""
