# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

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
        """mail.compose.message substitutes email_from with per-company email."""
        Composer = self.env["mail.compose.message"].with_user(self.user)
        composer = Composer.with_company(self.company_b).create(
            {
                "subject": "Test",
                "body": "hello",
                "composition_mode": "comment",
                "model": "res.partner",
                "res_ids": str([self.env.user.partner_id.id]),
            }
        )
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

    # ------------------------------------------------------------------
    # Integration: mail.thread._notify_by_email_prepare_rendering_context
    # ------------------------------------------------------------------

    def test_notify_rendering_context_uses_company_signature(self):
        """Outgoing notifications pick up the per-company signature."""
        partner = self.env["res.partner"].create(
            {"name": "Recipient", "email": "recipient@example.com"}
        )
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
        with self.assertRaises((ValidationError, AccessError)):
            self.env["user.signature.company"].with_user(self.user).create(
                {
                    "user_id": other.id,
                    "company_id": self.company_a.id,
                    "email": "poison@example.com",
                }
            )

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

