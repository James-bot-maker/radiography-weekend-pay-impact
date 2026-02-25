import streamlit as st
import pandas as pd
import numpy as np
from tax_uk import tax_and_ni_ruk

st.set_page_config(page_title="Weekend Working Pay Impact", layout="wide")

# =========================
# Inputs / constants
# =========================
CONTRACTED_HOURS_PER_WEEK = 37.5  # fixed per your instruction
WEEKS_PER_YEAR = 52
PAY_PERIODS_PER_YEAR = 12

# Month approximation (you requested 4.3 weeks/month for user-facing framing)
WEEKS_PER_MONTH_UI = 4.3
SUNDAYS_PER_MONTH_AVG = 52 / 12  # used for fair-share maths (4.333...)

# Staffing assumptions
AFFECTED_FTE = 22
STAFF_REQUIRED_PER_SUNDAY = 5

# Enhancements / hours
SUNDAY_UPLIFT = 0.60  # 60% enhancement => 1.6x base
NEW_SUNDAY_HOURS = 12.0
DEFAULT_BANK_SUNDAY_HOURS = 10.5

# Pension
DEFAULT_PENSION_RATE = 0.107  # your default

# Pay rates (April 2026 estimates provided)
BANDS = {
    "Band 6": {
        "Entry": 20.44,
        "Mid": 21.57,
        "Top": 24.61,
        "bank_sunday_rate": 44.70,  # assumed hourly bank rate
    },
    "Band 7": {
        "Entry": 25.26,
        "Mid": 26.56,  # assumed correction of "£26.56.70"
        "Top": 28.90,
        "bank_sunday_rate": 51.48,  # assumed hourly bank rate
    },
}

# Derived
TOTAL_SUNDAY_SHIFTS_PER_MONTH = STAFF_REQUIRED_PER_SUNDAY * SUNDAYS_PER_MONTH_AVG
FAIR_SHARE_SUNDAYS_PER_MONTH = TOTAL_SUNDAY_SHIFTS_PER_MONTH / AFFECTED_FTE  # default new Sundays/month


# =========================
# Helpers
# =========================
def money(x: float) -> str:
    return f"£{x:,.2f}"

def calc_base_annual(hourly: float) -> float:
    return hourly * CONTRACTED_HOURS_PER_WEEK * WEEKS_PER_YEAR

def calc_current_bank_monthly(bank_sundays_per_month: float, bank_hours: float, bank_rate: float) -> float:
    return bank_sundays_per_month * bank_hours * bank_rate

def calc_new_sundays_monthly(new_sundays_per_month: float, base_hourly: float) -> float:
    return new_sundays_per_month * NEW_SUNDAY_HOURS * base_hourly * (1.0 + SUNDAY_UPLIFT)

def calc_annual_leave_uplift_monthly(new_sundays_per_month: float, base_hourly: float, annual_leave_weeks: float) -> float:
    """
    Approximation: treat enhancement value as averaged over year and applied to annual leave weeks.
    Enhancement-only portion per Sunday = 12h * base * 0.60
    """
    enhancement_per_sunday = NEW_SUNDAY_HOURS * base_hourly * SUNDAY_UPLIFT
    sundays_per_year = new_sundays_per_month * 12
    annual_enhancement_total = sundays_per_year * enhancement_per_sunday

    weekly_avg_enh = annual_enhancement_total / 52
    annual_leave_uplift = weekly_avg_enh * annual_leave_weeks
    return annual_leave_uplift / 12

def compute_monthly_takehome(
    base_hourly: float,
    bank_sundays_per_month: float,
    bank_hours: float,
    bank_rate: float,
    new_sundays_per_month: float,
    pension_rate: float,
    include_leave_uplift: bool,
    annual_leave_weeks: float
) -> dict:
    base_annual = calc_base_annual(base_hourly)
    base_monthly = base_annual / 12

    current_weekend_monthly = calc_current_bank_monthly(bank_sundays_per_month, bank_hours, bank_rate)
    new_weekend_monthly = calc_new_sundays_monthly(new_sundays_per_month, base_hourly)

    leave_uplift_monthly = 0.0
    if include_leave_uplift:
        leave_uplift_monthly = calc_annual_leave_uplift_monthly(new_sundays_per_month, base_hourly, annual_leave_weeks)

    # Gross totals
    current_gross_monthly = base_monthly + current_weekend_monthly
    new_gross_monthly = base_monthly + new_weekend_monthly + leave_uplift_monthly

    # Pension:
    # - Current bank Sundays assumed non-pensionable
    # - New Sunday earnings + leave uplift assumed pensionable
    current_pension_monthly = 0.0
    new_pension_monthly = pension_rate * (new_weekend_monthly + leave_uplift_monthly)

    # Annualise for tax model
    current_gross_annual = current_gross_monthly * 12
    new_gross_annual = new_gross_monthly * 12
    current_pension_annual = current_pension_monthly * 12
    new_pension_annual = new_pension_monthly * 12

    current_tax = tax_and_ni_ruk(current_gross_annual, pension_deduction=current_pension_annual)
    new_tax = tax_and_ni_ruk(new_gross_annual, pension_deduction=new_pension_annual)

    current_takehome_annual = current_gross_annual - current_pension_annual - current_tax.income_tax - current_tax.employee_ni
    new_takehome_annual = new_gross_annual - new_pension_annual - new_tax.income_tax - new_tax.employee_ni

    return {
        "base_monthly": base_monthly,
        "current_weekend_monthly": current_weekend_monthly,
        "new_weekend_monthly": new_weekend_monthly,
        "leave_uplift_monthly": leave_uplift_monthly,
        "current_gross_monthly": current_gross_monthly,
        "new_gross_monthly": new_gross_monthly,
        "current_pension_monthly": current_pension_monthly,
        "new_pension_monthly": new_pension_monthly,
        "current_takehome_monthly": current_takehome_annual / 12,
        "new_takehome_monthly": new_takehome_annual / 12,
        "current_tax_annual": current_tax.income_tax,
        "new_tax_annual": new_tax.income_tax,
        "current_ni_annual": current_tax.employee_ni,
        "new_ni_annual": new_tax.employee_ni,
        "current_gross_annual": current_gross_annual,
        "new_gross_annual": new_gross_annual,
        "current_pension_annual": current_pension_annual,
        "new_pension_annual": new_pension_annual,
        "current_takehome_annual": current_takehome_annual,
        "new_takehome_annual": new_takehome_annual,
    }


# =========================
# Monte Carlo simulation
# =========================
def simulate_sundays_per_month_distribution(
    n_staff: int,
    staff_required_per_sunday: int,
    opt_out_count: int,
    keen_count: int,
    keen_weight: float,
    normal_weight: float,
    n_sims: int,
    seed: int,
    person_type: str
) -> np.ndarray:
    """
    Simulate allocation of Sunday shifts across staff using a simple swap-market model:

    - Each month has about: staff_required_per_sunday * 52/12 total shifts (rounded to nearest int).
    - opt_out staff take 0 by definition
    - keen staff have higher probability ("weight") of being allocated a shift when swaps happen
    - everyone else shares the remainder

    person_type:
      - "Average sharer" => a random non-opt-out, non-keen person
      - "Keen (picks up extras)" => a random keen person
      - "Opt-out (does none)" => always 0
    """
    rng = np.random.default_rng(seed)
    total_shifts = int(np.round(staff_required_per_sunday * (52 / 12)))  # ~22
    months_per_run = 12  # simulate a "year" then average per month

    if opt_out_count < 0:
        opt_out_count = 0
    opt_out_count = min(opt_out_count, n_staff)

    remaining = n_staff - opt_out_count
    keen_count = min(max(0, keen_count), remaining)

    # Indices: [0..opt_out-1] are opt-out; next keen_count are keen; rest are normal
    # Pick a representative person index based on person_type
    if person_type == "Opt-out (does none)":
        # representative opt-out person
        if opt_out_count == 0:
            # if none opt out, treat as average
            person_type = "Average sharer"
        else:
            target_index = 0

    if person_type == "Keen (picks up extras)":
        if keen_count == 0:
            person_type = "Average sharer"
        else:
            target_index = opt_out_count  # first keen

    if person_type == "Average sharer":
        # pick first normal if available; else fall back to keen; else opt-out
        if remaining - keen_count > 0:
            target_index = opt_out_count + keen_count  # first normal
        elif keen_count > 0:
            target_index = opt_out_count
        else:
            target_index = 0

    # weights for non-opt-out people
    weights = np.zeros(n_staff, dtype=float)
    # opt-outs remain 0
    # keen
    if keen_count > 0:
        weights[opt_out_count:opt_out_count + keen_count] = keen_weight
    # normal
    if remaining - keen_count > 0:
        weights[opt_out_count + keen_count:] = normal_weight

    # Hard cap per person per month: can't do more Sundays than exist; also avoids weird concentration
    # With ~4.33 Sundays/month and 5 required each Sunday, it's plausible some people do 3-4/month but rare.
    cap_per_person = min(total_shifts, 4)  # conservative cap

    results = np.zeros(n_sims, dtype=float)

    for sim in range(n_sims):
        monthly_counts = []

        for _m in range(months_per_run):
            counts = np.zeros(n_staff, dtype=int)

            for _shift in range(total_shifts):
                eligible = (weights > 0) & (counts < cap_per_person)
                if not np.any(eligible):
                    # If everyone hit cap (unlikely with chosen cap), relax cap slightly for this month
                    eligible = weights > 0
                    if not np.any(eligible):
                        break

                probs = weights[eligible] / weights[eligible].sum()
                chosen_local = rng.choice(np.where(eligible)[0], p=probs)
                counts[chosen_local] += 1

            monthly_counts.append(counts[target_index])

        # average Sundays per month for that simulated year
        results[sim] = float(np.mean(monthly_counts))

    return results


# =========================
# UI
# =========================
st.title("Weekend Working Pay Impact (Illustrative)")

st.caption(
    "Illustrative tool only. Tax/NI are simplified and cannot reflect all circumstances "
    "(tax codes, Scottish tax, student loans, salary sacrifice, multiple jobs, etc.)."
)

with st.sidebar:
    st.header("Your role / pay point")
    band = st.selectbox("Band", list(BANDS.keys()))
    point = st.selectbox("Pay point", ["Entry", "Mid", "Top"])
    base_hourly = float(BANDS[band][point])
    bank_rate = float(BANDS[band]["bank_sunday_rate"])

    st.divider()
    st.header("Current system (monthly)")
    current_bank_sundays = st.slider("Bank Sundays per month", 0.0, 6.0, 1.0, 0.25)
    bank_hours = st.slider("Average hours claimed per bank Sunday", 6.0, 12.0, DEFAULT_BANK_SUNDAY_HOURS, 0.25)

    st.divider()
    st.header("New system (monthly)")
    default_new = float(np.round(FAIR_SHARE_SUNDAYS_PER_MONTH, 2))
    new_sundays = st.slider(
        "Expected Sundays per month under new system",
        0.0, 6.0, default_new, 0.25
    )

    st.divider()
    st.header("Pension + leave assumptions")
    pension_rate = st.slider("NHS pension rate (assumed)", 0.0, 0.20, DEFAULT_PENSION_RATE, 0.001)
    include_leave_uplift = st.checkbox("Include annual leave uplift approximation (new system only)", value=True)
    annual_leave_weeks = st.slider("Annual leave weeks/year (assumed)", 4.0, 8.0, 6.5, 0.5)

    st.divider()
    st.header("Simulation (swap market)")
    sim_on = st.toggle("Show Monte Carlo simulation", value=False)

    if sim_on:
        person_type = st.selectbox(
            "Which best describes you?",
            ["Average sharer", "Keen (picks up extras)", "Opt-out (does none)"]
        )
        opt_out_count = st.slider("How many staff opt out of Sundays entirely?", 0, AFFECTED_FTE, 4)
        keen_count = st.slider("How many staff are keen to pick up extra Sundays?", 0, AFFECTED_FTE, 6)
        keen_weight = st.slider("How much more likely keen staff pick up swaps?", 1.0, 5.0, 2.0, 0.1)
        n_sims = st.slider("Simulation runs", 500, 20000, 5000, 500)
        seed = st.number_input("Random seed (for repeatable results)", value=42, step=1)

# =========================
# Core calculation (manual slider)
# =========================
res = compute_monthly_takehome(
    base_hourly=base_hourly,
    bank_sundays_per_month=current_bank_sundays,
    bank_hours=bank_hours,
    bank_rate=bank_rate,
    new_sundays_per_month=new_sundays,
    pension_rate=pension_rate,
    include_leave_uplift=include_leave_uplift,
    annual_leave_weeks=annual_leave_weeks,
)

delta_gross = res["new_gross_monthly"] - res["current_gross_monthly"]
delta_takehome = res["new_takehome_monthly"] - res["current_takehome_monthly"]
delta_pension = res["new_pension_monthly"] - res["current_pension_monthly"]

# =========================
# Display
# =========================
col1, col2 = st.columns([1.2, 0.8], gap="large")

with col1:
    st.subheader("Manual comparison (based on your Sunday inputs)")

    df = pd.DataFrame(
        [
            ["Base pay (estimated)", res["base_monthly"], res["base_monthly"], 0.0],
            ["Sunday pay", res["current_weekend_monthly"], res["new_weekend_monthly"], res["new_weekend_monthly"] - res["current_weekend_monthly"]],
            ["Annual leave uplift (approx.)", 0.0, res["leave_uplift_monthly"], res["leave_uplift_monthly"]],
            ["Gross total", res["current_gross_monthly"], res["new_gross_monthly"], delta_gross],
            ["Pension deduction (assumed)", res["current_pension_monthly"], res["new_pension_monthly"], delta_pension],
            ["Take-home (after tax/NI/pension)", res["current_takehome_monthly"], res["new_takehome_monthly"], delta_takehome],
        ],
        columns=["Line", "Current (monthly)", "New (monthly)", "Change"],
    )

    st.dataframe(
        df.style.format(
            {
                "Current (monthly)": money,
                "New (monthly)": money,
                "Change": money,
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

with col2:
    st.subheader("Context")
    st.write(f"- **{band} / {point}** base hourly: **{money(base_hourly)}**")
    st.write(f"- Base salary estimate (37.5h): **{money(res['base_monthly'])} / month**")
    st.write(f"- Fair-share Sundays/month (22 staff, 5 required): **{FAIR_SHARE_SUNDAYS_PER_MONTH:.2f}**")
    st.write(f"- Current bank Sunday rate assumed hourly: **{money(bank_rate)}**")
    st.info(
        "If your take-home decreases while pension increases: "
        "that’s usually because the new payments are pensionable (and tax interacts differently). "
        "This tool is for direction-of-travel, not exact payroll."
    )

st.divider()

# =========================
# Simulation section
# =========================
if sim_on:
    st.subheader("Monte Carlo simulation: likely Sundays/month for someone like you")

    sims = simulate_sundays_per_month_distribution(
        n_staff=AFFECTED_FTE,
        staff_required_per_sunday=STAFF_REQUIRED_PER_SUNDAY,
        opt_out_count=opt_out_count,
        keen_count=keen_count,
        keen_weight=keen_weight,
        normal_weight=1.0,
        n_sims=int(n_sims),
        seed=int(seed),
        person_type=person_type,
    )

    p10, p50, p90 = np.percentile(sims, [10, 50, 90])

    st.write(
        f"Based on these assumptions, a **{person_type}** might work approximately:\n\n"
        f"- **10th percentile:** {p10:.2f} Sundays/month\n"
        f"- **Median:** {p50:.2f} Sundays/month\n"
        f"- **90th percentile:** {p90:.2f} Sundays/month"
    )

    # Show histogram
    hist_df = pd.DataFrame({"Simulated Sundays/month": sims})
    st.bar_chart(hist_df.value_counts().sort_index())

    st.subheader("What that might mean for pay (range)")
    # Compute pay impact for p10/p50/p90 (holding current bank Sundays fixed, and only varying new Sundays)
    scenarios = []
    for label, s in [("P10", p10), ("Median", p50), ("P90", p90)]:
        r = compute_monthly_takehome(
            base_hourly=base_hourly,
            bank_sundays_per_month=current_bank_sundays,
            bank_hours=bank_hours,
            bank_rate=bank_rate,
            new_sundays_per_month=float(s),
            pension_rate=pension_rate,
            include_leave_uplift=include_leave_uplift,
            annual_leave_weeks=annual_leave_weeks,
        )
        scenarios.append(
            {
                "Scenario": label,
                "New Sundays/month": float(s),
                "Gross (new, monthly)": r["new_gross_monthly"],
                "Take-home (new, monthly)": r["new_takehome_monthly"],
                "Change vs current take-home": r["new_takehome_monthly"] - r["current_takehome_monthly"],
                "Pension (new, monthly)": r["new_pension_monthly"],
            }
        )

    scen_df = pd.DataFrame(scenarios)
    st.dataframe(
        scen_df.style.format(
            {
                "Gross (new, monthly)": money,
                "Take-home (new, monthly)": money,
                "Change vs current take-home": money,
                "Pension (new, monthly)": money,
                "New Sundays/month": "{:.2f}",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

st.divider()
st.subheader("Caveats (please read)")
st.markdown(
    """
- **Tax/NI** are simplified (annualised) and may differ from payroll calculations per pay period.
- Not included: **Scottish income tax**, **student loans**, **salary sacrifice**, **benefits**, **multiple jobs**, etc.
- **Sickness pay uplift** may exist if Sunday enhancements become contractual, but is not modelled.
- **Annual leave uplift** here is an approximation; real calculations depend on the preceding weeks’ averages.
"""
)