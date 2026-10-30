# Cyber Cafe Business OS — Telegram + Turso + GitHub Actions

This bundle updates the **same five existing repository files**. No extra repository file is required.

## Business OS commands

- `/stock`, `/stockadd`, `/stockuse` — inventory, movement ledger and low-stock alerts.
- `/expense`, `/expenses` — manually entered expenses.
- `/pnl today`, `/pnl 7d`, `/pnl 30d` — operational estimate of recorded verified payments minus entered expenses.
- `/crm` — customer activity, repeat orders and dormant-customer summary.
- `/sla` — overdue orders and observed turnaround-time metrics.
- `/biz` — command guide.

These are operational estimates, not audited accounting. Stock movements and expenses must be entered by staff.

## Payment gateway guide for non-technical shop owners

Run `/paymentsetup` in Telegram as the configured Owner. A button menu explains UPI/manual review, Razorpay, Cashfree, PhonePe PG, Paytm PG, and custom APIs in plain language. `/gatewaylist` shows generic REST providers configured in the database. This reduces the need to remember commands, but **the directory is not a claim that every named gateway is already integrated**.

### What works in this build

- **UPI QR + manual review:** available with the current order flow. The owner checks the real bank/UPI transaction before approval.
- **Generic REST pull adapter:** can be configured for a compatible API that provides a reliable lookup response with a unique exact UTR, final paid status, exact expected amount, and INR currency. The API host must be explicitly allowlisted.
- **Gateway-specific order creation, hosted checkout, signatures/checksums, and webhooks:** not universal. The current UPI QR flow does not create a Razorpay/Cashfree/PhonePe/Paytm merchant order automatically. Merely entering API keys cannot make it work.

### Why webhooks need hosting

A webhook provider sends an HTTP request to a publicly reachable HTTPS endpoint. GitHub Actions is a scheduled/long-running job runner, not a persistent inbound HTTP server. For webhook-only integration, deploy a dedicated HTTPS receiver or use a supported provider-managed relay, then verify the provider's signature/checksum and transaction mapping before updating Turso. Do not treat a browser redirect or unverified webhook body as payment proof.

Official documentation starting points (provider products and account permissions vary):
- Razorpay: https://razorpay.com/docs/api/ and https://razorpay.com/docs/webhooks/
- Cashfree: https://docs.cashfree.com/
- PhonePe: https://developer.phonepe.com/
- Paytm: https://business.paytm.com/docs/

The bot intentionally marks these popular gateway entries as **guided / not plug-and-play in this build** until a gateway-specific order/status/signature flow is implemented and tested. No software can safely promise compatibility with every gateway without that provider's API contract, merchant credentials, and an appropriate inbound endpoint where webhooks are required.

## Payment verification — strict and opt-in

Payment proofs remain **manual-review by default**. OCR, a screenshot, or a claimed UTR is not proof of settlement.

An optional config-driven REST adapter is included, but it auto-verifies only when the provider API returns a unique record matching **the exact UTR + paid status + expected amount + INR currency**. If any check is missing, ambiguous, unavailable, or mismatched, the payment stays in manual review. Providers that do not expose a reliable transaction lookup cannot be auto-verified by this adapter.

Owner-only Telegram commands:

- `/paymentsetup` — guided payment gateway directory for non-technical owners.
- `/gatewaylist` or `/providers` — list configured generic REST providers.
- `/addprovider <name> <JSON>` — add/update provider config.
- `/toggleprovider <name>` — enable/disable.
- `/delprovider <name>` — remove provider config.
- `/testprovider <name> <REAL_UTR> <ORDER_CODE>` — read-only API lookup; never approves an order.

Provider config is stored in Turso, but credentials must be referenced by GitHub Actions environment variables, not pasted into Telegram JSON. Example **template only** (not a working configuration for any named company):

```json
{
  "enabled": true,
  "priority": 10,
  "auth": {"type": "bearer", "token": {"env": "PROVIDER_API_TOKEN"}},
  "lookup": {"method": "GET", "url": "https://api.example.com/transactions/{utr}"},
  "verify": {"path": "status", "value": "SUCCESS"},
  "amount": {"path": "amount", "multiplier": 1, "tolerance": 0},
  "match": {"path": "utr", "source": "utr"},
  "currency": {"path": "currency", "value": "INR"},
  "id": {"path": "id"}
}
```

Paths and values must match the provider's **official API response**. If the API returns a list, set `lookup.records_path` to the list path; the adapter searches the list and requires exactly one UTR match. `multiplier` is normally `1` for rupees or `0.01` for paise. `headers` can contain non-secret literals or environment references such as `{"env":"PROVIDER_CLIENT_ID"}`. Auth supports `none`, `basic`, `bearer`, and `header`; credentials are env references only.

### Enable only after test

1. Add needed provider credentials under **GitHub → Settings → Secrets and variables → Actions → Secrets**. Never put secrets in source code or Telegram JSON.
2. Add repository variable `PAYMENT_PROVIDER_ALLOWED_HOSTS` with the exact API host(s), comma-separated (for example, the official host from the provider's docs, not a guessed hostname).
3. Add repository variable `PAYMENT_AUTO_VERIFY_ENABLED` with value `1` only after validating the config against official transaction records. Leave it unset/`0` otherwise.
4. Configure provider through Telegram as the Owner and use `/testprovider name REAL_UTR ORDER_CODE`. A failed/ambiguous test should remain manual. Test in a disposable database and test bot before real customer traffic.

Security behavior: HTTPS only, exact host allowlist, standard port only, redirects disabled, short timeout, limited response size, secrets read from environment, and fail-closed verification. The host allowlist must not be broadened to arbitrary domains. Do not assume that adding a provider JSON makes an API compatible. Some providers require webhooks, signatures, merchant-side order creation, or provider-specific code and therefore are **not** supported by this pull-based adapter alone.

## Configure GitHub Actions Secrets

Add these under **Settings → Secrets and variables → Actions → Secrets**:

- `BOT_TOKEN` — Telegram bot token.
- `TURSO_DATABASE_URL` — Turso database URL, e.g. `libsql://your-db-your-org.turso.io`.
- `TURSO_AUTH_TOKEN` — token for that database.
- `ADMIN_USER_IDS` — comma-separated Telegram user IDs allowed to administer the bot.
- `OWNER_USER_IDS` — comma-separated Owner IDs; provider configuration commands are Owner-only.
- `ADMIN_ALERT_CHAT_ID` — optional Telegram user/group chat ID for alerts.
- `UPI_ID` — optional UPI ID used to generate a payment QR.
- Provider credentials, if needed, using the exact environment variable names referenced in provider JSON.

Optional repository variable: `PAYEE_NAME`.

## Telegram service catalogue

Open `/admin` → **🧰 Service/fee/document manager**. Authorized admins can add categories/services, change fees and instructions, attach guide files, rename or disable services, and change urgent fee, UPI ID, payee name and default SLA. These settings are saved in Turso.

## Database and application APIs

- Database: Turso/libSQL embedded replica.
- Messaging: Telegram Bot API.
- No AI API or external OCR API is called. Optional OCR uses local Tesseract only if installed; OCR never approves payment.
- Existing databases receive an idempotent migration for provider metadata and payment source fields at startup.

## Important deployment limits

- GitHub Actions is **not an always-on host**. The workflow runs for up to 5h45m and schedules a new run every six hours; downtime and delayed scheduled starts are possible.
- This is a single-shop bot, not a production multi-tenant SaaS. Multi-shop isolation, tenant-specific bot tokens, stronger staff roles and formal accounting are not implemented.
- This Telegram bot cannot lock external PCs or automatically track PC sessions without client software on each PC.
- Auto-verification is not guaranteed for Razorpay, Cashfree, PhonePe, PayU, Paytm, BharatPe or any other named provider until the exact API is configured and tested. Do not use list-first-record configs or status-only configs.
- Before real deployment, test new order, payment proof, duplicate UTR, manual approval/rejection, provider timeout, amount mismatch, admin reversal, receipt delivery, backup and Turso sync in a separate test bot/database.

## Public repository safety

Never commit bot tokens, Turso tokens, `.env`, database files, customer exports, or backups. If a token was ever committed, revoke/rotate it immediately; deleting the visible line is not enough.

## Beginner mode: first shop setup (no coding in Telegram)

After the owner/admin account is authorized and the bot is running, the shop owner can finish common settings inside Telegram:

1. Send `/guide` for the plain-language start guide.
2. Send `/setup` and answer four questions: shop name, UPI ID (or `-` to skip), urgent fee, and target turnaround hours.
3. Send `/checksetup` to see a checklist of remaining setup tasks.
4. Open `/admin` → **🧰 Service/fee/document manager** to review each service, its price, customer instructions, and optional guide files.
5. Use a second Telegram account to place a test order and test the order, document, payment-review, and completion flow before announcing the bot to customers.

The guided wizard saves shop settings to Turso. It does not change the bot token, database credentials, or access-control IDs, and it cannot create GitHub/Turso accounts for you.

### One-time setup explained for a non-technical shop owner

- **Telegram bot:** open the official `@BotFather` account in Telegram, create a bot, and copy its token privately.
- **Turso database:** create a database and copy its database URL and auth token. Treat the token like a password.
- **GitHub repository:** in **Settings → Secrets and variables → Actions**, first add `BOT_TOKEN`, `TURSO_DATABASE_URL`, and `TURSO_AUTH_TOKEN`. Do not paste any token into a public issue, code file, or Telegram group.
- **Start once to get your Telegram ID:** open the repository's **Actions** tab → **Cyber Cafe Telegram Bot** → **Run workflow**. Open your bot in Telegram and send `/myid`; copy the numeric ID it returns.
- **Give yourself admin access:** add that numeric ID to both `OWNER_USER_IDS` and `ADMIN_USER_IDS` under GitHub Actions Secrets, then run the workflow again. Review the run log for success. User IDs are not usernames; do not add `@username` here.
- **Important:** if no owner/admin IDs are configured, the Telegram admin controls will not be available. If the GitHub Actions run ends, the bot may be offline until a later run starts. GitHub Actions is not a 24/7 hosting guarantee.

If these initial GitHub/Turso steps feel too difficult, have a trusted technical person configure them once. After deployment, routine service/price/instruction changes can be made in Telegram without editing code.




UI NOTE: Telegram bots cannot force a user phone into landscape orientation. This version uses one full-width button per row and prints complete service names/prices in the message to prevent two-column clipping on narrow Android screens. Telegram limits individual inline-button labels to 64 characters; longer details remain visible in the message.
