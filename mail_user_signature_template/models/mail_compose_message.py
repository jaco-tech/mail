# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, models


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    @api.depends("composition_mode", "email_from", "model",
                 "res_domain", "res_ids", "template_id", "record_company_id")
    def _compute_authorship(self):
        """Use the per-company email of the record's company (the Sending
        Company), unless a template or the context already forces email_from."""
        super()._compute_authorship()
        user = self.env.user
        for composer in self:
            # A template that forces email_from wins.
            if composer.template_id and composer.template_id.email_from:
                continue
            # A context-forced From must not be stomped (review finding 5).
            if composer.env.context.get("default_email_from"):
                continue
            # Key on the RECORD's company (the Sending Company), not the
            # navbar/env company. Fall back to env.company when the record has
            # no company (e.g. a partner without company_id).
            company = composer.record_company_id or composer.env.company
            company_email = user._get_company_email(company)
            if company_email and company_email != user.email:
                composer.email_from = user._get_company_email_formatted(company)
                # Keep author_id consistent with the substituted email_from.
                # The parent derived author_id from the pre-override email;
                # always pin to the current user's partner so author and
                # sender stay coherent even when the per-company email is
                # associated with a different partner record.
                composer.author_id = user.partner_id.id
