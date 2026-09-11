# Copyright 2026 jaco.tech
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
"""My Profile must open for a user with no HR group.

This module puts ``use_signature_template`` and ``signature_template_id`` on the
profile. ``res.users.read()`` elevates a user's read of their own record only
when EVERY requested field is self-accessible
(``odoo/addons/base/models/res_users.py:564-569``), so an unregistered field
here collapses the read to non-sudo and any ``hr.employee``-related field in the
same payload raises.
"""

from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestProfileSelfRead(TransactionCase):
    def test_profile_fields_are_self_accessible(self):
        readable, writeable = self.env["res.users"]._self_accessible_fields()
        for name in ("use_signature_template", "signature_template_id"):
            self.assertIn(
                name,
                readable,
                f"{name} is on My Profile but not self-readable, so it collapses "
                "the sudo branch in res.users.read() for every other field",
            )
            self.assertIn(
                name,
                writeable,
                f"{name} is editable on My Profile, so saving needs it writeable",
            )

    def test_a_plain_user_can_read_them_on_their_own_record(self):
        user = new_test_user(
            self.env, login="sig_profile_probe", groups="base.group_user"
        )
        own = self.env["res.users"].with_user(user).browse(user.id)
        own.web_read({"use_signature_template": {}, "signature_template_id": {}})

    def test_a_foreign_company_template_is_refused_on_write(self):
        """The view domain is not an authorization boundary.

        Making these fields self-writeable elevates the write for one's own
        record, so an RPC write bypassing the UI domain must be refused on the
        server.
        """
        from odoo.exceptions import ValidationError

        other_company = self.env["res.company"].create({"name": "Elders NV"})
        foreign = self.env["signature.template"].create(
            {
                "name": "Foreign",
                "company_id": other_company.id,
                "body_html": "<p>foreign</p>",
            }
        )
        user = new_test_user(
            self.env, login="sig_foreign_probe", groups="base.group_user"
        )
        with self.assertRaises(ValidationError):
            self.env["res.users"].with_user(user).browse(user.id).write(
                {"signature_template_id": foreign.id}
            )

    def test_a_plain_user_can_save_their_own_preferences(self):
        """The positive control: My Profile must be SAVEABLE, not just readable.

        This is the P0 the pre-super() mapping caused — it wrote the
        non-self-writeable stored twin before core could elevate the
        own-record write, so a plain user got
        "You are not allowed to modify 'User'".
        """
        company = self.env.user.company_id
        template = self.env["signature.template"].create(
            {
                "name": "Own company",
                "company_id": company.id,
                "body_html": "<p>own</p>",
            }
        )
        user = new_test_user(self.env, login="sig_save_probe", groups="base.group_user")
        user.company_id = company
        own = self.env["res.users"].with_user(user).browse(user.id)
        own.write(
            {"use_signature_template": True, "signature_template_id": template.id}
        )
        self.assertTrue(user._use_signature_template)
        self.assertEqual(user._signature_template_id, template)

    def test_saving_does_not_blank_the_signature(self):
        """`vals["signature"] = False` stored an empty signature.

        Latent until the save path was repaired; it would then have wiped a
        user's signature on every profile save. `signature` depends on both
        public fields, so the ORM recomputes it.
        """
        company = self.env.user.company_id
        template = self.env["signature.template"].create(
            {
                "name": "Renders",
                "company_id": company.id,
                "body_html": "<p>RENDERED-MARKER</p>",
            }
        )
        user = new_test_user(
            self.env, login="sig_blank_probe", groups="base.group_user"
        )
        user.company_id = company
        self.env["res.users"].with_user(user).browse(user.id).write(
            {"use_signature_template": True, "signature_template_id": template.id}
        )
        self.assertIn("RENDERED-MARKER", user.signature or "")

    def test_a_forced_company_accepts_the_echo_but_refuses_the_opt_out(self):
        """web_save echoes the computed value back; only a real opt-out raises.

        233cb7b could not tell those apart and silently dropped both, which is
        why test_08 and test_17 have been red since 2026-03-05.
        """
        company = self.env.user.company_id
        template = self.env["signature.template"].create(
            {
                "name": "Forced",
                "company_id": company.id,
                "body_html": "<p>forced</p>",
            }
        )
        company.use_signature_templates = True
        company.force_signature_template = True
        company.default_signature_template_id = template
        user = new_test_user(
            self.env, login="sig_forced_probe", groups="base.group_user"
        )
        user.company_id = company
        own = self.env["res.users"].with_user(user).browse(user.id)

        own.write({"use_signature_template": True})  # the echo must pass

        from odoo.exceptions import ValidationError as _VE

        with self.assertRaises(_VE):
            own.write({"use_signature_template": False})
