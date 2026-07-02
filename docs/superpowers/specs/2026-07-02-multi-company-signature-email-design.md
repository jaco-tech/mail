# Multi-Company Email Identity & Signatures — Design Spec

**Module:** `mail_user_signature_template`
**Branch:** `wip/multi-company-signature-email` (base commit `4b0d9e3`, off `19.0`)
**Date:** 2026-07-02
**Domain language:** see `mail_user_signature_template/CONTEXT.md`

## Problem

A single Odoo user whose login belongs to one company (the **Home Company**) must be able
to send email *as* a different company (the **Sending Company**) — with that company's From
address, outgoing mail server, and signature — without the Home Company's identity leaking
into the other context.

Driving scenario: Ann-Sophie logs in as `ann-sophie@steen-elektriciteit.be` but must email
steen-parts customers as `ann-sophie@steen-parts.be` with a steen-parts signature. Nothing
from steen-elektriciteit may appear in that mail (the **Identity Leaking** anti-goal).

## Confirmed infrastructure (prod, 2026-07-02)

- Per-domain outgoing mail servers with `from_filter`: `steen-parts.be` → M365,
  `steen-elektriciteit.be` → Google Workspace, `viaf.be, laurenssteen.be` → Google Workspace.
- Odoo core `ir_mail_server._find_mail_server(email_from)` routes the envelope by matching
  the From domain against `from_filter`. **Therefore a correct per-company `email_from` is
  sufficient to route via the right SPF/DKIM-authorized server** — the From override is a
  legitimate, deliverable mechanism, not spoofing.
- 14 companies exist; each domain has its own `mail.alias.domain` (bounce/catchall), so
  Odoo already derives per-company reply-to from the record's company `alias_domain_id`.

## Decisions (from grilling)

1. **Per-Company Identity** = `(From email, signature)` as an inseparable unit, modeled by
   `user.signature.company` (one row per user + company).
2. **Granularity:** per company, **explicitly configured**. No auto-derivation. No row →
   current behavior (user's normal email + signature).
3. **Sending Company resolution order:** (1) manual composer override → (2) record
   `company_id` → (3) navbar-active company (record-less fallback only).
4. **Manual override** ("Send as"): shown only to multi-company users
   (`len(user.company_ids) > 1`); lists configured identities + Home Company; flips From
   and signature together; defaults to the record-driven Sending Company.
5. **Management:** admin-managed only (Settings → Users). No self-service. Removes the
   impersonation surface.
6. **Reply-to / inbound:** out of scope — already correct via alias domains. Override only
   `email_from`, never `reply_to`.
7. **Rendering:** render signatures with `sudo()` (templates are admin-trusted). See ADR.
8. **Storage:** do not store per-company signature in `res.users.signature`. Render
   per-company on demand at send time. The stored field remains the user's default-company
   signature for the Preferences preview.

## Changes

### A. Signature rendering (fix findings 1, 2, 3)
- **`res_users.py`:** delete the `_init_store_data` override that rewrites `signature` on
  every page load. Revert `_compute_signature` to render with `user.company_id` (stored,
  deterministic, per-record) — not `env.company`.
- Keep `_get_company_signature(company)` as the on-demand per-company renderer used by send
  paths.
- **`signature_template.py`:** render with `sudo()` in `_render_signature` (or set
  `_unrestricted_rendering = True` on the model) so bare-variable templates render for
  non-admin users without `AccessError`.

### B. Email From on all send paths (fix findings 5, 6)
- **`mail_compose_message.py`:** in `_compute_authorship`, set `email_from` from the
  Sending Company identity keyed on the **record's company** (not `env.company`); **skip
  when `default_email_from` is in context**; keep pinning `author_id` to the acting user.
- **`mail_thread.py`:** add an `email_from` override in the notification-context path
  (matching the existing signature override) so notification/chatter emails carry the
  per-company address. Never set `reply_to`.

### C. Manual override "Send as" (new)
- **`mail_compose_message.py`:** add a field (e.g. `sending_company_id`, a Many2one to
  `res.company`) computed-default to the record-driven Sending Company; its onchange/compute
  drives `email_from` + the signature. Restrict the selectable set to the user's configured
  identities + Home Company.
- **View:** show the field only when `len(user.company_ids) > 1` (context flag or
  `invisible` domain on a helper field).

### D. Security & hygiene (fix findings 4, 7, 8, 11, 12)
- **HTML injection:** `Markup("<p>--<br/>%s</p>") % self.name` for the signature fallback;
  do not blanket-`Markup()` a raw f-string.
- **`sudo()`** the internal `user.signature.company` lookups (`_get_for_user_company`) so
  cross-env notify/recompute resolves the correct row.
- Add `NewId` guard to `_get_company_email`.
- **Drop dead self-service code:** remove `_get_signature_access_fields`, do not extend
  `SELF_WRITEABLE_FIELDS`, remove the unreachable standalone `user.signature.company` views;
  keep the admin Users-form o2m. Add a `display_name`/`_rec_name` to the model.
- **Light validation:** soft-warn (or constrain) that a configured identity `email`'s domain
  matches an authorized `ir.mail_server.from_filter` or a company alias domain, to catch
  typos that would route to the fallback server.

### E. Tests (fix coverage gaps)
- Non-admin user rendering a signature (would catch finding 1).
- Notify path where `env.user` ≠ author resolves the author's identity (finding 4).
- `default_email_from` in context survives the composer override (finding 5).
- Notification email carries per-company `email_from` (finding 6).
- "Send as" override flips From + signature together and is hidden for single-company users.
- Fallback (no row) == current behavior, for a non-admin user.

## Out of scope

- Per-company `reply_to` / inbound alias routing (already handled by `mail.alias.domain`).
- Per-company `ir.mail_server` selection code (Odoo's `from_filter` routing already does it).
- Self-service identity management.
- Auto-derivation of identities from alias domains / company email.

## ADR candidates (offer at review)

- **Render signatures with sudo** — trades "template editors can run QWeb in sudo" for
  "signatures render for all users"; acceptable because template editing is admin-restricted.
- **Do not store per-company signature in `res.users.signature`** — a future reader seeing
  the single stored field will wonder how per-company works; record that rendering is
  on-demand at send time by design.
