"""One decimal-based calculation for saved commercial records and documents."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


def number(value, label, *, positive=False):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{label} must be a valid number') from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f'{label} must be finite and {"positive" if positive else "non-negative"}')
    return result


def money(value):
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def calculate_document(items, total_amount=0, gst_rate=0, *, description='Training services', duration=0, day_rate=0):
    """Recompute every line; caller-supplied amount fields are never authoritative."""
    rows = []
    for index, item in enumerate(items or [], 1):
        if not isinstance(item, dict) or not str(item.get('description') or '').strip():
            raise ValueError(f'Line {index}: description is required')
        quantity = number(item.get('quantity', 1), f'Line {index} quantity', positive=True)
        rate = number(item.get('rate', 0), f'Line {index} rate')
        rows.append({**item, 'quantity': float(quantity), 'rate': float(rate),
                     'amount': float(money(quantity * rate))})
    if not rows:
        total = number(total_amount or 0, 'Total amount')
        if total > 0:
            # An agreed package price must not change through rounded daily rates.
            rows = [{'description': description, 'quantity': 1, 'rate': float(money(total)), 'amount': float(money(total))}]
        else:
            days = number(duration or 0, 'Duration')
            rate = number(day_rate or 0, 'Day rate')
            if days > 0 and rate > 0:
                rows = [{'description': description, 'quantity': float(days), 'rate': float(rate), 'amount': float(money(days * rate))}]
    subtotal = sum((Decimal(str(row['amount'])) for row in rows), Decimal(0))
    if subtotal <= 0:
        raise ValueError('At least one positive line item or agreed total is required')
    tax = number(gst_rate, 'Tax rate')
    if tax > 100:
        raise ValueError('Tax rate cannot exceed 100')
    tax_amount = money(subtotal * tax / 100)
    return {'items': rows, 'subtotal': float(subtotal), 'gst_rate': float(tax),
            'gst_amount': float(tax_amount), 'grand_total': float(subtotal + tax_amount)}
