# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class MailComposeMessage(models.TransientModel):
    _inherit = "mail.compose.message"

    sending_company_id = fields.Many2one(
        "res.company",
        string="Send As",
        compute="_compute_sending_company_id",
        readonly=False,
        store=True,
        help="Company identity (From address + signature) to send this mail with.",
    )
    allowed_sending_company_ids = fields.Many2many(
        "res.company",
        compute="_compute_allowed_sending_company_ids",
    )
    show_sending_company = fields.Boolean(
        compute="_compute_show_sending_company",
    )

    @api.depends("record_company_id")
    def _compute_sending_company_id(self):
        for composer in self:
            composer.sending_company_id = (
                composer.record_company_id or composer.env.company
            )

    @api.depends("res_ids")
    def _compute_allowed_sending_company_ids(self):
        companies = self.env.user._identity_company_ids()
        for composer in self:
            composer.allowed_sending_company_ids = companies

    def _compute_show_sending_company(self):
        show = len(self.env.user.company_ids) > 1
        for composer in self:
            composer.show_sending_company = show

    @api.depends("composition_mode", "email_from", "model",
                 "res_domain", "res_ids", "template_id", "record_company_id",
                 "sending_company_id")
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
            # Prefer the explicit "Send As" company, then the RECORD's company
            # (the Sending Company), then the navbar/env company. Fall back to
            # env.company when the record has no company (e.g. a partner without
            # company_id).
            company = (
                composer.sending_company_id
                or composer.record_company_id
                or composer.env.company
            )
            company_email = user._get_company_email(company)
            if company_email and company_email != user.email:
                composer.email_from = user._get_company_email_formatted(company)
                # Keep author_id consistent with the substituted email_from.
                # The parent derived author_id from the pre-override email;
                # always pin to the current user's partner so author and
                # sender stay coherent even when the per-company email is
                # associated with a different partner record.
                composer.author_id = user.partner_id.id

    def _action_send_mail(self, auto_commit=False):
        """Thread the chosen "Send As" company into message_post via context so
        the notify hooks render the From + signature for that company."""
        forced = self.sending_company_id
        composer = self
        if len(self) == 1 and forced:
            composer = self.with_context(force_sending_company_id=forced.id)
        return super(MailComposeMessage, composer)._action_send_mail(
            auto_commit=auto_commit
        )
