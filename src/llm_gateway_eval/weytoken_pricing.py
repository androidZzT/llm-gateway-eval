from __future__ import annotations

import csv
import html
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from .pricing import TokenPricing, official_pricing_for_model

DEFAULT_USD_CNY_RATE = 6.766895


@dataclass(frozen=True)
class WeyTokenPriceRow:
    model: str
    vendor: str | None
    group: str | None
    quota_type: int
    endpoint_types: list[str]
    input_per_million: float | None
    cached_input_per_million: float | None
    output_per_million: float | None
    fixed_price: float | None
    currency: str
    input_usd_per_million: float | None
    cached_input_usd_per_million: float | None
    output_usd_per_million: float | None
    fixed_usd_price: float | None
    usd_cny_rate: float | None
    official_input_per_million: float | None
    official_cached_input_per_million: float | None
    official_output_per_million: float | None
    official_currency: str | None
    official_input_cny_per_million: float | None
    official_cached_input_cny_per_million: float | None
    official_output_cny_per_million: float | None
    input_delta_percent: float | None
    output_delta_percent: float | None
    cache_delta_percent: float | None
    has_official_price: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class WeyTokenPricingError(ValueError):
    pass


def fetch_weytoken_pricing(base_url: str = "https://api.weytoken.com") -> dict[str, Any]:
    root = base_url.rstrip("/")
    with httpx.Client(timeout=20) as client:
        response = client.get(f"{root}/api/pricing")
        response.raise_for_status()
        payload = response.json()
    if not payload.get("success"):
        raise WeyTokenPricingError(payload.get("message") or "WeyToken pricing API returned success=false")
    return payload


def build_weytoken_price_rows(
    payload: dict[str, Any],
    group: str = "best",
    official_prices: dict[str, TokenPricing] | None = None,
    currency: str = "CNY",
    usd_cny_rate: float = DEFAULT_USD_CNY_RATE,
) -> list[WeyTokenPriceRow]:
    official_prices = official_prices or {}
    vendors = {
        int(vendor["id"]): vendor.get("name")
        for vendor in payload.get("vendors", [])
        if isinstance(vendor, dict) and vendor.get("id") is not None
    }
    group_ratio = {
        str(name): float(value)
        for name, value in (payload.get("group_ratio") or {}).items()
    }
    rows: list[WeyTokenPriceRow] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        selected = _select_group(item, group, group_ratio)
        if selected is None:
            continue
        selected_group, selected_ratio = selected
        official = official_prices.get(str(item.get("model_name"))) or official_pricing_for_model(str(item.get("model_name")))
        rows.append(_row_from_item(item, vendors, selected_group, selected_ratio, official, currency, usd_cny_rate))
    return sorted(rows, key=lambda row: (not row.has_official_price, row.vendor or "", row.model, row.group or ""))


def price_for_model(
    base_url: str,
    model: str,
    group: str = "best",
    currency: str = "USD",
    usd_cny_rate: float = DEFAULT_USD_CNY_RATE,
) -> TokenPricing | None:
    payload = fetch_weytoken_pricing(base_url)
    rows = build_weytoken_price_rows(payload, group=group, currency="CNY", usd_cny_rate=usd_cny_rate)
    for row in rows:
        if row.model == model and row.input_per_million is not None and row.output_per_million is not None:
            if currency.upper() == "USD":
                if row.input_usd_per_million is None or row.output_usd_per_million is None:
                    return None
                return TokenPricing(
                    input_per_million=row.input_usd_per_million,
                    cached_input_per_million=row.cached_input_usd_per_million,
                    output_per_million=row.output_usd_per_million,
                    currency="USD",
                )
            return TokenPricing(
                input_per_million=row.input_per_million,
                cached_input_per_million=row.cached_input_per_million,
                output_per_million=row.output_per_million,
                currency=currency,
            )
    return None


def load_official_price_file(path: str | Path | None) -> dict[str, TokenPricing]:
    if path is None:
        return {}
    source = Path(path)
    if source.suffix.lower() == ".json":
        return _load_official_json(source)
    return _load_official_csv(source)


def write_weytoken_pricing_outputs(
    rows: list[WeyTokenPriceRow],
    json_out: str | Path | None = None,
    csv_out: str | Path | None = None,
    markdown_out: str | Path | None = None,
    html_out: str | Path | None = None,
    missing_official_out: str | Path | None = None,
) -> list[Path]:
    written: list[Path] = []
    if json_out:
        path = Path(json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([row.to_dict() for row in rows], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    if csv_out:
        path = Path(csv_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(WeyTokenPriceRow.__dataclass_fields__))
            writer.writeheader()
            for row in rows:
                writer.writerow(row.to_dict())
        written.append(path)
    if markdown_out:
        path = Path(markdown_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_weytoken_pricing_markdown(rows), encoding="utf-8")
        written.append(path)
    if html_out:
        path = Path(html_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_weytoken_pricing_html(rows), encoding="utf-8")
        written.append(path)
    if missing_official_out:
        path = Path(missing_official_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "model",
                    "vendor",
                    "input_per_million",
                    "cached_input_per_million",
                    "output_per_million",
                    "currency",
                ],
            )
            writer.writeheader()
            for row in rows:
                if row.has_official_price or row.input_per_million is None or row.output_per_million is None:
                    continue
                writer.writerow(
                    {
                        "model": row.model,
                        "vendor": row.vendor or "",
                        "input_per_million": "",
                        "cached_input_per_million": "",
                        "output_per_million": "",
                        "currency": row.currency,
                    }
                )
        written.append(path)
    return written


def render_weytoken_pricing_markdown(rows: list[WeyTokenPriceRow]) -> str:
    matched = sum(1 for row in rows if row.has_official_price)
    lines = [
        "# WeyToken Pricing Comparison",
        "",
        f"- Models/groups: {len(rows)}",
        f"- Rows matched with official catalog: {matched}",
        f"- Rows missing official price: {len(rows) - matched}",
        "",
        "| Model | Vendor | Group | WeyToken Input | Official Input | Input Delta | WeyToken Output | Official Output | Output Delta |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| {model} | {vendor} | {group} | {wi} | {oi} | {idelta} | {wo} | {oo} | {odelta} |".format(
                model=row.model,
                vendor=row.vendor or "",
                group=row.group or "",
                wi=_weytoken_price_text(row.input_per_million, row.input_usd_per_million, row.currency),
                oi=_cny_money(row.official_input_cny_per_million),
                idelta=_pct(row.input_delta_percent),
                wo=_weytoken_price_text(row.output_per_million, row.output_usd_per_million, row.currency),
                oo=_cny_money(row.official_output_cny_per_million),
                odelta=_pct(row.output_delta_percent),
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- WeyToken token pricing is computed from its public `/api/pricing` payload using the same formula observed in the frontend: input = `model_ratio * 2 * group_ratio`, output = input * `completion_ratio`.",
            "- `group=best` chooses the lowest enabled group ratio for each model, matching the pricing page's all-groups view.",
            "- Official prices are matched by model name from the built-in catalog and optional `--official-prices` file; unmatched rows are kept for manual completion.",
            "- Use the generated missing-official CSV as an official price template, then rerun with `--official-prices` to compare every model.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_weytoken_pricing_html(rows: list[WeyTokenPriceRow], generated_at: str | None = None) -> str:
    matched = sum(1 for row in rows if row.has_official_price)
    input_statuses = [_comparison_label(row.input_per_million, row.official_input_cny_per_million) for row in rows]
    output_statuses = [_comparison_label(row.output_per_million, row.official_output_cny_per_million) for row in rows]
    expensive_count = sum(1 for _, class_name in [*input_statuses, *output_statuses] if class_name == "expensive")
    cheap_count = sum(1 for _, class_name in [*input_statuses, *output_statuses] if class_name == "cheap")
    coverage = 0 if not rows else round(matched / len(rows) * 100)
    generated = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    usd_cny_rate = _first_usd_cny_rate(rows)
    fx_note = "" if usd_cny_rate is None else f"；海外官方价按汇率 {usd_cny_rate:.6g} 折算为人民币"
    body_rows = "\n".join(_html_row(row) for row in rows)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>WeyToken 官方价格对比</title>
<style>
:root {{
  --ink:#172033; --muted:#657084; --line:#dfe5ee; --bg:#f6f8fb; --panel:#fff;
  --cheap:#087443; --expensive:#b42318; --same:#42526a; --missing:#7a869a;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif; color:var(--ink); background:var(--bg); }}
main {{ max-width:1240px; margin:0 auto; padding:36px 24px 56px; }}
header {{ display:flex; justify-content:space-between; gap:24px; align-items:flex-end; margin-bottom:22px; }}
h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0; }}
p {{ margin:0; color:var(--muted); line-height:1.6; }}
.meta {{ text-align:right; font-size:13px; color:var(--muted); }}
.cards {{ display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:12px; margin:24px 0; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:16px; }}
.card b {{ display:block; font-size:26px; margin-bottom:4px; }}
.card span {{ color:var(--muted); font-size:13px; }}
.note {{ background:#fff9e8; border:1px solid #f2d38b; border-radius:8px; padding:12px 14px; margin:18px 0 22px; color:#654200; }}
.table-wrap {{ overflow:auto; border:1px solid var(--line); border-radius:8px; background:var(--panel); }}
table {{ width:100%; border-collapse:collapse; min-width:1040px; }}
th,td {{ padding:11px 12px; border-bottom:1px solid #edf1f6; text-align:right; font-size:13px; white-space:nowrap; }}
th {{ position:sticky; top:0; background:#eef3f8; color:#42526a; font-weight:650; }}
th:first-child,td:first-child {{ text-align:left; min-width:280px; }}
td:first-child span {{ display:block; margin-top:3px; color:var(--muted); font-size:12px; }}
tr:last-child td {{ border-bottom:0; }}
tr.missing {{ background:#fafbfc; color:#697386; }}
.status {{ font-weight:700; }}
.cheap {{ color:var(--cheap); }}
.expensive {{ color:var(--expensive); }}
.same {{ color:var(--same); }}
.missing-text {{ color:var(--missing); font-weight:650; }}
.muted {{ color:var(--muted); }}
footer {{ margin-top:18px; color:var(--muted); font-size:13px; line-height:1.7; }}
@media (max-width:900px) {{ .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
@media (max-width:760px) {{ header {{ display:block; }} .meta {{ text-align:left; margin-top:12px; }} main {{ padding:24px 14px 44px; }} }}
</style>
</head>
<body>
<main>
<header>
  <div><h1>WeyToken 官方模型价格对比</h1><p>按 WeyToken 公开价格接口与官方价格目录对齐；报告统一使用人民币/百万 tokens{html.escape(fx_note)}。</p></div>
  <div class="meta">生成时间<br>{html.escape(generated)}</div>
</header>
<section class="cards">
  <div class="card"><b>{len(rows)}</b><span>WeyToken 价格行</span></div>
  <div class="card"><b>{matched}</b><span>已匹配官方价</span></div>
  <div class="card"><b>{len(rows) - matched}</b><span>待补官方价</span></div>
  <div class="card"><b>{expensive_count}</b><span>价格项更贵</span></div>
  <div class="card"><b>{cheap_count}</b><span>价格项更便宜</span></div>
</section>
<div class="note">说明：输入和输出分别判断；红色“贵”表示 WeyToken 高于官方，绿色“便宜”表示 WeyToken 低于官方，百分比为相对官方人民币价的变化幅度。覆盖率 {coverage}%。</div>
<div class="table-wrap"><table>
<thead><tr><th>模型</th><th>WeyToken 输入</th><th>官方输入</th><th>输入结论</th><th>WeyToken 输出</th><th>官方输出</th><th>输出结论</th><th>WeyToken 固定价</th><th>官方价</th></tr></thead>
<tbody>
{body_rows}
</tbody>
</table></div>
<footer>官方价格只采信一方厂商页面或已核实目录；未确认、下线、地区差异或非 token 计费模型保持待补。</footer>
</main>
</body>
</html>
"""


def is_weytoken_url(base_url: str) -> bool:
    host = urlparse(base_url).hostname or ""
    return host.endswith("weytoken.com")


def _row_from_item(
    item: dict[str, Any],
    vendors: dict[int, str | None],
    group_name: str | None,
    group_value: float,
    official: TokenPricing | None,
    currency: str,
    usd_cny_rate: float,
) -> WeyTokenPriceRow:
    quota_type = int(item.get("quota_type") or 0)
    input_price: float | None = None
    cached_price: float | None = None
    output_price: float | None = None
    fixed_price: float | None = None
    if quota_type == 0:
        model_ratio = float(item.get("model_ratio") or 0)
        completion_ratio = float(item.get("completion_ratio") or 1)
        input_price = round(model_ratio * 2 * group_value, 8)
        output_price = round(input_price * completion_ratio, 8)
        if item.get("cache_ratio") is not None:
            cached_price = round(input_price * float(item["cache_ratio"]), 8)
    else:
        fixed_price = round(float(item.get("model_price") or 0) * group_value, 8)

    input_usd_price = _to_usd(input_price, currency, usd_cny_rate)
    cached_usd_price = _to_usd(cached_price, currency, usd_cny_rate)
    output_usd_price = _to_usd(output_price, currency, usd_cny_rate)
    fixed_usd_price = _to_usd(fixed_price, currency, usd_cny_rate)
    official_currency = None if official is None else official.currency
    official_input_cny = _to_cny(None if official is None else official.input_per_million, official_currency, usd_cny_rate)
    official_cached_cny = _to_cny(
        None if official is None else official.cached_input_per_million,
        official_currency,
        usd_cny_rate,
    )
    official_output_cny = _to_cny(
        None if official is None else official.output_per_million,
        official_currency,
        usd_cny_rate,
    )

    return WeyTokenPriceRow(
        model=str(item.get("model_name") or ""),
        vendor=vendors.get(int(item["vendor_id"])) if item.get("vendor_id") is not None else None,
        group=group_name,
        quota_type=quota_type,
        endpoint_types=[str(value) for value in item.get("supported_endpoint_types") or []],
        input_per_million=input_price,
        cached_input_per_million=cached_price,
        output_per_million=output_price,
        fixed_price=fixed_price,
        currency=currency,
        input_usd_per_million=input_usd_price,
        cached_input_usd_per_million=cached_usd_price,
        output_usd_per_million=output_usd_price,
        fixed_usd_price=fixed_usd_price,
        usd_cny_rate=usd_cny_rate if currency.upper() == "CNY" else None,
        official_input_per_million=None if official is None else official.input_per_million,
        official_cached_input_per_million=None if official is None else official.cached_input_per_million,
        official_output_per_million=None if official is None else official.output_per_million,
        official_currency=official_currency,
        official_input_cny_per_million=official_input_cny,
        official_cached_input_cny_per_million=official_cached_cny,
        official_output_cny_per_million=official_output_cny,
        input_delta_percent=_delta_percent(input_price, official_input_cny),
        output_delta_percent=_delta_percent(output_price, official_output_cny),
        cache_delta_percent=_delta_percent(cached_price, official_cached_cny),
        has_official_price=official is not None,
    )


def _select_group(
    item: dict[str, Any],
    group: str,
    group_ratio: dict[str, float],
) -> tuple[str | None, float] | None:
    enabled_groups = [str(value) for value in item.get("enable_groups") or []]
    if group in {"best", "all"}:
        candidates = [(name, group_ratio[name]) for name in enabled_groups if name in group_ratio]
        if not candidates:
            return None, 1.0
        return min(candidates, key=lambda value: value[1])
    if group not in enabled_groups:
        return None
    return group, group_ratio.get(group, 1.0)


def _delta_percent(actual: float | None, official: float | None) -> float | None:
    if actual is None or official is None or official == 0:
        return None
    return round((actual / official - 1) * 100, 2)


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6g}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def _html_row(row: WeyTokenPriceRow) -> str:
    input_label, input_class = _comparison_label(row.input_per_million, row.official_input_cny_per_million)
    output_label, output_class = _comparison_label(row.output_per_million, row.official_output_cny_per_million)
    tr_class = "missing" if not row.has_official_price else ""
    official_status = "已匹配" if row.has_official_price else "待补"
    return """<tr class="{tr_class}">
  <td><strong>{model}</strong><span>{vendor} / {group}</span></td>
  <td>{weytoken_input}</td>
  <td>{official_input}</td>
  <td class="status {input_class}">{input_label}</td>
  <td>{weytoken_output}</td>
  <td>{official_output}</td>
  <td class="status {output_class}">{output_label}</td>
  <td>{fixed_price}</td>
  <td class="{official_class}">{official_status}</td>
</tr>""".format(
        tr_class=tr_class,
        model=html.escape(row.model),
        vendor=html.escape(row.vendor or "Unknown"),
        group=html.escape(row.group or ""),
        weytoken_input=html.escape(_weytoken_price_text(row.input_per_million, row.input_usd_per_million, row.currency)),
        official_input=html.escape(_cny_money(row.official_input_cny_per_million)),
        input_class=input_class,
        input_label=input_label,
        weytoken_output=html.escape(_weytoken_price_text(row.output_per_million, row.output_usd_per_million, row.currency)),
        official_output=html.escape(_cny_money(row.official_output_cny_per_million)),
        output_class=output_class,
        output_label=output_label,
        fixed_price=html.escape(_weytoken_price_text(row.fixed_price, row.fixed_usd_price, row.currency)),
        official_class="muted" if row.has_official_price else "missing-text",
        official_status=official_status,
    )


def _comparison_label(actual: float | None, official: float | None) -> tuple[str, str]:
    if actual is None or official is None:
        return "待补", "missing-text"
    if abs(actual - official) <= 1e-12:
        return "持平", "same"
    if actual > official:
        percent = _relative_difference_percent(actual, official)
        return "贵" if percent is None else f"贵 {percent:.2f}%", "expensive"
    percent = _relative_difference_percent(actual, official)
    return "便宜" if percent is None else f"便宜 {percent:.2f}%", "cheap"


def _relative_difference_percent(actual: float, official: float) -> float | None:
    if official == 0:
        return None
    return abs(actual / official - 1) * 100


def _money_with_unit(value: float | None) -> str:
    return "n/a" if value is None else f"${value:.6g}"


def _weytoken_price_text(value: float | None, usd_value: float | None, currency: str) -> str:
    if value is None:
        return "n/a"
    if currency.upper() == "CNY":
        return _cny_money(value)
    if currency.upper() == "USD":
        if usd_value is None:
            return "n/a"
        return _cny_money(usd_value)
    return f"{value:.6g} {currency}"


def _cny_money(value: float | None) -> str:
    return "n/a" if value is None else f"¥{value:.6g}"


def _to_usd(value: float | None, currency: str, usd_cny_rate: float) -> float | None:
    if value is None:
        return None
    if currency.upper() == "USD":
        return value
    if currency.upper() == "CNY":
        if usd_cny_rate <= 0:
            raise WeyTokenPricingError("usd_cny_rate must be greater than 0")
        return round(value / usd_cny_rate, 8)
    return None


def _to_cny(value: float | None, currency: str | None, usd_cny_rate: float) -> float | None:
    if value is None or currency is None:
        return None
    if currency.upper() == "CNY":
        return value
    if currency.upper() == "USD":
        return round(value * usd_cny_rate, 8)
    return None


def _first_usd_cny_rate(rows: list[WeyTokenPriceRow]) -> float | None:
    for row in rows:
        if row.usd_cny_rate is not None:
            return row.usd_cny_rate
    return None


def _load_official_csv(path: Path) -> dict[str, TokenPricing]:
    prices: dict[str, TokenPricing] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("input_per_million") or not row.get("output_per_million"):
                continue
            prices[row["model"]] = TokenPricing(
                input_per_million=float(row["input_per_million"]),
                cached_input_per_million=_optional_float(row.get("cached_input_per_million")),
                output_per_million=float(row["output_per_million"]),
                currency=row.get("currency") or "USD",
            )
    return prices


def _load_official_json(path: Path) -> dict[str, TokenPricing]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    prices: dict[str, TokenPricing] = {}
    for model, value in payload.items():
        prices[str(model)] = TokenPricing(
            input_per_million=float(value["input_per_million"]),
            cached_input_per_million=_optional_float(value.get("cached_input_per_million")),
            output_per_million=float(value["output_per_million"]),
            currency=value.get("currency") or "USD",
        )
    return prices


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)
