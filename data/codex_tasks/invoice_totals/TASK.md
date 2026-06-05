Fix the implementation so all tests pass.

Requirements:
- Use `Decimal` for money math.
- `calculate_invoice` receives line items with `quantity`, `unit_price`, and optional `discount_percent`.
- Round money values to two decimal places using `ROUND_HALF_UP`.
- Return `subtotal`, `tax`, and `total` as strings.
- Reject negative quantities, prices, discounts, and tax rates with `ValueError`.
- Run `bash ./verify.sh` before finishing.

