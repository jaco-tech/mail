# Multi-Company Email Identity & Signatures Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one Odoo user send email *as* different companies — each with its own From address and signature — with no Home-Company identity leaking into another company's mail.

**Architecture:** Per-Company Identity (`user.signature.company`, one row per user+company, admin-managed) resolves a `(From email, signature)` pair. The signature is rendered on demand at send time (never stored per-company); the From is set on every send path (composer + notification) so Odoo's `from_filter` routing selects the right SPF/DKIM-authorized mail server. Reply-to is left to Odoo's existing per-company alias domains.

**Tech Stack:** Odoo 19.0, Python, QWeb (`mail.render.mixin`), OWL-free form views.

## Global Constraints

- Odoo **19.0** conventions: `<list>` not `<tree>`; `self.env._()` for translations; `models.Constraint` for SQL constraints; no OWL directives in form views.
- Module under test: `mail_user_signature_template`. Full paths below are relative to the repo root `/home/jaco/DEV/jaco-tech-mail`.
- Spec: `docs/superpowers/specs/2026-07-02-multi-company-signature-email-design.md`. Domain language: `mail_user_signature_template/CONTEXT.md`. Decisions: `docs/adr/0001`, `docs/adr/0002`.
- **Never override `reply_to`.** Override only `email_from`.
- **Identities are admin-managed.** Regular users get read-only access to their own rows; only `group_signature_template_manager` / `base.group_system` may create/write/unlink.
- **Test command** (run in the dev Odoo instance; the developer manages the server lifecycle):
  ```bash
  odoo-bin -d <dev_db> -u mail_user_signature_template \
    --test-enable --test-tags /mail_user_signature_template \
    --stop-after-init --log-level=test
  ```
  New tests go in `mail_user_signature_template/tests/test_multi_company_signature.py` (existing `TransactionCase`, `@tagged("post_install", "-at_install")`). Expected-fail vs expected-pass is called out per step.

---

### Task 1: Stop poisoning the stored signature; render per-company with sudo

Removes the every-page-load write and cross-user recompute poisoning (review findings 1–3). Implements ADR-0001 (sudo render) and ADR-0002 (no stored per-company signature).

**Files:**
- Modify: `mail_user_signature_template/models/res_users.py` (`_compute_signature`, remove `_init_store_data`)
- Modify: `mail_user_signature_template/models/signature_template.py:408-431` (`_render_signature`)
- Test: `mail_user_signature_template/tests/test_multi_company_signature.py`

**Interfaces:**
- Produces: `signature.template._render_signature(user, company=None)` renders unrestricted (works for non-admin users). `res.users._compute_signature` renders the stored `signature` from `user.company_id` (deterministic). `res.users` no longer defines `_init_store_data`.

- [ ] **Step 1: Write the failing test** — add to the test class:

```python
def test_non_admin_can_render_signature(self):
    """A plain internal user (not admin, not template editor) renders
    a bare-variable template without AccessError (ADR-0001)."""
    plain = self.env["res.users"].create({
        "name": "Plain User",
        "login": "plain_render_user",
        "email": "plain@company-a-test.be",
        "company_id": self.company_a.id,
        "company_ids": [(6, 0, [self.company_a.id])],
        "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
    })
    sig = self.template_a.with_user(plain)._render_signature(plain)
    self.assertIn("Plain User", sig)

def test_compute_signature_uses_company_id_not_env_company(self):
    """Stored signature is rendered from the user's own company_id,
    independent of env.company (ADR-0002)."""
    user_b_env = self.user.with_company(self.company_b)
    user_b_env.invalidate_recordset(["signature"])
    user_b_env._compute_signature()
    # user.company_id is company_a → stored signature reflects company_a
    self.assertIn(self.company_a.name, self.user.signature or "")

def test_init_store_data_not_overridden(self):
    """The stored-field priming trick is gone (ADR-0002)."""
    self.assertNotIn("_init_store_data", vars(type(self.user)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run the test command with `--test-tags /mail_user_signature_template.test_non_admin_can_render_signature` style filter (or run the whole module).
Expected: `test_non_admin_can_render_signature` FAILS with `AccessError` ("Only members of ... Mail Template Editor"); `test_init_store_data_not_overridden` FAILS (method still present).

- [ ] **Step 3: Make `_render_signature` render unrestricted**

In `signature_template.py`, in `_render_signature`, change the render call to sudo:

```python
        # Render unrestricted: templates are admin-managed (ADR-0001), and the
        # bare context variables are not in mail_allowed_qweb_expressions(), so
        # restricted rendering would raise AccessError for non-admin users.
        rendered = self.sudo()._render_template(
            self.body_html,
            "res.users",
            user.ids,
            engine="qweb",
            add_context=values,
        )[user.id]
```

- [ ] **Step 4: Revert `_compute_signature` to per-record company**

In `res_users.py`, in `_compute_signature`, change the template branch to render with the user's own company (not `env.company`):

```python
            if (
                user.use_signature_template
                and user.signature_template_id
                and user.company_id.use_signature_templates
            ):
                # Stored signature is deterministic per user (ADR-0002):
                # render with the user's OWN company, never env.company, so a
                # batch recompute in another company's context cannot poison it.
                user.signature = user.signature_template_id._render_signature(
                    user, company=user.company_id
                )
```

- [ ] **Step 5: Delete the `_init_store_data` override**

In `res_users.py`, remove the entire `_init_store_data` method (currently ~lines 210-226) and its docstring. Also remove the now-unused `from email.utils import formataddr` only if nothing else uses it (it is still used by `_get_company_email_formatted` — keep it).

- [ ] **Step 6: Run tests to verify they pass**

Run the module test command.
Expected: the three new tests PASS; pre-existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add mail_user_signature_template/models/res_users.py \
        mail_user_signature_template/models/signature_template.py \
        mail_user_signature_template/tests/test_multi_company_signature.py
git commit -m "fix: render signatures unrestricted; stop storing per-company signature

Drop the _init_store_data trick that rewrote res.users.signature on every
page load and rendered the stored compute with env.company (cross-user
poisoning). Render with sudo so non-admin users don't hit AccessError.
Implements ADR-0001, ADR-0002."
```

---

### Task 2: Harden the resolution helpers (sudo lookups, NewId guard, HTML injection)

Fixes review findings 4, 7, 11.

**Files:**
- Modify: `mail_user_signature_template/models/user_signature_company.py:94-100` (`_get_for_user_company`)
- Modify: `mail_user_signature_template/models/res_users.py` (`_get_company_email`, `_get_company_signature`)
- Modify: `mail_user_signature_template/models/mail_thread.py` (Markup formatting)
- Test: same test file

**Interfaces:**
- Produces: `_get_for_user_company(user, company)` runs sudo. `_get_company_email` guards `NewId`. `_get_company_signature` returns an escaped `Markup` for the name-based fallback; `mail_thread` inserts it without re-marking plain strings safe.

- [ ] **Step 1: Write the failing test**

```python
def test_signature_fallback_escapes_user_name(self):
    """HTML in a user's name is escaped in the fallback signature
    (review finding 7 — no injection into outbound email)."""
    from markupsafe import Markup
    evil = self.env["res.users"].create({
        "name": '<a href="https://evil">reset</a>',
        "login": "evil_name_user",
        "email": "evil@company-a-test.be",
        "company_id": self.company_a.id,
        "company_ids": [(6, 0, [self.company_a.id])],
    })
    # No per-company row, no template → name-based fallback path.
    self.company_a.use_signature_templates = False
    sig = evil._get_company_signature(self.company_a)
    self.assertIsInstance(sig, Markup)
    self.assertIn("&lt;a href", sig)          # escaped
    self.assertNotIn("<a href", sig)          # not raw

def test_get_company_email_handles_newid(self):
    """_get_company_email on an unsaved record returns falsy, no crash."""
    new_user = self.env["res.users"].new({"name": "Draft"})
    self.assertFalse(new_user._get_company_email(self.company_a))
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `test_signature_fallback_escapes_user_name` FAILS (raw `<a href` present); `test_get_company_email_handles_newid` FAILS (NewId in search domain raises).

- [ ] **Step 3: Sudo the internal lookup**

In `user_signature_company.py`, `_get_for_user_company`:

```python
    @api.model
    def _get_for_user_company(self, user, company):
        """Find per-company signature record, return empty recordset if none.

        Runs as sudo: this data is not confidential to the system, and the
        own-record rule would otherwise hide the author's row when a
        notification/recompute runs in another user's env (review finding 4).
        """
        return self.sudo().search(
            [("user_id", "=", user.id), ("company_id", "=", company.id)],
            limit=1,
        )
```

- [ ] **Step 4: Guard NewId in `_get_company_email` and escape the fallback**

In `res_users.py`, add the import near the top (with the existing imports):

```python
from markupsafe import Markup
```

In `_get_company_email`, add the guard as the first lines after `self.ensure_one()`:

```python
        self.ensure_one()
        if not self.id or isinstance(self.id, NewId):
            return ""
```

In `_get_company_signature`, change the two return branches so rendered HTML is marked safe and the name fallback is escaped:

```python
        if use_template and template:
            return Markup(template._render_signature(self, company=company))

        # Fallback to stored signature (already sanitized) or an escaped default
        if not is_html_empty(self.signature):
            return self.signature
        return Markup("<p>--<br/>%s</p>") % self.name
```

- [ ] **Step 5: Fix the Markup insertion in `mail_thread`**

In `mail_thread.py`, change the signature wrap so a plain string would be escaped (only already-`Markup` values pass through):

```python
        company_signature = author_user._get_company_signature(company)
        if company_signature:
            render_values["signature"] = (
                Markup("<div>-- <br/>%s</div>") % company_signature
            )
```

(Drop the inner `Markup(company_signature)` — `_get_company_signature` now returns a `Markup` already.)

- [ ] **Step 6: Run tests to verify they pass**

Expected: both new tests PASS; existing tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add mail_user_signature_template/models/user_signature_company.py \
        mail_user_signature_template/models/res_users.py \
        mail_user_signature_template/models/mail_thread.py \
        mail_user_signature_template/tests/test_multi_company_signature.py
git commit -m "fix: sudo per-company lookups, guard NewId, escape name in signature fallback"
```

---

### Task 3: Set the per-company From on the notification path

Notifications currently switch the signature but not the From, so From and signature disagree and identity leaks (review finding 6). Set `email_from` in `_notify_by_email_get_base_mail_values` so the outgoing `mail.mail` carries the per-company address and Odoo's `from_filter` routing picks the right server.

**Files:**
- Modify: `mail_user_signature_template/models/mail_thread.py`
- Test: same test file

**Interfaces:**
- Consumes: `res.users._get_company_email_formatted(company)` (existing).
- Produces: `mail.thread._notify_by_email_get_base_mail_values(...)` returns `email_from` set to the author's per-company identity when one is configured for the message's company.

- [ ] **Step 1: Write the failing test**

```python
def test_notify_base_mail_values_sets_company_email_from(self):
    """Notification emails carry the per-company From (review finding 6)."""
    partner = self.env["res.partner"].create(
        {"name": "Recipient2", "email": "recipient2@example.com"}
    )
    record = partner.with_user(self.user).with_company(self.company_b)
    message = record.message_post(
        body="Hi", subject="S", message_type="comment",
        subtype_xmlid="mail.mt_comment",
    )
    vals = record._notify_by_email_get_base_mail_values(message, [])
    self.assertIn("annsophie@steen-parts-test.be", vals.get("email_from", ""))
    # reply_to must NOT be overridden by us
    self.assertNotIn("reply_to", vals)
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `email_from` not in `vals`.

- [ ] **Step 3: Add the override**

In `mail_thread.py`, add a second override on the `MailThread` class:

```python
    def _notify_by_email_get_base_mail_values(
        self, message, recipients_data, additional_values=None
    ):
        """Set the per-company From so the notification routes via the right
        outgoing mail server (from_filter) and does not leak the home company.

        Keyed on the record's company (self.company_id) — the Sending Company —
        falling back to env.company when the record has none. Never sets
        reply_to (handled by Odoo's per-company alias domains).
        """
        vals = super()._notify_by_email_get_base_mail_values(
            message, recipients_data, additional_values=additional_values
        )
        author_user = message.author_id.user_ids[:1]
        if not author_user:
            return vals
        company = (
            self.company_id
            if "company_id" in self._fields and self.company_id
            else self.env.company
        )
        company_email = author_user._get_company_email(company)
        if company_email and company_email != author_user.email:
            vals["email_from"] = author_user._get_company_email_formatted(company)
        return vals
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mail_user_signature_template/models/mail_thread.py \
        mail_user_signature_template/tests/test_multi_company_signature.py
git commit -m "feat: set per-company email_from on notification path"
```

---

### Task 4: Fix the composer to key on the record's company and respect default_email_from

The composer overrides `email_from` from `env.company` (wrong dimension) and stomps a context-forced `default_email_from` (review finding 5). Switch to `record_company_id` and skip when the context forces a From.

**Files:**
- Modify: `mail_user_signature_template/models/mail_compose_message.py`
- Test: same test file

**Interfaces:**
- Consumes: `mail.compose.message.record_company_id` (Odoo core computed field).
- Produces: `_compute_authorship` sets `email_from` from `record_company_id or env.company`, and is a no-op when `default_email_from` is in context.

- [ ] **Step 1: Write the failing tests**

```python
def test_composer_respects_default_email_from(self):
    """A context-forced default_email_from is not overridden (finding 5)."""
    Composer = self.env["mail.compose.message"].with_user(self.user)
    composer = Composer.with_company(self.company_b).with_context(
        default_email_from="forced@elsewhere.be"
    ).create({
        "subject": "T", "body": "x", "composition_mode": "comment",
        "model": "res.partner", "res_ids": str([self.user.partner_id.id]),
    })
    self.assertIn("forced@elsewhere.be", composer.email_from)

def test_composer_keys_on_record_company(self):
    """email_from follows the record's company, not the navbar company."""
    # A partner belonging to company_b, composed while env company is company_a.
    partner_b = self.env["res.partner"].create(
        {"name": "PartB", "company_id": self.company_b.id}
    )
    Composer = self.env["mail.compose.message"].with_user(self.user)
    composer = Composer.with_company(self.company_a).create({
        "subject": "T", "body": "x", "composition_mode": "comment",
        "model": "res.partner", "res_ids": str([partner_b.id]),
    })
    self.assertIn("annsophie@steen-parts-test.be", composer.email_from)
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `test_composer_respects_default_email_from` FAILS (overridden to company_b email); `test_composer_keys_on_record_company` FAILS (uses env.company = company_a → falls back to user email).

- [ ] **Step 3: Rewrite `_compute_authorship`**

Replace the override body in `mail_compose_message.py`:

```python
    @api.depends("composition_mode", "email_from", "model",
                 "res_domain", "res_ids", "template_id", "record_company_id")
    def _compute_authorship(self):
        """Use the per-company email of the record's company (the Sending
        Company), unless a template or the context already forces email_from."""
        super()._compute_authorship()
        user = self.env.user
        for composer in self:
            if composer.template_id and composer.template_id.email_from:
                continue
            if composer.env.context.get("default_email_from"):
                continue
            company = composer.record_company_id or composer.env.company
            company_email = user._get_company_email(company)
            if company_email and company_email != user.email:
                composer.email_from = user._get_company_email_formatted(company)
                composer.author_id = user.partner_id.id
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: both new tests PASS. Note: the pre-existing `test_composer_email_from_uses_company_email` composes on `self.user.partner_id` (no company) with `with_company(company_b)` → falls back to `env.company` = company_b, still PASS. `test_composer_email_from_falls_back_in_company_a` → PASS.

- [ ] **Step 5: Commit**

```bash
git add mail_user_signature_template/models/mail_compose_message.py \
        mail_user_signature_template/tests/test_multi_company_signature.py
git commit -m "fix: composer keys email_from on record company, respects default_email_from"
```

---

### Task 5: "Send as" manual override on the composer (multi-company users)

Adds a `sending_company_id` selector shown only to multi-company users. Switching it flips **both** From and signature (they move as a unit) by threading the chosen company through `message_post` into the notify hooks.

**Files:**
- Modify: `mail_user_signature_template/models/mail_compose_message.py`
- Modify: `mail_user_signature_template/models/mail_thread.py`
- Modify: `mail_user_signature_template/models/res_users.py` (helper for allowed companies)
- Create: `mail_user_signature_template/views/mail_compose_message_views.xml`
- Modify: `mail_user_signature_template/__manifest__.py` (register the new view)
- Test: same test file

**Interfaces:**
- Consumes: `res.users._identity_company_ids()` (new) → recordset of companies the user may send as (Home Company + configured identities).
- Produces: `mail.compose.message.sending_company_id`; when set, `_action_send_mail` posts with context `force_sending_company_id`, and both notify hooks (`_notify_by_email_prepare_rendering_context`, `_notify_by_email_get_base_mail_values`) prefer that company over the record's company.

- [ ] **Step 1: Write the failing tests**

```python
def test_identity_company_ids_lists_home_plus_configured(self):
    """Selectable 'send as' companies = home company + configured identities."""
    companies = self.user._identity_company_ids()
    self.assertIn(self.company_a, companies)  # home
    self.assertIn(self.company_b, companies)  # configured identity
    basic = self.env["res.users"].create({
        "name": "Solo", "login": "solo_identity", "email": "solo@a.be",
        "company_id": self.company_a.id,
        "company_ids": [(6, 0, [self.company_a.id])],
    })
    self.assertEqual(basic._identity_company_ids(), self.company_a)

def test_send_as_override_flips_from_and_signature(self):
    """Overriding sending_company_id drives both From and signature."""
    partner = self.env["res.partner"].create(
        {"name": "Rcpt3", "email": "r3@example.com", "company_id": self.company_a.id}
    )
    Composer = self.env["mail.compose.message"].with_user(self.user)
    composer = Composer.with_company(self.company_a).create({
        "subject": "T", "body": "x", "composition_mode": "comment",
        "model": "res.partner", "res_ids": str([partner.id]),
        "sending_company_id": self.company_b.id,
    })
    # From flips to company_b identity even though record/env are company_a
    self.assertIn("annsophie@steen-parts-test.be", composer.email_from)
    # Signature (via notify hook honoring the forced company) is company_b's
    record = partner.with_user(self.user).with_context(
        force_sending_company_id=self.company_b.id
    )
    msg = record.message_post(body="x", message_type="comment",
                              subtype_xmlid="mail.mt_comment")
    ctx = record._notify_by_email_prepare_rendering_context(msg, msg_vals={})
    self.assertIn(self.company_b.name, str(ctx.get("signature") or ""))
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL — `_identity_company_ids` and `sending_company_id` do not exist; the forced-company context is ignored by the notify hook.

- [ ] **Step 3: Add the allowed-companies helper**

In `res_users.py`:

```python
    def _identity_company_ids(self):
        """Companies this user may send as: Home Company + configured identities."""
        self.ensure_one()
        configured = self.signature_company_ids.mapped("company_id")
        return self.company_id | configured
```

- [ ] **Step 4: Add the `sending_company_id` field and use it in the composer**

In `mail_compose_message.py`, add the field and fold it into `_compute_authorship`:

```python
    sending_company_id = fields.Many2one(
        "res.company",
        string="Send As",
        compute="_compute_sending_company_id",
        readonly=False,
        store=True,
        help="Company identity (From address + signature) to send this mail with.",
    )

    @api.depends("record_company_id")
    def _compute_sending_company_id(self):
        for composer in self:
            composer.sending_company_id = (
                composer.record_company_id or composer.env.company
            )
```

Update `_compute_authorship` to prefer `sending_company_id`:

```python
            company = composer.sending_company_id or composer.record_company_id \
                or composer.env.company
```

(Add `sending_company_id` to its `@api.depends`.)

- [ ] **Step 5: Thread the chosen company through send → notify**

In `mail_compose_message.py`, override the send entry point to inject context:

```python
    def _action_send_mail(self, auto_commit=False):
        forced = self.sending_company_id
        composer = self
        if len(self) == 1 and forced:
            composer = self.with_context(force_sending_company_id=forced.id)
        return super(MailComposeMessage, composer)._action_send_mail(
            auto_commit=auto_commit
        )
```

In `mail_thread.py`, in **both** notify hooks, resolve the company as: forced context → record company → env.company. Add a small helper at the top of the `MailThread` class and use it in both overrides:

```python
    def _signature_sending_company(self):
        forced = self.env.context.get("force_sending_company_id")
        if forced:
            return self.env["res.company"].browse(forced)
        if "company_id" in self._fields and self.company_id:
            return self.company_id
        return self.env.company
```

Replace the `company = ...` lines in `_notify_by_email_prepare_rendering_context` and `_notify_by_email_get_base_mail_values` with `company = self._signature_sending_company()`.

- [ ] **Step 6: Add the composer view (gated to multi-company users)**

Create `mail_user_signature_template/views/mail_compose_message_views.xml`:

```xml
<odoo>
    <record id="mail_compose_message_form_send_as" model="ir.ui.view">
        <field name="name">mail.compose.message.form.send.as</field>
        <field name="model">mail.compose.message</field>
        <field name="inherit_id" ref="mail.email_compose_message_wizard_form"/>
        <field name="arch" type="xml">
            <field name="subject" position="before">
                <field name="sending_company_id"
                       invisible="context.get('uid_company_count', 1) &lt; 2"
                       options="{'no_create': True, 'no_open': True}"
                       domain="[('id', 'in', allowed_sending_company_ids)]"/>
                <field name="allowed_sending_company_ids"
                       column_invisible="1" invisible="1"/>
            </field>
        </field>
    </record>
</odoo>
```

Add the helper field backing the domain in `mail_compose_message.py`:

```python
    allowed_sending_company_ids = fields.Many2many(
        "res.company",
        compute="_compute_allowed_sending_company_ids",
    )

    @api.depends("res_ids")
    def _compute_allowed_sending_company_ids(self):
        companies = self.env.user._identity_company_ids()
        for composer in self:
            composer.allowed_sending_company_ids = companies
```

Register the view in `__manifest__.py` under `"data"` (after the existing views):

```python
        "views/mail_compose_message_views.xml",
```

> Visibility note: the `invisible` expression uses `uid_company_count` from the web client context (present in Odoo 19 user context as the number of allowed companies). If unavailable in this build, fall back to hiding via a computed boolean `show_sending_company` = `len(user.company_ids) > 1` and bind `invisible="not show_sending_company"`.

- [ ] **Step 7: Run tests to verify they pass**

Expected: both new tests PASS; all prior tests still PASS.

- [ ] **Step 8: Commit**

```bash
git add mail_user_signature_template/models/mail_compose_message.py \
        mail_user_signature_template/models/mail_thread.py \
        mail_user_signature_template/models/res_users.py \
        mail_user_signature_template/views/mail_compose_message_views.xml \
        mail_user_signature_template/__manifest__.py \
        mail_user_signature_template/tests/test_multi_company_signature.py
git commit -m "feat: 'Send as' composer override flips From + signature for multi-company users"
```

---

### Task 6: Make identities admin-managed; drop dead self-service code

Regular users get read-only access to their own rows; only managers/system write. Remove the unreachable self-service scaffolding and give the model a display name (review finding 8).

**Files:**
- Modify: `mail_user_signature_template/security/ir.model.access.csv`
- Modify: `mail_user_signature_template/models/res_users.py` (remove `_get_signature_access_fields`)
- Modify: `mail_user_signature_template/models/user_signature_company.py` (add `_rec_name`/`display_name`)
- Delete: `mail_user_signature_template/views/user_signature_company_views.xml` (unreachable standalone views)
- Modify: `mail_user_signature_template/__manifest__.py` (drop the deleted view if it is registered)
- Test: same test file

**Interfaces:**
- Produces: `base.group_user` has read-only access to `user.signature.company`; create/write/unlink require `group_signature_template_manager` or `base.group_system`. `res.users` no longer defines `_get_signature_access_fields`.

- [ ] **Step 1: Write the failing test**

```python
def test_regular_user_cannot_write_identity(self):
    """A plain user cannot create/write their own identity (admin-managed)."""
    plain = self.env["res.users"].create({
        "name": "NoWrite", "login": "nowrite_user", "email": "nw@a.be",
        "company_id": self.company_a.id,
        "company_ids": [(6, 0, [self.company_a.id])],
        "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
    })
    with self.assertRaises((AccessError,)):
        self.env["user.signature.company"].with_user(plain).create({
            "user_id": plain.id, "company_id": self.company_a.id,
            "email": "self@a.be",
        })

def test_regular_user_can_read_own_identity(self):
    """A plain user can still READ their own identity row."""
    plain = self.env["res.users"].create({
        "name": "CanRead", "login": "canread_user", "email": "cr@a.be",
        "company_id": self.company_b.id,
        "company_ids": [(6, 0, [self.company_b.id])],
        "groups_id": [(6, 0, [self.env.ref("base.group_user").id])],
    })
    row = self.env["user.signature.company"].create({
        "user_id": plain.id, "company_id": self.company_b.id,
    })
    visible = self.env["user.signature.company"].with_user(plain).search(
        [("id", "=", row.id)]
    )
    self.assertTrue(visible)
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `test_regular_user_cannot_write_identity` FAILS (current ACL grants `1,1,1,1` to `base.group_user`).

- [ ] **Step 3: Tighten the ACL**

In `ir.model.access.csv`, change the `base.group_user` line to read-only and add a manager line:

```csv
access_user_signature_company_user,user.signature.company.user,model_user_signature_company,base.group_user,1,0,0,0
access_user_signature_company_manager,user.signature.company.manager,model_user_signature_company,mail_user_signature_template.group_signature_template_manager,1,1,1,1
access_user_signature_company_system,user.signature.company.system,model_user_signature_company,base.group_system,1,1,1,1
```

- [ ] **Step 4: Remove dead code and add display name**

In `res_users.py`, delete the `_get_signature_access_fields` method entirely (nothing in Odoo 19 core calls it).

In `user_signature_company.py`, add a computed display name (dialogs show a meaningful title):

```python
    display_name = fields.Char(compute="_compute_display_name")

    @api.depends("user_id.name", "company_id.name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.user_id.name} — {rec.company_id.name}"
```

- [ ] **Step 5: Delete the unreachable standalone views**

```bash
git rm mail_user_signature_template/views/user_signature_company_views.xml
```

Then, in `__manifest__.py`, remove the `"views/user_signature_company_views.xml"` entry from `"data"` if present. (The admin Users-form o2m in `views/res_users_views.xml` stays.)

- [ ] **Step 6: Run tests to verify they pass**

Expected: both new tests PASS; module still installs/updates cleanly (no reference to the deleted view).

- [ ] **Step 7: Commit**

```bash
git add -A mail_user_signature_template/
git commit -m "refactor: make per-company identities admin-managed; drop dead self-service code"
```

---

### Task 7: Light validation of the identity email domain

Warn when a configured identity `email`'s domain has no authorized outgoing server / alias domain — catches typos that would route to the fallback server (review finding 9). Admin-only, so a soft check via constraint.

**Files:**
- Modify: `mail_user_signature_template/models/user_signature_company.py`
- Test: same test file

**Interfaces:**
- Produces: `user.signature.company` raises `ValidationError` on save if `email` is set and its domain matches neither any `ir.mail_server.from_filter` nor any `mail.alias.domain`.

- [ ] **Step 1: Write the failing test**

```python
def test_identity_email_domain_must_be_authorized(self):
    """An identity email on an unknown domain is rejected."""
    with self.assertRaises(ValidationError):
        self.env["user.signature.company"].create({
            "user_id": self.user.id, "company_id": self.company_a.id,
            "email": "someone@totally-unknown-domain.example",
        })

def test_identity_email_domain_authorized_passes(self):
    """An identity email whose domain has a mail server / alias domain is ok."""
    srv = self.env["ir.mail_server"].create({
        "name": "Test parts", "smtp_host": "smtp.example.com",
        "from_filter": "steen-parts-test.be",
    })
    self.assertTrue(srv)
    rec = self.env["user.signature.company"].create({
        "user_id": self.user.id, "company_id": self.company_a.id,
        "email": "ok@steen-parts-test.be",
    })
    self.assertTrue(rec.id)
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: `test_identity_email_domain_must_be_authorized` FAILS (no validation yet).

- [ ] **Step 3: Add the constraint**

In `user_signature_company.py`:

```python
    @api.constrains("email")
    def _check_email_domain_authorized(self):
        """Warn (block) when the From domain has no authorized outgoing server
        or alias domain — it would route via the fallback server and likely
        fail SPF/DKIM."""
        for rec in self:
            if not rec.email or "@" not in rec.email:
                continue
            domain = rec.email.rsplit("@", 1)[-1].lower()
            servers = self.env["ir.mail_server"].sudo().search([])
            filters = set()
            for server in servers:
                for part in (server.from_filter or "").split(","):
                    part = part.strip().lower()
                    if part:
                        filters.add(part.rsplit("@", 1)[-1])
            alias_domains = set(
                self.env["mail.alias.domain"].sudo().mapped("name")
            )
            if domain not in filters and domain not in alias_domains:
                raise ValidationError(
                    self.env._(
                        "The domain '%(domain)s' has no authorized outgoing mail "
                        "server or alias domain. Mail sent from this address may "
                        "fail delivery (SPF/DKIM).",
                        domain=domain,
                    )
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: both PASS. (Note: `setUpClass` creates `company_b` with website `steen-parts-test.be`; the existing `sig_company_b.email = annsophie@steen-parts-test.be` is created before any matching mail server exists — so add a mail server with `from_filter="steen-parts-test.be"` and an alias domain in `setUpClass`, or set `sig_company_b` up after creating them. Update `setUpClass` accordingly so existing tests keep passing.)

- [ ] **Step 5: Update setUpClass so existing fixtures satisfy the constraint**

In `setUpClass`, before creating `cls.sig_company_b`, add:

```python
        cls.env["mail.alias.domain"].create({"name": "steen-parts-test.be"})
```

- [ ] **Step 6: Run the full module test suite**

Expected: ALL tests PASS.

- [ ] **Step 7: Commit**

```bash
git add mail_user_signature_template/models/user_signature_company.py \
        mail_user_signature_template/tests/test_multi_company_signature.py
git commit -m "feat: validate identity email domain against authorized servers/alias domains"
```

---

## Self-Review

**Spec coverage:**
- §A signature rendering → Task 1 ✅
- §B email_from on all send paths → Task 3 (notify) + Task 4 (composer) ✅
- §C "Send as" override → Task 5 ✅
- §D security & hygiene: sudo lookups/NewId/injection → Task 2; admin-managed + dead code + display_name → Task 6; light validation → Task 7 ✅
- §E tests → folded into each task (non-admin render T1, cross-env T2/T3, default_email_from T4, override T5, admin-managed T6) ✅
- ADR-0001 (sudo render) → Task 1; ADR-0002 (no stored per-company) → Task 1 ✅

**Placeholder scan:** no TBD/TODO; every code step shows the code; the one soft note (Task 5 visibility fallback) gives an explicit alternative, not a placeholder.

**Type consistency:** `_get_company_email(company)`, `_get_company_email_formatted(company)`, `_get_company_signature(company)`, `_get_for_user_company(user, company)`, `_identity_company_ids()`, `_signature_sending_company()`, `sending_company_id` used consistently across tasks. Notify hooks both consume `_signature_sending_company()` after Task 5 (Task 3 introduces its own `company = ...`; Task 5 step 5 explicitly replaces it — noted).

**Out-of-scope confirmed absent:** no `reply_to` override, no per-company `ir.mail_server` code, no self-service, no auto-derivation.
