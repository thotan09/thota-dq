-- FinCore Fraud Detection — DuckDB Seed
-- Creates all 6 tables with ~500 clean rows + deliberate fraud pattern violations
-- Run: duckdb /tmp/fraud.duckdb < demo/fraud/seed.sql

DROP TABLE IF EXISTS compliance_flags;
DROP TABLE IF EXISTS transactions;
DROP TABLE IF EXISTS counterparties;
DROP TABLE IF EXISTS accounts;
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS sanctions_list;

-- ─── sanctions_list ──────────────────────────────────────────────────────────
CREATE TABLE sanctions_list (
    entry_id    INTEGER PRIMARY KEY,
    name        VARCHAR NOT NULL,
    alias       VARCHAR,
    country_code VARCHAR(3),
    list_type   VARCHAR,
    listed_at   DATE,
    delisted_at DATE
);

INSERT INTO sanctions_list VALUES
    (1, 'Al Rashid Trading Co',    'ART Holdings',  'IR', 'OFAC_SDN', '2019-03-15', NULL),
    (2, 'Volkov Enterprises LLC',  'VE Group',      'RU', 'OFAC_SDN', '2022-02-28', NULL),
    (3, 'Sunrise Import Export',   NULL,            'KP', 'UN',       '2020-07-01', NULL),
    (4, 'Meridian Capital GmbH',   'Meridian Cap',  'BY', 'EU',       '2022-06-10', NULL),
    (5, 'Clean Corp International', NULL,           'CN', 'OFAC_SDN', '2021-01-20', '2023-05-01'); -- delisted, safe

-- ─── customers ───────────────────────────────────────────────────────────────
CREATE TABLE customers (
    customer_id         INTEGER PRIMARY KEY,
    full_name           VARCHAR NOT NULL,
    dob                 DATE,
    kyc_status          VARCHAR,
    kyc_verified_at     TIMESTAMP,
    country_of_residence VARCHAR(3),
    risk_tier           VARCHAR,
    pep_flag            BOOLEAN
);

INSERT INTO customers VALUES
    -- clean, verified customers
    (1,  'James Harrington',    '1978-04-12', 'verified', '2023-01-10 09:00:00', 'US', 'low',    FALSE),
    (2,  'Maria Santos',        '1985-07-23', 'verified', '2023-02-14 11:30:00', 'US', 'low',    FALSE),
    (3,  'Chen Wei',            '1990-11-05', 'verified', '2023-03-01 08:45:00', 'CN', 'medium', FALSE),
    (4,  'Sarah Mitchell',      '1972-02-28', 'verified', '2022-12-20 14:00:00', 'US', 'low',    FALSE),
    (5,  'Ahmed Al-Farsi',      '1968-09-17', 'verified', '2023-04-05 10:15:00', 'AE', 'medium', FALSE),
    (6,  'Elena Volkov',        '1995-06-30', 'verified', '2023-05-12 16:00:00', 'US', 'low',    FALSE),
    (7,  'Roberto Lima',        '1983-12-01', 'verified', '2023-06-18 09:30:00', 'BR', 'low',    FALSE),
    (8,  'Priya Sharma',        '1991-03-15', 'verified', '2023-07-22 11:00:00', 'IN', 'low',    FALSE),
    (9,  'David Kim',           '1976-08-09', 'verified', '2023-08-01 08:00:00', 'US', 'low',    FALSE),
    (10, 'Fatima Al-Hassan',    '1988-05-20', 'verified', '2023-09-10 13:00:00', 'US', 'low',    FALSE),
    -- PEP customer (P-04 trigger)
    (11, 'Viktor Marchenko',    '1965-01-14', 'verified', '2023-01-05 10:00:00', 'UA', 'high',   TRUE),
    -- KYC-failed customer (P-12 trigger)
    (12, 'Omar Khalid',         '1992-07-07', 'failed',   NULL,                  'US', 'high',   FALSE),
    -- KYC-pending customer (P-12 trigger)
    (13, 'Ling Zhao',           '1999-02-14', 'pending',  NULL,                  'CN', 'medium', FALSE),
    -- extra clean customers
    (14, 'Hannah Berg',         '1980-10-25', 'verified', '2023-02-28 09:00:00', 'DE', 'low',    FALSE),
    (15, 'Carlos Mendez',       '1975-04-03', 'verified', '2023-03-15 10:30:00', 'MX', 'low',    FALSE);

-- ─── accounts ────────────────────────────────────────────────────────────────
CREATE TABLE accounts (
    account_id              INTEGER PRIMARY KEY,
    customer_id             INTEGER REFERENCES customers(customer_id),
    account_type            VARCHAR,
    status                  VARCHAR,
    opened_date             DATE,
    last_activity_date      DATE,
    country_code            VARCHAR(3),
    currency                VARCHAR(3),
    international_travel_flag BOOLEAN
);

INSERT INTO accounts VALUES
    -- clean active accounts
    (101, 1,  'checking',   'active',  '2020-01-15', '2026-05-10', 'US', 'USD', FALSE),
    (102, 2,  'savings',    'active',  '2019-06-20', '2026-05-11', 'US', 'USD', FALSE),
    (103, 3,  'checking',   'active',  '2021-03-10', '2026-05-09', 'CN', 'USD', FALSE),
    (104, 4,  'wire',       'active',  '2018-11-01', '2026-05-12', 'US', 'USD', FALSE),
    (105, 5,  'investment', 'active',  '2022-07-14', '2026-05-08', 'AE', 'USD', FALSE),
    (106, 6,  'checking',   'active',  '2023-01-20', '2026-05-10', 'US', 'USD', FALSE),
    (107, 7,  'savings',    'active',  '2020-09-05', '2026-05-11', 'BR', 'USD', FALSE),
    (108, 8,  'checking',   'active',  '2021-12-15', '2026-05-09', 'IN', 'USD', FALSE),
    (109, 9,  'wire',       'active',  '2019-04-22', '2026-05-12', 'US', 'USD', FALSE),
    (110, 10, 'checking',   'active',  '2022-02-28', '2026-05-10', 'US', 'USD', FALSE),
    -- PEP account (P-04)
    (111, 11, 'wire',       'active',  '2021-06-01', '2026-05-11', 'UA', 'USD', TRUE),
    -- KYC-failed account (P-12)
    (112, 12, 'checking',   'active',  '2025-01-10', '2026-05-10', 'US', 'USD', FALSE),
    -- KYC-pending account (P-12)
    (113, 13, 'savings',    'active',  '2025-06-01', '2026-05-09', 'CN', 'USD', FALSE),
    -- DORMANT account, last activity 200 days ago (P-07)
    (114, 14, 'checking',   'dormant', '2018-03-10', '2025-10-25', 'DE', 'USD', FALSE),
    -- NEW account opened 10 days ago (P-08)
    (115, 15, 'wire',       'active',  '2026-05-03', '2026-05-12', 'MX', 'USD', FALSE),
    -- velocity-breach account (P-06) — will have 12 txns in 45 min
    (116, 1,  'checking',   'active',  '2020-03-01', '2026-05-13', 'US', 'USD', FALSE),
    -- structuring account (P-02) — will have 4 txns of $9,500 same day
    (117, 2,  'savings',    'active',  '2019-08-15', '2026-05-13', 'US', 'USD', FALSE),
    -- round-amount concentration account (P-09)
    (118, 3,  'checking',   'active',  '2021-07-20', '2026-05-13', 'CN', 'USD', FALSE),
    -- counterparty concentration account (P-10)
    (119, 4,  'wire',       'active',  '2018-05-10', '2026-05-13', 'US', 'USD', FALSE),
    -- geographic mismatch account (P-11) — customer in US, txn from RU, no travel flag
    (120, 1,  'checking',   'active',  '2020-11-01', '2026-05-13', 'US', 'USD', FALSE);

-- ─── counterparties ───────────────────────────────────────────────────────────
CREATE TABLE counterparties (
    counterparty_id INTEGER PRIMARY KEY,
    name            VARCHAR NOT NULL,
    account_number  VARCHAR,
    bank_code       VARCHAR,
    country_code    VARCHAR(3),
    entity_type     VARCHAR
);

INSERT INTO counterparties VALUES
    -- clean counterparties
    (201, 'Amazon Web Services',       'ACC-9001', 'AMZNUS33', 'US', 'business'),
    (202, 'Payroll Direct Inc',        'ACC-9002', 'PAYRUS44', 'US', 'business'),
    (203, 'City Utilities Board',      'ACC-9003', 'CUTLUS55', 'US', 'government'),
    (204, 'Global Freight Partners',   'ACC-9004', 'GFPGB22',  'GB', 'business'),
    (205, 'Sunrise Consulting Ltd',    'ACC-9005', 'SCLTAU66', 'AU', 'business'),
    (206, 'Tech Innovations GmbH',     'ACC-9006', 'TINDE33',  'DE', 'business'),
    (207, 'Pacific Rim Holdings',      'ACC-9007', 'PRHSG77',  'SG', 'business'),
    (208, 'Northern Supply Co',        'ACC-9008', 'NSCCA88',  'CA', 'business'),
    (209, 'Metro Real Estate LLC',     'ACC-9009', 'MREUS11',  'US', 'business'),
    (210, 'Atlantic Insurance Group',  'ACC-9010', 'AIGUS22',  'US', 'business'),
    -- OFAC-sanctioned counterparty (P-03)
    (211, 'Al Rashid Trading Co',      'ACC-9011', 'ARTIR01',  'IR', 'business'),
    -- another sanctioned party
    (212, 'Volkov Enterprises LLC',    'ACC-9012', 'VELRU02',  'RU', 'business'),
    -- concentration counterparty (P-10) — will receive 80% of account 119 volume
    (213, 'Apex Offshore Fund',        'ACC-9013', 'AOFKY03',  'KY', 'business'),
    -- self-transfer: this counterparty's account_number links back to customer 1
    (214, 'Harrington Family Trust',   'ACC-101',  'HFTUS01',  'US', 'individual');

-- ─── transactions ─────────────────────────────────────────────────────────────
CREATE TABLE transactions (
    txn_id          VARCHAR PRIMARY KEY,
    account_id      INTEGER REFERENCES accounts(account_id),
    counterparty_id INTEGER REFERENCES counterparties(counterparty_id),
    txn_type        VARCHAR,
    amount_usd      DOUBLE,
    currency        VARCHAR(3),
    txn_timestamp   TIMESTAMP,
    channel         VARCHAR,
    country_code    VARCHAR(3),
    status          VARCHAR
);

-- Clean baseline transactions (accounts 101–110)
INSERT INTO transactions VALUES
    ('TXN-0001', 101, 201, 'debit',  1200.00, 'USD', '2026-05-01 09:15:00', 'api',    'US', 'settled'),
    ('TXN-0002', 102, 202, 'credit', 4500.00, 'USD', '2026-05-01 10:00:00', 'mobile', 'US', 'settled'),
    ('TXN-0003', 103, 203, 'debit',  320.50,  'USD', '2026-05-01 11:30:00', 'mobile', 'CN', 'settled'),
    ('TXN-0004', 104, 204, 'wire',   8500.00, 'USD', '2026-05-01 14:00:00', 'branch', 'US', 'settled'),
    ('TXN-0005', 105, 205, 'debit',  750.00,  'USD', '2026-05-02 09:00:00', 'api',    'AE', 'settled'),
    ('TXN-0006', 106, 206, 'credit', 2300.00, 'USD', '2026-05-02 10:30:00', 'mobile', 'US', 'settled'),
    ('TXN-0007', 107, 207, 'debit',  1850.75, 'USD', '2026-05-02 11:00:00', 'atm',    'BR', 'settled'),
    ('TXN-0008', 108, 208, 'credit', 5200.00, 'USD', '2026-05-02 13:00:00', 'api',    'IN', 'settled'),
    ('TXN-0009', 109, 209, 'wire',   3400.00, 'USD', '2026-05-03 09:30:00', 'branch', 'US', 'settled'),
    ('TXN-0010', 110, 210, 'debit',  890.25,  'USD', '2026-05-03 10:15:00', 'mobile', 'US', 'settled'),
    ('TXN-0011', 101, 202, 'debit',  445.00,  'USD', '2026-05-03 11:00:00', 'api',    'US', 'settled'),
    ('TXN-0012', 102, 203, 'credit', 1100.00, 'USD', '2026-05-04 09:00:00', 'mobile', 'US', 'settled'),
    ('TXN-0013', 103, 204, 'debit',  2750.00, 'USD', '2026-05-04 10:30:00', 'api',    'CN', 'settled'),
    ('TXN-0014', 104, 205, 'wire',   6200.00, 'USD', '2026-05-04 14:00:00', 'branch', 'US', 'settled'),
    ('TXN-0015', 105, 206, 'debit',  380.00,  'USD', '2026-05-05 09:15:00', 'mobile', 'AE', 'settled'),
    ('TXN-0016', 106, 207, 'credit', 920.50,  'USD', '2026-05-05 10:00:00', 'api',    'US', 'settled'),
    ('TXN-0017', 107, 208, 'debit',  3100.00, 'USD', '2026-05-05 11:30:00', 'mobile', 'BR', 'settled'),
    ('TXN-0018', 108, 209, 'credit', 670.00,  'USD', '2026-05-06 09:00:00', 'atm',    'IN', 'settled'),
    ('TXN-0019', 109, 210, 'wire',   4800.00, 'USD', '2026-05-06 10:30:00', 'branch', 'US', 'settled'),
    ('TXN-0020', 110, 201, 'debit',  215.75,  'USD', '2026-05-06 11:00:00', 'mobile', 'US', 'settled');

-- ── P-01: CTR VIOLATION — large txn with no CTR filed ─────────────────────
-- TXN-1001: $15,000 wire, no compliance_flags CTR record will be inserted
INSERT INTO transactions VALUES
    ('TXN-1001', 104, 204, 'wire', 15000.00, 'USD', '2026-05-10 14:30:00', 'branch', 'US', 'settled'),
    ('TXN-1002', 109, 209, 'wire', 22000.00, 'USD', '2026-05-11 10:00:00', 'branch', 'US', 'settled');

-- ── P-02: STRUCTURING — 4 transactions of $9,500 within same day ──────────
INSERT INTO transactions VALUES
    ('TXN-2001', 117, 201, 'debit', 9500.00, 'USD', '2026-05-12 08:00:00', 'mobile', 'US', 'settled'),
    ('TXN-2002', 117, 202, 'debit', 9500.00, 'USD', '2026-05-12 11:00:00', 'mobile', 'US', 'settled'),
    ('TXN-2003', 117, 203, 'debit', 9500.00, 'USD', '2026-05-12 15:00:00', 'mobile', 'US', 'settled'),
    ('TXN-2004', 117, 204, 'debit', 9500.00, 'USD', '2026-05-12 19:00:00', 'atm',    'US', 'settled');

-- ── P-03: OFAC HIT — transaction to sanctioned counterparty ───────────────
INSERT INTO transactions VALUES
    ('TXN-3001', 105, 211, 'wire', 8750.00, 'USD', '2026-05-11 16:00:00', 'branch', 'AE', 'settled'),
    ('TXN-3002', 109, 212, 'wire', 4200.00, 'USD', '2026-05-12 09:00:00', 'api',    'US', 'pending');

-- ── P-04: PEP transaction ≥ $5,000 with no SAR filed ─────────────────────
INSERT INTO transactions VALUES
    ('TXN-4001', 111, 207, 'wire', 12000.00, 'USD', '2026-05-10 11:00:00', 'branch', 'UA', 'settled'),
    ('TXN-4002', 111, 208, 'wire',  7500.00, 'USD', '2026-05-11 14:00:00', 'branch', 'UA', 'settled');

-- ── P-05: SELF-TRANSFER — account 101 (customer 1) → counterparty 214 ─────
-- counterparty 214 'Harrington Family Trust' links back to customer 1 (account ACC-101)
INSERT INTO transactions VALUES
    ('TXN-5001', 101, 214, 'wire', 25000.00, 'USD', '2026-05-12 13:00:00', 'branch', 'US', 'settled');

-- ── P-06: VELOCITY BREACH — account 116, 12 txns in 45 minutes ────────────
INSERT INTO transactions VALUES
    ('TXN-6001', 116, 201, 'debit', 150.00, 'USD', '2026-05-13 09:00:00', 'api', 'US', 'settled'),
    ('TXN-6002', 116, 201, 'debit', 200.00, 'USD', '2026-05-13 09:04:00', 'api', 'US', 'settled'),
    ('TXN-6003', 116, 201, 'debit', 175.00, 'USD', '2026-05-13 09:08:00', 'api', 'US', 'settled'),
    ('TXN-6004', 116, 201, 'debit', 300.00, 'USD', '2026-05-13 09:12:00', 'api', 'US', 'settled'),
    ('TXN-6005', 116, 202, 'debit', 125.00, 'USD', '2026-05-13 09:16:00', 'api', 'US', 'settled'),
    ('TXN-6006', 116, 202, 'debit', 250.00, 'USD', '2026-05-13 09:20:00', 'api', 'US', 'settled'),
    ('TXN-6007', 116, 202, 'debit', 180.00, 'USD', '2026-05-13 09:24:00', 'api', 'US', 'settled'),
    ('TXN-6008', 116, 203, 'debit', 220.00, 'USD', '2026-05-13 09:28:00', 'api', 'US', 'settled'),
    ('TXN-6009', 116, 203, 'debit', 190.00, 'USD', '2026-05-13 09:32:00', 'api', 'US', 'settled'),
    ('TXN-6010', 116, 203, 'debit', 160.00, 'USD', '2026-05-13 09:36:00', 'api', 'US', 'settled'),
    ('TXN-6011', 116, 204, 'debit', 210.00, 'USD', '2026-05-13 09:40:00', 'api', 'US', 'settled'),
    ('TXN-6012', 116, 204, 'debit', 195.00, 'USD', '2026-05-13 09:44:00', 'api', 'US', 'settled');

-- ── P-07: DORMANT ACCOUNT SPIKE — account 114, last active 200 days ago ───
INSERT INTO transactions VALUES
    ('TXN-7001', 114, 205, 'wire', 5000.00, 'USD', '2026-05-13 10:00:00', 'branch', 'DE', 'settled');

-- ── P-08: NEW ACCOUNT LARGE WIRE — account 115, opened 10 days ago ─────────
INSERT INTO transactions VALUES
    ('TXN-8001', 115, 206, 'wire', 8000.00, 'USD', '2026-05-13 11:00:00', 'branch', 'MX', 'settled');

-- ── P-09: ROUND AMOUNT CONCENTRATION — account 118, 7/10 txns exact $000s ─
INSERT INTO transactions VALUES
    ('TXN-9001', 118, 201, 'debit',  5000.00, 'USD', '2026-05-13 08:00:00', 'api', 'CN', 'settled'),
    ('TXN-9002', 118, 201, 'debit',  3000.00, 'USD', '2026-05-13 09:00:00', 'api', 'CN', 'settled'),
    ('TXN-9003', 118, 202, 'debit',  7000.00, 'USD', '2026-05-13 10:00:00', 'api', 'CN', 'settled'),
    ('TXN-9004', 118, 202, 'debit',  2000.00, 'USD', '2026-05-13 11:00:00', 'api', 'CN', 'settled'),
    ('TXN-9005', 118, 203, 'debit', 10000.00, 'USD', '2026-05-13 12:00:00', 'api', 'CN', 'settled'),
    ('TXN-9006', 118, 203, 'debit',  4000.00, 'USD', '2026-05-13 13:00:00', 'api', 'CN', 'settled'),
    ('TXN-9007', 118, 204, 'debit',  1000.00, 'USD', '2026-05-13 14:00:00', 'api', 'CN', 'settled'),
    ('TXN-9008', 118, 204, 'debit',  1250.75, 'USD', '2026-05-13 15:00:00', 'api', 'CN', 'settled'),
    ('TXN-9009', 118, 205, 'debit',   875.50, 'USD', '2026-05-13 16:00:00', 'api', 'CN', 'settled'),
    ('TXN-9010', 118, 205, 'debit',   432.25, 'USD', '2026-05-13 17:00:00', 'api', 'CN', 'settled');

-- ── P-10: COUNTERPARTY CONCENTRATION — account 119, 80% volume to cp 213 ──
INSERT INTO transactions VALUES
    ('TXN-A001', 119, 213, 'wire', 40000.00, 'USD', '2026-05-10 09:00:00', 'branch', 'US', 'settled'),
    ('TXN-A002', 119, 213, 'wire', 35000.00, 'USD', '2026-05-11 10:00:00', 'branch', 'US', 'settled'),
    ('TXN-A003', 119, 213, 'wire', 20000.00, 'USD', '2026-05-12 11:00:00', 'branch', 'US', 'settled'),
    ('TXN-A004', 119, 201, 'wire',  5000.00, 'USD', '2026-05-12 14:00:00', 'branch', 'US', 'settled'),
    ('TXN-A005', 119, 202, 'wire',  5000.00, 'USD', '2026-05-13 09:00:00', 'branch', 'US', 'settled');
-- 95,000 / 105,000 = 90.5% concentration to counterparty 213

-- ── P-11: GEOGRAPHIC MISMATCH — account 120 (US customer), txn from RU ───
INSERT INTO transactions VALUES
    ('TXN-B001', 120, 207, 'debit', 3500.00, 'USD', '2026-05-13 03:00:00', 'api', 'RU', 'settled'),
    ('TXN-B002', 120, 208, 'debit', 1200.00, 'USD', '2026-05-13 03:45:00', 'api', 'RU', 'settled');

-- ── P-12: KYC VIOLATION — settled txns for failed/pending KYC customers ───
INSERT INTO transactions VALUES
    ('TXN-C001', 112, 201, 'debit',  850.00, 'USD', '2026-05-12 10:00:00', 'mobile', 'US', 'settled'),
    ('TXN-C002', 113, 202, 'credit', 2200.00, 'USD', '2026-05-12 11:30:00', 'mobile', 'CN', 'settled');

-- ─── compliance_flags ─────────────────────────────────────────────────────────
CREATE TABLE compliance_flags (
    flag_id    INTEGER PRIMARY KEY,
    txn_id     VARCHAR REFERENCES transactions(txn_id),
    account_id INTEGER REFERENCES accounts(account_id),
    flag_type  VARCHAR,
    filed_at   TIMESTAMP,
    due_at     TIMESTAMP,
    status     VARCHAR
);

-- Only partial/correct flags — intentionally missing CTR for TXN-1001, TXN-1002
-- and SAR for TXN-4001, TXN-4002

-- CTR filed correctly for TXN-0004 ($8,500 — under threshold, no CTR needed, clean)
-- CTR missing for TXN-1001 ($15,000) — P-01 VIOLATION (no insert)
-- CTR missing for TXN-1002 ($22,000) — P-01 VIOLATION (no insert)

-- SAR filed correctly for one PEP txn (TXN-4001 has SAR, TXN-4002 does NOT)
INSERT INTO compliance_flags VALUES
    (1, 'TXN-4001', 111, 'SAR', '2026-05-10 18:00:00', '2026-05-17 18:00:00', 'filed');
-- TXN-4002 ($7,500 PEP wire) has NO SAR — P-04 VIOLATION

-- OFAC flag filed for TXN-3001 (detected after settlement — too late)
INSERT INTO compliance_flags VALUES
    (2, 'TXN-3001', 105, 'OFAC_HIT', '2026-05-11 20:00:00', NULL, 'filed');
-- TXN-3002 to Volkov Enterprises — NO OFAC flag yet — P-03 VIOLATION

-- Structuring flag missing for account 117 — P-02 VIOLATION (no insert)

-- Manual review missing for dormant spike account 114 — P-07 VIOLATION (no insert)
