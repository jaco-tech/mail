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
