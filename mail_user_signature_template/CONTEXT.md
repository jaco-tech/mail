# Multi-Company Email Identity & Signatures

How a single Odoo user, whose login belongs to one company, can send email *as* a
different company — with that company's From address, outgoing mail server, and
signature — without the login company's identity leaking into the other context.

## Language

**Home Company**:
The company of the user's Odoo login / default `company_id`.
_Example_: Ann-Sophie logs in as `ann-sophie@steen-elektriciteit.be`; steen-elektriciteit is her Home Company.

**Sending Company**:
The company on whose behalf a specific email is sent. May differ from the Home Company.
_Avoid_: "current company" (ambiguous — see Flagged ambiguities), "active company".

**Per-Company Identity**:
The `(From email, signature)` pair a user presents when sending as a given Sending Company. Modeled by the `user.signature.company` record (one per user + company).
_Avoid_: "alias" (Odoo `mail.alias` is a different concept — inbound routing).

**Identity Leaking**:
The anti-goal: any Home-Company identity — From address, signature, logo, branding — appearing in an email whose Sending Company is different. Preventing this is the feature's core purpose.

**From-Filter Routing**:
Odoo's built-in selection of the outgoing `ir.mail_server` by matching the From address's domain against each server's `from_filter` (`ir_mail_server._find_mail_server`). Prod has one authorized server per domain, so a correct per-company From address is sufficient to route via the right (SPF/DKIM-authorized) server.

## Relationships

- A **User** has one **Home Company** and zero or more **Per-Company Identities**.
- A **Per-Company Identity** belongs to exactly one **User** + one **Sending Company**.
- The **Sending Company** determines the From address, which (via **From-Filter Routing**) determines the outgoing mail server and thus which domain's SPF/DKIM signs the mail.
- **Identity Leaking** occurs when the **Sending Company** is not correctly propagated to *every* send path (composer AND notification).

## Confirmed infrastructure (prod, checked 2026-07-02)

Per-domain outgoing mail servers already exist with `from_filter` set:
- `steen-parts.be` → M365 / Office365
- `steen-elektriciteit.be` → Google Workspace
- `viaf.be, laurenssteen.be` → Google Workspace

Therefore per-company From is a legitimate, deliverable mechanism here — not a spoofing risk — provided `email_from` is set correctly on all send paths.

## Example dialogue

> **Dev:** "When Ann-Sophie emails a steen-parts customer, what's the **Sending Company**?"
> **Domain expert:** "steen-parts — even though her login (**Home Company**) is steen-elektriciteit. Nothing from steen-elektriciteit should show up: not the From, not the signature. That's **Identity Leaking** and it's the whole thing we're preventing."

## Sending Company resolution (decided 2026-07-02)

The **Sending Company** for an email is determined by, in order:
1. **Manual override** on the mail composer, if the user set one for this email.
2. The **record's `company_id`** (the document the email is about) — the default.
3. The **navbar-active company** — fallback only when there is no record (e.g. a
   brand-new Discuss/compose with no `company_id`).

Automated notification emails (chatter) have no composer, so they always use (2)/(3).

The manual override selector ("Send as") is only shown to **multi-company users**
(`len(user.company_ids) > 1`). Single-company users never see it.

The override switches the **whole Per-Company Identity as a unit**: From address and
signature always move together (never a From from one company with a signature from
another). The selector lists only the companies the user has a configured Per-Company
Identity for, plus the Home Company as default.

## Granularity & fallback (decided 2026-07-02)

Per-Company Identity is **per company, explicitly configured** — no auto-derivation from
alias domain or company email. A company **without** a configured `user.signature.company`
row falls back to the user's normal email and normal signature — i.e. exactly the current
behavior. The user configures a row only for companies that genuinely need a distinct
identity, not for all companies they belong to.

## Who manages identities (decided 2026-07-02)

Per-Company Identities are **admin-managed only** (Settings → Users). Regular users do
not self-configure their own From addresses — this removes the impersonation surface.
The half-built self-service path in the WIP (preferences o2m, `SELF_WRITEABLE_FIELDS`,
`_get_signature_access_fields`) is dropped; the admin Users-form o2m is kept.

## Reply-to / inbound (out of scope — already correct)

Each domain has its own `mail.alias.domain` (bounce/catchall). Odoo derives reply-to from
the **record's company → `alias_domain_id` → `catchall@domain`**, the same record-company
driver as the Sending Company default. This feature therefore **overrides only
`email_from`, never `reply_to`**, so existing per-company inbound routing is preserved. (A
manual override to a company other than the record's would let From and reply-to diverge —
accepted as a rare edge case.)

## Flagged ambiguities

- "current company" was used to mean both the user's navbar-active company and the company a record belongs to. Resolved: the **Sending Company** is what matters; resolution order is recorded above (record `company_id` first, navbar-active only as record-less fallback, manual override wins).
