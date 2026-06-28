# Product maturity roadmap

Goal: bring ClubModule / Cyber Bonus to a reliable commercial product that can be sold to computer clubs with predictable onboarding, support, security, and operations.

## Target score: 9/10

| Area | Current estimate | Target | What 9/10 means |
| --- | ---: | ---: | --- |
| Product value | 8/10 | 9/10 | Clear club ROI, packaged use cases, demo data, repeatable sales story. |
| Functionality | 7/10 | 9/10 | Core owner and guest flows are complete, stable, and documented. |
| UX/UI | 5/10 | 9/10 | Owner can onboard, diagnose integrations, and manage CRM mechanics without developer help. |
| Architecture | 5/10 | 9/10 | Versioned DB migrations, separated services, testable business logic, predictable background jobs. |
| Security | 3-4/10 | 9/10 | Strict secrets, role boundaries, audit logs, rate limits, data protection baseline. |
| Scaling | 4/10 | 9/10 | Queue/worker model, monitoring, capacity plan, safe multi-club operations. |
| Onboarding | 4/10 | 9/10 | New club can be connected using a checklist and in-product diagnostics. |
| Support | 3/10 | 9/10 | Logs, alerts, admin support panel, backup/restore, incident playbooks. |
| Legal/commercial | 2/10 | 9/10 | Offer, privacy policy, SLA, tariff model, customer-facing materials. |

## Phase 1: Pilot readiness

Expected duration: 3-5 weeks.

Outcome: 2-3 pilot clubs can be connected manually and supported without constant emergency fixes.

### Engineering

- Add production environment validation.
- Add DB migration tool and move schema changes out of runtime code.
- Apply `scripts/migrate.py` before every production deploy.
- Add smoke tests and CI for import/config/security checks.
- Add liveness and readiness endpoints for deployment checks.
- Add deployment documentation for web app, guest bot, admin bot, and scheduled scripts.
- Add basic smoke tests for auth, owner dashboard, guest dashboard, and critical JSON endpoints.
- Add structured logging for sync scripts and Telegram workers.
- Add backup and restore instructions for MySQL.

### Product

- Create club onboarding checklist.
- Create LANGAME connection checklist.
- Create Telegram bot/chat setup checklist.
- Add a visible diagnostics block for sync status and bot status.
- Prepare a demo script for owner presentation.

### Security

- Require production secrets.
- Enable secure cookies in production.
- Review all owner/admin routes for club_id isolation.
- Add rate limiting for login and Telegram token polling.
- Add audit log table for sensitive owner/admin actions.

## Phase 2: Sales-ready product

Expected duration: 2-3 months.

Outcome: product can be sold as a managed SaaS with a repeatable setup process.

### Engineering

- Add CI with linting and tests.
- Add release process with changelog and rollback notes.
- Add admin support panel for clubs, sync status, bots, and recent errors.
- Add background job tracking in DB instead of relying only on log file mtimes.
- Add monitoring and alerts for failed syncs, bot failures, high error rates, and stale data.
- Add data export tools for club support and customer trust.

### Product

- Improve owner UX for first setup.
- Add guided empty states and integration status messages.
- Package 3-5 standard CRM scenarios: inactive guests, first visit, birthday, bonus giveaway, mission campaign.
- Add tariff boundaries and feature flags.
- Prepare customer-facing onboarding guide and FAQ.

### Commercial

- Define pricing model.
- Define support levels.
- Prepare sales deck and one-page offer.
- Prepare privacy policy, terms, and data processing agreement.

## Phase 3: SaaS scaling

Expected duration: 4-6 months.

Outcome: product can serve dozens of clubs with lower manual support load.

### Engineering

- Move recurring work to a proper task queue or managed scheduler.
- Add per-club health dashboard.
- Add tenant-aware performance metrics.
- Add DB indexes based on production query traces.
- Add load testing for dashboards, mailing, sync, and guest traffic.
- Add disaster recovery runbook.

### Product

- Add self-service onboarding where possible.
- Add in-product recommendations based on CRM data.
- Add admin tools for support impersonation with audit trail.
- Add lifecycle emails/Telegram messages for owners.

### Commercial

- Add billing process or billing integration.
- Add partner/channel materials.
- Add implementation package for paid onboarding.

## Definition of done for 9/10

- A new club can be onboarded using documented steps without code changes.
- Production cannot start with missing critical secrets.
- All schema changes are delivered through migrations.
- A support operator can see whether syncs, bots, mailings, and bonuses are healthy.
- Critical flows have automated smoke tests.
- Customer data handling is documented and contract-ready.
- Releases have rollback instructions.
- There are at least 2 successful pilot case studies with measured results.
