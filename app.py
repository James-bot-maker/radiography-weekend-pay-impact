import streamlit as st
import pandas as pd
from tax_uk import tax_and_ni_ruk

st.set_page_config(page_title="Weekend Working Pay Impact", layout="wide")

# ----------------------------
# Constants you provided
# ----------------------------
HOURS_PER_MONTH_WEEKS = 4.3  # user requested assumption

BANDS = {
    "Band 6": {
        "Entry": 20.44,
        "Mid": 21.57,
        "Top": 24.61,
        "bank_sun_rate": 44.70,  # assumed hourly bank rate
    },
    "Band 7": {
        "Entry": 25.26,
        "Mid": 26.56,  # you wrote "£26.56.70" - assumed typo for £26.56
        "Top": 28.90,
        "bank_sun_rate": 51.48,  # assumed hourly bank rate
    },
}

SUNDAY_ENHANCEMENT = 0.60  # 60% uplift => 1.6x base
NEW_SUN_HOURS = 12.0

DEFAULT_BANK_HOURS = 10.5  # slider default

# Sunday staffing / fairness assumptions
STAFF_REQUIRED_PER_SUNDAY = 5
AFFECTED_FTE = 22
OPT_OUT_ESTIMATE = 4  # "there may only be 4 who would wish to not work any at all"

SUNS_PER_MONTH = 52 / 12  # 4.333...
TOTAL_SUNDAY_SHIFTS_PER_MONTH = STAFF_REQUIRED_PER_SUNDAY * SUNS_PER_MONTH
FAIR_SHARE_SUNS_PER_MONTH = TOTAL_SUNDAY_SHIFTS_PER_MONTH / AFFECTED_FTE

# if 4 opt out, remaining share:
REMAINING = max(1, AFFECTED_FTE - OPT_OUT_ESTIMATE)
FAIR_SHARE_IF_OPTOUT = TOTAL_SUNDAY_SHIFTS_PER_MONTH / REMAINING
EXTRA_POOL_PER_MONTH = FAIR_SHARE_SUNS_PER_MONTH * OPT_OUT_ESTIMATE  # shifts/month to be redistributed

# Hard cap: you can't work more Sundays than exist in a month on average (unless double-covering same day, ignored)
MAX_POSSIBLE_SUNS_PER_MONTH = SUNS_PER_MONTH

# ----------------------------
# Helpers
# ----------------------------
def money(x: float) -> str:
    return f"£{x:,.2f}"

def calc_base_annual(hourly: float, contracted_hours_per_week: float) -> float:
    return hourly * contracted_hours_per_week * 52

def calc_current_monthly(bank_sundays: float, bank_hours: float, bank_rate: float) -> float:
    return bank_sundays * bank_hours * bank_rate

def calc_new_monthly(new_sundays: float, base_hourly: float) -> float:
    return new_sundays * NEW_SUN_HOURS * base_hourly * (1.0 + SUNDAY_ENHANCEMENT)

def calc_annual_leave_uplift_monthly(new_sundays_per_month: float, base_hourly: float, annual_leave_weeks: float = 6.5) -> float:
    """
    Rough approximation:
    - weekly enhancement value averaged over year
    - paid again during annual leave weeks based on 13-week average concept (simplified)
    """
    # enhancement portion per Sunday (the extra above base):
    enhancement_per_sunday = NEW_SUN_HOURS * base_hourly * SUNDAY_ENHANCEMENT
    sundays_per_year = new_sundays_per_month * 12
    annual_enhancement_total = sundays_per_year * enhancement_per_sunday

    weekly_avg_enh = annual_enhancement_total / 52
    annual_leave_uplift = weekly_avg_enh * annual_leave_weeks
    return annual_leave_uplift / 12

# ----------------------------
# UI
# ----------------------------
st.title("Weekend Working Pay Impact (Illustrative Calculator)")
st.caption(
    "This tool is **illustrative only**. It uses simplified tax/NI assumptions and cannot reflect individual circumstances "
    "(e.g., student loans, salary sacrifice, benefits, multiple jobs, Scottish tax, tax codes, childcare, etc.). "
    "Please do your own research."
)

with st.sidebar:
    st.header("Your details")

    band = st.selectbox("Band", list(BANDS.keys()))
    point = st.selectbox("Pay point", list(BANDS[band].keys())[:3])  # Entry/Mid/Top
    base_hourly = BANDS[band][point]
    bank_rate = BANDS[band]["bank_sun_rate"]

    st.divider()
    contracted_hours_per_week = st.number_input(
        "Contracted hours per week (for base salary estimate)",
        min_value=1.0, max_value=60.0, value=37.5, step=0.5
    )

    st.divider()
    st.subheader("Current pattern (monthly)")
    current_saturdays = st.slider("Saturdays worked (count, per month)", 0.0, 6.0, 4.0, 0.5)
    current_bank_sundays = st.slider("Bank Sundays worked (count, per month)", 0.0, 6.0, 1.0, 0.25)
    bank_hours = st.slider("Average hours claimed per bank Sunday", 6.0, 12.0, DEFAULT_BANK_HOURS, 0.25)

    st.divider()
    st.subheader("New pattern (monthly)")
    default_new_sundays = float(round(FAIR_SHARE_SUNS_PER_MONTH, 2))
    new_sundays = st.slider(
        "Expected Sundays worked under the new system (count, per month)",
        0.0, 6.0, default_new_sundays, 0.25
    )

    st.divider()
    st.subheader("Pension + leave assumptions")
    pension_rate = st.slider("NHS pension contribution rate (assumed)", 0.0, 0.2, 0.107, 0.001)
    include_annual_leave_uplift = st.checkbox("Include annual leave uplift approximation (new system only)", value=True)
    annual_leave_weeks = st.slider("Annual leave weeks per year (assumed)", 4.0, 8.0, 6.5, 0.5)

# ----------------------------
# Calculations
# ----------------------------
base_annual = calc_base_annual(base_hourly, contracted_hours_per_week)
base_monthly = base_annual / 12

current_monthly_weekend = calc_current_monthly(current_bank_sundays, bank_hours, bank_rate)

new_monthly_weekend = calc_new_monthly(new_sundays, base_hourly)

leave_uplift_monthly = 0.0
if include_annual_leave_uplift:
    leave_uplift_monthly = calc_annual_leave_uplift_monthly(new_sundays, base_hourly, annual_leave_weeks)

# Pension:
# - current bank Sundays assumed NON-pensionable
# - new Sunday earnings assumed pensionable
new_pension_monthly = pension_rate * (new_monthly_weekend + (leave_uplift_monthly if include_annual_leave_uplift else 0.0))
current_pension_monthly = 0.0

# Gross totals (base + weekend + optional leave uplift)
current_gross_monthly = base_monthly + current_monthly_weekend
new_gross_monthly = base_monthly + new_monthly_weekend + leave_uplift_monthly

# Convert to annual for tax model
current_gross_annual = current_gross_monthly * 12
new_gross_annual = new_gross_monthly * 12

current_pension_annual = current_pension_monthly * 12
new_pension_annual = new_pension_monthly * 12

current_tax = tax_and_ni_ruk(current_gross_annual, pension_deduction=current_pension_annual)
new_tax = tax_and_ni_ruk(new_gross_annual, pension_deduction=new_pension_annual)

current_takehome_annual = current_gross_annual - current_pension_annual - current_tax.income_tax - current_tax.employee_ni
new_takehome_annual = new_gross_annual - new_pension_annual - new_tax.income_tax - new_tax.employee_ni

# monthly view
current_takehome_monthly = current_takehome_annual / 12
new_takehome_monthly = new_takehome_annual / 12

delta_gross_monthly = new_gross_monthly - current_gross_monthly
delta_takehome_monthly = new_takehome_monthly - current_takehome_monthly
delta_pension_monthly = new_pension_monthly - current_pension_monthly

# ----------------------------
# Layout / Outputs
# ----------------------------
colA, colB = st.columns([1.15, 0.85], gap="large")

with colA:
    st.subheader("Summary (monthly)")

    summary = pd.DataFrame([
        ["Base pay (estimated)", base_monthly, base_monthly, 0.0],
        ["Weekend pay (Sundays)", current_monthly_weekend, new_monthly_weekend, new_monthly_weekend - current_monthly_weekend],
        ["Annual leave uplift (approx.)", 0.0, leave_uplift_monthly, leave_uplift_monthly],
        ["Gross total", current_gross_monthly, new_gross_monthly, delta_gross_monthly],
        ["Pension deduction (assumed)", current_pension_monthly, new_pension_monthly, delta_pension_monthly],
        ["Take-home (after tax/NI/pension)", current_takehome_monthly, new_takehome_monthly, delta_takehome_monthly],
    ], columns=["Line", "Current (monthly)", "New (monthly)", "Change"])

    st.dataframe(
        summary.style.format({
            "Current (monthly)": money,
            "New (monthly)": money,
            "Change": money,
        }),
        use_container_width=True,
        hide_index=True
    )

    st.info(
        "Note: the **take-home** calculation uses an annualised simplified UK model for income tax and employee NI "
        "(not a full PAYE calculation). Results are best used for **direction of travel**, not precision."
    )

with colB:
    st.subheader("Your inputs at a glance")
    st.write(
        f"- **{band} / {point}** base hourly: **{money(base_hourly)}**\n"
        f"- Current bank Sunday rate assumed hourly: **{money(bank_rate)}**\n"
        f"- Current bank Sundays/month: **{current_bank_sundays}** at **{bank_hours}h**\n"
        f"- New Sundays/month: **{new_sundays}** at **{NEW_SUN_HOURS}h** with **60%** enhancement\n"
        f"- Pension rate assumed: **{pension_rate*100:.1f}%**"
    )

    st.subheader("Fair share defaults (for context)")
    st.write(
        f"- Sundays per month (average): **{SUNS_PER_MONTH:.2f}**\n"
        f"- Total Sunday shifts/month (5 staff needed): **{TOTAL_SUNDAY_SHIFTS_PER_MONTH:.2f}**\n"
        f"- Fair share per person (22 FTE): **{FAIR_SHARE_SUNS_PER_MONTH:.2f} Sundays/month** (default)\n"
        f"- If ~4 opt out entirely, remaining 18 share: **{FAIR_SHARE_IF_OPTOUT:.2f} Sundays/month** each\n"
    )

    # "picked up" limitation
    max_if_one_person_picks_all_extras = min(
        MAX_POSSIBLE_SUNS_PER_MONTH,
        FAIR_SHARE_SUNS_PER_MONTH + EXTRA_POOL_PER_MONTH
    )

    st.subheader("Picked-up shifts: rough bounds")
    st.write(
        f"- Extra pool created if ~4 people do **0**: about **{EXTRA_POOL_PER_MONTH:.2f} extra Sundays/month** to redistribute.\n"
        f"- A single person cannot realistically exceed about **{MAX_POSSIBLE_SUNS_PER_MONTH:.2f} Sundays/month** (there aren’t more Sundays).\n"
        f"- So an upper bound for one keen person is roughly **{max_if_one_person_picks_all_extras:.2f} Sundays/month**."
    )

st.divider()
st.subheader("Detailed annual breakdown (for transparency)")

detail = pd.DataFrame([
    ["Current gross (annual)", current_gross_annual],
    ["Current income tax (annual)", current_tax.income_tax],
    ["Current employee NI (annual)", current_tax.employee_ni],
    ["Current pension (annual)", current_pension_annual],
    ["Current take-home (annual)", current_takehome_annual],
    ["New gross (annual)", new_gross_annual],
    ["New income tax (annual)", new_tax.income_tax],
    ["New employee NI (annual)", new_tax.employee_ni],
    ["New pension (annual)", new_pension_annual],
    ["New take-home (annual)", new_takehome_annual],
], columns=["Item", "Amount"])

st.dataframe(detail.style.format({"Amount": money}), use_container_width=True, hide_index=True)

st.divider()
st.subheader("Important caveats / things not included (but worth mentioning)")
st.markdown(
    """
- **Sickness pay uplift**: if Sunday enhancements become contractual/pensionable, some elements of paid leave/sickness may increase.
- **Individual tax**: this tool does not include Scottish tax bands, tax codes, student loans, childcare, multiple employments, etc.
- **Outer London weighting**: excluded as requested; confirm locally how weekend enhancements interact with weighting.
- **Saturday enhancements**: not modelled here (your brief focused on Sunday changes). Add if needed.
"""
)