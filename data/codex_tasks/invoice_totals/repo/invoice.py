def calculate_invoice(items: list[dict], tax_rate: str = "0") -> dict[str, str]:
    subtotal = 0.0
    for item in items:
        subtotal += float(item["quantity"]) * float(item["unit_price"])
    tax = subtotal * float(tax_rate)
    return {"subtotal": str(round(subtotal, 2)), "tax": str(round(tax, 2)), "total": str(round(subtotal + tax, 2))}

