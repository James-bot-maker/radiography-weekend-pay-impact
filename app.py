import streamlit as st
import pandas as pd
import numpy as np
from tax_uk import tax_and_ni_ruk

st.set_page_config(page_title="Sunday Working Pay Impact", layout="wide")

# -----------------------
# Fixed assumptions
# -----------------------
CONTRACTED_HOURS_PER_WEEK = 37.5
WEEKS_PER_YEAR = 52

AFFECTED_FTE = 22
STAFF_REQUIRED_PER_SUNDAY = 5
SUNDAYS_PER_MONTH_AVG = 52 / 12  # 4.333...

NEW_SUNDAY_HOURS = 12.0
SUNDAY_UPLIFT = 0.60              # enhancement-only portion
DEFAULT_PENSION_RATE = 0.107

DEFAULT_BANK_SUNDAY_HOURS = 10.5

BANDS = {
    "Band 6": {
        "Entry": 20.44,
        "Mid": 21.57,
        "Top": 24.61,
        "bank_sunday_rate": 44.70,  # assumed hourly
    },
    "Band 7": {
        "Entry": 25.26,
        "Mid": 26.56,               # assumed correction
        "Top": 28.90,
        "bank_sunday_rate": 51.48,  # assumed hourly
    },
}

TOTAL_SUNDAY_SHIFTS_PER_MONTH = STAFF_REQUIRED_PER_SUNDAY * SUNDAYS_PER_MONTH_AVG
FAIR_SHARE_SUNDAYS_PER_MONTH = TOTAL_SUNDAY_SHIFTS_PER_MONTH / AFFECTED_FTE


# -----------------------
# Helpers
# -----------------------
def money(x: float) -> str:
    return f"£{x:,.2f}"


def base_annual_salary(hourly: float) -> float:
    return hourly * CONTRACTED_HOURS_PER_WEEK * WEEKS_PER_YEAR


def current_bank_monthly(bank_sundays_per_month: float, bank_hours: float, bank_rate: float) -> float:
    # Current bank Sundays are extra pay on top of base salary (non-pensionable assumed)
    return bank_sundays_per_month * bank_hours * bank_rate


def new_enhancement_monthly(new_sundays_per_month: float, base_hourly: float) -> float:
    # New system: Sundays are within 37.5h, so only enhancement portion is additional pay
    return new_sundays_per_month * NEW_SUNDAY_HOURS * base_hourly * SUNDAY_UPLIFT


def annual_leave_uplift_monthly(enhancement_monthly: float, annual_leave_weeks: float) -> float:
    # simple approximation based on averaged enhancement over year
    annual_enh = enhancement_monthly * 12
    weekly_avg = annual_enh / 52
    annual_leave_uplift = weekly_avg * annual_leave_weeks
    return annual_leave_uplift / 12


def compute_monthly_outcome(
    base_hourly: float,
    current_bank_sundays: float,
    bank_hours: float,
    bank_rate: float,
    new_sundays: float,
    pension_rate: float,
    include_leave_uplift: bool,
    annual_leave_weeks: float,
) -> dict:
    base_monthly = base_annual_salary(base_hourly) / 12

    current_bank_pay_m = current_bank_monthly(current_bank_sundays, bank_hours, bank_rate)

    new_enh_m = new_enhancement_monthly(new_sundays, base_hourly)
    leave_uplift_m = annual_leave_uplift_monthly(new_enh_m, annual_leave_weeks) if include_leave_uplift else 0.0

    current_gross_m = base_monthly + current_bank_pay_m
    new_gross_m = base_monthly + new_enh_m + leave_uplift_m

    # Incremental pension: enhancement (+ leave uplift) becomes pensionable; base already pensionable anyway.
    current_pension_m = 0.0
    new_pension_m = pension_rate * (new_enh_m + leave_uplift_m)

    # Annualise for simplified tax/NI
    current_gross_a = current_gross_m * 12
    new_gross_a = new_gross_m * 12
    current_pension_a = current_pension_m * 12
    new_pension_a = new_pension_m * 12

    current_tax = tax_and_ni_ruk(current_gross_a, pension_deduction=current_pension_a)
    new_tax = tax_and_ni_ruk(new_gross_a, pension_deduction=new_pension_a)

    current_takehome_a = current_gross_a - current_pension_a - current_tax.income_tax - current_tax.employee_ni
    new_takehome_a = new_gross_a - new_pension_a - new_tax.income_tax - new_tax.employee_ni

    return {
        "base_monthly": base_monthly,
        "current_bank_pay_m": current_bank_pay_m,
        "new_enh_m": new_enh_m,
        "leave_uplift_m": leave_uplift_m,
        "current_gross_m": current_gross_m,
        "new_gross_m": new_gross_m,
        "current_pension_m": current_pension_m,
        "new_pension_m": new_pension_m,
        "current_takehome_m": current_takehome_a / 12,
        "new_takehome_m": new_takehome_a / 12,
    }


# -----------------------
# FAST simulation (vectorised multinomial) + cache
# -----------------------
@st.cache_data(show_spinner=False)
def simulate_sundays_fast(
    n_staff: int,
    staff_required_per_sunday: int,
    opt_out_count: int,
    keen_count: int,
    keen_weight: float,
    n_sims: int,
    seed: int,
    person_type: str,
) -> np.ndarray:
    """
    Each month we allocate total_shifts (≈22) across staff using weighted probabilities.
    We repeat for 12 months and average Sundays/month for a representative person.
    """
    rng = np.random.default_rng(seed)
    total_shifts = int(np.round(staff_required_per_sunday * (52 / 12)))  # ~22
    months = 12

    opt_out_count = int(np.clip(opt_out_count, 0, n_staff))
    remaining = n_staff - opt_out_count
    keen_count = int(np.clip(keen_count, 0, remaining))

    # weights
    w = np.zeros(n_staff, dtype=float)
    if keen_count > 0:
        w[opt_out_count:opt_out_count + keen_count] = keen_weight
    if remaining - keen_count > 0:
        w[opt_out_count + keen_count:] = 1.0

    if w.sum() == 0:
        return np.zeros(n_sims, dtype=float)

    p = w / w.sum()

    # representative target
    if person_type == "Opt-out":
        target = 0 if opt_out_count > 0 else (opt_out_count + keen_count if remaining - keen_count > 0 else opt_out_count)
    elif person_type == "Keen":
        target = opt_out_count if keen_count > 0 else (opt_out_count + keen_count if remaining - keen_count > 0 else 0)
    else:  # Average
        if remaining - keen_count > 0:
            target = opt_out_count + keen_count
        elif keen_count > 0:
            target = opt_out_count
        else:
            target = 0

    draws = rng.multinomial(total_shifts, p, size=(n_sims, months))  # (n_sims, months, n_staff)
    return draws[:, :, target].mean(axis=1)


# -----------------------
# UI
# -----------------------
st.title("Sunday Working Pay Impact (simple, individual-facing)")
st.caption(
    "Illustrative tool. Uses simplified annualised UK tax/NI. "
    "Does not include tax codes, Scottish tax, student loans, salary sacrifice, etc."
)

with st.sidebar:
    st.header("Pay point")
    band = st.selectbox("Band", list(BANDS.keys()))
    point = st.selectbox("Pay point", ["Entry", "Mid", "Top"])
    base_hourly = float(BANDS[band][point])
    bank_rate = float(BANDS[band]["bank_sunday_rate"])

    st.divider()
    st.header("Current system (monthly)")
    current_bank_sundays = st.slider("Bank Sundays per month (extra work)", 0.0, 6.0, 1.0, 0.25)
    bank_hours = st.slider("Avg hours per bank Sunday", 6.0, 12.0, DEFAULT_BANK_SUNDAY_HOURS, 0.25)

    st.divider()
    st.header("New system (monthly)")
    default_new = float(np.round(FAIR_SHARE_SUNDAYS_PER_MONTH, 2))
    new_sundays = st.slider("Contracted Sundays per month (within 37.5h)", 0.0, 6.0, default_new, 0.25)

    st.divider()
    st.header("Pension + leave")
    pension_rate = st.slider("Pension rate (assumed)", 0.0, 0.20, DEFAULT_PENSION_RATE, 0.001)
    include_leave_uplift = st.checkbox("Include annual leave uplift approximation", value=True)
    annual_leave_weeks = st.slider("Annual leave weeks/year (assumed)", 4.0, 8.0, 6.5, 0.5)

    st.divider()
    st.header("Simulation")
    sim_on = st.toggle("Run simulation (swap market)", value=False)
    run_sim = False
    if sim_on:
        person_type = st.selectbox("I am…", ["Average", "Keen", "Opt-out"])
        opt_out_count = st.slider("How many staff opt out?", 0, AFFECTED_FTE, 4)
        keen_count = st.slider("How many staff are keen for extras?", 0, AFFECTED_FTE, 6)
        keen_weight = st.slider("Keen likelihood multiplier", 1.0, 5.0, 2.0, 0.1)
        n_sims = st.slider("Simulation runs (speed vs smoothness)", 500, 10000, 2000, 500)
        seed = st.number_input("Random seed (repeatability)", value=42, step=1)
        run_sim = st.button("Run simulation")


# -----------------------
# Manual comparison
# -----------------------
res = compute_monthly_outcome(
    base_hourly=base_hourly,
    current_bank_sundays=current_bank_sundays,
    bank_hours=bank_hours,
    bank_rate=bank_rate,
    new_sundays=new_sundays,
    pension_rate=pension_rate,
    include_leave_uplift=include_leave_uplift,
    annual_leave_weeks=annual_leave_weeks,
)

df = pd.DataFrame(
    [
        ["Base pay (37.5h)", res["base_monthly"], res["base_monthly"], 0.0],
        ["Current: bank Sunday pay", res["current_bank_pay_m"], 0.0, -res["current_bank_pay_m"]],
        ["New: Sunday enhancement (extra 60%)", 0.0, res["new_enh_m"], res["new_enh_m"]],
        ["New: annual leave uplift (approx.)", 0.0, res["leave_uplift_m"], res["leave_uplift_m"]],
        ["Gross total", res["current_gross_m"], res["new_gross_m"], res["new_gross_m"] - res["current_gross_m"]],
        ["Incremental pension deduction", res["current_pension_m"], res["new_pension_m"], res["new_pension_m"]],
        ["Take-home (after tax/NI/pension)", res["current_takehome_m"], res["new_takehome_m"], res["new_takehome_m"] - res["current_takehome_m"]],
    ],
    columns=["Line", "Current (monthly)", "New (monthly)", "Change"],
)

st.subheader("Manual comparison (monthly)")
st.dataframe(
    df.style.format({"Current (monthly)": money, "New (monthly)": money, "Change": money}),
    use_container_width=True,
    hide_index=True,
)

st.write(f"Fair-share default Sundays/month (22 staff, 5 required): **{FAIR_SHARE_SUNDAYS_PER_MONTH:.2f}**")

st.divider()

# -----------------------
# Simulation section
# -----------------------
if sim_on and run_sim:
    with st.spinner("Running simulation…"):
        sims = simulate_sundays_fast(
            n_staff=AFFECTED_FTE,
            staff_required_per_sunday=STAFF_REQUIRED_PER_SUNDAY,
            opt_out_count=opt_out_count,
            keen_count=keen_count,
            keen_weight=keen_weight,
            n_sims=int(n_sims),
            seed=int(seed),
            person_type=person_type,
        )

    p10, p50, p90 = np.percentile(sims, [10, 50, 90])

    st.subheader("Simulation results (likely Sundays/month for someone like you)")
    st.write(
        f"- **10th percentile:** {p10:.2f}\n"
        f"- **Median:** {p50:.2f}\n"
        f"- **90th percentile:** {p90:.2f}"
    )

    # Histogram without Streamlit/Pandas index weirdness
    bins = np.arange(-0.25, 6.25, 0.25)
    counts, edges = np.histogram(sims, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    chart_df = pd.DataFrame({"Sundays/month": centers, "Count": counts})
    st.bar_chart(chart_df.set_index("Sundays/month"))

    st.subheader("What that could mean for take-home (range)")
    rows = []
    for label, s in [("P10", p10), ("Median", p50), ("P90", p90)]:
        r = compute_monthly_outcome(
            base_hourly=base_hourly,
            current_bank_sundays=current_bank_sundays,
            bank_hours=bank_hours,
            bank_rate=bank_rate,
            new_sundays=float(s),
            pension_rate=pension_rate,
            include_leave_uplift=include_leave_uplift,
            annual_leave_weeks=annual_leave_weeks,
        )
        rows.append(
            {
                "Scenario": label,
                "Contracted Sundays/month": float(s),
                "New take-home (monthly)": r["new_takehome_m"],
                "Change vs current take-home": r["new_takehome_m"] - res["current_takehome_m"],
            }
        )

    out_df = pd.DataFrame(rows)
    st.dataframe(
        out_df.style.format(
            {
                "Contracted Sundays/month": "{:.2f}",
                "New take-home (monthly)": money,
                "Change vs current take-home": money,
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("Caveats")
st.markdown(
    """
- Illustrative only. Tax/NI are simplified and annualised.
- Not included: Scottish tax, student loans, salary sacrifice, benefits, multiple jobs, tax codes, childcare, etc.
- Annual leave uplift is an approximation based on averaged enhancements.
- Sickness pay uplift may exist under contractual enhancements but is not modelled.
"""
)