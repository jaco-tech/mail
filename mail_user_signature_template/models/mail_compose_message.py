# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    @api.depends("composition_mode", "email_from", "model",
                 "res_domain", "res_ids", "template_id")
    def _compute_authorship(self):
        """Override to use per-company email when available."""
        super()._compute_authorship()
        user = self.env.user
        for composer in self:
            # Only override when no template email_from is set
            if composer.template_id and composer.template_id.email_from:
                continue
            company_email = user._get_company_email()
            if company_email and company_email != user.email:
                composer.email_from = user._get_company_email_formatted()
                # Keep author_id consistent with the substituted email_from.
                # The parent derived author_id from the pre-override email;
                # always pin to the current user's partner so author and
                # sender stay coherent even when the per-company email is
                # associated with a different partner record.
                composer.author_id = user.partner_id.id
