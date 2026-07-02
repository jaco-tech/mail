# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from markupsafe import Markup

from odoo.exceptions import AccessError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMultiCompanySignature(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.ref("base.main_company")
        cls.company_b = cls.env["res.company"].create(
            {
                "name": "Steen Parts Test",
                "email": "info@steen-parts-test.be",
                "phone": "+32 123 456 789",
                "website": "https://www.steen-parts-test.be",
            }
        )

        # Enable signature templates on both companies
        cls.company_a.use_signature_templates = True
        cls.company_b.use_signature_templates = True

        # Create templates per company
        cls.template_a = cls.env["signature.template"].create(
            {
                "name": "Company A Template",
                "body_html": """<div>
                    <strong><t t-out="name"/></strong><br/>
                    <t t-out="email"/><br/>
                    <t t-out="company_name"/>
                </div>""",
                "company_id": cls.company_a.id,
            }
        )
        cls.template_b = cls.env["signature.template"].create(
            {
                "name": "Company B Template",
                "body_html": """<div>
                    <strong><t t-out="name"/></strong><br/>
                    <t t-out="email"/><br/>
                    <t t-out="company_name"/>
                </div>""",
                "company_id": cls.company_b.id,
            }
        )

        cls.company_a.default_signature_template_id = cls.template_a
        cls.company_b.default_signature_template_id = cls.template_b

        # Create a multi-company user
        cls.user = cls.env["res.users"].create(
            {
                "name": "Ann-Sophie Test",
                "login": "annsophie_test",
                "email": "annsophie@company-a-test.be",
                "company_id": cls.company_a.id,
                "company_ids": [(6, 0, [cls.company_a.id, cls.company_b.id])],
            }
        )

        # Authorize the company B mail domain so identity emails on it satisfy
        # the domain-authorization constraint (Task 7).
        cls.env["mail.alias.domain"].create({"name": "steen-parts-test.be"})

        # Set up per-company email for company B
        cls.sig_company_b = cls.env["user.signature.company"].create(
            {
                "user_id": cls.user.id,
                "company_id": cls.company_b.id,
                "email": "annsophie@steen-parts-test.be",
                "use_signature_template": True,
                "signature_template_id": cls.template_b.id,
            }
        )

    def test_get_company_email_default(self):
        """Per-company email returns user default when no override exists."""
        email = self.user._get_company_email(self.company_a)
        self.assertEqual(email, "annsophie@company-a-test.be")

    def test_get_company_email_override(self):
        """Per-company email returns override when configured."""
        email = self.user._get_company_email(self.company_b)
        self.assertEqual(email, "annsophie@steen-parts-test.be")

    def test_get_company_email_formatted(self):
        """Formatted email uses per-company email."""
        formatted = self.user._get_company_email_formatted(self.company_b)
        self.assertIn("annsophie@steen-parts-test.be", formatted)
        self.assertIn("Ann-Sophie Test", formatted)

    def test_get_company_signature_company_a(self):
        """Signature for company A uses company A's template and data."""
        sig = self.user._get_company_signature(self.company_a)
        self.assertIn(self.company_a.name, sig)
        self.assertIn("annsophie@company-a-test.be", sig)

    def test_get_company_signature_company_b(self):
        """Signature for company B uses company B's template, email, and data."""
        sig = self.user._get_company_signature(self.company_b)
        self.assertIn(self.company_b.name, sig)
        self.assertIn("annsophie@steen-parts-test.be", sig)
        # Should NOT contain company A data
        self.assertNotIn(self.company_a.name, sig)

    def test_render_values_use_correct_company(self):
        """_get_render_values uses the given company, not user.company_id."""
        values = self.template_b._get_render_values(self.user, company=self.company_b)
        self.assertEqual(values["company_name"], self.company_b.name)
        self.assertEqual(values["company_email"], self.company_b.email)
        self.assertEqual(values["email"], "annsophie@steen-parts-test.be")

    def test_backward_compat_no_per_company_record(self):
        """Without per-company records, falls back to existing behavior."""
        # Create a user with NO per-company records
        user2 = self.env["res.users"].create(
            {
                "name": "Basic User",
                "login": "basic_test_user",
                "email": "basic@company-a-test.be",
                "company_id": self.company_a.id,
                "company_ids": [(6, 0, [self.company_a.id])],
            }
        )
        # Should fall back to user.email
        email = user2._get_company_email(self.company_a)
        self.assertEqual(email, "basic@company-a-test.be")

        # Signature should still render
        sig = user2._get_company_signature(self.company_a)
        self.assertTrue(sig)
        self.assertIn("Basic User", sig)

    def test_get_or_create(self):
        """_get_or_create finds existing or creates new record."""
        # Should find existing
        record = self.env["user.signature.company"]._get_or_create(
            self.user, self.company_b
        )
        self.assertEqual(record.id, self.sig_company_b.id)

        # Should create new for company A
        record_a = self.env["user.signature.company"]._get_or_create(
            self.user, self.company_a
        )
        self.assertTrue(record_a.id)
        self.assertEqual(record_a.user_id, self.user)
        self.assertEqual(record_a.company_id, self.company_a)

    def test_forced_template_overrides_per_company(self):
        """Company force_signature_template overrides per-company preferences."""
        self.company_b.force_signature_template = True
        sig = self.user._get_company_signature(self.company_b)
        self.assertIn(self.company_b.name, sig)

    def test_company_signatures_disabled(self):
        """When company disables signature templates, falls back to default."""
        self.company_b.use_signature_templates = False
        sig = self.user._get_company_signature(self.company_b)
        # Should still return something (fallback)
        self.assertTrue(sig)

    # ------------------------------------------------------------------
    # Integration: active-company default (no explicit company arg)
    # ------------------------------------------------------------------

    def test_with_company_default_picks_active_company(self):
        """Without explicit company arg, helpers use self.env.company."""
        user_b = self.user.with_company(self.company_b)
        self.assertEqual(
            user_b._get_company_email(),
            "annsophie@steen-parts-test.be",
        )
        sig = user_b._get_company_signature()
        self.assertIn(self.company_b.name, sig)
        self.assertIn("annsophie@steen-parts-test.be", sig)

        user_a = self.user.with_company(self.company_a)
        self.assertEqual(
            user_a._get_company_email(),
            "annsophie@company-a-test.be",
        )

    # ------------------------------------------------------------------
    # Integration: mail.compose.message._compute_authorship
    # ------------------------------------------------------------------

    def test_composer_email_from_uses_company_email(self):
        """mail.compose.message substitutes email_from with per-company email.

        The record has no company_id, so core's _mail_get_companies resolves
        record_company_id to the default (env.company = company_b) and the
        composer picks up company_b's per-company email override.
        """
        no_company_partner = self.env["res.partner"].create(
            {"name": "NoCompany", "company_id": False}
        )
        Composer = self.env["mail.compose.message"].with_user(self.user)
        composer = Composer.with_company(self.company_b).create(
            {
                "subject": "Test",
                "body": "hello",
                "composition_mode": "comment",
                "model": "res.partner",
                "res_ids": str([no_company_partner.id]),
            }
        )
        # No company on the record -> record_company_id resolves to env.company.
        self.assertEqual(composer.record_company_id, self.company_b)
        self.assertIn("annsophie@steen-parts-test.be", composer.email_from)
        # author_id must stay the acting user's partner
        self.assertEqual(composer.author_id, self.user.partner_id)

    def test_composer_email_from_falls_back_in_company_a(self):
        """Without per-company record for company A, composer uses user.email."""
        Composer = self.env["mail.compose.message"].with_user(self.user)
        composer = Composer.with_company(self.company_a).create(
            {
                "subject": "Test",
                "body": "hello",
                "composition_mode": "comment",
                "model": "res.partner",
                "res_ids": str([self.env.user.partner_id.id]),
            }
        )
        # company A has no per-company email override → should match user.email
        self.assertIn("annsophie@company-a-test.be", composer.email_from)

    def test_composer_respects_default_email_from(self):
        """A context-forced default_email_from is not overridden (finding 5).

        env.company is company_b (which HAS a per-company email override), so
        without the guard our override would stomp email_from with the company_b
        address. Forcing a recompute of _compute_authorship (the ORM otherwise
        applies default_email_from as the create-time field default and skips the
        compute entirely) proves the override's context guard is what preserves
        the forced From.
        """
        Composer = self.env["mail.compose.message"].with_user(self.user)
        composer = Composer.with_company(self.company_b).with_context(
            default_email_from="forced@elsewhere.be"
        ).create({
            "subject": "T", "body": "x", "composition_mode": "comment",
            "model": "res.partner", "res_ids": str([self.user.partner_id.id]),
        })
        # Force _compute_authorship to actually run in the default_email_from
        # context so the override branch (not the create-time default) is tested.
        composer._compute_authorship()
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
        # Prove the record-company path: record_company_id resolves to company_b
        # (res.partner._mail_get_companies surfaces the partner's company_id),
        # NOT the env.company (company_a) that the composer runs under.
        self.assertEqual(composer.record_company_id, self.company_b)
        self.assertIn("annsophie@steen-parts-test.be", composer.email_from)

    # ------------------------------------------------------------------
    # Task 5: "Send as" manual override on the composer
    # ------------------------------------------------------------------

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
        partner.message_subscribe(partner_ids=self.user.partner_id.ids)
        record = partner.with_user(self.user).with_context(
            force_sending_company_id=self.company_b.id
        )
        msg = record.message_post(body="x", message_type="comment",
                                  subtype_xmlid="mail.mt_comment")
        ctx = record._notify_by_email_prepare_rendering_context(msg, msg_vals={})
        self.assertIn(self.company_b.name, str(ctx.get("signature") or ""))

    def test_send_as_override_real_send_path_flips_from_and_signature(self):
        """Full send path: _action_send_mail threads the forced company into
        message_post → BOTH notify hooks render for company_b.

        Unlike the direct-hook test above, this drives the composer's own
        _action_send_mail (no manually injected context) and inspects the
        outgoing mail.mail to prove the forced "Send As" company reaches both
        the From (get_base_mail_values hook) and the signature
        (prepare_rendering_context hook).
        """
        partner = self.env["res.partner"].create(
            {"name": "RcptSend", "email": "rcptsend@example.com",
             "company_id": self.company_a.id}
        )
        # An EXTERNAL follower (no linked user) receives an *email* notification,
        # which is what materialises a mail.mail. self.user.partner_id is also
        # subscribed so the internal acting user is allowed to post, but as an
        # internal user it is notified via inbox, not email.
        external = self.env["res.partner"].create(
            {"name": "External Rcpt", "email": "external.rcpt@example.com"}
        )
        partner.message_subscribe(
            partner_ids=(self.user.partner_id + external).ids
        )

        Composer = self.env["mail.compose.message"].with_user(self.user)
        composer = Composer.with_company(self.company_a).create({
            "subject": "SendAs subject",
            "body": "<p>hello</p>",
            "composition_mode": "comment",
            "model": "res.partner",
            "res_ids": str([partner.id]),
            "sending_company_id": self.company_b.id,
        })
        composer._action_send_mail()

        # Locate the message this composer posted, then its outgoing mail.mail.
        message = self.env["mail.message"].search(
            [("model", "=", "res.partner"), ("res_id", "=", partner.id),
             ("subject", "=", "SendAs subject")],
            order="id desc", limit=1,
        )
        self.assertTrue(message, "composer should have posted a mail.message")
        mail = self.env["mail.mail"].search(
            [("mail_message_id", "=", message.id)], limit=1,
        )
        self.assertTrue(mail, "message_post should have queued a mail.mail")

        # From flips to company_b's per-company identity via the real send path.
        self.assertIn("annsophie@steen-parts-test.be", mail.email_from)
        # Signature rendered into the body is company_b's (name marker present,
        # company_a's per-company email absent).
        body = mail.body_html or ""
        self.assertIn(self.company_b.name, body)
        self.assertNotIn("annsophie@company-a-test.be", body)

    # ------------------------------------------------------------------
    # Integration: mail.thread._notify_by_email_prepare_rendering_context
    # ------------------------------------------------------------------

    def test_notify_rendering_context_uses_company_signature(self):
        """Outgoing notifications pick up the per-company signature."""
        partner = self.env["res.partner"].create(
            {"name": "Recipient", "email": "recipient@example.com"}
        )
        # Plain internal users cannot write res.partner in Odoo 19, and
        # mail.message create requires write/create access on the related
        # document (or follower status). Subscribe the acting user so the
        # post is allowed and the sudo-rendered signature path is exercised.
        partner.message_subscribe(partner_ids=self.user.partner_id.ids)
        record = partner.with_user(self.user).with_company(self.company_b)
        message = record.message_post(
            body="Hello",
            subject="Subj",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
            email_add_signature=True,
        )
        render_values = record._notify_by_email_prepare_rendering_context(
            message, msg_vals={}
        )
        signature_html = str(render_values.get("signature") or "")
        self.assertIn(self.company_b.name, signature_html)
        self.assertIn("annsophie@steen-parts-test.be", signature_html)
        self.assertNotIn("annsophie@company-a-test.be", signature_html)

    # ------------------------------------------------------------------
    # Integration: mail.thread._notify_by_email_get_base_mail_values
    # ------------------------------------------------------------------

    def test_notify_base_mail_values_sets_company_email_from(self):
        """Notification emails carry the per-company From (review finding 6)."""
        partner = self.env["res.partner"].create(
            {"name": "Recipient2", "email": "recipient2@example.com"}
        )
        partner.message_subscribe(partner_ids=self.user.partner_id.ids)
        record = partner.with_user(self.user).with_company(self.company_b)
        message = record.message_post(
            body="Hi", subject="S", message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        vals = record._notify_by_email_get_base_mail_values(message, [])
        self.assertIn("annsophie@steen-parts-test.be", vals.get("email_from", ""))
        # reply_to must NOT be overridden by us
        self.assertNotIn("reply_to", vals)

    # ------------------------------------------------------------------
    # Security: record rules and constraints
    # ------------------------------------------------------------------

    def test_user_cannot_read_other_users_record(self):
        """Record rule restricts users to their own per-company records."""
        other = self.env["res.users"].create(
            {
                "name": "Other Person",
                "login": "other_test_user",
                "email": "other@example.com",
                "company_id": self.company_a.id,
                "company_ids": [(6, 0, [self.company_a.id])],
            }
        )
        # Other tries to read Ann-Sophie's record — should get empty recordset
        visible = (
            self.env["user.signature.company"]
            .with_user(other)
            .search([("id", "=", self.sig_company_b.id)])
        )
        self.assertFalse(
            visible,
            "Record rule should hide another user's per-company record",
        )

    def test_user_cannot_reassign_record_to_other_user(self):
        """@api.constrains blocks non-admin from writing user_id != self."""
        other = self.env["res.users"].create(
            {
                "name": "Other Person",
                "login": "other_constr_user",
                "email": "other2@example.com",
                "company_id": self.company_a.id,
                "company_ids": [(6, 0, [self.company_a.id])],
            }
        )
        # NOTE: Odoo's custom assertRaises accepts a single exception class,
        # not a tuple. The own-records rule denies creating a row whose
        # user_id is another user -> AccessError (both before and after the
        # admin-managed ACL change).
        with self.assertRaises(AccessError):
            self.env["user.signature.company"].with_user(self.user).create(
                {
                    "user_id": other.id,
                    "company_id": self.company_a.id,
                    "email": "poison@example.com",
                }
            )

    def test_regular_user_cannot_write_identity(self):
        """A plain user cannot create/write their own identity (admin-managed)."""
        plain = self.env["res.users"].create(
            {
                "name": "NoWrite",
                "login": "nowrite_user",
                "email": "nw@a.be",
                "company_id": self.company_a.id,
                "company_ids": [(6, 0, [self.company_a.id])],
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        # Odoo's custom assertRaises accepts a single exception class, not a
        # tuple. With the admin-managed ACL, create is denied at the ACL level.
        with self.assertRaises(AccessError):
            self.env["user.signature.company"].with_user(plain).create(
                {
                    "user_id": plain.id,
                    "company_id": self.company_a.id,
                    "email": "self@a.be",
                }
            )

    def test_manager_can_write_other_users_identity(self):
        """A Signature Manager (trusted admin role, NOT sysadmin) can create an
        identity row for ANOTHER user."""
        manager_group_id = self.env.ref(
            "mail_user_signature_template.group_signature_template_manager"
        ).id
        manager = self.env["res.users"].create(
            {
                "name": "Sig Manager",
                "login": "sig_manager_user",
                "email": "mgr@a.be",
                "company_id": self.company_a.id,
                "company_ids": [(6, 0, [self.company_a.id])],
                "group_ids": [(6, 0, [manager_group_id])],
            }
        )
        # Manager must NOT be a system admin for this test to be meaningful.
        self.assertFalse(manager.has_group("base.group_system"))
        other = self.env["res.users"].create(
            {
                "name": "Managed Person",
                "login": "managed_by_manager",
                "email": "managed@a.be",
                "company_id": self.company_a.id,
                "company_ids": [(6, 0, [self.company_a.id])],
            }
        )
        row = (
            self.env["user.signature.company"]
            .with_user(manager)
            .create(
                {
                    "user_id": other.id,
                    "company_id": self.company_a.id,
                }
            )
        )
        self.assertTrue(row.id)
        self.assertEqual(row.user_id, other)

    def test_regular_user_can_read_own_identity(self):
        """A plain user can still READ their own identity row."""
        plain = self.env["res.users"].create(
            {
                "name": "CanRead",
                "login": "canread_user",
                "email": "cr@a.be",
                "company_id": self.company_b.id,
                "company_ids": [(6, 0, [self.company_b.id])],
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        row = self.env["user.signature.company"].create(
            {
                "user_id": plain.id,
                "company_id": self.company_b.id,
            }
        )
        visible = self.env["user.signature.company"].with_user(plain).search(
            [("id", "=", row.id)]
        )
        self.assertTrue(visible)

    def test_identity_email_domain_must_be_authorized(self):
        """An identity email on an unknown domain is rejected."""
        with self.assertRaises(ValidationError):
            self.env["user.signature.company"].create(
                {
                    "user_id": self.user.id,
                    "company_id": self.company_a.id,
                    "email": "someone@totally-unknown-domain.example",
                }
            )

    def test_identity_email_domain_authorized_passes(self):
        """An identity email whose domain has a mail server / alias domain is ok."""
        # Use a domain covered ONLY by the ir.mail_server.from_filter (no
        # mail.alias.domain fixture exists for it), so authorization can come
        # only from the from_filter branch under test.
        srv = self.env["ir.mail_server"].create(
            {
                "name": "Test parts",
                "smtp_host": "smtp.example.com",
                "from_filter": "mailserver-only-test.be",
            }
        )
        self.assertTrue(srv)
        rec = self.env["user.signature.company"].create(
            {
                "user_id": self.user.id,
                "company_id": self.company_a.id,
                "email": "ok@mailserver-only-test.be",
            }
        )
        self.assertTrue(rec.id)

    def test_template_company_mismatch_blocked(self):
        """Can't assign a template from a different company."""
        with self.assertRaises(ValidationError):
            self.env["user.signature.company"].create(
                {
                    "user_id": self.user.id,
                    "company_id": self.company_a.id,
                    "signature_template_id": self.template_b.id,
                }
            )

    # ------------------------------------------------------------------
    # ADR-0001 / ADR-0002: unrestricted render, no stored poisoning
    # ------------------------------------------------------------------

    def test_non_admin_can_render_signature(self):
        """A plain internal user (not admin, not template editor) renders
        a bare-variable template without AccessError (ADR-0001)."""
        plain = self.env["res.users"].create({
            "name": "Plain User",
            "login": "plain_render_user",
            "email": "plain@company-a-test.be",
            "company_id": self.company_a.id,
            "company_ids": [(6, 0, [self.company_a.id])],
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
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

    # ------------------------------------------------------------------
    # Hardening: HTML escaping in fallback + NewId guard (Task 2)
    # ------------------------------------------------------------------

    def test_signature_fallback_escapes_user_name(self):
        """HTML in a user's name is escaped in the fallback signature
        (review finding 7 — no injection into outbound email)."""
        evil = self.env["res.users"].create({
            "name": '<a href="https://evil">reset</a>',
            "login": "evil_name_user",
            "email": "evil@company-a-test.be",
            "company_id": self.company_a.id,
            "company_ids": [(6, 0, [self.company_a.id])],
        })
        # No per-company row, no template → name-based fallback path.
        # Disable templates on the company and clear any stored signature so
        # the branch under test (name fallback) is genuinely hit.
        self.company_a.use_signature_templates = False
        evil.signature = False
        sig = evil._get_company_signature(self.company_a)
        self.assertIsInstance(sig, Markup)
        self.assertIn("&lt;a href", sig)          # escaped
        self.assertNotIn("<a href", sig)          # not raw

    def test_stored_signature_branch_returns_markup_no_double_escape(self):
        """The STORED-signature fallback branch must return a markupsafe.Markup
        so mail_thread's ``Markup(...) % signature`` insertion does NOT
        double-escape a real custom signature (cold-cache regression guard).

        A TransactionCase can't produce a genuinely cold ORM cache, so this
        asserts the invariant at the type level plus a no-double-escape check.
        """
        user = self.env["res.users"].create({
            "name": "Custom Sig User",
            "login": "custom_sig_user",
            "email": "custom@company-a-test.be",
            "company_id": self.company_a.id,
            "company_ids": [(6, 0, [self.company_a.id])],
        })
        # Force the stored-signature branch: no templates, a non-empty custom
        # signature containing HTML.
        self.company_a.use_signature_templates = False
        user.signature = "<p>Custom <b>Sig</b></p>"

        result = user._get_company_signature(self.company_a)
        self.assertIsInstance(result, Markup)

        # Wrapping via %-insertion (as mail_thread does) must not escape the
        # already-safe HTML: the <b> tag survives, it is not turned into &lt;b&gt;.
        wrapped = Markup("<div>%s</div>") % result
        self.assertIn("<b>Sig</b>", wrapped)
        self.assertNotIn("&lt;b&gt;", wrapped)

    def test_get_company_email_handles_newid(self):
        """_get_company_email on an unsaved record returns falsy, no crash."""
        new_user = self.env["res.users"].new({"name": "Draft"})
        self.assertFalse(new_user._get_company_email(self.company_a))

    def test_signature_escapes_malicious_user_name(self):
        """A user-settable name containing HTML is escaped in the rendered
        avatar markup (review finding 1 — no injection into outbound email)."""
        evil = self.env["res.users"].create({
            "name": "<img src=x onerror=alert(1)>",
            "login": "evil_avatar_user",
            "email": "evil_avatar@company-a-test.be",
            "company_id": self.company_a.id,
            "company_ids": [(6, 0, [self.company_a.id])],
        })
        template = self.env["signature.template"].create({
            "name": "Avatar Template",
            "body_html": '<div><t t-out="user_image"/></div>',
            "company_id": self.company_a.id,
        })
        sig = template._render_signature(evil, company=self.company_a)
        # The raw payload must not survive; it must be HTML-escaped.
        self.assertNotIn("<img src=x onerror=alert(1)>", sig)
        self.assertIn("&lt;img", sig)

    def test_crafted_sending_company_is_ignored(self):
        """A forced sending company the user has NO identity for is ignored;
        resolution falls back to the record/home company, no AccessError
        (review finding 2)."""
        company_c = self.env["res.company"].create({
            "name": "Crafted Evil Co",
        })
        company_c.use_signature_templates = True
        # Sanity: company_c is neither the user's home nor a configured identity.
        self.assertNotIn(company_c, self.user._identity_company_ids())

        partner = self.env["res.partner"].create(
            {"name": "CraftRcpt", "email": "craft@example.com"}
        )
        partner.message_subscribe(partner_ids=self.user.partner_id.ids)
        record = partner.with_user(self.user).with_company(self.company_b)
        message = record.message_post(
            body="Hello", subject="Craft", message_type="comment",
            subtype_xmlid="mail.mt_comment", email_add_signature=True,
        )
        # Craft a context forcing a company the user may NOT send as.
        crafted = record.with_context(force_sending_company_id=company_c.id)
        render_values = crafted._notify_by_email_prepare_rendering_context(
            message, msg_vals={}
        )
        signature_html = str(render_values.get("signature") or "")
        # The forced company is ignored: its name must NOT appear. Resolution
        # falls back to the posting/record company (company_b). No AccessError
        # was raised reaching this point.
        self.assertNotIn(company_c.name, signature_html)
        self.assertIn(self.company_b.name, signature_html)

    def test_init_store_data_not_overridden(self):
        """The stored-field priming trick is gone (ADR-0002).

        The mail module legitimately defines `_init_store_data`; this guards
        that OUR module no longer overrides it. `__module__` of the resolved
        method must therefore point at the mail addon, not at this module —
        reintroducing our override would flip it and fail this assertion.
        """
        method = type(self.user)._init_store_data
        self.assertNotIn(
            "mail_user_signature_template",
            method.__module__,
            "res.users._init_store_data must not be overridden by this module",
        )

