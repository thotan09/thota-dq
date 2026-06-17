# AML / Fraud Detection Policy — FinCore Bank

Version: 2.1.0 | Effective: 2026-01-01 | Owner: Compliance & Risk

---

## Tier 1 — Regulatory (Zero Tolerance, Critical Severity)

### P-01: Currency Transaction Report (CTR) Filing
Any single transaction with amount_usd >= 10,000 must have a corresponding
compliance_flags record with flag_type = 'CTR' and status IN ('filed', 'waived')
within 24 hours of the transaction timestamp.
Regulation: Bank Secrecy Act 31 U.S.C. § 5313.
Penalty: Up to $25,000 per violation per day.

### P-02: Structuring Detection (Smurfing)
Any account that executes 3 or more transactions each between 9,000 and 9,999 USD
within any rolling 24-hour window is flagged as potential structuring.
These accounts must have a compliance_flags record with flag_type = 'STRUCTURING'.
Regulation: 31 U.S.C. § 5324 — structuring to evade reporting requirements.
Penalty: Criminal prosecution, asset seizure.

### P-03: OFAC Sanctions Screening
No settled or pending transaction may involve a counterparty whose name appears
on the active sanctions_list (delisted_at IS NULL).
Matching must catch exact name matches on counterparties.name vs sanctions_list.name.
Regulation: OFAC SDN List — 31 C.F.R. Parts 500-598.
Penalty: Civil penalty up to $1,000,000 per violation.

### P-04: Politically Exposed Person (PEP) Oversight
Any transaction >= 5,000 USD involving a customer with pep_flag = TRUE must have
a compliance_flags record with flag_type = 'SAR' (Suspicious Activity Report).
Regulation: FinCEN guidance FIN-2012-G003.
Penalty: Regulatory action, license revocation.

---

## Tier 2 — Fraud Signals (High Severity)

### P-05: Self-Transfer Prevention
A transaction's account_id must not map to the same customer_id as the
counterparty's linked account. Cross-reference: accounts.customer_id for both
the source account and any account linked to counterparties.account_number.
This prevents circular fund movement and layering.

### P-06: Velocity Breach
No account may execute more than 10 transactions within any rolling 60-minute
window. Count transactions by account_id where txn_timestamp falls within a
60-minute sliding window. Flag the account and the excess transactions.

### P-07: Dormant Account Reactivation Spike
An account whose last_activity_date is more than 180 days before the current
transaction date must not transact more than 1,000 USD without a manual review
compliance flag (flag_type = 'MANUAL_REVIEW').
Sudden reactivation of dormant accounts is a common money-mule indicator.

### P-08: New Account Large Wire
Any account opened fewer than 30 days before the transaction date must not
initiate a wire transfer (txn_type = 'wire') exceeding 5,000 USD.
New accounts with immediate large wires are a primary fraud vector.

---

## Tier 3 — Anomaly Signals (Medium Severity)

### P-09: Round Amount Concentration
If more than 40% of an account's transactions on a single calendar day are
exact multiples of 1,000 USD (amount_usd % 1000 = 0), flag the account.
Round-number concentration is a known structuring and layering indicator.

### P-10: Counterparty Concentration
No single counterparty_id should account for more than 60% of an account's
total outbound transaction volume (sum of amount_usd) within any 7-day window.
Concentration indicates potential layering or business-email-compromise payouts.

### P-11: Geographic Mismatch
A transaction's country_code must match the customer's country_of_residence
unless the account has international_travel_flag = TRUE.
Geographic mismatches without a travel flag indicate potential account takeover.

---

## Tier 4 — KYC / Data Completeness (Baseline)

### P-12: KYC Status Gate
No transaction with status = 'settled' may belong to a customer whose
kyc_status is 'pending' or 'failed'. Settling transactions for unverified
customers violates onboarding policy and AML know-your-customer requirements.
All customers must complete KYC before any transaction is settled.
