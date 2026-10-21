# Copyright 2026 jaco.tech
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""A plain internal user must be able to preview and render signatures.

``signature.template`` inherits ``mail.render.mixin`` with restricted
rendering, so rendering in a non-editor user's env sets
``raise_on_forbidden_code_for_model``: every expression outside
``mail_allowed_qweb_expressions()`` (a handful of ``object.*`` paths) raises
"Only members of Mail Template Editor group are allowed to edit
templates containing sensible placeholders". That includes this module's
own documented placeholders (``name``, ``email``, ``company_logo``, ...), so
every real signature template fails for such a user. Templates are only
authorable by signature managers / system admins (see
``security/ir.model.access.csv``), so rendering them for read-only display is
safe for every internal user.
"""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestRenderNonEditor(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.ref("base.main_company")
        cls.plain_user = new_test_user(
            cls.env,
            login="sig_plain_renderer",
            name="Plain Signature Renderer",
            groups="base.group_user",
            company_id=cls.company.id,
        )
        cls.plain_user.email = "plain.renderer@example.com"
        # Created as superuser, i.e. by a template author. ``name`` is one of
        # the module's documented placeholders, ``object.email`` an object
        # expression; neither is in mail_allowed_qweb_expressions().
        cls.template = cls.env["signature.template"].create(
            {
                "name": "Placeholder Template",
                "company_id": cls.company.id,
                "body_html": (
                    '<p><strong><t t-out="name"/></strong><br/>'
                    '<t t-out="object.email"/></p>'
                ),
            }
        )

    def test_plain_user_is_not_a_template_editor(self):
        """Guard the premise: the user must hit the restricted render path."""
        self.assertFalse(self.plain_user.has_group("mail.group_mail_template_editor"))
        self.assertFalse(self.plain_user._is_admin())

    def test_render_signature_as_plain_user(self):
        template = self.template.with_user(self.plain_user)
        rendered = template._render_signature(self.plain_user)
        self.assertIn("Plain Signature Renderer", rendered)
        self.assertIn("plain.renderer@example.com", rendered)

    def test_template_preview_html_as_plain_user(self):
        template = self.template.with_user(self.plain_user)
        self.assertIn("Plain Signature Renderer", template.preview_html)

    def test_preview_wizard_as_plain_user(self):
        """My Profile -> preview signature opens this wizard."""
        action = (
            self.env["res.users"]
            .with_user(self.plain_user)
            .browse(self.plain_user.id)
            .action_preview_signature()
        )
        self.assertEqual(action["res_model"], "signature.template.preview")
        wizard = (
            self.env["signature.template.preview"]
            .with_user(self.plain_user)
            .create(
                {
                    "template_id": self.template.id,
                    "user_id": self.plain_user.id,
                }
            )
        )
        values = wizard.read(["preview_html"])[0]
        self.assertIn("Plain Signature Renderer", values["preview_html"])
        self.assertIn("plain.renderer@example.com", values["preview_html"])
