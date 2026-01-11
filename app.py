import calendar
from typing import Dict, List, Tuple

import pandas as pd
import streamlit as st

from tax_engine import (
    CHILD_BENEFIT_MONTHLY,
    PUBLIC_BENEFITS_TEMPLATE,
    SpouseInputs,
    TaxSettings,
    calculate_spouse_summary,
    calculate_commute_deduction,
    prepare_tax_bases,
    allocate_personal_allowance,
    serialize_deductions,
    serialize_summary,
)


DEFAULT_EXPENSE_CATEGORIES = {
    "Bolig og forsyning": 8500.0,
    "Dagligvarer": 6000.0,
    "Transport": 2500.0,
    "Boern (institution/fritid)": 3200.0,
    "Forsikringer og sundhed": 1500.0,
    "Abonnementer og fritid": 1200.0,
}

st.set_page_config(
    page_title="Budget for dansk aegtepar",
    layout="wide",
)

st.title("Budgetoverblik for dansk aegtepar med to boern")
st.caption(
    "Interaktiv model der estimerer maanedlig nettoindtjening baseret paa danske skatteregler, "
    "standardfradrag og boerneydelser. Alle beloeb kan justeres, og beregningen er vejledende."
)


def sidebar_settings() -> Tuple[TaxSettings, float, float]:
    st.sidebar.header("Skatteparametre")
    municipal = st.sidebar.slider("Kommuneskat (%)", 20.0, 28.0, 24.5, 0.1) / 100
    church = st.sidebar.slider("Kirkeskat (%)", 0.0, 1.2, 0.7, 0.1) / 100
    bottom = st.sidebar.slider("Bundskat (%)", 10.0, 15.0, 12.1, 0.1) / 100
    top = st.sidebar.slider("Topskat (%)", 10.0, 20.0, 15.0, 0.1) / 100
    top_threshold = st.sidebar.number_input("Topskat traeskel (aarligt)", value=618400.0, step=10000.0)

    settings = TaxSettings(
        municipal_rate=municipal,
        church_rate=church,
        bottom_tax_rate=bottom,
        top_tax_rate=top,
        top_tax_threshold=top_threshold,
    )

    st.sidebar.header("Boernepenge")
    child_counts = {}
    for bracket, monthly in CHILD_BENEFIT_MONTHLY.items():
        child_counts[bracket] = st.sidebar.number_input(
            f"Antal boern {bracket} aar", min_value=0, value=2 if bracket == "3-6" else 0, step=1
        )
    child_benefit_monthly = sum(count * monthly for bracket, count in child_counts.items())

    st.sidebar.header("Andre skattefri beloeb")
    household_tax_free_extra = st.sidebar.number_input(
        "Skattefri husstandstilskud (maanedlig)", min_value=0.0, value=0.0, step=100.0
    )

    return settings, child_benefit_monthly, household_tax_free_extra


def collect_spouse_inputs(idx: int, container, auto_mortgage_share: float = 0.0) -> SpouseInputs:
    with container:
        st.subheader(f"Person {idx}")
        name = st.text_input(f"Navn person {idx}", value=f"Person {idx}")
        monthly_salary = st.number_input(
            "Maanedlig loen (A-indkomst)", min_value=0.0, value=35000.0 if idx == 1 else 28000.0, step=1000.0,
            key=f"salary_{idx}",
        )
        monthly_honorarium = st.number_input(
            "Maanedlig honorar (A-indkomst)", min_value=0.0, value=0.0, step=500.0, key=f"honorar_{idx}"
        )
        monthly_b_income = st.number_input(
            "B-indkomst / freelancing (maanedlig)", min_value=0.0, value=0.0, step=500.0, key=f"b_income_{idx}"
        )

        st.markdown("### Offentlige ydelser")
        taxable_public = 0.0
        tax_free_public = 0.0
        for benefit, meta in PUBLIC_BENEFITS_TEMPLATE.items():
            amount = st.number_input(
                f"{benefit} (maanedlig)", min_value=0.0, value=meta["default"], step=500.0,
                key=f"benefit_{benefit}_{idx}",
            )
            if meta["taxable"]:
                taxable_public += amount
            else:
                tax_free_public += amount

        monthly_gifts = st.number_input(
            "Gaver / arveforskud (maanedlig, skattefri)", min_value=0.0, value=0.0, step=500.0,
            key=f"gift_{idx}", help="Typisk pengegaver fra foraeldre/bedsteforaeldre inden for bundfradraget"
        )

        st.markdown("### Fradrag (aarlige beloeb)")
        st.caption("Alle beloeb angives i DKK pr. aar. Hjaelpeteksterne forklarer, hvad der giver fradrag.")
        with st.expander("Vis og forklar fradrag", expanded=True):
            st.markdown(
                "*Fradragene reducerer den skattepligtige indkomst efter AM-bidrag.*\n"
                "- **Renteudgifter:** Nettorenter paa realkredit- eller banklaan (boligmodulet beregner et standardbelob).\n"
                "- **BoligJob (haandvaerker):** Arbejdslon til service/foerstehaandsarbejde.\n"
                "- **Fagforening/A-kasse:** Kontingent og efterlonsbidrag.\n"
                "- **Koerselsfradrag:** Afstand bolig-arbejde over 24 km pr. dag.\n"
                "- **Andre fradrag:** Fx private pensionsindskud eller studiegeldsrenter."
            )
            mortgage = st.number_input(
                "Renteudgifter (forhaandsudfyldt)", min_value=0.0, value=float(auto_mortgage_share),
                step=2000.0, key=f"mortgage_{idx}",
                help="Tal fra boligmodulet indsattes automatisk, men kan justeres hvis du har andre renter"
            )
            st.caption(
                f"Forhaandsudfyldt rente fra boligmodulet: {auto_mortgage_share:,.0f} DKK/aar".replace(",", " ")
            )
            handyman = st.number_input(
                "Haandvaerker (BoligJob) fradrag", min_value=0.0, value=0.0, step=1000.0, key=f"handyman_{idx}",
                help="Aarlige arbejdsloen-udgifter til service/vedligehold som er godkendt i BoligJobordningen"
            )
            union_fee = st.number_input(
                "Fagforening/A-kasse", min_value=0.0, value=6000.0 if idx == 1 else 5000.0,
                step=500.0, key=f"union_{idx}",
                help="Kontingent til fagforening, a-kasse og evt. efterlonsbidrag"
            )
            other = st.number_input(
                "Andre fradrag (fx pensionsindskud, studiegift)", min_value=0.0, value=0.0,
                step=1000.0, key=f"other_{idx}",
                help="Samlede fradrag som ikke passer i de andre kategorier"
            )
            st.markdown("#### Koerselsfradrag (beregnes automatisk)")
            commute_distance = st.number_input(
                "Afstand bolig \u2192 arbejde (km pr. vej)", min_value=0.0,
                value=20.0 if idx == 1 else 12.0, step=0.5, key=f"commute_distance_{idx}",
                help="Indtast gennemsnitlig afstand i kilometer fra hjem til arbejde for en enkelt tur"
            )
            commute_days = st.number_input(
                "Pendlerdage pr. aar", min_value=0, value=210, step=5, key=f"commute_days_{idx}",
                help="Antal gange du fysisk moedte paa arbejde i loebet af aaret"
            )
            commute_adjustment = st.number_input(
                "Manuel justering af koerselsfradrag", min_value=-50000.0, value=0.0, step=500.0,
                key=f"commute_adjust_{idx}", help="Brug dette felt til at tilfoeje/fratraekke beloeb hvis du pendler fra flere adresser"
            )
            auto_commute = calculate_commute_deduction(commute_distance, commute_days)
            commute = max(0.0, auto_commute + commute_adjustment)
            summary_text = (
                f"Automatisk koerselsfradrag: {auto_commute:,.0f} DKK/aar baseret paa {commute_distance:.1f} km pr. vej"
                f" og {commute_days} pendlerdage."
            )
            st.caption(summary_text.replace(",", " "))

        return SpouseInputs(
            name=name.strip() or f"Person {idx}",
            monthly_salary=monthly_salary,
            monthly_honorarium_a_income=monthly_honorarium,
            monthly_b_income=monthly_b_income,
            monthly_public_taxable=taxable_public,
            monthly_public_tax_free=tax_free_public,
            monthly_gifts_tax_free=monthly_gifts,
            annual_mortgage_interest=mortgage,
            annual_handyman_deduction=handyman,
            annual_union_fee=union_fee,
            annual_commute_deduction=commute,
            annual_other_deductions=other,
        )


def household_summary(
    summaries: List[dict], child_benefit_monthly: float, household_tax_free_extra: float
) -> pd.DataFrame:
    months = list(calendar.month_name[1:])
    month_records = []
    combined_net = sum(item["monthly_net"] for item in summaries)
    child_monthly = child_benefit_monthly
    other_tax_free = household_tax_free_extra

    for name in months:
        total = combined_net + child_monthly + other_tax_free
        record = {
            "Maaned": name,
            summaries[0]["name"]: summaries[0]["monthly_net"],
            summaries[1]["name"]: summaries[1]["monthly_net"],
            "Boernepenge": child_monthly,
            "Andre skattefri": other_tax_free,
            "Husstand netto": total,
        }
        month_records.append(record)

    return pd.DataFrame(month_records)


def mortgage_module() -> dict:
    st.subheader("Boligkoebsscenarie")
    with st.expander("Saadan kan et koeb se ud", expanded=False):
        purchase_price = st.number_input(
            "Koebesum", min_value=0.0, value=4000000.0, step=50000.0, help="Total pris for boligen inkl. evt. bud"
        )
        down_payment_pct = st.slider(
            "Egenbetaling (%)", min_value=5.0, max_value=40.0, value=10.0, step=1.0,
            help="Typisk mindst 5% kontant udbetaling"
        )
        interest_rate = st.number_input(
            "Aarlig rente (%)", min_value=0.0, value=3.5, step=0.1,
            help="Gennemsnitlig aarlig rente paa laanet"
        )
        term_years = st.number_input(
            "Loebetid (aar)", min_value=5, max_value=40, value=30, step=1,
            help="Antal aar laanet afdrages over"
        )
        property_tax = st.number_input(
            "Ejendomsskat + forsikring (aar)", min_value=0.0, value=18000.0, step=1000.0,
            help="Samlede aarlige udgifter til grundskyld og bygningsforsikring"
        )
        maintenance_pct = st.slider(
            "Vedligehold (% af koebesum pr. aar)", 0.0, 2.0, 1.0, 0.1,
            help="Tommelregel: 1% af huset til vedligeholdelse"
        )
        interest_split_pct = st.slider(
            "Fordeling af renteudgift til Person 1 (%)", 0, 100, 50, 1,
            help="Brug skyderen til at bestemme hvor meget af renteudgiften der tilfalder hver person"
        )

    down_payment = purchase_price * (down_payment_pct / 100.0)
    loan_amount = max(0.0, purchase_price - down_payment)
    monthly_rate = (interest_rate / 100.0) / 12.0
    total_payments = int(term_years * 12)
    if loan_amount == 0 or total_payments == 0:
        monthly_payment = 0.0
    elif monthly_rate == 0:
        monthly_payment = loan_amount / total_payments
    else:
        factor = (1 + monthly_rate) ** total_payments
        monthly_payment = loan_amount * (monthly_rate * factor) / (factor - 1)

    property_tax_monthly = property_tax / 12.0
    maintenance_monthly = (purchase_price * (maintenance_pct / 100.0)) / 12.0
    total_monthly = monthly_payment + property_tax_monthly + maintenance_monthly
    annual_interest_estimate = loan_amount * (interest_rate / 100.0)
    interest_split_fraction = interest_split_pct / 100.0

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Maanedlig ydelse", f"{monthly_payment:,.0f} DKK".replace(",", " "))
    col_b.metric("Ejendomsskat/forsikring", f"{property_tax_monthly:,.0f} DKK".replace(",", " "))
    col_c.metric("Vedligehold", f"{maintenance_monthly:,.0f} DKK".replace(",", " "))
    st.caption(
        "Summen ovenfor viser hvad boligen koster hver maaned ekskl. varme/el. "
        "Juster satserne for at afspejle jeres konkrete finansiering."
    )
    st.caption(
        f"Skoennet aarlig renteudgift: {annual_interest_estimate:,.0f} DKK (fordelt {interest_split_pct}% / {100-interest_split_pct}%)."
        .replace(",", " ")
    )

    return {
        "monthly_total": total_monthly,
        "monthly_payment": monthly_payment,
        "property_tax_monthly": property_tax_monthly,
        "maintenance_monthly": maintenance_monthly,
        "annual_interest": annual_interest_estimate,
        "interest_split_fraction": interest_split_fraction,
    }


def car_module() -> dict:
    st.subheader("Bilscenarie")
    with st.expander("Tilpas bilbudget", expanded=False):
        car_price = st.number_input(
            "Pris paa bil", min_value=0.0, value=300000.0, step=10000.0,
            help="Kontantpris ved koeb af bil"
        )
        car_down_payment = st.slider(
            "Udbetaling (%)", min_value=0.0, max_value=50.0, value=20.0, step=1.0,
            help="Typisk mindst 20% for at holde laanet nede"
        )
        car_rate = st.number_input(
            "Aarlig rente paa billaan (%)", min_value=0.0, value=4.0, step=0.1
        )
        car_term_years = st.number_input(
            "Loebetid (aar)", min_value=1, max_value=10, value=7, step=1
        )
        km_per_year = st.number_input(
            "Koersel pr. aar (km)", min_value=0.0, value=18000.0, step=1000.0
        )
        efficiency = st.number_input(
            "Forbrug (km pr. liter / kWh)", min_value=1.0, value=17.0, step=0.5,
            help="Angiv hvor langt bilen koekrer per liter benzin/diesel eller pr. kWh"
        )
        fuel_price = st.number_input(
            "Pris pr. liter/kWh (DKK)", min_value=0.0, value=14.0, step=0.5
        )
        insurance = st.number_input(
            "Forsikring + vaegtafgift (aarlig)", min_value=0.0, value=9000.0, step=500.0
        )
        maintenance = st.number_input(
            "Service/vedligehold (aarlig)", min_value=0.0, value=6000.0, step=500.0
        )

    car_down_payment_amount = car_price * (car_down_payment / 100.0)
    car_loan = max(0.0, car_price - car_down_payment_amount)
    car_monthly_rate = (car_rate / 100.0) / 12.0
    car_payments = int(car_term_years * 12)
    if car_loan == 0 or car_payments == 0:
        car_monthly_payment = 0.0
    elif car_monthly_rate == 0:
        car_monthly_payment = car_loan / car_payments
    else:
        factor = (1 + car_monthly_rate) ** car_payments
        car_monthly_payment = car_loan * (car_monthly_rate * factor) / (factor - 1)

    fuel_monthly = 0.0
    if efficiency > 0:
        liters_per_month = (km_per_year / 12.0) / efficiency
        fuel_monthly = liters_per_month * fuel_price

    insurance_monthly = insurance / 12.0
    maintenance_monthly = maintenance / 12.0
    total_car_monthly = car_monthly_payment + fuel_monthly + insurance_monthly + maintenance_monthly

    c1, c2, c3 = st.columns(3)
    c1.metric("Billaan pr. maaned", f"{car_monthly_payment:,.0f} DKK".replace(",", " "))
    c2.metric("Drift (braendstof)", f"{fuel_monthly:,.0f} DKK".replace(",", " "))
    c3.metric("Forsikring + service", f"{(insurance_monthly+maintenance_monthly):,.0f} DKK".replace(",", " "))
    st.caption("Samlet biludgift pr. maaned inkluderer laan, braendstof, forsikring og service.")

    return {
        "monthly_total": total_car_monthly,
        "monthly_payment": car_monthly_payment,
        "fuel_monthly": fuel_monthly,
        "insurance_monthly": insurance_monthly,
        "maintenance_monthly": maintenance_monthly,
    }


def fixed_expenses_module(household_monthly_net: float, auto_categories: Dict[str, float] | None = None) -> None:
    st.subheader("Faste maanedlige udgifter")
    st.caption(
        "Brug felterne til at indtaste de stoerste faste poster. "
        "Tallene fratraekkes husstandens nettoindtjening for at vise raadighedsbeloebet."
    )

    expense_blueprint = dict(DEFAULT_EXPENSE_CATEGORIES)
    if auto_categories:
        expense_blueprint.update({k: round(v, 2) for k, v in auto_categories.items() if v > 0})

    expense_cols = st.columns(3)
    expenses = {}
    for idx, (label, default_value) in enumerate(expense_blueprint.items()):
        col = expense_cols[idx % 3]
        with col:
            expenses[label] = st.number_input(
                label,
                min_value=0.0,
                value=float(default_value),
                step=250.0,
                key=f"expense_{idx}",
            )

    other_fixed = st.number_input(
        "Andre faste udgifter", min_value=0.0, value=0.0, step=250.0, key="expense_other"
    )
    expenses["Andre faste udgifter"] = other_fixed

    total_expenses = sum(expenses.values())
    net_after_expenses = household_monthly_net - total_expenses

    metrics_col1, metrics_col2 = st.columns(2)
    metrics_col1.metric("Samlede faste udgifter", f"{total_expenses:,.0f} DKK".replace(",", " "))
    metrics_col2.metric(
        "Raadighed efter faste udgifter", f"{net_after_expenses:,.0f} DKK".replace(",", " ")
    )

    expense_df = pd.DataFrame(
        {"Kategori": list(expenses.keys()), "Maanedligt beloeb": list(expenses.values())}
    )
    st.dataframe(expense_df, use_container_width=True, hide_index=True)

    st.caption(
        "Inkluder saavel de sikre (fx realkredit, institution) som mere variable poster "
        "for at faa et realistisk raadighedsbeloeb."
    )


settings, child_benefit_monthly, household_tax_free_extra = sidebar_settings()

mortgage_details = mortgage_module()
car_details = car_module()

person1_mortgage_share = 0.0
person2_mortgage_share = 0.0
if mortgage_details["annual_interest"] > 0:
    person1_mortgage_share = mortgage_details["annual_interest"] * mortgage_details["interest_split_fraction"]
    person2_mortgage_share = max(
        0.0, mortgage_details["annual_interest"] - person1_mortgage_share
    )

input_columns = st.columns(2)
spouse_inputs = [
    collect_spouse_inputs(1, input_columns[0], person1_mortgage_share),
    collect_spouse_inputs(2, input_columns[1], person2_mortgage_share),
]

tax_bases = prepare_tax_bases(spouse_inputs, settings)
allowance_extras, allowance_unused, allowance_needs = allocate_personal_allowance(tax_bases, settings)

spouse_summaries = []
deduction_details = []
for base, extra in zip(tax_bases, allowance_extras):
    summary, deductions = calculate_spouse_summary(base, settings, personal_allowance_extra=extra)
    spouse_summaries.append(serialize_summary(summary))
    deduction_details.append(serialize_deductions(deductions))


st.divider()
st.subheader("Nettoindtjening per person")
col_results = st.columns(2)
for col, summary, deductions in zip(col_results, spouse_summaries, deduction_details):
    with col:
        st.metric(
            f"{summary['name']} - netto per maaned",
            f"{summary['monthly_net']:,} DKK".replace(",", " "),
            help="Beregnet efter AM-bidrag, indkomstskat og fradrag",
        )
        shared_allowance = deductions.get("shared_personal_allowance", 0.0)
        shared_text = ""
        if shared_allowance > 0:
            shared_text = f" | Modtaget fradrag fra partner: {shared_allowance:,.0f} DKK".replace(",", " ")
        st.caption(
            (
                f"Effektiv skat: {summary['effective_tax_rate']*100:.1f}% | AM-bidrag: {summary['am_contribution']:,} DKK"
                + shared_text
            ).replace(",", " ")
        )
        detail_df = pd.DataFrame(
            {
                "Post": [
                    "Loen + honorar",
                    "B-indkomst",
                    "Skattepligtig offentlig indkomst",
                    "Skattefri overfoersler",
                    "AM-bidrag",
                    "Total skat",
                    "Netto (aar)",
                ],
                "Beloeb (DKK)": [
                    summary["employment_income"],
                    summary["b_income"],
                    summary["taxable_public"],
                    summary["tax_free_transfers"],
                    summary["am_contribution"],
                    summary["total_tax"],
                    summary["annual_net"],
                ],
            }
        )
        st.dataframe(detail_df, use_container_width=True, hide_index=True)
        with st.expander("Fradragsdetaljer"):
            st.json(deductions)


household_df = household_summary(spouse_summaries, child_benefit_monthly, household_tax_free_extra)
st.subheader("Husstandens maanedlige udvikling")
st.dataframe(household_df, use_container_width=True, hide_index=True)

st.bar_chart(
    household_df.set_index("Maaned")[
        [spouse_summaries[0]["name"], spouse_summaries[1]["name"], "Boernepenge", "Andre skattefri"]
    ]
)

if any(extra > 0 for extra in allowance_extras):
    transfer_lines = []
    for summary, extra in zip(spouse_summaries, allowance_extras):
        if extra > 0:
            transfer_lines.append(
                f"{summary['name']} modtog {extra:,.0f} DKK af partnerens personfradrag".replace(",", " ")
            )
    if transfer_lines:
        st.info(
            "Aegtefaelleoverfoersel af personfradrag:\n" + "\n".join(f"- {line}" for line in transfer_lines)
        )

household_monthly_net = household_df["Husstand netto"].iloc[0] if not household_df.empty else 0.0
auto_categories = {}
if mortgage_details["monthly_total"] > 0:
    auto_categories["Boliglaan (beregnet)"] = mortgage_details["monthly_total"]
if car_details["monthly_total"] > 0:
    auto_categories["Bil (laan + drift)"] = car_details["monthly_total"]
fixed_expenses_module(household_monthly_net, auto_categories)

csv = household_df.to_csv(index=False).encode("utf-8")
st.download_button("Download maanedligt budget (CSV)", data=csv, file_name="husstand_budget.csv")

st.divider()
st.markdown(
    "**Note:** Modellen anvender forsimplede skatteparametre for 2024/2025 og "
    "givne beloeb er ikke udtryk for officiel raadgivning. Kontrollere altid mod SKAT."
)
