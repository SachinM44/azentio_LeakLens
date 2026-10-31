"""Policy rule validation: coverage, waiting periods, network, exclusions, non-payable items, room and ICU daily
limits, sub-limits, the annual benefit limit, plus the line-level sanity checks (days vs stay, dates, arithmetic)
and the missing-evidence rule (ask, do not invent)."""
from __future__ import annotations

from typing import Dict, List, Optional

from core.checks._common import (code_in, is_icu_line, is_room_line, line_evidence, make_finding, matches_any, money,
                                 per_day_line, positive_lines, product_for, similar, stay_days, unit_price, within)
from core.schemas.finding import AmountKind, CheckId, ClauseRef, Evidence, Finding, Severity
from core.schemas.master import ClaimType, HistoryRecord, InvoiceLine, MasterRecord, Policy, Sublimit


def _clause(policy: Policy, clause_id: Optional[str], text: str) -> Optional[ClauseRef]:
    if not clause_id:
        return None
    return ClauseRef(clause_id=clause_id, text=text, score=1.0)


def check_coverage(record: MasterRecord) -> List[Finding]:
    claim, policy = record.claim, record.policy
    if policy is None:
        return []
    cur = claim.currency
    if not within(claim.incident_date, policy.start_date, policy.end_date):
        return [make_finding(
            record, CheckId.COVERAGE_INACTIVE, amount=claim.requested_amount, kind=AmountKind.CALCULATED,
            rule_id="COV-01", rule_text="Only incidents inside the policy period are covered.",
            calculation=f"incident {claim.incident_date} outside {policy.start_date}..{policy.end_date}; "
                        f"not payable = requested {money(claim.requested_amount, cur)}",
            reason="The incident date falls outside the policy period.",
            evidence=[Evidence(source="policy", ref=policy.policy_number,
                               quote=f"cover {policy.start_date} to {policy.end_date}"),
                      Evidence(source="claim", ref=claim.claim_id, quote=f"incident date {claim.incident_date}")],
            severity=Severity.HIGH)]
    if policy.members and claim.claimant_id not in policy.members:
        return [make_finding(
            record, CheckId.COVERAGE_INACTIVE, amount=claim.requested_amount, kind=AmountKind.CALCULATED,
            rule_id="COV-02", rule_text="Only members listed on the policy are covered.",
            calculation=f"member {claim.claimant_id} not on policy {policy.policy_number}; not payable = requested",
            reason="The claimant is not a covered member of this policy.",
            evidence=[Evidence(source="policy", ref=policy.policy_number, quote=f"members: {', '.join(policy.members)}")],
            severity=Severity.HIGH)]
    return []


def check_waiting_periods(record: MasterRecord) -> List[Finding]:
    claim, policy = record.claim, record.policy
    if policy is None:
        return []
    days = (claim.incident_date - policy.start_date).days
    findings: List[Finding] = []
    if policy.waiting_period_days and 0 <= days < policy.waiting_period_days and claim.claim_type != ClaimType.MOTOR:
        findings.append(make_finding(
            record, CheckId.WAITING_PERIOD, amount=claim.requested_amount, kind=AmountKind.CALCULATED, rule_id="WAIT-01",
            rule_text=f"Claims in the first {policy.waiting_period_days} days of cover are not payable (accidents excepted).",
            calculation=f"incident is day {days} of cover; waiting period {policy.waiting_period_days} days",
            reason="The treatment falls inside the initial waiting period.",
            evidence=[Evidence(source="policy", ref=policy.policy_number, quote=f"start {policy.start_date}; waiting {policy.waiting_period_days} days")],
            severity=Severity.HIGH))
    ped = matches_any(claim.diagnosis, policy.declared_ped) if policy.declared_ped else None
    if ped and policy.ped_waiting_days and 0 <= days < policy.ped_waiting_days and not findings:
        findings.append(make_finding(
            record, CheckId.WAITING_PERIOD, amount=claim.requested_amount, kind=AmountKind.CALCULATED, rule_id="WAIT-02",
            rule_text=f"A declared pre-existing condition is covered only after {policy.ped_waiting_days} days.",
            calculation=f"diagnosis matches declared condition '{ped}'; day {days} of cover < {policy.ped_waiting_days}",
            reason=f"The diagnosis relates to the declared pre-existing condition '{ped}' and is still in its waiting period.",
            evidence=[Evidence(source="claim", ref=claim.claim_id, quote=f"diagnosis: {claim.diagnosis}"),
                      Evidence(source="policy", ref=policy.policy_number, quote=f"declared: {', '.join(policy.declared_ped)}")],
            severity=Severity.HIGH))
    return findings


def check_network(record: MasterRecord) -> List[Finding]:
    claim, policy = record.claim, record.policy
    if policy is None or not policy.network_provider_ids or claim.provider_id in policy.network_provider_ids:
        return []
    return [make_finding(
        record, CheckId.OUT_OF_NETWORK, amount=claim.requested_amount, kind=AmountKind.CALCULATED, rule_id="NET-01",
        rule_text="Treatment is payable only at network providers.",
        calculation=f"provider {claim.provider_id} not in the policy network; not payable = requested",
        reason=f"{claim.provider_name or claim.provider_id} is outside the policy's provider network.",
        evidence=[Evidence(source="policy", ref=policy.policy_number, quote=f"network: {', '.join(policy.network_provider_ids[:8])}")],
        severity=Severity.HIGH)]


def check_exclusions(record: MasterRecord) -> List[Finding]:
    claim, policy = record.claim, record.policy
    if policy is None:
        return []
    findings: List[Finding] = []
    matched_lines = set()
    for line in positive_lines(record):
        for excl in policy.exclusions:
            kw = matches_any(line.description, excl.keywords)
            if code_in(line, excl.codes) or kw:
                findings.append(make_finding(
                    record, CheckId.EXCLUDED_SERVICE, amount=line.amount, kind=AmountKind.CALCULATED,
                    rule_id=f"EXCL-{excl.exclusion_id}", rule_text=excl.text,
                    calculation=f"excluded line {money(line.amount, claim.currency)} -> 0",
                    reason=f"'{line.description}' falls under the exclusion '{excl.exclusion_id}'"
                           + (f" (matched '{kw}')" if kw else " (matched by code)") + ".",
                    lines=[line], clause=_clause(policy, excl.clause_id, excl.text)))
                matched_lines.add(line.line_id)
                break
    if not matched_lines and claim.diagnosis:
        for excl in policy.exclusions:
            kw = matches_any(claim.diagnosis, excl.keywords)
            if kw:
                findings.append(make_finding(
                    record, CheckId.EXCLUDED_SERVICE, amount=claim.requested_amount, kind=AmountKind.CALCULATED,
                    rule_id=f"EXCL-{excl.exclusion_id}", rule_text=excl.text,
                    calculation=f"diagnosis '{claim.diagnosis}' matches '{kw}'; whole claim excluded = requested",
                    reason=f"The treatment ('{claim.diagnosis}') is excluded under '{excl.exclusion_id}'.",
                    evidence=[Evidence(source="claim", ref=claim.claim_id, quote=f"diagnosis: {claim.diagnosis}")],
                    clause=_clause(policy, excl.clause_id, excl.text), severity=Severity.HIGH))
                break
    return findings


def check_non_payable(record: MasterRecord) -> List[Finding]:
    # The insurer's rule book (Config screen) decides; a policy's own list is used only when the product has none.
    policy = record.policy
    product_items = product_for(record).non_payable_items
    items = product_items or (policy.non_payable_items if policy else [])
    if not items:
        return []
    findings: List[Finding] = []
    for line in positive_lines(record):
        hit = matches_any(line.description, items, threshold=0.92)
        if hit:
            findings.append(make_finding(
                record, CheckId.NON_PAYABLE_ITEM, amount=line.amount, kind=AmountKind.CALCULATED, rule_id="NPI-01",
                rule_text="Items on the non-payable list are borne by the insured.",
                calculation=f"non-payable line {money(line.amount, record.claim.currency)} -> 0",
                reason=f"'{line.description}' matches the non-payable item '{hit}'.", lines=[line]))
    return findings


def check_room_limits(record: MasterRecord) -> List[Finding]:
    claim, policy = record.claim, record.policy
    if policy is None:
        return []
    findings: List[Finding] = []
    for line in positive_lines(record):
        if is_icu_line(line) and policy.icu_limit_per_day:
            limit, check_rule, label = policy.icu_limit_per_day, "ICU-01", "ICU"
        elif is_room_line(line) and policy.room_rent_limit_per_day:
            limit, check_rule, label = policy.room_rent_limit_per_day, "ROOM-01", "room rent"
        else:
            continue
        rate = unit_price(line)
        if rate > limit + 0.5:
            days = line.quantity or 1
            excess = round((rate - limit) * days, 2)
            findings.append(make_finding(
                record, CheckId.ROOM_LIMIT_EXCEEDED, amount=excess, kind=AmountKind.CALCULATED, rule_id=check_rule,
                rule_text=f"The {label} limit is {money(limit, claim.currency)} per day.",
                calculation=f"({money(rate, claim.currency)} - {money(limit, claim.currency)}) x {days:g} day(s) = {money(excess, claim.currency)}",
                reason=f"{label.capitalize()} billed at {money(rate, claim.currency)}/day against a limit of {money(limit, claim.currency)}/day.",
                lines=[line], evidence=[line_evidence(line, claim.currency),
                                        Evidence(source="policy", ref=policy.policy_number, quote=f"{label} limit {money(limit, claim.currency)}/day")]))
    return findings


def _sublimit_lines(record: MasterRecord, sub: Sublimit) -> List[InvoiceLine]:
    if sub.basis != "sessions_per_year" and record.claim.diagnosis and matches_any(record.claim.diagnosis, sub.keywords):
        return positive_lines(record)  # the whole episode is the capped procedure (cataract, maternity ...)
    return [l for l in positive_lines(record) if code_in(l, sub.codes) or matches_any(l.description, sub.keywords)]


def check_sublimits(record: MasterRecord) -> List[Finding]:
    claim, policy = record.claim, record.policy
    if policy is None:
        return []
    findings: List[Finding] = []
    for sub in policy.sublimits:
        lines = _sublimit_lines(record, sub)
        if not lines:
            continue
        clause = _clause(policy, sub.clause_id, f"{sub.name}: limit {sub.limit:g} ({sub.basis})")
        if sub.basis == "sessions_per_year":
            sessions = sum(l.quantity for l in lines)
            earlier = sum(hl.quantity for h in record.history if h.claimant_id == claim.claimant_id
                          and within(h.incident_date, policy.start_date, policy.end_date)
                          for hl in h.lines if code_in(hl, sub.codes) or matches_any(hl.description, sub.keywords))
            total = sessions + earlier
            if total > sub.limit:
                excess_sessions = min(sessions, total - sub.limit)
                avg = sum(l.amount for l in lines) / max(sessions, 1)
                excess = round(excess_sessions * avg, 2)
                findings.append(make_finding(
                    record, CheckId.SUBLIMIT_EXCEEDED, amount=excess, kind=AmountKind.CALCULATED,
                    rule_id=f"SUB-{sub.sublimit_id}", rule_text=f"{sub.name}: at most {sub.limit:g} sessions per policy year.",
                    calculation=f"{earlier:g} earlier + {sessions:g} now = {total:g} > {sub.limit:g}; "
                                f"{excess_sessions:g} session(s) x {money(avg, claim.currency)} = {money(excess, claim.currency)}",
                    reason=f"The policy-year allowance for {sub.name.lower()} is used up.", lines=lines, clause=clause))
            continue
        total = round(sum(l.amount for l in lines), 2)
        earlier = 0.0
        if sub.basis == "per_year":
            earlier = sum(hl.amount for h in record.history if h.claimant_id == claim.claimant_id
                          and within(h.incident_date, policy.start_date, policy.end_date)
                          for hl in h.lines if code_in(hl, sub.codes) or matches_any(hl.description, sub.keywords))
        if total + earlier > sub.limit + 0.5:
            excess = round(min(total, total + earlier - sub.limit), 2)
            findings.append(make_finding(
                record, CheckId.SUBLIMIT_EXCEEDED, amount=excess, kind=AmountKind.CALCULATED,
                rule_id=f"SUB-{sub.sublimit_id}", rule_text=f"{sub.name} is limited to {money(sub.limit, claim.currency)} {sub.basis.replace('_', ' ')}.",
                calculation=(f"{money(total, claim.currency)}" + (f" + earlier {money(earlier, claim.currency)}" if earlier else "")
                             + f" - limit {money(sub.limit, claim.currency)} = {money(excess, claim.currency)}"),
                reason=f"Charges for {sub.name.lower()} exceed the sub-limit.", lines=lines, clause=clause))
    return findings


def used_in_policy_year(record: MasterRecord) -> float:
    policy, claim = record.policy, record.claim
    if policy is None:
        return 0.0
    return round(sum(h.paid_amount for h in record.history
                     if h.claimant_id == claim.claimant_id and h.claim_id != claim.claim_id
                     and within(h.incident_date, policy.start_date, policy.end_date)), 2)


def check_benefit_limit(record: MasterRecord) -> List[Finding]:
    claim, policy = record.claim, record.policy
    if policy is None:
        return []
    used = used_in_policy_year(record)
    remaining = max(0.0, policy.annual_limit - used)
    if claim.requested_amount <= remaining + 0.5:
        return []
    excess = round(claim.requested_amount - remaining, 2)
    return [make_finding(
        record, CheckId.BENEFIT_LIMIT_EXCEEDED, amount=excess, kind=AmountKind.CALCULATED, rule_id="LIMIT-01",
        rule_text=f"Total benefits in a policy year cannot exceed {money(policy.annual_limit, claim.currency)}.",
        calculation=f"limit {money(policy.annual_limit, claim.currency)} - already paid {money(used, claim.currency)} = "
                    f"{money(remaining, claim.currency)} left; requested {money(claim.requested_amount, claim.currency)} - "
                    f"{money(remaining, claim.currency)} = {money(excess, claim.currency)}",
        reason="The claim exceeds what is left of the annual limit after earlier claims.",
        evidence=[Evidence(source="history", ref=claim.claimant_id, quote=f"paid this policy year: {money(used, claim.currency)}"),
                  Evidence(source="policy", ref=policy.policy_number, quote=f"annual limit {money(policy.annual_limit, claim.currency)}")],
        severity=Severity.HIGH)]


def check_quantity_vs_stay(record: MasterRecord) -> List[Finding]:
    claim = record.claim
    stay = stay_days(claim)
    if stay is None:
        return []
    findings: List[Finding] = []
    for line in positive_lines(record):
        if not (is_room_line(line) or is_icu_line(line)):
            continue
        if line.quantity > stay:
            rate = unit_price(line)
            excess = round((line.quantity - stay) * rate, 2)
            findings.append(make_finding(
                record, CheckId.QUANTITY_VS_STAY, amount=excess, kind=AmountKind.CALCULATED, rule_id="STAY-01",
                rule_text="Daily charges are payable only for the days actually stayed.",
                calculation=f"billed {line.quantity:g} days, stayed {stay} ({claim.admission_date} to {claim.discharge_date}); "
                            f"({line.quantity:g} - {stay}) x {money(rate, claim.currency)} = {money(excess, claim.currency)}",
                reason=f"'{line.description}' is billed for more days than the admission lasted.", lines=[line]))
    return findings


def check_dates(record: MasterRecord) -> List[Finding]:
    claim = record.claim
    if not (claim.admission_date and claim.discharge_date):
        return []
    findings: List[Finding] = []
    for line in positive_lines(record):
        if line.service_date and not within(line.service_date, claim.admission_date, claim.discharge_date, slack_days=1):
            findings.append(make_finding(
                record, CheckId.DATE_OUTSIDE_EPISODE, amount=line.amount, kind=AmountKind.CALCULATED, rule_id="DATE-01",
                rule_text="Only services dated within the admission episode belong to an inpatient claim.",
                calculation=f"service {line.service_date} outside {claim.admission_date}..{claim.discharge_date} (+/-1 day); "
                            f"line {money(line.amount, claim.currency)} -> 0",
                reason=f"'{line.description}' is dated outside the admission.", lines=[line]))
    return findings


def check_arithmetic(record: MasterRecord) -> List[Finding]:
    claim = record.claim
    findings: List[Finding] = []
    for line in positive_lines(record):
        if line.unit_price is None or not line.quantity:
            continue
        expected = round(line.quantity * line.unit_price, 2)
        if line.amount - expected > 1.0:
            findings.append(make_finding(
                record, CheckId.ARITHMETIC_MISMATCH, amount=line.amount - expected, kind=AmountKind.CALCULATED,
                rule_id="ARITH-01", rule_text="A line's amount must equal quantity x unit price.",
                calculation=f"{line.quantity:g} x {money(line.unit_price, claim.currency)} = {money(expected, claim.currency)}; "
                            f"billed {money(line.amount, claim.currency)}; excess {money(line.amount - expected, claim.currency)}",
                reason=f"'{line.description}' is billed above quantity x rate.", lines=[line]))
    lines_total = round(sum(l.amount for l in record.lines), 2)
    if record.lines and claim.requested_amount - lines_total > 1.0:
        findings.append(make_finding(
            record, CheckId.ARITHMETIC_MISMATCH, amount=claim.requested_amount - lines_total, kind=AmountKind.CALCULATED,
            rule_id="ARITH-02", rule_text="The amount claimed cannot exceed the invoice lines.",
            calculation=f"requested {money(claim.requested_amount, claim.currency)} - lines {money(lines_total, claim.currency)} = "
                        f"{money(claim.requested_amount - lines_total, claim.currency)}",
            reason="The requested amount is higher than the invoices support.",
            evidence=[Evidence(source="claim", ref=claim.claim_id, quote=f"requested {money(claim.requested_amount, claim.currency)}; "
                                                                        f"{len(record.lines)} lines total {money(lines_total, claim.currency)}")]))
    return findings


def check_missing_evidence(record: MasterRecord) -> List[Finding]:
    claim = record.claim
    product = product_for(record)
    problems: List[str] = []
    if record.policy is None:
        problems.append("the policy terms are not on file")
    if not record.lines:
        problems.append("no invoice lines were supplied")
    if record.documents or claim.source in ("documents", "mixed"):
        required = product.required_documents.get(claim.claim_type.value, [])
        present = set(record.document_types.values())
        missing = [d for d in required if d not in present]
        if missing:
            problems.append("missing documents: " + ", ".join(missing))
    if not problems:
        return []
    return [make_finding(
        record, CheckId.MISSING_EVIDENCE, amount=0.0, kind=AmountKind.SUSPECTED, rule_id="EVID-01",
        rule_text="A claim is assessed only on complete evidence; otherwise clarification is requested.",
        reason="Clarification requested: " + "; ".join(problems) + ".",
        evidence=[Evidence(source="claim", ref=claim.claim_id, quote=p) for p in problems], severity=Severity.MEDIUM)]
