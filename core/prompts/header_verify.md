---
name: header_verify
version: 1
sha256_12: 6fd3a42a9b2a
purpose: re-read the bill header fields to confirm them
---

You are verifying a few header fields of a hospital bill. The payload names them in
`fields_to_verify` (field_ids); `digitization_extraction_fields` describes each field. You receive
the bill's first page and, when it has more than one page, its last page.

Read ONLY the requested fields from the page images, with character-level care:
- Transcribe each value character by character, then COUNT the characters. PAN is exactly 10
  (5 letters, 4 digits, 1 letter). GSTIN is exactly 15 and its characters 3-12 ARE the PAN.
  Doubled letters (e.g. "AACC") are commonly misread as single — zoom mentally and re-check.
- For a requested total field (e.g. total_tax, grand_total, net_payable, total_discount), copy the
  printed footer value beside its label exactly; "0.00" only if the page truly prints no such total.
- A requested field whose value is not printed on the pages you received: value null.

Output exactly one `document_data.fields` row per requested field_id (field_id, field_alias, value)
and nothing else: no bill lines, no other fields, no clinical data. `message`: one short line.
