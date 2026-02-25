from dataclasses import dataclass

@dataclass
class TaxResult:
    taxable_income: float
    income_tax: float
    employee_ni: float
    personal_allowance_used: float


def personal_allowance(adjusted_net_income: float) -> float:
    """
    UK Personal Allowance (rUK) with taper from £100k to £125,140.
    Source: GOV.UK guidance. (Calculator uses 2025/26 style values.)
    """
    pa = 12_570.0
    if adjusted_net_income <= 100_000:
        return pa
    if adjusted_net_income >= 125_140:
        return 0.0
    reduction = (adjusted_net_income - 100_000) / 2.0
    return max(0.0, pa - reduction)


def income_tax_ruk(annual_gross: float, pension_deduction: float = 0.0) -> TaxResult:
    """
    Rough rUK income tax model (England/Wales/NI):
    - Basic 20% up to £37,700 taxable
    - Higher 40% up to £125,140 taxable
    - Additional 45% above that
    Uses adjusted net income = gross - pension (approx).
    """
    adjusted = max(0.0, annual_gross - pension_deduction)
    pa = personal_allowance(adjusted)
    taxable = max(0.0, adjusted - pa)

    # taxable bands (rUK)
    basic_band = 37_700.0
    higher_limit = 125_140.0 - pa  # simplified; works acceptably for most cases

    tax = 0.0
    # basic
    b = min(taxable, basic_band)
    tax += 0.20 * b

    # higher
    remaining = taxable - b
    if remaining > 0:
        h_band = max(0.0, min(remaining, max(0.0, higher_limit - basic_band)))
        tax += 0.40 * h_band
        remaining -= h_band

    # additional
    if remaining > 0:
        tax += 0.45 * remaining

    return TaxResult(
        taxable_income=taxable,
        income_tax=tax,
        employee_ni=0.0,
        personal_allowance_used=pa
    )


def employee_ni_annual(annual_gross: float) -> float:
    """
    Employee Class 1 NI (simplified):
    - 8% between PT and UEL
    - 2% above UEL
    Uses annual equivalents of 2025/26-ish thresholds:
      PT: £12,570 (approx aligned with monthly £1,048)
      UEL: £50,270
    """
    pt = 12_570.0
    uel = 50_270.0

    if annual_gross <= pt:
        return 0.0

    main = min(annual_gross, uel) - pt
    above = max(0.0, annual_gross - uel)

    return 0.08 * main + 0.02 * above


def tax_and_ni_ruk(annual_gross: float, pension_deduction: float = 0.0) -> TaxResult:
    tr = income_tax_ruk(annual_gross, pension_deduction=pension_deduction)
    tr.employee_ni = employee_ni_annual(max(0.0, annual_gross))  # NI isn't reduced by pension in this simple model
    return tr