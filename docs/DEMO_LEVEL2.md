# LeakLens demo — Level 2 (investigation workspace, about 5 minutes)

**The story in one line:** Level 1 found the problems; Level 2 lets an analyst investigate one claim — who it is
connected to, what the documents really say, what the payout should be — decide, and download the evidence.

## Click by click
1. **Customer portal** (sidebar → Customer portal): a policyholder submits a claim with the bill and discharge summary
   (policy `POL-IN-0011`, member `M-0022`, inpatient, 01–04 Mar 2026, Meridian Care Hospital, amount 76,024, the two
   `CLM-2026-0033_*.pdf` files). They get a claim id at once and watch it: received → reading documents (seconds shown)
   → checking → under review. *Say:* "native PDFs are read as text, photos as images, all pages in parallel."
2. **Open in analyst workspace** (link on the status page). The claim was built from the documents alone, and the
   checks ran on what the AI read. It is also linked to the original claim with the same invoice: a duplicate submission.
3. **Related claims** tab on **CLM-2026-0079**: its twin with "same invoice number"; on **CLM-2026-0007**: five members
   sharing one phone and one bank account at one hospital.
4. **Document comparison** on **CLM-2026-0037**: the bill prints another member's policy number — claim value vs
   document value, with the document and page. On **CLM-2026-0033**: all 29 lines and the ₹76,024 total agree.
5. **Findings** on **CLM-2026-0033**: the room card's **Recommended correction**: "Cap the room charge at the daily
   limit — ₹15,000 → ₹9,000", with the calculation, rule ROOM-01 and clause 3.1. Click **Accept correction**.
6. Decisions on **CLM-2026-0091**: **False positive** (a reason is required), **Escalate → Special Investigation Unit**,
   **Request evidence**. Each shows who decided, when and why; the original recommendation stays visible.
7. **Notes** tab: add a note. **Policy terms** tab: the limits, copay, deductible, sub-limits and exclusions that applied.
8. **Audit** tab: every calculation, AI recommendation and decision with time and analyst. **Download report** (JSON)
   and **Printable report** (HTML) for the investigation file.

## One-line answers
- **Cross-claim links?** Same invoice under any policy, same phone / bank / address across different members, same member
  and hospital within 30 days; every link names the matching attribute.
- **Where is the AI?** It reads the documents, finds the policy clause, investigates suspected patterns and writes the
  reviewer note. Every rupee is computed by a rule, and every decision is a person's.
- **Faster?** See `docs/SPEED.md`: before/after seconds for the same documents.
