from dataclasses import dataclass

@dataclass
class TaxResult:
    taxable_income: float
    income_tax: float
    employee_ni: float
    personal_allowance_used: float


def personal_allowance(adjusted_net_income: float) -> float:
    """
    Simplified UK personal allowance with taper.
    - Full PA to £100k
    - Tapers to 0 by £125,140
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
    Simplified rUK income tax model (England/Wales/NI).
    Uses adjusted net income = gross - pension_deduction (approx).
    Bands used (typical recent rUK values):
      - 20% basic: first £37,700 taxable
      - 40% higher: next up to £125,140 (with PA effects)
      - 45% additional above
    """
    adjusted = max(0.0, annual_gross - pension_deduction)
    pa = personal_allowance(adjusted)
    taxable = max(0.0, adjusted - pa)

    basic_band = 37_700.0

    tax = 0.0
    b = min(taxable, basic_band)
    tax += 0.20 * b
    remaining = taxable - b

    if remaining > 0:
        # This is a simplified way to handle higher band width.
        # It is accurate enough for "direction of travel" comparisons.
        higher_taxable_cap = max(0.0, 125_140.0 - pa - basic_band)
        h = min(remaining, higher_taxable_cap)
        tax += 0.40 * h
        remaining -= h

    if remaining > 0:
        tax += 0.45 * remaining

    return TaxResult(
        taxable_income=taxable,
        income_tax=tax,
        employee_ni=0.0,
        personal_allowance_used=pa,
    )


def employee_ni_annual(annual_gross: float) -> float:
    """
    Simplified employee Class 1 NI (annualised):
      - 8% between PT and UEL
      - 2% above UEL
    Uses typical recent thresholds:
      PT: £12,570
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
    tr.employee_ni = employee_ni_annual(max(0.0, annual_gross))
    return tr