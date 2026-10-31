"""Synthetic claims dataset generator.

Run from the repo root:  python -m data.synthetic.generate --out data/synthetic/out

Everything is derived from one fixed seed, so re-running produces byte-identical files. Two fictional
insurers (an Indian retail health product in INR and a UAE group health product in AED), 8 providers,
60 members, 30 policies, 125 claims with 5-40 invoice lines each, 40 history claims, planted leakage of
every kind the checks know about, an answer key with the exact calculated amounts, a documents manifest
and rendered bills / discharge summaries for eight claims. Every record is validated through the Pydantic
contracts in core/schemas before it is written.

Layout: entity builders (products, providers, members + policies, history), clean-claim builders per claim
type, one plant_* function per leakage scenario, then finalise() which assigns ids, computes amounts and
settlements, builds the key and the manifest, and writes every file.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from core.schemas.finding import CheckId
from core.schemas.master import (Claim, ClaimType, Copay, Deductible, Exclusion, HistoryRecord, InvoiceLine,
                                 LineCategory, Policy, ProductConfig, Sublimit)
from data.synthetic import catalog as cat
from data.synthetic.documents import rasterise_pdf, render_bill_pdf, render_discharge_pdf

SEED = 20261031
TOTAL_CLAIMS = 125
HISTORY_COUNT = 40
HISTORY_WITH_LINES = 15
CLAIM_WINDOW = (date(2026, 1, 2), date(2026, 10, 20))
HISTORY_PAID_WINDOW = (date(2025, 6, 1), date(2026, 2, 28))
SCAN_DPI = 150
SCAN_ROTATION_DEG = 1.5


# ---------------------------------------------------------------------------
# Internal records (before ids exist)
# ---------------------------------------------------------------------------
@dataclass
class Member:
    claimant_id: str
    name: str
    gender: str
    date_of_birth: date
    policy_number: str
    product_id: str
    market: str
    relationship: str
    phone: str
    bank_account: str
    address: str
    city: str


@dataclass
class Line:
    invoice_no: str
    service_date: date
    code: str
    code_system: str
    description: str
    category: str
    quantity: float
    unit_price: float
    amount: float
    patient_share: float = 0.0
    serial_no: int = 0
    line_id: str = ""


@dataclass
class Bundle:
    member: Member
    policy: Policy
    provider: Dict[str, object]
    claim_type: str
    incident_date: date
    admission_date: Optional[date]
    discharge_date: Optional[date]
    diagnosis: str
    diagnosis_code: str
    currency: str
    doctor: str
    room_category: Optional[str] = None
    lines: List[Line] = field(default_factory=list)
    submitted_at: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    settlement_override: Optional[Callable[["Bundle"], float]] = None
    missing_document_types: List[str] = field(default_factory=list)
    document_facts_override: Dict[str, str] = field(default_factory=dict)
    render: bool = False
    scan: bool = False
    claim_id: str = ""
    order: int = 0

    @property
    def total(self) -> float:
        return money(sum(l.amount for l in self.lines))

    @property
    def market(self) -> str:
        return self.member.market

    @property
    def stay_nights(self) -> int:
        if self.admission_date and self.discharge_date:
            return max(1, (self.discharge_date - self.admission_date).days)
        return 0


@dataclass
class HistoryBundle:
    record: HistoryRecord
    member: Member


@dataclass
class KeyRow:
    bundle: Bundle
    check_id: CheckId
    lines: List[Line]
    amount_kind: str
    note: str
    amount: Optional[float] = None                      # fixed amount, or None to use amount_rule
    amount_rule: str = "fixed"                           # fixed | requested | outlier
    related_bundles: List[Bundle] = field(default_factory=list)
    related_ids: List[str] = field(default_factory=list)


@dataclass
class NegRow:
    bundle: Bundle
    check_id: CheckId
    note: str


@dataclass
class Context:
    rng: random.Random
    products: Dict[str, ProductConfig] = field(default_factory=dict)
    providers: Dict[str, Dict[str, object]] = field(default_factory=dict)
    price_factor: Dict[Tuple[str, str], float] = field(default_factory=dict)
    members: List[Member] = field(default_factory=list)
    policies: Dict[str, Policy] = field(default_factory=dict)
    bundles: List[Bundle] = field(default_factory=list)
    history: List[HistoryBundle] = field(default_factory=list)
    positives: List[KeyRow] = field(default_factory=list)
    negatives: List[NegRow] = field(default_factory=list)
    member_use: Dict[str, int] = field(default_factory=dict)
    reserved: List[str] = field(default_factory=list)
    invoice_seq: Dict[str, int] = field(default_factory=dict)
    history_seq: int = 0

    def member(self, claimant_id: str) -> Member:
        for m in self.members:
            if m.claimant_id == claimant_id:
                return m
        raise KeyError(claimant_id)

    def policy_of(self, member: Member) -> Policy:
        return self.policies[member.policy_number]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def money(x: float) -> float:
    return round(float(x) + 0.0, 2)


def round_price(market: str, price: float) -> float:
    step = 10.0 if market == "IN" else 5.0
    if price >= 100:
        return float(int(round(price / step)) * step)
    return float(round(price))


def base_price(market: str, code: str) -> float:
    return cat.IN_SERVICES[code][2] if market == "IN" else cat.AE_SERVICES[code][2]


def unit_price(ctx: Context, provider_id: str, code: str) -> float:
    market = str(ctx.providers[provider_id]["market"])
    return round_price(market, base_price(market, code) * ctx.price_factor[(provider_id, code)])


def next_invoice(ctx: Context, provider_id: str, year: int = 2026) -> str:
    prefix = str(ctx.providers[provider_id]["invoice_prefix"])
    key = f"{prefix}-{year}"
    ctx.invoice_seq[key] = ctx.invoice_seq.get(key, 0) + 1
    return f"{prefix}-{year}-{ctx.invoice_seq[key]:05d}"


def utc(d: date, hour: int, minute: int) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


def submitted_after(ctx: Context, last_day: date, min_days: int = 3, max_days: int = 12) -> datetime:
    return utc(last_day + timedelta(days=ctx.rng.randint(min_days, max_days)), 9 + ctx.rng.randint(0, 8),
               ctx.rng.randint(0, 59))


def add_line(ctx: Context, b: Bundle, invoice_no: str, code: str, quantity: float, service_date: date,
             price: Optional[float] = None, description: Optional[str] = None, amount: Optional[float] = None) -> Line:
    """Append a catalogue line priced at the claim's provider; price / description / amount can be forced."""
    market = b.market
    if market == "IN":
        desc, category, _ = cat.IN_SERVICES[code]
        code_system = "internal"
    else:
        desc, category, _, code_system = cat.AE_SERVICES[code]
    rate = price if price is not None else unit_price(ctx, str(b.provider["provider_id"]), code)
    line = Line(invoice_no=invoice_no, service_date=service_date, code=code, code_system=code_system,
                description=description or desc, category=category, quantity=float(quantity), unit_price=money(rate),
                amount=money(amount if amount is not None else rate * quantity))
    b.lines.append(line)
    return line


def claim_window(policy: Policy) -> Tuple[date, date]:
    lo = max(policy.start_date + timedelta(days=policy.waiting_period_days + 1), CLAIM_WINDOW[0])
    hi = min(policy.end_date, CLAIM_WINDOW[1])
    return lo, hi


def pick_start_date(ctx: Context, policy: Policy, span_days: int = 0) -> date:
    lo, hi = claim_window(policy)
    room = (hi - lo).days - span_days
    if room < 0:
        raise ValueError(f"policy {policy.policy_number} has no room for a {span_days}-day episode")
    return lo + timedelta(days=ctx.rng.randint(0, room))


def pick_member(ctx: Context, market: str, *, copay: Optional[bool] = None, limits: Optional[Sequence[float]] = None,
                ped: Optional[bool] = None, network_restricted: Optional[bool] = None, reserve: bool = False,
                exclude: Sequence[str] = ()) -> Member:
    """Least-used member whose policy matches the constraints; ties broken by the seeded rng."""
    candidates: List[Member] = []
    for m in ctx.members:
        if m.market != market or m.claimant_id in ctx.reserved or m.claimant_id in exclude:
            continue
        p = ctx.policies[m.policy_number]
        if copay is not None and bool(p.copay.inpatient_pct or p.copay.outpatient_pct) != copay:
            continue
        if limits is not None and p.annual_limit not in limits:
            continue
        if ped is not None and bool(p.declared_ped) != ped:
            continue
        if network_restricted is not None and bool(p.network_provider_ids) != network_restricted:
            continue
        candidates.append(m)
    if not candidates:
        raise ValueError("no member matches the constraints")
    least = min(ctx.member_use.get(m.claimant_id, 0) for m in candidates)
    pool = [m for m in candidates if ctx.member_use.get(m.claimant_id, 0) == least]
    chosen = ctx.rng.choice(pool)
    ctx.member_use[chosen.claimant_id] = ctx.member_use.get(chosen.claimant_id, 0) + 1
    if reserve:
        ctx.reserved.append(chosen.claimant_id)
    return chosen


def reserve_member(ctx: Context, claimant_id: str) -> Member:
    ctx.reserved.append(claimant_id)
    ctx.member_use[claimant_id] = ctx.member_use.get(claimant_id, 0) + 1
    return ctx.member(claimant_id)


def register(ctx: Context, b: Bundle) -> Bundle:
    b.order = len(ctx.bundles)
    ctx.bundles.append(b)
    return b


def positive(ctx: Context, b: Bundle, check: CheckId, lines: List[Line], amount: Optional[float], kind: str, note: str,
             amount_rule: str = "fixed", related_bundles: Sequence[Bundle] = (), related_ids: Sequence[str] = ()) -> None:
    b.tags.append(check.value)
    ctx.positives.append(KeyRow(bundle=b, check_id=check, lines=list(lines), amount=amount, amount_kind=kind,
                                note=note, amount_rule=amount_rule, related_bundles=list(related_bundles),
                                related_ids=list(related_ids)))


def negative(ctx: Context, b: Bundle, check: CheckId, note: str) -> None:
    ctx.negatives.append(NegRow(bundle=b, check_id=check, note=note))


def handler_settlement(b: Bundle, total: Optional[float] = None) -> float:
    """The figure a handler who applies only deductible and copay would propose (deductible first, then copay)."""
    t = b.total if total is None else total
    p = b.policy
    deductible = p.deductible.amount if (p.deductible.basis == "per_visit" and b.claim_type == "outpatient") else 0.0
    pct = {"inpatient": p.copay.inpatient_pct, "daycare": p.copay.inpatient_pct, "outpatient": p.copay.outpatient_pct,
           "pharmacy": p.copay.pharmacy_pct}[b.claim_type]
    return money((t - deductible) * (1 - pct / 100.0))


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
def build_products() -> Dict[str, ProductConfig]:
    in_product = ProductConfig(
        product_id=cat.PRODUCT_IN, name="Retail Health Shield (India)", insurer=cat.INSURER_IN, market="IN",
        currency="INR", required_documents=cat.REQUIRED_DOCUMENTS_IN, non_payable_items=cat.NON_PAYABLE_IN,
        auto_triage_threshold=5000.0, near_duplicate_amount_tolerance_pct=3.0, near_duplicate_days=3,
        repeatable_service_codes=["PHY001", "DIA001", "CHE001"], provider_outlier_zscore=2.5,
        policy_wording_file="data/policies/IN-HEALTH-RETAIL.md")
    ae_product = ProductConfig(
        product_id=cat.PRODUCT_AE, name="Group Health Plan (UAE)", insurer=cat.INSURER_AE, market="AE",
        currency="AED", required_documents=cat.REQUIRED_DOCUMENTS_AE, non_payable_items=cat.NON_PAYABLE_AE,
        auto_triage_threshold=500.0, near_duplicate_amount_tolerance_pct=3.0, near_duplicate_days=3,
        repeatable_service_codes=["97110", "90935", "96413"], provider_outlier_zscore=2.5,
        policy_wording_file="data/policies/AE-HEALTH-GROUP.md")
    return {in_product.product_id: in_product, ae_product.product_id: ae_product}


# ---------------------------------------------------------------------------
# Providers and their price books
# ---------------------------------------------------------------------------
def build_providers(ctx: Context) -> None:
    for p in cat.PROVIDERS:
        ctx.providers[str(p["provider_id"])] = dict(p)
    for p in cat.PROVIDERS:
        pid, market, profile = str(p["provider_id"]), str(p["market"]), str(p["profile"])
        codes = list(cat.IN_SERVICES) if market == "IN" else list(cat.AE_SERVICES)
        for code in codes:
            if profile == "inflated":
                f = ctx.rng.uniform(1.6, 2.2)
            elif market == "IN":
                f = ctx.rng.uniform(0.92, 1.08)
            else:
                f = ctx.rng.uniform(0.95, 1.05)
            ctx.price_factor[(pid, code)] = f


# ---------------------------------------------------------------------------
# Members and policies
# ---------------------------------------------------------------------------
IN_LIMITS = {1: 300000, 2: 500000, 3: 400000, 4: 1000000, 5: 750000, 6: 300000, 7: 500000, 8: 400000, 9: 1000000,
             10: 750000, 11: 300000, 12: 500000, 13: 400000, 14: 1000000, 15: 750000, 16: 300000, 17: 500000,
             18: 400000, 19: 500000, 20: 400000}
IN_COPAY_POLICIES = {2, 4, 6, 8, 10, 12, 14, 16, 17, 18}
IN_PED_POLICIES = {3: ["diabetes"], 7: ["diabetes"], 11: ["diabetes"], 15: ["diabetes"], 5: ["hypertension"],
                   9: ["hypertension"]}
IN_POLICY_COVERAGE_INACTIVE = 19      # ends 2026-03-31
IN_POLICY_NEW = 20                    # starts 2026-02-15: the general waiting period case
AE_RESTRICTED_NETWORK_POLICIES = {1, 2, 3, 4, 5, 6, 7}


def in_sublimits() -> List[Sublimit]:
    return [
        Sublimit(sublimit_id="CATARACT", name="Cataract surgery (per eye, per claim)", limit=40000.0, basis="per_claim",
                 keywords=["cataract", "phaco", "iol"], codes=["SUR-CAT", "MED-IOL", "MED-IOL-PREM"],
                 clause_id=cat.CLAUSES_IN["CATARACT"]),
        Sublimit(sublimit_id="MATERNITY", name="Maternity (per delivery)", limit=50000.0, basis="per_claim",
                 keywords=["maternity", "delivery", "caesarean", "lscs"], codes=["SUR-LSCS", "SUR-NVD"],
                 clause_id=cat.CLAUSES_IN["MATERNITY"]),
        Sublimit(sublimit_id="PHYSIO_SESSIONS", name="Physiotherapy sessions per policy year", limit=20.0,
                 basis="sessions_per_year", keywords=["physiotherapy"], codes=["PHY001"],
                 clause_id=cat.CLAUSES_IN["PHYSIO_SESSIONS"]),
    ]


def in_exclusions() -> List[Exclusion]:
    return [
        Exclusion(exclusion_id="COSMETIC", text="Cosmetic or aesthetic treatment of any description, unless required "
                  "to restore function after an accident covered by this policy.", keywords=["cosmetic", "aesthetic",
                  "rhinoplasty", "liposuction", "scar revision"], codes=["SUR-COS"], clause_id=cat.CLAUSES_IN["COSMETIC"]),
        Exclusion(exclusion_id="DENTAL", text="Dental treatment or surgery of any kind unless necessitated by an "
                  "accidental injury and requiring hospitalisation.", keywords=["dental", "tooth", "root canal",
                  "orthodontic"], codes=["DEN-RCT", "DEN-EXT"], clause_id=cat.CLAUSES_IN["DENTAL"]),
        Exclusion(exclusion_id="OPD_CONSULT", text="Out-patient consultation and treatment not resulting in "
                  "hospitalisation or day care treatment.", keywords=["opd consultation", "outpatient consultation"],
                  codes=["CONS-OPD"], clause_id=cat.CLAUSES_IN["OPD_CONSULT"]),
    ]


def ae_sublimits() -> List[Sublimit]:
    return [
        Sublimit(sublimit_id="MATERNITY", name="Maternity (per pregnancy)", limit=10000.0, basis="per_claim",
                 keywords=["maternity", "delivery", "caesarean", "obstetric"], codes=["59510", "59400"],
                 clause_id=cat.CLAUSES_AE["MATERNITY"]),
        Sublimit(sublimit_id="PHYSIO", name="Physiotherapy sessions per policy year", limit=15.0,
                 basis="sessions_per_year", keywords=["physiotherapy", "therapeutic exercises"], codes=["97110"],
                 clause_id=cat.CLAUSES_AE["PHYSIO"]),
    ]


def ae_exclusions() -> List[Exclusion]:
    return [
        Exclusion(exclusion_id="DENTAL", text="Dental treatment, dental surgery and orthodontics, except emergency "
                  "treatment of accidental injury to sound natural teeth.", keywords=["dental", "tooth", "root canal",
                  "endodontic", "oral evaluation"], codes=["D7140", "D3310", "D0120"], clause_id=cat.CLAUSES_AE["DENTAL"]),
        Exclusion(exclusion_id="OPTICAL", text="Optical services: eye tests for refractive error, spectacles, "
                  "contact lenses and refractive surgery.", keywords=["optical", "refractive", "spectacles"],
                  codes=["92015"], clause_id=cat.CLAUSES_AE["OPTICAL"]),
        Exclusion(exclusion_id="COSMETIC", text="Cosmetic or plastic surgery and treatment to change appearance, "
                  "unless reconstructive after a covered accident or surgery.", keywords=["cosmetic", "blepharoplasty",
                  "aesthetic"], codes=["15823"], clause_id=cat.CLAUSES_AE["COSMETIC"]),
    ]


def synth_person(ctx: Context, market: str, gender: str, surname: str) -> str:
    if market == "IN":
        first = ctx.rng.choice(cat.FIRST_IN_M if gender == "M" else cat.FIRST_IN_F)
    else:
        first = ctx.rng.choice(cat.FIRST_AE_M if gender == "M" else cat.FIRST_AE_F)
    return f"{first} {surname}"


def synth_phone(ctx: Context, market: str) -> str:
    if market == "IN":
        return "+91 9" + "".join(str(ctx.rng.randint(0, 9)) for _ in range(9))
    return "+971 5" + "".join(str(ctx.rng.randint(0, 9)) for _ in range(8))


def synth_bank(ctx: Context, market: str) -> str:
    prefix = "SBX" if market == "IN" else "GBX"
    return prefix + "".join(str(ctx.rng.randint(0, 9)) for _ in range(12))


def synth_address(ctx: Context, market: str) -> Tuple[str, str]:
    if market == "IN":
        city = ctx.rng.choice(cat.CITIES_IN)
        return f"{ctx.rng.randint(2, 180)} {ctx.rng.choice(cat.STREETS_IN)}, {city}", city
    city = ctx.rng.choice(cat.CITIES_AE)
    return f"Flat {ctx.rng.randint(101, 1909)}, {ctx.rng.choice(cat.STREETS_AE)}, {city}", city


def build_members_and_policies(ctx: Context) -> None:
    """20 IN policies x 2 members, 10 AE policies x 2 members. Families share an address, never phone or bank."""
    seq = 0
    for i in range(1, 21):
        policy_number = f"POL-IN-{i:04d}"
        if i == IN_POLICY_COVERAGE_INACTIVE:
            start = date(2025, 4, 1)
        elif i == IN_POLICY_NEW:
            start = date(2026, 2, 15)
        else:
            start = date(2025, 4, 1) + timedelta(days=13 * (i - 1))
        end = start + timedelta(days=364)
        surname = cat.LAST_IN[(i - 1) % len(cat.LAST_IN)]
        address, city = synth_address(ctx, "IN")
        members: List[str] = []
        for k, (gender, rel) in enumerate((("M", "self"), ("F", "spouse"))):
            seq += 1
            cid = f"M-{seq:04d}"
            members.append(cid)
            ctx.members.append(Member(
                claimant_id=cid, name=synth_person(ctx, "IN", gender, surname), gender=gender,
                date_of_birth=date(1968 + ctx.rng.randint(0, 30), ctx.rng.randint(1, 12), ctx.rng.randint(1, 28)),
                policy_number=policy_number, product_id=cat.PRODUCT_IN, market="IN", relationship=rel,
                phone=synth_phone(ctx, "IN"), bank_account=synth_bank(ctx, "IN"), address=address, city=city))
        pct = 10.0 if i in IN_COPAY_POLICIES else 0.0
        limit = float(IN_LIMITS[i])
        ctx.policies[policy_number] = Policy(
            policy_number=policy_number, product_id=cat.PRODUCT_IN, holder_id=members[0], members=members,
            start_date=start, end_date=end, currency="INR", annual_limit=limit,
            deductible=Deductible(amount=0.0, basis="per_claim"),
            copay=Copay(inpatient_pct=pct, outpatient_pct=pct, pharmacy_pct=pct),
            room_rent_limit_per_day=limit * 0.01, icu_limit_per_day=limit * 0.02, sublimits=in_sublimits(),
            exclusions=in_exclusions(), non_payable_items=list(cat.NON_PAYABLE_IN), network_provider_ids=[],
            waiting_period_days=30, ped_waiting_days=730, declared_ped=list(IN_PED_POLICIES.get(i, [])),
            proportionate_deduction=True)
    for j in range(1, 11):
        policy_number = f"POL-AE-{j:04d}"
        surname = cat.LAST_AE[(j - 1) % len(cat.LAST_AE)]
        address, city = synth_address(ctx, "AE")
        members = []
        for gender, rel in (("M", "self"), ("F", "spouse")):
            seq += 1
            cid = f"M-{seq:04d}"
            members.append(cid)
            ctx.members.append(Member(
                claimant_id=cid, name=synth_person(ctx, "AE", gender, surname), gender=gender,
                date_of_birth=date(1970 + ctx.rng.randint(0, 28), ctx.rng.randint(1, 12), ctx.rng.randint(1, 28)),
                policy_number=policy_number, product_id=cat.PRODUCT_AE, market="AE", relationship=rel,
                phone=synth_phone(ctx, "AE"), bank_account=synth_bank(ctx, "AE"), address=address, city=city))
        ctx.policies[policy_number] = Policy(
            policy_number=policy_number, product_id=cat.PRODUCT_AE, holder_id=members[0], members=members,
            start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), currency="AED", annual_limit=150000.0,
            deductible=Deductible(amount=50.0, basis="per_visit"),
            copay=Copay(inpatient_pct=0.0, outpatient_pct=20.0, pharmacy_pct=30.0),
            room_rent_limit_per_day=1500.0, icu_limit_per_day=5000.0, sublimits=ae_sublimits(),
            exclusions=ae_exclusions(), non_payable_items=list(cat.NON_PAYABLE_AE),
            network_provider_ids=list(cat.AE_NETWORK_PROVIDERS) if j in AE_RESTRICTED_NETWORK_POLICIES else [],
            waiting_period_days=0, ped_waiting_days=0, declared_ped=[], proportionate_deduction=False)


# ---------------------------------------------------------------------------
# Clean claim builders
# ---------------------------------------------------------------------------
def new_bundle(ctx: Context, member: Member, provider_id: str, claim_type: str, incident: date, dx: str, icd: str,
               admission: Optional[date] = None, discharge: Optional[date] = None) -> Bundle:
    provider = ctx.providers[provider_id]
    doctors = cat.DOCTORS_IN if member.market == "IN" else cat.DOCTORS_AE
    return Bundle(member=member, policy=ctx.policy_of(member), provider=provider, claim_type=claim_type,
                  incident_date=incident, admission_date=admission, discharge_date=discharge, diagnosis=dx,
                  diagnosis_code=icd, currency="INR" if member.market == "IN" else "AED", doctor=ctx.rng.choice(doctors))


def choose_room(ctx: Context, provider_id: str, policy: Policy) -> Tuple[str, str]:
    """The costliest room class whose rate at this provider sits within the policy's daily limit."""
    chosen = cat.IN_ROOM_CLASSES[0]
    for code, label in cat.IN_ROOM_CLASSES:
        if policy.room_rent_limit_per_day is None or unit_price(ctx, provider_id, code) <= policy.room_rent_limit_per_day:
            chosen = (code, label)
    return chosen


def day_in_stay(ctx: Context, b: Bundle) -> date:
    assert b.admission_date is not None
    return b.admission_date + timedelta(days=ctx.rng.randint(0, b.stay_nights))


def build_in_inpatient(ctx: Context, member: Member, provider_id: str, template: Dict[str, object], *,
                       nights: Optional[int] = None, icu_nights: Optional[int] = None, admission: Optional[date] = None,
                       room_code: Optional[str] = None, room_rate: Optional[float] = None,
                       icu_rate: Optional[float] = None, lab_count: Optional[int] = None) -> Bundle:
    rng = ctx.rng
    policy = ctx.policy_of(member)
    stay = template["stay"]
    nights = nights if nights is not None else rng.randint(stay[0], stay[1])
    icu_range = template.get("icu", (0, 0))
    icu_nights = icu_nights if icu_nights is not None else rng.randint(icu_range[0], icu_range[1])
    icu_nights = min(icu_nights, nights - 1) if nights > 1 else 0
    admission = admission or pick_start_date(ctx, policy, nights)
    discharge = admission + timedelta(days=nights)
    b = new_bundle(ctx, member, provider_id, "inpatient", admission, str(template["dx"]), str(template["icd"]),
                   admission, discharge)
    inv = next_invoice(ctx, provider_id)
    if room_code is None:
        room_code, room_label = choose_room(ctx, provider_id, policy)
    else:
        room_label = dict(cat.IN_ROOM_CLASSES)[room_code]
    b.room_category = room_label
    add_line(ctx, b, inv, room_code, nights - icu_nights, admission, price=room_rate)
    if icu_nights:
        add_line(ctx, b, inv, "ICU001", icu_nights, admission, price=icu_rate)
    add_line(ctx, b, inv, "NUR001", nights, admission)
    add_line(ctx, b, inv, "VIS001", nights, admission)
    proc = template.get("proc")
    if proc == "SUR-NVD":
        add_line(ctx, b, inv, "SUR-NVD", 1, admission)
        add_line(ctx, b, inv, "LR001", 1, admission)       # a normal delivery uses the labour room, not the theatre
    elif proc:
        op_day = admission + timedelta(days=1) if nights > 1 else admission
        add_line(ctx, b, inv, str(proc), 1, op_day)
        add_line(ctx, b, inv, "OT001", 1, op_day)
        add_line(ctx, b, inv, "ANE001", 1, op_day)
        if template.get("implant"):
            add_line(ctx, b, inv, str(template["implant"]), 1, op_day)
    labs = rng.sample(cat.IN_LABS_COMMON, lab_count if lab_count is not None else rng.randint(3, 6))
    if "Dengue" in str(template["dx"]):
        labs.append("LAB-DENGUE")
    if "Enteric" in str(template["dx"]):
        labs.append("LAB-WIDAL")
    for code in labs:
        add_line(ctx, b, inv, code, 1, day_in_stay(ctx, b))
    radiology = ["RAD-XRAY", "RAD-ECG"]
    if proc in ("SUR-APP", "SUR-CHOL", "SUR-HERN"):
        radiology.append(rng.choice(["RAD-USG", "RAD-CT"]))
    elif proc in ("SUR-ORIF", "SUR-TKR"):
        radiology.append("RAD-XRAY-KNEE")
    elif icu_nights:
        radiology.append("RAD-ECHO")
    for code in rng.sample(radiology, rng.randint(1, len(radiology))):
        add_line(ctx, b, inv, code, 1, day_in_stay(ctx, b))
    for code in rng.sample(cat.IN_PHARMA_COMMON, rng.randint(4, 10)):
        add_line(ctx, b, inv, code, rng.randint(2, 12), day_in_stay(ctx, b))
    for code in rng.sample(cat.IN_MEDICAL_PAYABLE, rng.randint(1, 3)):
        add_line(ctx, b, inv, code, rng.randint(1, 3), admission)
    b.submitted_at = submitted_after(ctx, discharge)
    return b


def build_in_daycare_cataract(ctx: Context, member: Member, provider_id: str, *, premium: bool = False,
                              surgeon_rate: Optional[float] = None, ot_rate: Optional[float] = None,
                              on: Optional[date] = None) -> Bundle:
    policy = ctx.policy_of(member)
    day = on or pick_start_date(ctx, policy, 0)
    t = cat.IN_TEMPLATE_CATARACT
    b = new_bundle(ctx, member, provider_id, "daycare", day, str(t["dx"]), str(t["icd"]), day, day)
    b.room_category = "Day care"
    inv = next_invoice(ctx, provider_id)
    add_line(ctx, b, inv, "SUR-CAT", 1, day, price=surgeon_rate)
    add_line(ctx, b, inv, "MED-IOL-PREM" if premium else "MED-IOL", 1, day)
    add_line(ctx, b, inv, "OT-DC", 1, day, price=ot_rate)
    add_line(ctx, b, inv, "VIS001", 1, day)
    add_line(ctx, b, inv, "LAB-RBS", 1, day)
    add_line(ctx, b, inv, "PH-014", 1, day)
    add_line(ctx, b, inv, "PH-002", 10, day)
    b.submitted_at = submitted_after(ctx, day)
    return b


def build_in_daycare_chemo(ctx: Context, member: Member, provider_id: str) -> Bundle:
    policy = ctx.policy_of(member)
    day = pick_start_date(ctx, policy, 0)
    t = cat.IN_TEMPLATE_CHEMO
    b = new_bundle(ctx, member, provider_id, "daycare", day, str(t["dx"]), str(t["icd"]), day, day)
    b.room_category = "Day care"
    inv = next_invoice(ctx, provider_id)
    add_line(ctx, b, inv, "CHE001", 1, day)
    add_line(ctx, b, inv, "PH-020", 1, day)
    add_line(ctx, b, inv, "PH-005", 2, day)
    add_line(ctx, b, inv, "PH-003", 1, day)
    add_line(ctx, b, inv, "PH-004", 2, day)
    add_line(ctx, b, inv, "LAB-CBC", 1, day)
    add_line(ctx, b, inv, "LAB-LFT", 1, day)
    add_line(ctx, b, inv, "VIS001", 1, day)
    add_line(ctx, b, inv, "MED-CAN", 1, day)
    b.submitted_at = submitted_after(ctx, day)
    return b


def build_in_daycare_sessions(ctx: Context, member: Member, provider_id: str, code: str, sessions: int,
                              template: Dict[str, object], gap_days: int) -> Bundle:
    """A course of repeated sessions (dialysis, physiotherapy) on distinct dates: a legitimate repeat."""
    policy = ctx.policy_of(member)
    span = gap_days * (sessions - 1)
    first = pick_start_date(ctx, policy, span)
    b = new_bundle(ctx, member, provider_id, "daycare", first, str(template["dx"]), str(template["icd"]), None, None)
    inv = next_invoice(ctx, provider_id)
    for s in range(sessions):
        add_line(ctx, b, inv, code, 1, first + timedelta(days=gap_days * s))
    if code == "DIA001":
        add_line(ctx, b, inv, "PH-021", sessions, first)
        add_line(ctx, b, inv, "LAB-CBC", 1, first)
        add_line(ctx, b, inv, "LAB-KFT", 1, first)
    else:
        add_line(ctx, b, inv, "VIS001", 1, first)
    b.submitted_at = submitted_after(ctx, first + timedelta(days=span))
    return b


def build_in_pharmacy(ctx: Context, member: Member, provider_id: str) -> Bundle:
    policy = ctx.policy_of(member)
    day = pick_start_date(ctx, policy, 0)
    dx = ctx.rng.choice(cat.IN_INPATIENT_TEMPLATES)
    b = new_bundle(ctx, member, provider_id, "pharmacy", day, f"Post-hospitalisation medicines - {dx['dx']}",
                   str(dx["icd"]))
    inv = next_invoice(ctx, provider_id)
    for code in ctx.rng.sample(cat.IN_PHARMA_COMMON, ctx.rng.randint(5, 10)):
        add_line(ctx, b, inv, code, ctx.rng.randint(5, 30), day)
    b.submitted_at = submitted_after(ctx, day)
    return b


def build_ae_outpatient(ctx: Context, member: Member, provider_id: str, *, visit: Optional[date] = None,
                        template: Optional[Tuple[str, str]] = None) -> Bundle:
    rng = ctx.rng
    policy = ctx.policy_of(member)
    day = visit or pick_start_date(ctx, policy, 0)
    dx, icd = template or rng.choice(cat.AE_OP_TEMPLATES)
    b = new_bundle(ctx, member, provider_id, "outpatient", day, dx, icd)
    inv = next_invoice(ctx, provider_id)
    add_line(ctx, b, inv, rng.choice(cat.AE_CONSULT_CODES), 1, day)
    labs = rng.sample(cat.AE_OP_LABS, rng.randint(1, 3))
    if rng.random() < 0.5:
        labs.append(rng.choice(cat.AE_OP_RADIOLOGY))
    drugs = rng.sample(cat.AE_OP_DRUGS, rng.randint(1, 3))
    while len(labs) + len(drugs) < 4:
        extra = rng.choice([c for c in cat.AE_OP_LABS + cat.AE_OP_DRUGS if c not in labs + drugs])
        (labs if extra in cat.AE_OP_LABS else drugs).append(extra)
    for code in labs:
        add_line(ctx, b, inv, code, 1, day)
    for code in drugs:
        add_line(ctx, b, inv, code, 1, day)
    b.submitted_at = submitted_after(ctx, day, 1, 8)
    return b


def build_ae_pharmacy(ctx: Context, member: Member, provider_id: str) -> Bundle:
    policy = ctx.policy_of(member)
    day = pick_start_date(ctx, policy, 0)
    dx, icd = ctx.rng.choice(cat.AE_OP_TEMPLATES)
    b = new_bundle(ctx, member, provider_id, "pharmacy", day, f"Prescription - {dx}", icd)
    inv = next_invoice(ctx, provider_id)
    for code in ctx.rng.sample(cat.AE_PHARMACY_DRUGS, ctx.rng.randint(5, 8)):
        add_line(ctx, b, inv, code, ctx.rng.randint(1, 2), day)
    b.submitted_at = submitted_after(ctx, day, 1, 8)
    return b


def build_ae_inpatient(ctx: Context, member: Member, provider_id: str, template: Optional[Dict[str, object]] = None,
                       *, nights: Optional[int] = None, admission: Optional[date] = None) -> Bundle:
    rng = ctx.rng
    policy = ctx.policy_of(member)
    t = template or rng.choice(cat.AE_IP_TEMPLATES)
    stay = t["stay"]
    nights = nights if nights is not None else rng.randint(stay[0], stay[1])
    admission = admission or pick_start_date(ctx, policy, nights)
    discharge = admission + timedelta(days=nights)
    b = new_bundle(ctx, member, provider_id, "inpatient", admission, str(t["dx"]), str(t["icd"]), admission, discharge)
    b.room_category = cat.ROOM_CATEGORY_AE
    inv = next_invoice(ctx, provider_id)
    add_line(ctx, b, inv, "ROOM-STD", nights, admission)
    add_line(ctx, b, inv, "NUR-01", nights, admission)
    add_line(ctx, b, inv, "99223", 1, admission)
    if nights > 1:
        add_line(ctx, b, inv, "99232", nights - 1, admission + timedelta(days=1))
    if t.get("proc"):
        op_day = admission if nights == 1 else admission + timedelta(days=1)
        add_line(ctx, b, inv, str(t["proc"]), 1, op_day)
        add_line(ctx, b, inv, str(t["anaes"]), 1, op_day)
        add_line(ctx, b, inv, "OT-01", 1, op_day)
    for code in rng.sample(cat.AE_OP_LABS, rng.randint(2, 4)):
        add_line(ctx, b, inv, code, 1, day_in_stay(ctx, b))
    for code in rng.sample(["71046", "93000", "76700"], rng.randint(1, 2)):
        add_line(ctx, b, inv, code, 1, day_in_stay(ctx, b))
    for code in rng.sample(cat.AE_IP_DRUGS, rng.randint(3, 6)):
        add_line(ctx, b, inv, code, rng.randint(1, 6), day_in_stay(ctx, b))
    b.submitted_at = submitted_after(ctx, discharge)
    return b


def build_clean_claims(ctx: Context, count: int) -> List[Bundle]:
    """Generic clean claims to fill the dataset: a fixed mix of types and providers."""
    rng = ctx.rng
    out: List[Bundle] = []
    mix = (["in_ip"] * 26 + ["in_dc"] * 6 + ["in_ph"] * 7 + ["ae_op"] * 12 + ["ae_ph"] * 4 + ["ae_ip"] * 5)
    while len(mix) < count:
        mix.append(rng.choice(["in_ip", "ae_op"]))
    mix = mix[:count]
    rng.shuffle(mix)
    for kind in mix:
        if kind.startswith("in"):
            member = pick_member(ctx, "IN")
            provider = rng.choice(cat.IN_NORMAL_PROVIDERS + [cat.PROVIDER_RELATED_PARTY])
            if kind == "in_ip":
                b = build_in_inpatient(ctx, member, provider, rng.choice(cat.IN_INPATIENT_TEMPLATES))
            elif kind == "in_dc":
                b = rng.choice([
                    lambda: build_in_daycare_cataract(ctx, member, provider),
                    lambda: build_in_daycare_chemo(ctx, member, provider)])()
            else:
                b = build_in_pharmacy(ctx, member, provider)
        else:
            member = pick_member(ctx, "AE")
            policy = ctx.policy_of(member)
            provider = rng.choice(policy.network_provider_ids or cat.AE_ALL_PROVIDERS)
            if kind == "ae_op":
                b = build_ae_outpatient(ctx, member, provider)
            elif kind == "ae_ph":
                b = build_ae_pharmacy(ctx, member, provider)
            else:
                b = build_ae_inpatient(ctx, member, provider)
        out.append(register(ctx, b))
    return out


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------
def next_history_id(ctx: Context) -> str:
    ctx.history_seq += 1
    return f"HCL-2025-{ctx.history_seq:04d}"


def history_lines(ctx: Context, member: Member, provider_id: str, claim_id: str, invoice_no: str,
                  incident: date) -> List[InvoiceLine]:
    """A small paid episode (3 nights) for a history record that carries lines."""
    rng = ctx.rng
    codes: List[Tuple[str, float, date]] = [("RM-TWIN", 3, incident), ("NUR001", 3, incident), ("VIS001", 3, incident)]
    for code in rng.sample(cat.IN_LABS_COMMON, 2):
        codes.append((code, 1, incident + timedelta(days=rng.randint(0, 2))))
    codes.append((rng.choice(["RAD-XRAY", "RAD-USG", "RAD-ECG"]), 1, incident + timedelta(days=1)))
    for code in rng.sample(cat.IN_PHARMA_COMMON, 3):
        codes.append((code, rng.randint(2, 8), incident + timedelta(days=rng.randint(0, 3))))
    lines: List[InvoiceLine] = []
    for n, (code, qty, day) in enumerate(codes, start=1):
        desc, category, _ = cat.IN_SERVICES[code]
        rate = unit_price(ctx, provider_id, code)
        lines.append(InvoiceLine(line_id=f"{claim_id}:{invoice_no}:{n}", claim_id=claim_id, invoice_no=invoice_no,
                                 serial_no=n, service_date=day, code=code, code_system="internal", description=desc,
                                 category=LineCategory(category), quantity=float(qty), unit_price=rate,
                                 amount=money(rate * qty), provider_id=provider_id))
    return lines


def make_history(ctx: Context, member: Member, provider_id: str, incident: date, requested: Optional[float] = None,
                 with_lines: bool = False, lines: Optional[List[InvoiceLine]] = None, paid_share: float = 1.0,
                 paid_on: Optional[date] = None) -> HistoryBundle:
    policy = ctx.policy_of(member)
    claim_id = next_history_id(ctx)
    invoice_no = next_invoice(ctx, provider_id, year=incident.year)
    if lines is not None:
        built = [l.model_copy(update={"claim_id": claim_id, "invoice_no": invoice_no,
                                      "line_id": f"{claim_id}:{invoice_no}:{l.serial_no}"}) for l in lines]
    elif with_lines:
        built = history_lines(ctx, member, provider_id, claim_id, invoice_no, incident)
    else:
        built = []
    if built:
        requested = money(sum(l.amount for l in built))
    assert requested is not None
    approved = money(requested * paid_share)
    pct = policy.copay.inpatient_pct
    paid = money(approved * (1 - pct / 100.0))
    if paid_on is None:
        paid_on = incident + timedelta(days=ctx.rng.randint(20, 40))
        paid_on = min(max(paid_on, HISTORY_PAID_WINDOW[0]), HISTORY_PAID_WINDOW[1])
    record = HistoryRecord(claim_id=claim_id, policy_number=member.policy_number, claimant_id=member.claimant_id,
                           provider_id=provider_id, incident_date=incident, invoice_numbers=[invoice_no],
                           requested_amount=requested, approved_amount=approved, paid_amount=paid, paid_on=paid_on,
                           lines=built, contact_phone=member.phone, bank_account=member.bank_account,
                           address=member.address)
    hb = HistoryBundle(record=record, member=member)
    ctx.history.append(hb)
    return hb


def build_generic_history(ctx: Context, count: int, with_lines: int) -> None:
    """Earlier claims inside each member's current policy term: IN members from 2025-05, AE members in 2026-01."""
    rng = ctx.rng
    made = 0
    in_with_lines = 0
    in_members = [m for m in ctx.members if m.market == "IN" and ctx.policy_of(m).start_date <= date(2025, 10, 1)
                  and m.claimant_id not in ctx.reserved]
    ae_members = [m for m in ctx.members if m.market == "AE"]
    while made < count:
        if made % 5 == 4:
            m = rng.choice(ae_members)
            incident = date(2026, 1, 2) + timedelta(days=rng.randint(0, 20))
            requested = float(rng.randint(60, 800) * 5)
            make_history(ctx, m, rng.choice(cat.AE_NETWORK_PROVIDERS), incident, requested=requested,
                         paid_share=rng.choice([1.0, 0.95, 0.9]), paid_on=incident + timedelta(days=rng.randint(20, 35)))
        else:
            m = rng.choice(in_members)
            p = ctx.policy_of(m)
            lo = max(p.start_date, date(2025, 5, 1))
            hi = min(p.end_date, date(2026, 1, 20))
            incident = lo + timedelta(days=rng.randint(0, (hi - lo).days))
            provider = rng.choice(cat.IN_NORMAL_PROVIDERS)
            if in_with_lines < with_lines:
                in_with_lines += 1
                make_history(ctx, m, provider, incident, with_lines=True, paid_share=rng.choice([1.0, 0.97, 0.92]))
            else:
                make_history(ctx, m, provider, incident, requested=float(rng.randint(80, 600) * 100),
                             paid_share=rng.choice([1.0, 0.95, 0.9]))
        made += 1


# ---------------------------------------------------------------------------
# Plants: one function per scenario. Each builds its own claims so the key amounts are exact by construction.
# ---------------------------------------------------------------------------
def copy_bundle(ctx: Context, src: Bundle, *, day_shift: int = 0, amount_factor: float = 1.0,
                new_invoice: bool = False, submit_shift_days: int = 21) -> Bundle:
    shift = timedelta(days=day_shift)
    b = Bundle(member=src.member, policy=src.policy, provider=src.provider, claim_type=src.claim_type,
               incident_date=src.incident_date + shift,
               admission_date=src.admission_date + shift if src.admission_date else None,
               discharge_date=src.discharge_date + shift if src.discharge_date else None,
               diagnosis=src.diagnosis, diagnosis_code=src.diagnosis_code, currency=src.currency, doctor=src.doctor,
               room_category=src.room_category)
    invoice_map: Dict[str, str] = {}
    for l in src.lines:
        inv = l.invoice_no
        if new_invoice:
            inv = invoice_map.setdefault(l.invoice_no, next_invoice(ctx, str(src.provider["provider_id"])))
        rate = money(l.unit_price * amount_factor)
        b.lines.append(Line(invoice_no=inv, service_date=l.service_date + shift, code=l.code, code_system=l.code_system,
                            description=l.description, category=l.category, quantity=l.quantity, unit_price=rate,
                            amount=money(rate * l.quantity)))
    assert src.submitted_at is not None
    b.submitted_at = src.submitted_at + timedelta(days=submit_shift_days)
    return b


def plant_duplicate_claim(ctx: Context) -> None:
    """The same invoice resubmitted three weeks later as a new claim (2 cases)."""
    for _ in range(2):
        member = pick_member(ctx, "IN")
        original = register(ctx, build_in_inpatient(ctx, member, ctx.rng.choice(cat.IN_NORMAL_PROVIDERS),
                                                    ctx.rng.choice(cat.IN_INPATIENT_TEMPLATES)))
        copy = register(ctx, copy_bundle(ctx, original))
        positive(ctx, copy, CheckId.DUPLICATE_CLAIM, copy.lines, None, "calculated",
                 "Exact resubmission of an earlier claim: same member, provider, dates, invoice number and lines.",
                 amount_rule="requested", related_bundles=[original])
        negative(ctx, original, CheckId.DUPLICATE_CLAIM, "The original submission; only the later resubmission is a duplicate.")


def plant_duplicate_line(ctx: Context, host: Bundle) -> None:
    """The same test billed twice on one invoice: two standalone claims plus one on the related-party host."""
    rng = ctx.rng
    # (a) IN inpatient, Complete Blood Count twice, identical rows; rendered as a PDF bill
    a = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), "P-001", cat.IN_INPATIENT_TEMPLATES[4]))
    a.render = True
    cbc = next(l for l in a.lines if l.code == "LAB-CBC") if any(l.code == "LAB-CBC" for l in a.lines) else \
        add_line(ctx, a, a.lines[0].invoice_no, "LAB-CBC", 1, day_in_stay(ctx, a))
    dup = add_line(ctx, a, cbc.invoice_no, "LAB-CBC", 1, cbc.service_date, price=cbc.unit_price)
    positive(ctx, a, CheckId.DUPLICATE_LINE, [cbc, dup], dup.amount, "calculated",
             "Complete Blood Count billed twice on the same invoice, same date and amount.")
    # (b) on the related-party host: Liver Function Test twice, second row worded differently, same code
    lft = next((l for l in host.lines if l.code == "LAB-LFT"), None) or \
        add_line(ctx, host, host.lines[0].invoice_no, "LAB-LFT", 1, day_in_stay(ctx, host))
    dup_b = add_line(ctx, host, lft.invoice_no, "LAB-LFT", 1, lft.service_date, price=lft.unit_price,
                     description="LFT (Liver Function Test)")
    positive(ctx, host, CheckId.DUPLICATE_LINE, [lft, dup_b], dup_b.amount, "calculated",
             "Liver Function Test billed twice (second row worded 'LFT'), same code, date and amount.")
    # (c) AE inpatient, CPT 85025 CBC twice
    c = register(ctx, build_ae_inpatient(ctx, pick_member(ctx, "AE", network_restricted=True), "P-004",
                                         cat.AE_IP_TEMPLATES[2]))
    first = next((l for l in c.lines if l.code == "85025"), None) or \
        add_line(ctx, c, c.lines[0].invoice_no, "85025", 1, day_in_stay(ctx, c))
    dup_c = add_line(ctx, c, first.invoice_no, "85025", 1, first.service_date, price=first.unit_price)
    positive(ctx, c, CheckId.DUPLICATE_LINE, [first, dup_c], dup_c.amount, "calculated",
             "CPT 85025 CBC billed twice on the same activity date.")
    rng.random()


def plant_cross_claim_duplicate_line(ctx: Context) -> None:
    """A readmission on the day the earlier (paid) claim ended; one line of the paid bill is billed again (2 cases)."""
    for provider_id, template in (("P-002", cat.IN_INPATIENT_TEMPLATES[8]), ("P-003", cat.IN_INPATIENT_TEMPLATES[4])):
        member = pick_member(ctx, "IN")
        policy = ctx.policy_of(member)
        nights = 4
        admission = max(pick_start_date(ctx, policy, nights + 60), claim_window(policy)[0] + timedelta(days=4))
        earlier_incident = admission - timedelta(days=4)
        hist = make_history(ctx, member, provider_id, earlier_incident, with_lines=True, paid_share=1.0,
                            paid_on=admission + timedelta(days=28))
        # put the shared line on the history's last day = the new admission day
        shared_code = "RAD-CT"
        desc, category, _ = cat.IN_SERVICES[shared_code]
        rate = unit_price(ctx, provider_id, shared_code)
        n = len(hist.record.lines) + 1
        inv = hist.record.invoice_numbers[0]
        shared = InvoiceLine(line_id=f"{hist.record.claim_id}:{inv}:{n}", claim_id=hist.record.claim_id, invoice_no=inv,
                             serial_no=n, service_date=admission, code=shared_code, code_system="internal",
                             description=desc, category=LineCategory(category), quantity=1.0, unit_price=rate,
                             amount=rate, provider_id=provider_id)
        hist.record.lines.append(shared)
        total = money(sum(l.amount for l in hist.record.lines))
        hist.record.requested_amount = total
        hist.record.approved_amount = total
        hist.record.paid_amount = money(total * (1 - policy.copay.inpatient_pct / 100.0))
        b = register(ctx, build_in_inpatient(ctx, member, provider_id, template, nights=nights, admission=admission))
        rebilled = add_line(ctx, b, b.lines[0].invoice_no, shared_code, 1, admission, price=rate)
        positive(ctx, b, CheckId.CROSS_CLAIM_DUPLICATE_LINE, [rebilled], rebilled.amount, "calculated",
                 f"CT scan dated {admission.isoformat()} was already paid on history claim {hist.record.claim_id} "
                 f"(line {shared.line_id}); readmission on the day the earlier episode ended.",
                 related_ids=[hist.record.claim_id])


def plant_near_duplicate(ctx: Context) -> None:
    """Resubmission with the dates moved by one day, every amount up 2% and a fresh invoice number (3 cases)."""
    originals = [
        register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), "P-001", cat.IN_INPATIENT_TEMPLATES[1])),
        register(ctx, build_ae_outpatient(ctx, pick_member(ctx, "AE", network_restricted=True), "P-005")),
    ]
    for original in originals:
        copy = register(ctx, copy_bundle(ctx, original, day_shift=1, amount_factor=1.02, new_invoice=True,
                                         submit_shift_days=10))
        positive(ctx, copy, CheckId.NEAR_DUPLICATE, copy.lines, None, "suspected",
                 "Same member, provider and lines as an earlier claim, dates +1 day, amounts +2%, new invoice number.",
                 amount_rule="requested", related_bundles=[original])
        negative(ctx, original, CheckId.NEAR_DUPLICATE, "The original; only the later near-copy should be flagged.")
    # third case: near-copy of a claim already paid in history
    member = pick_member(ctx, "IN")
    hist = make_history(ctx, member, "P-002", date(2026, 1, 12), with_lines=True, paid_share=1.0,
                        paid_on=date(2026, 2, 16))
    src = new_bundle(ctx, member, "P-002", "inpatient", date(2026, 1, 12), "Acute gastroenteritis with dehydration",
                     "A09", date(2026, 1, 12), date(2026, 1, 15))
    src.room_category = "Twin sharing"
    for l in hist.record.lines:
        src.lines.append(Line(invoice_no=l.invoice_no, service_date=l.service_date or date(2026, 1, 12), code=l.code or "",
                              code_system=l.code_system or "internal", description=l.description,
                              category=l.category.value if l.category else "other", quantity=l.quantity,
                              unit_price=l.unit_price or 0.0, amount=l.amount))
    src.submitted_at = utc(date(2026, 1, 20), 10, 0)
    copy = register(ctx, copy_bundle(ctx, src, day_shift=1, amount_factor=1.02, new_invoice=True, submit_shift_days=40))
    positive(ctx, copy, CheckId.NEAR_DUPLICATE, copy.lines, None, "suspected",
             f"Near-copy of history claim {hist.record.claim_id} (paid {hist.record.paid_on}): dates +1 day, "
             "amounts +2%, new invoice number.", amount_rule="requested", related_ids=[hist.record.claim_id])


def plant_legit_repeats(ctx: Context) -> None:
    """Repeated services that must NOT be flagged: physio x6 (two members), dialysis x3, CBC on two dates (x2)."""
    tkr = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN", limits=[750000.0, 1000000.0]), "P-002",
                                           cat.IN_TEMPLATE_TKR, nights=8))
    inv = tkr.lines[0].invoice_no
    for s in range(6):
        add_line(ctx, tkr, inv, "PHY001", 1, tkr.admission_date + timedelta(days=2 + s))
    physio = register(ctx, build_in_daycare_sessions(ctx, pick_member(ctx, "IN"), "P-003", "PHY001", 6,
                                                     cat.IN_TEMPLATE_PHYSIO, gap_days=2))
    dialysis = register(ctx, build_in_daycare_sessions(ctx, pick_member(ctx, "IN"), "P-001", "DIA001", 3,
                                                       cat.IN_TEMPLATE_DIALYSIS, gap_days=3))
    for b, what in ((tkr, "6 physiotherapy sessions on 6 distinct dates after knee replacement"),
                    (physio, "6 physiotherapy sessions on 6 distinct dates (course of treatment)"),
                    (dialysis, "3 haemodialysis sessions on 3 distinct dates")):
        negative(ctx, b, CheckId.DUPLICATE_LINE, f"Legitimate repeat: {what}; PHY001/DIA001 are repeatable codes.")
        negative(ctx, b, CheckId.NEAR_DUPLICATE, f"Legitimate repeat: {what}.")
    negative(ctx, tkr, CheckId.SUBLIMIT_EXCEEDED, "6 physiotherapy sessions are inside the 20-sessions-per-year sub-limit.")
    negative(ctx, physio, CheckId.SUBLIMIT_EXCEEDED, "6 physiotherapy sessions are inside the 20-sessions-per-year sub-limit.")
    for _ in range(2):
        b = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), ctx.rng.choice(cat.IN_NORMAL_PROVIDERS),
                                             cat.IN_INPATIENT_TEMPLATES[6], nights=5))
        cbc = next((l for l in b.lines if l.code == "LAB-CBC"), None)
        if cbc is None:
            cbc = add_line(ctx, b, b.lines[0].invoice_no, "LAB-CBC", 1, b.admission_date)
        cbc.service_date = b.admission_date
        add_line(ctx, b, cbc.invoice_no, "LAB-CBC", 1, b.admission_date + timedelta(days=3), price=cbc.unit_price)
        negative(ctx, b, CheckId.DUPLICATE_LINE, "Complete Blood Count on admission and again three days later: "
                 "distinct service dates, a legitimate repeat in dengue monitoring.")


def plant_room_limit(ctx: Context) -> List[Bundle]:
    """Room / ICU charged above the daily limit (4 cases); the first is the brief's own example."""
    out: List[Bundle] = []
    # the brief: room 5,000/day against a 3,000 limit for 3 days = 6,000
    m = pick_member(ctx, "IN", copay=False, limits=[300000.0])
    b = register(ctx, build_in_inpatient(ctx, m, "P-001", cat.IN_INPATIENT_TEMPLATES[0], nights=3, icu_nights=0,
                                         room_code="RM-SGL", room_rate=5000.0))
    b.render = True
    room = b.lines[0]
    positive(ctx, b, CheckId.ROOM_LIMIT_EXCEEDED, [room], money((5000 - 3000) * 3), "calculated",
             "Room 5,000/day vs limit 3,000/day (1% of 300,000) for 3 days: (5,000 - 3,000) x 3 = 6,000.")
    out.append(b)
    specs = [
        ("P-002", 500000.0, "RM-DLX", 7000.0, 4, None, None),     # limit 5,000: (7,000-5,000) x 4 = 8,000
        ("P-003", 400000.0, "RM-SGL", 4800.0, 2, None, None),     # limit 4,000: (4,800-4,000) x 2 = 1,600 (under triage)
        ("P-001", 300000.0, None, None, 5, 2, 8000.0),            # ICU limit 6,000: (8,000-6,000) x 2 = 4,000
    ]
    for provider, limit, room_code, room_rate, nights, icu_nights, icu_rate in specs:
        m = pick_member(ctx, "IN", limits=[limit])
        policy = ctx.policy_of(m)
        b = register(ctx, build_in_inpatient(ctx, m, provider, ctx.rng.choice(cat.IN_INPATIENT_TEMPLATES[4:9]),
                                             nights=nights, icu_nights=icu_nights or 0, room_code=room_code,
                                             room_rate=room_rate, icu_rate=icu_rate))
        if icu_nights:
            icu = next(l for l in b.lines if l.code == "ICU001")
            excess = money((icu.unit_price - policy.icu_limit_per_day) * icu.quantity)
            positive(ctx, b, CheckId.ROOM_LIMIT_EXCEEDED, [icu], excess, "calculated",
                     f"ICU {icu.unit_price:,.0f}/day vs ICU limit {policy.icu_limit_per_day:,.0f}/day for "
                     f"{icu.quantity:.0f} days = {excess:,.0f}.")
        else:
            room = b.lines[0]
            excess = money((room.unit_price - policy.room_rent_limit_per_day) * room.quantity)
            positive(ctx, b, CheckId.ROOM_LIMIT_EXCEEDED, [room], excess, "calculated",
                     f"Room {room.unit_price:,.0f}/day vs limit {policy.room_rent_limit_per_day:,.0f}/day for "
                     f"{room.quantity:.0f} days = {excess:,.0f}.")
        out.append(b)
    return out


def plant_excluded_service(ctx: Context) -> List[Bundle]:
    """Excluded services: a cosmetic add-on line, a dental line on a hospital bill, dental codes on a UAE visit."""
    out: List[Bundle] = []
    a = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), "P-002", cat.IN_INPATIENT_TEMPLATES[3]))
    cos = add_line(ctx, a, a.lines[0].invoice_no, "SUR-COS", 1, a.admission_date + timedelta(days=2))
    positive(ctx, a, CheckId.EXCLUDED_SERVICE, [cos], cos.amount, "calculated",
             f"Cosmetic scar revision is excluded (clause {cat.CLAUSES_IN['COSMETIC']}).")
    out.append(a)
    b = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), "P-003", cat.IN_INPATIENT_TEMPLATES[5]))
    rct = add_line(ctx, b, b.lines[0].invoice_no, "DEN-RCT", 1, b.admission_date + timedelta(days=1))
    positive(ctx, b, CheckId.EXCLUDED_SERVICE, [rct], rct.amount, "calculated",
             f"Dental treatment is excluded (clause {cat.CLAUSES_IN['DENTAL']}).")
    out.append(b)
    c = register(ctx, build_ae_outpatient(ctx, pick_member(ctx, "AE", network_restricted=True), "P-004",
                                          template=("Acute tonsillitis", "J03.90")))
    d1 = add_line(ctx, c, c.lines[0].invoice_no, "D0120", 1, c.incident_date)
    d2 = add_line(ctx, c, c.lines[0].invoice_no, "D7140", 1, c.incident_date)
    positive(ctx, c, CheckId.EXCLUDED_SERVICE, [d1, d2], money(d1.amount + d2.amount), "calculated",
             f"Dental codes D0120 and D7140 are excluded (clause {cat.CLAUSES_AE['DENTAL']}).")
    out.append(c)
    return out


def add_non_payables(ctx: Context, b: Bundle, codes: Sequence[str]) -> List[Line]:
    inv = b.lines[0].invoice_no
    day = b.admission_date or b.incident_date
    days = max(1, b.stay_nights)
    lines: List[Line] = []
    for code in codes:
        desc = (cat.IN_SERVICES if b.market == "IN" else cat.AE_SERVICES)[code][0]
        per_day = "(per day)" in desc
        qty = days if per_day else {"CONS-GLV": 10, "CONS-SYR": 20, "CONS-WATER": 6, "CONS-MASK": 10}.get(code, 1)
        lines.append(add_line(ctx, b, inv, code, qty, day))
    return lines


def plant_non_payable(ctx: Context, hosts: Sequence[Bundle]) -> List[Bundle]:
    """Non-payable consumables on 10 claims: the hosts plus three standalone claims (two IN, one AE)."""
    rng = ctx.rng
    in_sets = [["CONS-GLV", "CONS-SYR", "CONS-ADM"], ["CONS-ADM", "CONS-TOIL", "CONS-WATER", "CONS-DIET"],
               ["CONS-REG", "CONS-DOC", "CONS-TV"], ["CONS-GLV", "CONS-COT", "CONS-THERM", "CONS-NEB"],
               ["CONS-BELT", "CONS-CREPE", "CONS-SPIRIT"], ["CONS-ADM", "CONS-TEL", "CONS-VIS", "CONS-ATT"],
               ["CONS-MASK", "CONS-SAN", "CONS-TIS", "CONS-SLIP"], ["CONS-BP", "CONS-UP", "CONS-HWB", "CONS-GLV"]]
    ae_sets = [["NP-AE-07", "NP-AE-08", "NP-AE-04"], ["NP-AE-06", "NP-AE-05", "NP-AE-12"]]
    targets: List[Bundle] = list(hosts)
    targets.append(register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), "P-001", cat.IN_INPATIENT_TEMPLATES[2])))
    targets.append(register(ctx, build_ae_inpatient(ctx, pick_member(ctx, "AE", network_restricted=True), "P-004",
                                                    cat.AE_IP_TEMPLATES[5])))
    out: List[Bundle] = []
    i_in = 0
    for b in targets:
        if b.market == "IN":
            codes = in_sets[i_in % len(in_sets)]
            i_in += 1
        else:
            codes = ae_sets[0]
        lines = add_non_payables(ctx, b, codes)
        names = sorted({cat.non_payable_name_for(l.code, b.market) or "" for l in lines})
        positive(ctx, b, CheckId.NON_PAYABLE_ITEM, lines, money(sum(l.amount for l in lines)), "calculated",
                 f"Non-payable items on the bill: {', '.join(names)} (sum of those lines).")
        out.append(b)
    rng.random()
    return out


def plant_sublimit(ctx: Context) -> List[Bundle]:
    """Cataract billed 55,000 against a 40,000 sub-limit; LSCS delivery 68,000 against 50,000."""
    out: List[Bundle] = []
    m = pick_member(ctx, "IN", copay=False)
    # 55,000 = surgeon 18,000 + premium IOL 25,000 + theatre 9,000 + visit 800 + RBS 120 + drops 140 + paracetamol 30 ...
    b = register(ctx, build_in_daycare_cataract(ctx, m, "P-002", premium=True, surgeon_rate=18000.0, ot_rate=9000.0))
    filler = money(55000 - b.total)
    add_line(ctx, b, b.lines[0].invoice_no, "ANE001", 1, b.incident_date, price=filler)
    assert b.total == 55000.0, b.total
    b.render = True
    positive(ctx, b, CheckId.SUBLIMIT_EXCEEDED, b.lines, money(55000 - 40000), "calculated",
             f"Cataract claim total 55,000 vs sub-limit 40,000 per eye per claim (clause {cat.CLAUSES_IN['CATARACT']}) = 15,000.")
    out.append(b)
    m2 = pick_member(ctx, "IN", copay=False, limits=[500000.0, 750000.0, 1000000.0])
    c = register(ctx, build_in_inpatient(ctx, m2, "P-001", cat.IN_TEMPLATE_LSCS, nights=3, icu_nights=0, lab_count=3))
    target = float((int(c.total) // 5000 + 2) * 5000)      # the next round figure at least 5,000 above the lines
    add_line(ctx, c, c.lines[0].invoice_no, "PH-024", 1, c.admission_date + timedelta(days=1),
             price=money(target - c.total), description="Inj. Oxytocin 10 IU and labour room charges")
    assert c.total == target, c.total
    positive(ctx, c, CheckId.SUBLIMIT_EXCEEDED, c.lines, money(target - 50000), "calculated",
             f"Maternity claim total {target:,.0f} vs sub-limit 50,000 per delivery (clause "
             f"{cat.CLAUSES_IN['MATERNITY']}) = {target - 50000:,.0f}.")
    out.append(c)
    return out


def plant_benefit_limit(ctx: Context) -> None:
    """Members whose paid history leaves less than the new claim needs (2 cases)."""
    specs = [("M-0001", "P-001", [180000.0, 95000.0], 300000.0), ("M-0025", "P-003", [320000.0, 60000.0], 400000.0)]
    for cid, provider, paid, limit in specs:
        m = reserve_member(ctx, cid)
        policy = ctx.policy_of(m)
        assert policy.annual_limit == limit and policy.copay.inpatient_pct == 0
        incidents = [policy.start_date + timedelta(days=150), policy.start_date + timedelta(days=230)]
        hist_ids: List[str] = []
        for amount, incident in zip(paid, incidents):
            h = make_history(ctx, m, provider, incident, requested=amount, paid_share=1.0,
                             paid_on=incident + timedelta(days=30))
            hist_ids.append(h.record.claim_id)
        remaining = money(limit - sum(paid))
        b = register(ctx, build_in_inpatient(ctx, m, provider, cat.IN_INPATIENT_TEMPLATES[3], nights=6,
                                             admission=incidents[1] + timedelta(days=60)))
        excess = money(b.total - remaining)
        assert excess > 0
        positive(ctx, b, CheckId.BENEFIT_LIMIT_EXCEEDED, [], excess, "calculated",
                 f"History paid {sum(paid):,.0f} of the {limit:,.0f} annual limit ({', '.join(hist_ids)}); "
                 f"{remaining:,.0f} remains; claim {b.total:,.0f} exceeds it by {excess:,.0f}.",
                 related_ids=hist_ids)
        b.settlement_override = lambda bb: bb.total     # the handler ignored the exhausted limit


def plant_copay_not_applied(ctx: Context) -> List[Bundle]:
    """Handler proposed the full amount on a 10% copay policy (3 cases)."""
    out: List[Bundle] = []
    builders = [
        lambda m: build_in_inpatient(ctx, m, "P-002", cat.IN_INPATIENT_TEMPLATES[1]),
        lambda m: build_in_inpatient(ctx, m, "P-003", cat.IN_INPATIENT_TEMPLATES[7]),
        lambda m: build_in_daycare_chemo(ctx, m, "P-001"),
    ]
    for build in builders:
        m = pick_member(ctx, "IN", copay=True)
        b = register(ctx, build(m))
        b.settlement_override = lambda bb: bb.total
        positive(ctx, b, CheckId.COPAY_NOT_APPLIED, [], money(b.total * 0.10), "calculated",
                 f"Proposed settlement equals the full {b.total:,.0f}; the 10% copay ({b.total * 0.10:,.0f}) was not applied.")
        negative(ctx, b, CheckId.SETTLEMENT_MISMATCH, "The gap is exactly the missed copay; do not double count.")
        out.append(b)
    return out


def plant_deductible_not_applied(ctx: Context) -> List[Bundle]:
    """UAE outpatient visits where the handler applied the 20% copay but forgot the AED 50 per-visit deductible."""
    out: List[Bundle] = []
    for provider in ("P-004", "P-005", "P-004"):
        m = pick_member(ctx, "AE", network_restricted=True)
        b = register(ctx, build_ae_outpatient(ctx, m, provider))
        b.settlement_override = lambda bb: money(bb.total * 0.80)
        correct = handler_settlement(b)
        leak = money(b.total * 0.80 - correct)
        positive(ctx, b, CheckId.DEDUCTIBLE_NOT_APPLIED, [], leak, "calculated",
                 f"Proposed {b.total * 0.80:,.2f} = 80% of {b.total:,.2f}; correct is (total - 50 deductible) x 80% = "
                 f"{correct:,.2f}; leakage {leak:,.2f} (= 50 x 80% because the copay applies after the deductible).")
        negative(ctx, b, CheckId.SETTLEMENT_MISMATCH, "The gap is exactly the missed deductible; do not double count.")
        out.append(b)
    return out


def plant_settlement_mismatch(ctx: Context) -> None:
    """Proposed settlement above the recalculation for a reason no other check explains (2 cases)."""
    m = pick_member(ctx, "IN", copay=False)
    a = register(ctx, build_in_inpatient(ctx, m, "P-002", cat.IN_INPATIENT_TEMPLATES[2]))
    discount = add_line(ctx, a, a.lines[0].invoice_no, "OT001", 1, a.discharge_date, price=-5000.0,
                        description="Hospital discount (corporate tie-up)")
    a.settlement_override = lambda bb: money(bb.total + 5000.0)
    positive(ctx, a, CheckId.SETTLEMENT_MISMATCH, [discount], 5000.0, "calculated",
             "The bill carries a -5,000 hospital discount line; the handler proposed the gross amount (net + 5,000).")
    m2 = pick_member(ctx, "AE", network_restricted=True)
    b = register(ctx, build_ae_inpatient(ctx, m2, "P-005", cat.AE_IP_TEMPLATES[0]))
    b.settlement_override = lambda bb: money(bb.total + 400.0)
    positive(ctx, b, CheckId.SETTLEMENT_MISMATCH, [], 400.0, "calculated",
             "Inpatient, no copay or deductible: proposed is 400 above the line total (keying error).")


def plant_quantity_vs_stay(ctx: Context) -> None:
    """Room billed for more days than the stay (2 cases); each also carries a line dated after discharge."""
    for provider, template, nights, extra_days in (("P-001", cat.IN_INPATIENT_TEMPLATES[0], 3, 2),
                                                   ("P-003", cat.IN_INPATIENT_TEMPLATES[6], 4, 3)):
        m = pick_member(ctx, "IN")
        b = register(ctx, build_in_inpatient(ctx, m, provider, template, nights=nights, icu_nights=0))
        room = b.lines[0]
        room.quantity = float(nights + extra_days)
        room.amount = money(room.unit_price * room.quantity)
        positive(ctx, b, CheckId.QUANTITY_VS_STAY, [room], money(room.unit_price * extra_days), "calculated",
                 f"Room billed for {nights + extra_days} days; stay is {nights} nights ({b.admission_date} to "
                 f"{b.discharge_date}); {extra_days} x {room.unit_price:,.0f} = {room.unit_price * extra_days:,.0f}.")
        late = add_line(ctx, b, room.invoice_no, "LAB-LIPID", 1, b.discharge_date + timedelta(days=4))
        positive(ctx, b, CheckId.DATE_OUTSIDE_EPISODE, [late], late.amount, "calculated",
                 f"Lipid Profile dated {late.service_date}, four days after discharge on {b.discharge_date}.")
        negative(ctx, b, CheckId.SETTLEMENT_MISMATCH, "The gap equals the extra room days plus the late line; do not double count.")


def plant_arithmetic_mismatch(ctx: Context, host: Bundle) -> None:
    """qty x rate != amount: one standalone claim (rendered) and one on an inflated-provider host."""
    m = pick_member(ctx, "IN")
    a = register(ctx, build_in_inpatient(ctx, m, "P-002", cat.IN_INPATIENT_TEMPLATES[4]))
    a.render = True
    bad = add_line(ctx, a, a.lines[0].invoice_no, "PH-006", 3, a.admission_date + timedelta(days=1), price=1200.0,
                   amount=4600.0)
    positive(ctx, a, CheckId.ARITHMETIC_MISMATCH, [bad], money(4600 - 3 * 1200), "calculated",
             "Inj. Enoxaparin: 3 x 1,200 = 3,600 but the line amount printed is 4,600; excess 1,000.")
    lab = next(l for l in host.lines if l.category == "lab")
    lab.quantity = 2.0
    lab.amount = money(lab.unit_price * 2 + 800)
    positive(ctx, host, CheckId.ARITHMETIC_MISMATCH, [lab], 800.0, "calculated",
             f"{lab.description}: 2 x {lab.unit_price:,.0f} = {lab.unit_price * 2:,.0f} but the amount printed is "
             f"{lab.amount:,.0f}; excess 800.")


def plant_coverage_inactive(ctx: Context) -> None:
    """Admission after the policy ended (policy 19 ends 2026-03-31)."""
    m = reserve_member(ctx, "M-0037")
    policy = ctx.policy_of(m)
    assert policy.end_date == date(2026, 3, 31)
    b = register(ctx, build_in_inpatient(ctx, m, "P-003", cat.IN_INPATIENT_TEMPLATES[7], nights=3,
                                         admission=date(2026, 5, 10)))
    positive(ctx, b, CheckId.COVERAGE_INACTIVE, [], None, "calculated",
             f"Admission 2026-05-10 is after the policy end date {policy.end_date}; nothing is payable.",
             amount_rule="requested")


def plant_waiting_period(ctx: Context) -> None:
    """(a) admission 18 days into a new policy (30-day waiting period); (b) a declared PED inside 730 days."""
    m = reserve_member(ctx, "M-0039")
    policy = ctx.policy_of(m)
    assert policy.start_date == date(2026, 2, 15)
    b = register(ctx, build_in_inpatient(ctx, m, "P-002", cat.IN_INPATIENT_TEMPLATES[5], nights=2,
                                         admission=date(2026, 3, 5)))
    positive(ctx, b, CheckId.WAITING_PERIOD, [], None, "calculated",
             f"Admission 2026-03-05 is 18 days after policy start {policy.start_date}; the 30-day waiting period "
             f"(clause {cat.CLAUSES_IN['WAITING']}) applies.", amount_rule="requested")
    m2 = reserve_member(ctx, "M-0005")
    policy2 = ctx.policy_of(m2)
    assert "diabetes" in policy2.declared_ped and policy2.copay.inpatient_pct == 0
    c = register(ctx, build_in_inpatient(ctx, m2, "P-001", cat.IN_TEMPLATE_PED, nights=4))
    positive(ctx, c, CheckId.WAITING_PERIOD, [], None, "calculated",
             f"Diagnosis names the declared pre-existing condition 'diabetes'; policy started {policy2.start_date}, "
             f"inside the 730-day PED waiting period (clause {cat.CLAUSES_IN['PED']}).", amount_rule="requested")


def plant_out_of_network(ctx: Context) -> None:
    """UAE inpatient admissions at the out-of-network hospital under restricted-network policies (2 cases)."""
    for template in (cat.AE_IP_TEMPLATES[1], cat.AE_IP_TEMPLATES[3]):
        m = pick_member(ctx, "AE", network_restricted=True)
        b = register(ctx, build_ae_inpatient(ctx, m, "P-006", template))
        positive(ctx, b, CheckId.OUT_OF_NETWORK, [], None, "calculated",
                 f"Provider P-006 is not in the policy network {ctx.policy_of(m).network_provider_ids}; no cover outside "
                 f"the network except emergencies (clause {cat.CLAUSES_AE['NETWORK']}).", amount_rule="requested")


def plant_provider_outlier(ctx: Context) -> List[Bundle]:
    """Four admissions at the inflated provider P-007 (unit prices 1.6-2.2x the peers)."""
    out: List[Bundle] = []
    for template in (cat.IN_INPATIENT_TEMPLATES[0], cat.IN_INPATIENT_TEMPLATES[1], cat.IN_INPATIENT_TEMPLATES[4],
                     cat.IN_INPATIENT_TEMPLATES[3]):
        m = pick_member(ctx, "IN", limits=[750000.0, 1000000.0])
        b = register(ctx, build_in_inpatient(ctx, m, cat.PROVIDER_INFLATED, template))
        positive(ctx, b, CheckId.PROVIDER_PRICE_OUTLIER, b.lines, None, "suspected",
                 "Every unit price at P-007 is 1.6-2.2x the catalogue base the other providers bill around; amount = "
                 "sum over lines of (unit price - base price) x qty. Compute peer stats leaving P-007 out.",
                 amount_rule="outlier")
        out.append(b)
    return out


def plant_related_party(ctx: Context) -> List[Bundle]:
    """Five claimants on five different policies share one phone, bank account and address; all claim at P-008."""
    ring = ["M-0012", "M-0016", "M-0020", "M-0024", "M-0028"]
    shared_phone, shared_bank = "+91 9822004411", "SBX440011223344"
    shared_address = "17 Canal Side, Nagpur"
    out: List[Bundle] = []
    for cid in ring:
        m = reserve_member(ctx, cid)
        m.phone, m.bank_account, m.address, m.city = shared_phone, shared_bank, shared_address, "Nagpur"
    for cid, template in zip(ring, cat.IN_INPATIENT_TEMPLATES[4:9]):
        b = register(ctx, build_in_inpatient(ctx, ctx.member(cid), cat.PROVIDER_RELATED_PARTY, template))
        out.append(b)
    for b in out:
        positive(ctx, b, CheckId.RELATED_PARTY_PATTERN, [], None, "suspected",
                 f"Phone {shared_phone}, bank {shared_bank} and address are shared by five claimants on different "
                 "policies, all treated at P-008.", amount_rule="requested", related_bundles=[o for o in out if o is not b])
    return out


def plant_consistency_mismatch(ctx: Context) -> None:
    """The attached bill carries another member's name (case 1) or policy number (case 2); both rendered."""
    others = [m for m in ctx.members if m.market == "IN" and m.claimant_id not in ctx.reserved]
    a_member = pick_member(ctx, "IN")
    a = register(ctx, build_in_inpatient(ctx, a_member, "P-001", cat.IN_INPATIENT_TEMPLATES[6]))
    other = next(m for m in others if m.policy_number != a_member.policy_number)
    a.render = True
    a.document_facts_override = {"claimant_name": other.name}
    positive(ctx, a, CheckId.CONSISTENCY_MISMATCH, [], None, "suspected",
             f"The bill names '{other.name}' ({other.claimant_id}) but the claim is for '{a_member.name}' "
             f"({a_member.claimant_id}).", amount_rule="requested")
    b_member = pick_member(ctx, "IN", exclude=[other.claimant_id])
    b = register(ctx, build_in_inpatient(ctx, b_member, "P-003", cat.IN_INPATIENT_TEMPLATES[1]))
    other2 = next(m for m in others if m.policy_number not in (b_member.policy_number, a_member.policy_number,
                                                               other.policy_number))
    b.render = True
    b.document_facts_override = {"policy_number": other2.policy_number}
    positive(ctx, b, CheckId.CONSISTENCY_MISMATCH, [], None, "suspected",
             f"The bill prints policy {other2.policy_number} but the claim is under {b_member.policy_number}.",
             amount_rule="requested")


def plant_missing_evidence(ctx: Context, hosts: Sequence[Bundle]) -> None:
    """Required documents absent: two related-party hosts and one standalone claim. Amount 0: ask, do not invent."""
    specs = [(hosts[0], ["itemized_final_hospital_bill"]), (hosts[1], ["discharge_summary"])]
    standalone = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), "P-002", cat.IN_INPATIENT_TEMPLATES[9]))
    specs.append((standalone, ["discharge_summary", "pre_auth_form"]))
    for b, missing in specs:
        b.missing_document_types = list(missing)
        positive(ctx, b, CheckId.MISSING_EVIDENCE, [], 0.0, "suspected",
                 f"Required documents absent: {', '.join(missing)}; request them instead of inventing a finding.")


def plant_negatives(ctx: Context) -> None:
    """Clean claims built to look like trouble: boundaries, families, open networks, payable consumables."""
    rng = ctx.rng
    # room rate exactly on the limit (policy 500k -> 5,000/day)
    for provider in ("P-001", "P-002"):
        m = pick_member(ctx, "IN", limits=[500000.0])
        b = register(ctx, build_in_inpatient(ctx, m, provider, cat.IN_INPATIENT_TEMPLATES[5], room_code="RM-SGL",
                                             room_rate=5000.0))
        negative(ctx, b, CheckId.ROOM_LIMIT_EXCEEDED, "Room 5,000/day equals the 5,000 limit exactly; no excess.")
    # a family: two members of one policy at the same hospital, sharing only the address
    fam = ctx.policies["POL-IN-0007"].members
    for cid, template in zip(fam, (cat.IN_INPATIENT_TEMPLATES[0], cat.IN_INPATIENT_TEMPLATES[6])):
        m = ctx.member(cid)
        ctx.member_use[cid] = ctx.member_use.get(cid, 0) + 1
        b = register(ctx, build_in_inpatient(ctx, m, "P-002", template))
        negative(ctx, b, CheckId.RELATED_PARTY_PATTERN, "Spouses on the same policy share an address but not phone or "
                 "bank account; a household, not a pattern.")
        negative(ctx, b, CheckId.WAITING_PERIOD, "Policy declares diabetes as PED; this diagnosis is unrelated.")
    # open-network UAE policies may use P-006
    for build in (lambda m: build_ae_outpatient(ctx, m, "P-006"), lambda m: build_ae_inpatient(ctx, m, "P-006")):
        m = pick_member(ctx, "AE", network_restricted=False)
        b = register(ctx, build(m))
        negative(ctx, b, CheckId.OUT_OF_NETWORK, "The policy has an empty network list (any provider allowed).")
    # payable medical items that look like consumables
    for provider in ("P-003", "P-001"):
        b = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), provider, cat.IN_INPATIENT_TEMPLATES[2]))
        inv = b.lines[0].invoice_no
        for code in ("MED-CAN", "MED-SET", "MED-DRS", "MED-SUT"):
            if not any(l.code == code for l in b.lines):
                add_line(ctx, b, inv, code, 2, b.admission_date)
        negative(ctx, b, CheckId.NON_PAYABLE_ITEM, "IV cannula, infusion set, dressing pack and sutures are payable "
                 "medical items, not on the non-payable list.")
    # cataract within the sub-limit
    b = register(ctx, build_in_daycare_cataract(ctx, pick_member(ctx, "IN"), "P-003"))
    assert b.total <= 40000, b.total
    negative(ctx, b, CheckId.SUBLIMIT_EXCEEDED, f"Cataract claim {b.total:,.0f} is inside the 40,000 sub-limit.")
    # a prescribed vitamin on a UAE pharmacy claim
    m = pick_member(ctx, "AE", network_restricted=True)
    b = register(ctx, build_ae_pharmacy(ctx, m, "P-005"))
    add_line(ctx, b, b.lines[0].invoice_no, "DRG-0114", 1, b.incident_date)
    negative(ctx, b, CheckId.NON_PAYABLE_ITEM, "Vitamin D3 is prescribed (drug code, prescription attached); only "
             "'vitamins without prescription' are non-payable.")
    # a member with history well below the limit
    with_history = [h.member for h in ctx.history if h.member.market == "IN" and h.member.claimant_id not in ctx.reserved]
    m = with_history[rng.randrange(len(with_history))]
    ctx.member_use[m.claimant_id] = ctx.member_use.get(m.claimant_id, 0) + 1
    b = register(ctx, build_in_inpatient(ctx, m, "P-001", cat.IN_INPATIENT_TEMPLATES[0]))
    paid = sum(h.record.paid_amount for h in ctx.history if h.member is m)
    negative(ctx, b, CheckId.BENEFIT_LIMIT_EXCEEDED, f"History paid {paid:,.0f} of {ctx.policy_of(m).annual_limit:,.0f}; "
             "the new claim fits inside the remaining limit.")
    # a clean UAE inpatient claim and a clean IN claim rendered as documents (the IN one as a scanned JPEG)
    b = register(ctx, build_ae_inpatient(ctx, pick_member(ctx, "AE", network_restricted=True), "P-004", cat.AE_IP_TEMPLATES[4]))
    b.render = True
    c = register(ctx, build_in_inpatient(ctx, pick_member(ctx, "IN"), "P-002", cat.IN_INPATIENT_TEMPLATES[0]))
    c.render = True
    c.scan = True


# ---------------------------------------------------------------------------
# Finalise: ids, amounts, settlements, validation, key, manifest, documents, files
# ---------------------------------------------------------------------------
def patient_share(b: Bundle, line: Line, is_first_consult: bool) -> float:
    if b.market != "AE":
        return 0.0
    p = b.policy
    if b.claim_type == "outpatient":
        share = line.amount * p.copay.outpatient_pct / 100.0
        if is_first_consult:
            share = p.deductible.amount + (line.amount - p.deductible.amount) * p.copay.outpatient_pct / 100.0
        return money(share)
    if b.claim_type == "pharmacy":
        return money(line.amount * p.copay.pharmacy_pct / 100.0)
    return 0.0


def assign_ids(ctx: Context) -> None:
    ordered = sorted(ctx.bundles, key=lambda b: (b.submitted_at, b.order))
    for n, b in enumerate(ordered, start=1):
        b.claim_id = f"CLM-2026-{n:04d}"
        serial: Dict[str, int] = {}
        consult_seen = False
        for l in b.lines:
            serial[l.invoice_no] = serial.get(l.invoice_no, 0) + 1
            l.serial_no = serial[l.invoice_no]
            l.line_id = f"{b.claim_id}:{l.invoice_no}:{l.serial_no}"
            is_consult = l.code in cat.AE_CONSULT_CODES and not consult_seen
            consult_seen = consult_seen or is_consult
            l.patient_share = patient_share(b, l, is_consult)
    ctx.bundles = ordered


def to_claim(b: Bundle, source: str) -> Claim:
    proposed = b.settlement_override(b) if b.settlement_override else handler_settlement(b)
    invoices: List[str] = []
    for l in b.lines:
        if l.invoice_no not in invoices:
            invoices.append(l.invoice_no)
    return Claim(claim_id=b.claim_id, policy_number=b.member.policy_number, product_id=b.member.product_id,
                 claimant_id=b.member.claimant_id, claimant_name=b.member.name,
                 provider_id=str(b.provider["provider_id"]), provider_name=str(b.provider["provider_name"]),
                 claim_type=ClaimType(b.claim_type), incident_date=b.incident_date, admission_date=b.admission_date,
                 discharge_date=b.discharge_date, diagnosis=b.diagnosis, diagnosis_code=b.diagnosis_code,
                 room_category=b.room_category, requested_amount=b.total, proposed_settlement=proposed,
                 currency=b.currency, invoice_numbers=invoices, submitted_at=b.submitted_at, status="ingested",
                 source=source, contact_phone=b.member.phone, bank_account=b.member.bank_account,
                 address=b.member.address, extra={})


def to_invoice_line(b: Bundle, l: Line) -> InvoiceLine:
    return InvoiceLine(line_id=l.line_id, claim_id=b.claim_id, invoice_no=l.invoice_no, serial_no=l.serial_no,
                       service_date=l.service_date, code=l.code, code_system=l.code_system, description=l.description,
                       category=LineCategory(l.category), quantity=l.quantity, unit_price=l.unit_price, amount=l.amount,
                       provider_id=str(b.provider["provider_id"]))


def key_amount(row: KeyRow) -> float:
    if row.amount_rule == "requested":
        return row.bundle.total
    if row.amount_rule == "outlier":
        return money(sum((l.unit_price - base_price(row.bundle.market, l.code)) * l.quantity for l in row.bundle.lines))
    assert row.amount is not None
    return money(row.amount)


def fmt_amount(x: float) -> str:
    return f"{x:,.2f}"


def document_plan(ctx: Context, b: Bundle, claim: Claim) -> Dict[str, object]:
    """Which documents this claim has, what the bill prints in its header, and what is missing."""
    product = ctx.products[b.member.product_id]
    required = list(product.required_documents.get(b.claim_type, []))
    present = [t for t in required if t not in b.missing_document_types]
    bill_type = "medicine_pharmacy_bills" if b.claim_type == "pharmacy" else "itemized_final_hospital_bill"
    docs: List[Dict[str, object]] = []
    for n, doc_type in enumerate(present, start=1):
        docs.append({"document_id": f"DOC-{b.claim_id}-{n:02d}", "document_type": doc_type, "file": None,
                     "rendered": False, "pages": None})
    facts: Dict[str, str] = {}
    if bill_type in present:
        facts = {"claimant_name": b.member.name, "policy_number": b.member.policy_number,
                 "provider_name": str(b.provider["provider_name"]),
                 "admission_date": b.admission_date.isoformat() if b.admission_date else b.incident_date.isoformat(),
                 "discharge_date": b.discharge_date.isoformat() if b.discharge_date else b.incident_date.isoformat(),
                 "invoice_no": claim.invoice_numbers[0], "net_payable": fmt_amount(b.total)}
        facts.update(b.document_facts_override)
    return {"claim_id": b.claim_id, "claim_type": b.claim_type, "product_id": b.member.product_id,
            "required_documents": required, "required_documents_present": present,
            "missing_documents": [t for t in required if t not in present], "documents": docs,
            "document_facts": facts}


def render_documents(ctx: Context, b: Bundle, plan: Dict[str, object], claim: Claim, out_dir: Path) -> None:
    folder = out_dir / "documents" / b.claim_id
    folder.mkdir(parents=True, exist_ok=True)
    facts = dict(plan["document_facts"])  # type: ignore[arg-type]
    insurer = ctx.products[b.member.product_id].insurer
    bill_pdf = folder / f"{b.claim_id}_bill.pdf"
    pages = render_bill_pdf(str(bill_pdf), provider=b.provider, insurer=insurer, claim=claim.model_dump(mode="json"),
                            member={"claimant_id": b.member.claimant_id, "date_of_birth": b.member.date_of_birth.isoformat(),
                                    "gender": b.member.gender}, lines=[vars(l) for l in b.lines], facts=facts,
                            doctor=b.doctor, currency=b.currency)
    bill_files: List[str] = [str(bill_pdf.relative_to(out_dir)).replace("\\", "/")]
    if b.scan:
        jpgs = rasterise_pdf(str(bill_pdf), str(folder), f"{b.claim_id}_bill_scan", dpi=SCAN_DPI,
                             rotation_deg=SCAN_ROTATION_DEG)
        bill_pdf.unlink()
        bill_files = [str(Path(j).relative_to(out_dir)).replace("\\", "/") for j in jpgs]
    ds_pdf = folder / f"{b.claim_id}_discharge_summary.pdf"
    render_discharge_pdf(str(ds_pdf), provider=b.provider, claim=claim.model_dump(mode="json"),
                         member={"claimant_id": b.member.claimant_id, "date_of_birth": b.member.date_of_birth.isoformat(),
                                 "gender": b.member.gender}, lines=[vars(l) for l in b.lines], facts=facts, doctor=b.doctor,
                         insurer=insurer)
    for doc in plan["documents"]:  # type: ignore[union-attr]
        if doc["document_type"] == "itemized_final_hospital_bill":
            doc.update({"file": bill_files[0] if len(bill_files) == 1 else bill_files, "rendered": True, "pages": pages,
                        "format": "jpeg-scan" if b.scan else "pdf"})
        elif doc["document_type"] == "discharge_summary":
            doc.update({"file": str(ds_pdf.relative_to(out_dir)).replace("\\", "/"), "rendered": True, "pages": 1,
                        "format": "pdf"})


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def pin_xlsx(path: Path) -> None:
    """Re-zip the workbook with fixed entry dates and fixed document timestamps so two runs are byte-identical
    (openpyxl stamps both the zip entries and docProps/core.xml with the current time)."""
    fixed = (2026, 1, 1, 0, 0, 0)
    stamp = "2026-01-01T00:00:00Z"
    with zipfile.ZipFile(path) as src:
        entries = [(info.filename, src.read(info.filename)) for info in src.infolist()]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name, payload in entries:
            if name == "docProps/core.xml":
                text = payload.decode("utf-8")
                text = re.sub(r"(<dcterms:created[^>]*>)[^<]*", r"\g<1>" + stamp, text)
                text = re.sub(r"(<dcterms:modified[^>]*>)[^<]*", r"\g<1>" + stamp, text)
                payload = text.encode("utf-8")
            info = zipfile.ZipInfo(name, date_time=fixed)
            info.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(info, payload)


def flat(record: Dict[str, object], list_fields: Sequence[str], drop: Sequence[str] = ()) -> Dict[str, object]:
    out = {k: v for k, v in record.items() if k not in drop}
    for k in list_fields:
        if k in out:
            out[k] = "|".join(str(x) for x in out[k])  # type: ignore[union-attr]
    return out


def finalise(ctx: Context, out_dir: Path) -> Dict[str, int]:
    assign_ids(ctx)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(out_dir / "documents", ignore_errors=True)     # no stale folders from earlier runs
    claims: List[Dict[str, object]] = []
    lines: List[Dict[str, object]] = []
    manifest: List[Dict[str, object]] = []
    rendered = 0
    for b in ctx.bundles:
        assert 5 <= len(b.lines) <= 40, (b.claim_id, len(b.lines))
        claim = to_claim(b, source="mixed" if b.render else "structured")
        plan = document_plan(ctx, b, claim)
        if b.render:
            render_documents(ctx, b, plan, claim, out_dir)
            rendered += 1
        manifest.append(plan)
        claims.append(claim.model_dump(mode="json"))
        for l in b.lines:
            row = to_invoice_line(b, l).model_dump(mode="json")
            row["patient_share"] = l.patient_share
            lines.append(row)
    line_ids = {row["line_id"] for row in lines}
    assert len(line_ids) == len(lines), "line ids must be unique"

    positives: List[Dict[str, object]] = []
    for row in ctx.positives:
        ids = [l.line_id for l in row.lines]
        assert all(i in line_ids for i in ids), ids
        related = [rb.claim_id for rb in row.related_bundles] + list(row.related_ids)
        positives.append({"claim_id": row.bundle.claim_id, "check_id": row.check_id.value, "line_ids": ids,
                          "amount": key_amount(row), "amount_kind": row.amount_kind, "currency": row.bundle.currency,
                          "related_claim_ids": related, "note": row.note})
    negatives = [{"claim_id": n.bundle.claim_id, "check_id": n.check_id.value, "note": n.note} for n in ctx.negatives]
    positives.sort(key=lambda r: (r["claim_id"], r["check_id"]))
    negatives.sort(key=lambda r: (r["claim_id"], r["check_id"]))
    dirty = {r["claim_id"] for r in positives}
    clean_count = len(ctx.bundles) - len(dirty)
    per_check: Dict[str, int] = {}
    for r in positives:
        per_check[str(r["check_id"])] = per_check.get(str(r["check_id"]), 0) + 1
    answer_key = {"seed": SEED, "claims": len(ctx.bundles), "clean_claims": clean_count,
                  "conventions": {
                      "stay_nights": "discharge_date - admission_date in days (same-day discharge counts as 1)",
                      "settlement_order": "lines total - calculated deductions - deductible (per visit, outpatient) "
                                          "then copay %; benefit cap last",
                      "room_limit_amount": "(rate - daily limit) x days billed; proportionate deduction is not in the key",
                      "suspected_amounts": "exposure, not leakage: not scored for exactness"},
                  "counts_per_check": dict(sorted(per_check.items())), "positives": positives, "negatives": negatives}

    policies = [p.model_dump(mode="json") for p in ctx.policies.values()]
    products = [p.model_dump(mode="json") for p in ctx.products.values()]
    providers = [{k: v for k, v in p.items()} for p in ctx.providers.values()]
    claimants = [{"claimant_id": m.claimant_id, "name": m.name, "gender": m.gender,
                  "date_of_birth": m.date_of_birth.isoformat(), "policy_number": m.policy_number,
                  "product_id": m.product_id, "relationship": m.relationship, "phone": m.phone,
                  "bank_account": m.bank_account, "address": m.address, "city": m.city} for m in ctx.members]
    history = [h.record.model_dump(mode="json") for h in ctx.history]
    history_lines_rows = [dict(l) for h in history for l in h["lines"]]  # type: ignore[union-attr]

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "products.json", products)
    write_json(out_dir / "policies.json", policies)
    write_json(out_dir / "claims.json", claims)
    write_json(out_dir / "invoice_lines.json", lines)
    write_json(out_dir / "history.json", history)
    write_json(out_dir / "answer_key.json", answer_key)
    write_json(out_dir / "documents_manifest.json", {"seed": SEED, "documents_root": "data/synthetic/out",
                                                     "claims": manifest})
    claims_flat = [flat(c, ["invoice_numbers"], drop=["extra"]) for c in claims]
    history_flat = [flat(h, ["invoice_numbers"], drop=["lines"]) for h in history]
    pd.DataFrame(claims_flat).to_csv(out_dir / "claims.csv", index=False)
    pd.DataFrame(lines).to_csv(out_dir / "invoice_lines.csv", index=False)
    pd.DataFrame(history_flat).to_csv(out_dir / "history.csv", index=False)
    pd.DataFrame(history_lines_rows).to_csv(out_dir / "history_lines.csv", index=False)
    pd.DataFrame(providers).to_csv(out_dir / "providers.csv", index=False)
    pd.DataFrame(claimants).to_csv(out_dir / "claimants.csv", index=False)
    with pd.ExcelWriter(out_dir / "claims.xlsx", engine="openpyxl") as xl:
        pd.DataFrame(claims_flat).to_excel(xl, sheet_name="claims", index=False)
        pd.DataFrame(lines).to_excel(xl, sheet_name="invoice_lines", index=False)
        pd.DataFrame(history_flat).to_excel(xl, sheet_name="history", index=False)
        pd.DataFrame(history_lines_rows).to_excel(xl, sheet_name="history_lines", index=False)
        pd.DataFrame(providers).to_excel(xl, sheet_name="providers", index=False)
        pd.DataFrame(claimants).to_excel(xl, sheet_name="claimants", index=False)
    pin_xlsx(out_dir / "claims.xlsx")
    return {"products": len(products), "policies": len(policies), "providers": len(providers),
            "claimants": len(claimants), "claims": len(claims), "clean_claims": clean_count,
            "invoice_lines": len(lines), "history": len(history), "history_with_lines": sum(1 for h in history if h["lines"]),
            "history_lines": len(history_lines_rows), "positives": len(positives), "negatives": len(negatives),
            "documents_rendered": rendered, **{f"key:{k}": v for k, v in sorted(per_check.items())}}


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def generate(out_dir: Path) -> Dict[str, int]:
    ctx = Context(rng=random.Random(SEED))
    ctx.products = build_products()
    build_providers(ctx)
    build_members_and_policies(ctx)

    # scenarios that reserve members or create history come first
    related = plant_related_party(ctx)
    plant_benefit_limit(ctx)
    plant_coverage_inactive(ctx)
    plant_waiting_period(ctx)
    planted_history = len(ctx.history)
    plant_cross_claim_duplicate_line(ctx)
    plant_near_duplicate(ctx)
    planted_history = len(ctx.history)
    planted_history_with_lines = sum(1 for h in ctx.history if h.record.lines)
    build_generic_history(ctx, HISTORY_COUNT - planted_history, HISTORY_WITH_LINES - planted_history_with_lines)

    room = plant_room_limit(ctx)
    outliers = plant_provider_outlier(ctx)
    excluded = plant_excluded_service(ctx)
    plant_non_payable(ctx, hosts=room + outliers[:2] + related[:1] + excluded[1:2])
    plant_duplicate_claim(ctx)
    plant_duplicate_line(ctx, host=related[1])
    plant_sublimit(ctx)
    plant_copay_not_applied(ctx)
    plant_deductible_not_applied(ctx)
    plant_settlement_mismatch(ctx)
    plant_quantity_vs_stay(ctx)
    plant_arithmetic_mismatch(ctx, host=outliers[2])
    plant_out_of_network(ctx)
    plant_consistency_mismatch(ctx)
    plant_missing_evidence(ctx, hosts=related[3:5])
    plant_legit_repeats(ctx)
    plant_negatives(ctx)

    build_clean_claims(ctx, TOTAL_CLAIMS - len(ctx.bundles))
    assert len(ctx.bundles) == TOTAL_CLAIMS, len(ctx.bundles)
    return finalise(ctx, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the synthetic claims dataset")
    parser.add_argument("--out", default="data/synthetic/out", help="Output folder")
    args = parser.parse_args()
    counts = generate(Path(args.out))
    for k, v in counts.items():
        print(f"{k:>32}: {v}")


if __name__ == "__main__":
    main()
