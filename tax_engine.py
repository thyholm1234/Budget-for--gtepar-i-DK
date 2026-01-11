from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple


@dataclass
class TaxSettings:
    """Container for the tax parameters that can be tuned from the UI."""

    municipal_rate: float = 0.245  # Kommuneskat (default 24.5%)
    church_rate: float = 0.007     # Kirkeskat (default 0.7%)
    bottom_tax_rate: float = 0.1209  # Bundskat
    top_tax_rate: float = 0.15
    am_rate: float = 0.08
    top_tax_threshold: float = 618400.0  # 2024 threshold after AM contribution
    personal_allowance: float = 48000.0
    employment_deduction_rate: float = 0.1
    employment_deduction_cap: float = 43500.0


@dataclass
class SpouseInputs:
    """Normalized income and deduction inputs for a single person."""

    name: str
    monthly_salary: float
    monthly_honorarium_a_income: float
    monthly_b_income: float
    monthly_public_taxable: float
    monthly_public_tax_free: float
    monthly_gifts_tax_free: float
    annual_mortgage_interest: float
    annual_handyman_deduction: float
    annual_union_fee: float
    annual_commute_deduction: float
    annual_other_deductions: float

    def annual_employment_income(self) -> float:
        return 12.0 * (self.monthly_salary + self.monthly_honorarium_a_income)

    def annual_b_income(self) -> float:
        return 12.0 * self.monthly_b_income

    def annual_public_taxable(self) -> float:
        return 12.0 * self.monthly_public_taxable

    def annual_tax_free_transfers(self) -> float:
        return 12.0 * (self.monthly_public_tax_free + self.monthly_gifts_tax_free)


CHILD_BENEFIT_MONTHLY = {
    "0-2": 4971.0 / 3.0,  # paid quarterly; converted to monthly equivalent
    "3-6": 3933.0 / 3.0,
    "7-14": 3093.0 / 3.0,
    "15-17": 961.0,
}


PUBLIC_BENEFITS_TEMPLATE = {
    "Dagpenge": {"default": 0.0, "taxable": True},
    "Barselsdagpenge": {"default": 0.0, "taxable": True},
    "Kontanthjaelp": {"default": 0.0, "taxable": True},
    "Boligstoette": {"default": 0.0, "taxable": False},
    "Tilskud fra kommune": {"default": 0.0, "taxable": False},
}


def _rounded(value: float) -> float:
    return round(value, 2)


def _employment_deduction(income: float, settings: TaxSettings) -> float:
    raw = income * settings.employment_deduction_rate
    return min(raw, settings.employment_deduction_cap)


@dataclass
class SpouseTaxBase:
    inputs: SpouseInputs
    employment_income: float
    b_income: float
    taxable_public: float
    tax_free_transfers: float
    am_contribution: float
    income_after_am: float
    employment_deduction: float
    non_personal_deductions: float
    base_income: float
    taxable_after_other: float


def _build_tax_base(inputs: SpouseInputs, settings: TaxSettings) -> SpouseTaxBase:
    employment_income = inputs.annual_employment_income()
    b_income = inputs.annual_b_income()
    taxable_public = inputs.annual_public_taxable()
    tax_free_transfers = inputs.annual_tax_free_transfers()

    am_contribution = employment_income * settings.am_rate
    income_after_am = employment_income - am_contribution

    employment_deduction = _employment_deduction(employment_income, settings)
    non_personal_deductions = (
        employment_deduction
        + inputs.annual_mortgage_interest
        + inputs.annual_handyman_deduction
        + inputs.annual_union_fee
        + inputs.annual_commute_deduction
        + inputs.annual_other_deductions
    )

    base_income = income_after_am + b_income + taxable_public
    taxable_after_other = max(0.0, base_income - non_personal_deductions)

    return SpouseTaxBase(
        inputs=inputs,
        employment_income=employment_income,
        b_income=b_income,
        taxable_public=taxable_public,
        tax_free_transfers=tax_free_transfers,
        am_contribution=am_contribution,
        income_after_am=income_after_am,
        employment_deduction=employment_deduction,
        non_personal_deductions=non_personal_deductions,
        base_income=base_income,
        taxable_after_other=taxable_after_other,
    )


def prepare_tax_bases(spouses: List[SpouseInputs], settings: TaxSettings) -> List[SpouseTaxBase]:
    return [_build_tax_base(spouse, settings) for spouse in spouses]


def allocate_personal_allowance(
    bases: List[SpouseTaxBase], settings: TaxSettings
) -> Tuple[List[float], List[float], List[float]]:
    """Return shared allowance extras, unused amounts, and remaining needs."""

    extras = [0.0 for _ in bases]
    unused = []
    needs = []

    for base in bases:
        used = min(settings.personal_allowance, base.taxable_after_other)
        unused.append(settings.personal_allowance - used)
        needs.append(max(0.0, base.taxable_after_other - settings.personal_allowance))

    if len(bases) == 2:
        extras[0] = min(needs[0], unused[1])
        extras[1] = min(needs[1], unused[0])

    return extras, unused, needs


def calculate_commute_deduction(distance_each_way_km: float, annual_days: float) -> float:
    """Approximate Danish befordringsfradrag based on daily distance."""

    if distance_each_way_km <= 0 or annual_days <= 0:
        return 0.0

    daily_round_trip = distance_each_way_km * 2.0
    deductible_distance = max(0.0, daily_round_trip - 24.0)
    primary_band = min(deductible_distance, 96.0)  # 24-120 km zone per day
    secondary_band = max(0.0, deductible_distance - 96.0)

    daily_deduction = primary_band * 2.23 + secondary_band * 1.12
    return _rounded(daily_deduction * annual_days)


def calculate_spouse_summary(
    base: SpouseTaxBase,
    settings: TaxSettings,
    personal_allowance_extra: float = 0.0,
) -> Tuple[Dict[str, float], Dict[str, float]]:
    """Return breakdown (annual totals) and deduction details for one person."""

    inputs = base.inputs
    effective_personal_allowance = settings.personal_allowance + personal_allowance_extra
    deduction_total = effective_personal_allowance + base.non_personal_deductions

    taxable_base = max(0.0, base.base_income - deduction_total)

    bottom_tax = taxable_base * settings.bottom_tax_rate
    municipal_tax = taxable_base * settings.municipal_rate
    church_tax = taxable_base * settings.church_rate

    top_tax_base = max(
        0.0,
        (base.income_after_am + base.b_income) - settings.top_tax_threshold,
    )
    top_tax = top_tax_base * settings.top_tax_rate

    total_tax = bottom_tax + municipal_tax + church_tax + top_tax

    annual_net_taxable = (
        base.employment_income + base.b_income + base.taxable_public - base.am_contribution - total_tax
    )
    annual_net = annual_net_taxable + base.tax_free_transfers

    breakdown = {
        "name": inputs.name,
        "employment_income": _rounded(base.employment_income),
        "b_income": _rounded(base.b_income),
        "taxable_public": _rounded(base.taxable_public),
        "tax_free_transfers": _rounded(base.tax_free_transfers),
        "am_contribution": _rounded(base.am_contribution),
        "taxable_base": _rounded(taxable_base),
        "bottom_tax": _rounded(bottom_tax),
        "municipal_tax": _rounded(municipal_tax),
        "church_tax": _rounded(church_tax),
        "top_tax": _rounded(top_tax),
        "total_tax": _rounded(total_tax),
        "annual_net": _rounded(annual_net),
        "monthly_net": _rounded(annual_net / 12.0),
        "effective_tax_rate": _rounded(
            total_tax / max(1.0, base.employment_income + base.b_income + base.taxable_public)
        ),
    }

    deductions = {
        "personal_allowance": settings.personal_allowance,
        "shared_personal_allowance": _rounded(personal_allowance_extra),
        "personal_allowance_effective": _rounded(effective_personal_allowance),
        "employment_deduction": _rounded(base.employment_deduction),
        "mortgage_interest": _rounded(inputs.annual_mortgage_interest),
        "handyman": _rounded(inputs.annual_handyman_deduction),
        "union_fee": _rounded(inputs.annual_union_fee),
        "commute": _rounded(inputs.annual_commute_deduction),
        "other": _rounded(inputs.annual_other_deductions),
        "total": _rounded(deduction_total),
    }

    return breakdown, deductions


def serialize_summary(summary: Dict[str, float]) -> Dict[str, float]:
    """Ensure floats are rounded when displayed or exported."""
    return {k: _rounded(v) if isinstance(v, float) else v for k, v in summary.items()}


def serialize_deductions(deductions: Dict[str, float]) -> Dict[str, float]:
    return {k: _rounded(v) for k, v in deductions.items()}
