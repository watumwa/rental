# RentPro

RentPro is a Django property-operations system built around the complete rental lifecycle:

`Owner → Property → Vacancy → Application → Tenant → Lease → Move-in → Billing → Payment → Maintenance → Renewal/notice → Move-out → Deposit settlement → Owner payout`

Amounts are presented in UGX and the payment workflow supports cash, bank, MTN Mobile Money and Airtel Money records.

## End-to-end workflows

- Role-based workspaces for administrators, property managers, accountants, maintenance officers, landlords and tenants
- Owner payout details, management-fee configuration, properties, buildings, units, vendors and inventory
- Vacancy applications with screening, approval/rejection, automatic prospective-tenant creation and unit reservation
- Pending lease approval, completed move-in inspection requirement, activation and recurring billing
- Monthly, quarterly or annual rent schedules plus recurring service charges
- Manual late fees, damage charges, other charges and ledger credits
- Meter registration, verified water/electricity readings and automatic utility charges
- Oldest-charge-first allocation for partial and advance payments
- Permanent receipts, payment voids, unallocated-credit refunds and provider/bank reconciliation
- Separate immutable security-deposit receipts, deductions and refunds
- Arrears ageing and idempotent daily reminder queuing
- Maintenance assignment and controlled new-to-closed status transitions
- Move-in, routine and move-out inspections with condition items, readings, keys and acknowledgement
- Lease notices, amendments, rent changes, term extensions, renewals and controlled move-out closure
- Secure document register with permission-checked downloads
- In-app, email, SMS and WhatsApp communication queues and audit history
- Property expenses, owner statements, management fees, approval and payout references
- Tenant and landlord self-service portals with data scoped to their linked profile
- Dashboard, global search, audit logs, printable records and CSV performance export

Financial records are append-only: payments, allocations, receipts, refunds, deposit transactions, rent charges and expenses cannot be deleted through the operational application. Corrections use voids, refunds, credits or amendments so history remains visible.

## Run locally

```bash
./.venv/bin/python manage.py migrate
./.venv/bin/python manage.py createsuperuser
./.venv/bin/python manage.py runserver
```

Open <http://127.0.0.1:8000/>. New Django users receive the `Viewer` role. Assign their operational role under **User profiles** in Django Admin before they use the staff workspace. Link landlord and tenant portal accounts through the corresponding `user` field.

## Load Uganda demo data

```bash
./.venv/bin/python seed.py
```

The idempotent seed creates fictional Uganda-oriented records across the complete workflow, including 10 landlords, 10 properties, 20 units, 10 tenants, 20 applications, 10 leases and at least 10 records in each major operational module. It also prints the local demo credentials when complete. Never use the demo identities, phone numbers, references or password in production.

## Daily operations

Run this command daily from cron, systemd or the deployment scheduler:

```bash
./.venv/bin/python manage.py run_daily_operations
```

It marks leases expiring within 45 days, expires ended leases and queues one arrears reminder per charge per day.

## Verify

```bash
./.venv/bin/python manage.py check
./.venv/bin/python manage.py makemigrations --check --dry-run
./.venv/bin/python manage.py test rentalapp
```

The suite currently covers 19 access-control, rent-accounting, application, inspection, lease, utility, deposit, owner-statement and daily-automation scenarios.

For a deployment-mode security check:

```bash
RENTAL_DEBUG=0 \
RENTAL_SECRET_KEY='replace-with-a-long-random-secret' \
RENTAL_ALLOWED_HOSTS='rent.example.com' \
./.venv/bin/python manage.py check --deploy
```

## Environment configuration

| Variable | Purpose | Development default |
|---|---|---|
| `RENTAL_SECRET_KEY` | Django signing secret | Unsafe development-only value |
| `RENTAL_DEBUG` | Enables Django debug mode | `1` |
| `RENTAL_ALLOWED_HOSTS` | Comma-separated host names | `localhost,127.0.0.1,testserver` |
| `RENTAL_CSRF_TRUSTED_ORIGINS` | Comma-separated HTTPS origins | Empty |
| `RENTAL_DB_ENGINE` | Django database backend | SQLite |
| `RENTAL_DB_NAME` | Database name or SQLite path | `db.sqlite3` |
| `RENTAL_DB_USER` | Database user | Empty |
| `RENTAL_DB_PASSWORD` | Database password | Empty |
| `RENTAL_DB_HOST` | Database host | Empty |
| `RENTAL_DB_PORT` | Database port | Empty |
| `RENTAL_SECURE_SSL_REDIRECT` | Redirect production traffic to HTTPS | `1` |
| `RENTAL_HSTS_SECONDS` | Production HSTS duration | `31536000` |

Use PostgreSQL, HTTPS, encrypted backups and restricted media storage for production. Do not commit production credentials or identity/lease documents.

## Integration boundary

External email, SMS, WhatsApp, Mobile Money and bank connections require provider credentials and a deployment-specific delivery/webhook adapter. RentPro stores auditable queues and reconciliation records but intentionally does not pretend that a queued external message or imported transaction was delivered by a provider.

Ugandan deposit, notice, rent-increase, tax and privacy rules are not hard-coded. Have current policies reviewed professionally before enabling automated fees, statutory notices or tax filing.
