# Database Schema — FinCore Fraud Detection

## Table: accounts
Primary entity. Each row is a bank account.

| Column | Type | Description |
|---|---|---|
| account_id | INTEGER | Primary key |
| customer_id | INTEGER | FK → customers.customer_id |
| account_type | VARCHAR | 'checking', 'savings', 'wire', 'investment' |
| status | VARCHAR | 'active', 'frozen', 'dormant', 'closed' |
| opened_date | DATE | Date account was opened |
| last_activity_date | DATE | Date of most recent prior transaction |
| country_code | VARCHAR(3) | ISO country code of account registration |
| currency | VARCHAR(3) | Primary currency (e.g. 'USD') |
| international_travel_flag | BOOLEAN | TRUE if customer declared international travel |

## Table: customers
KYC / identity data for each customer.

| Column | Type | Description |
|---|---|---|
| customer_id | INTEGER | Primary key |
| full_name | VARCHAR | Legal full name |
| dob | DATE | Date of birth |
| kyc_status | VARCHAR | 'verified', 'pending', 'failed' |
| kyc_verified_at | TIMESTAMP | When KYC was completed |
| country_of_residence | VARCHAR(3) | ISO country code |
| risk_tier | VARCHAR | 'low', 'medium', 'high' |
| pep_flag | BOOLEAN | TRUE = Politically Exposed Person |

## Table: transactions
Core ledger. Every debit, credit, wire, ACH, or internal transfer.

| Column | Type | Description |
|---|---|---|
| txn_id | VARCHAR | Primary key (e.g. 'TXN-00001') |
| account_id | INTEGER | FK → accounts.account_id |
| counterparty_id | INTEGER | FK → counterparties.counterparty_id |
| txn_type | VARCHAR | 'debit', 'credit', 'wire', 'ach', 'internal' |
| amount_usd | DOUBLE | Transaction amount in USD |
| currency | VARCHAR(3) | Original currency |
| txn_timestamp | TIMESTAMP | Exact time of transaction |
| channel | VARCHAR | 'mobile', 'branch', 'api', 'atm' |
| country_code | VARCHAR(3) | Country where transaction originated |
| status | VARCHAR | 'pending', 'settled', 'reversed', 'flagged' |

## Table: counterparties
External parties receiving or sending funds.

| Column | Type | Description |
|---|---|---|
| counterparty_id | INTEGER | Primary key |
| name | VARCHAR | Legal name of counterparty |
| account_number | VARCHAR | Their bank account number |
| bank_code | VARCHAR | SWIFT/routing code |
| country_code | VARCHAR(3) | Counterparty country |
| entity_type | VARCHAR | 'individual', 'business', 'government' |

## Table: compliance_flags
CTR, SAR, OFAC, STRUCTURING, and MANUAL_REVIEW filings.

| Column | Type | Description |
|---|---|---|
| flag_id | INTEGER | Primary key |
| txn_id | VARCHAR | FK → transactions.txn_id (nullable for account-level flags) |
| account_id | INTEGER | FK → accounts.account_id |
| flag_type | VARCHAR | 'CTR', 'SAR', 'OFAC_HIT', 'STRUCTURING', 'MANUAL_REVIEW' |
| filed_at | TIMESTAMP | When the flag was filed |
| due_at | TIMESTAMP | Regulatory deadline |
| status | VARCHAR | 'filed', 'overdue', 'waived' |

## Table: sanctions_list
OFAC SDN and equivalent sanctions entries.

| Column | Type | Description |
|---|---|---|
| entry_id | INTEGER | Primary key |
| name | VARCHAR | Sanctioned entity or individual name |
| alias | VARCHAR | Known alias (nullable) |
| country_code | VARCHAR(3) | Country of sanctioned party |
| list_type | VARCHAR | 'OFAC_SDN', 'EU', 'UN' |
| listed_at | DATE | Date added to list |
| delisted_at | DATE | Date removed (NULL = still active) |

## Key Relationships

- transactions.account_id → accounts.account_id
- transactions.counterparty_id → counterparties.counterparty_id
- accounts.customer_id → customers.customer_id
- compliance_flags.txn_id → transactions.txn_id
- compliance_flags.account_id → accounts.account_id
- Sanctions check: counterparties.name = sanctions_list.name WHERE sanctions_list.delisted_at IS NULL
