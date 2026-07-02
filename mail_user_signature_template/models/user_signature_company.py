# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class UserSignatureCompany(models.Model):
    _name = "user.signature.company"
    _description = "Per-Company Email Signature Settings"
    _order = "user_id, company_id"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        ondelete="cascade",
        index=True,
    )
    email = fields.Char(
        help="Email address to use when sending from this company. "
        "Leave empty to use the user's default email.",
    )
    use_signature_template = fields.Boolean(
        default=True,
        help="Use a signature template for this company",
    )
    signature_template_id = fields.Many2one(
        "signature.template",
        string="Signature Template",
        domain="[('company_id', '=', company_id)]",
        help="Signature template to use for this company",
    )
    display_name = fields.Char(compute="_compute_display_name")

    @api.depends("user_id.name", "company_id.name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                " — ".join(filter(None, [rec.user_id.name, rec.company_id.name])) or ""
            )

    _user_company_unique = models.Constraint(
        "UNIQUE(user_id, company_id)",
        "A user can only have one signature configuration per company.",
    )

    @api.constrains("user_id")
    def _check_user_id_ownership(self):
        """Non-admin users can only manage their own per-company records.

        The record rule restricts read visibility, but a user with write
        access could otherwise reassign their row to another user (bypassing
        the unique constraint on create, or poisoning another user's data).
        """
        if (
            self.env.su
            or self.env.user.has_group("base.group_system")
            or self.env.user.has_group(
                "mail_user_signature_template.group_signature_template_manager"
            )
        ):
            return
        for record in self:
            if record.user_id.id != self.env.user.id:
                raise ValidationError(
                    self.env._(
                        "You can only manage your own per-company signature settings."
                    )
                )

    @api.constrains("signature_template_id", "company_id")
    def _check_template_company(self):
        """Ensure the chosen template belongs to the same company."""
        for record in self:
            tpl = record.signature_template_id
            if tpl and tpl.company_id and tpl.company_id != record.company_id:
                raise ValidationError(
                    self.env._(
                        "Signature template '%(tpl)s' belongs to company '%(tpl_co)s', "
                        "but this record targets company '%(co)s'.",
                        tpl=tpl.name,
                        tpl_co=tpl.company_id.name,
                        co=record.company_id.name,
                    )
                )

    @api.constrains("company_id", "user_id")
    def _check_company_in_user_companies(self):
        """Ensure the identity's company is one the user actually belongs to.

        The send path sudo()s the forced company, so an identity configured for
        a company outside the user's ``company_ids`` could let that user send as
        a company they are not a member of. Reject it server-side.
        """
        for rec in self:
            if (
                rec.company_id
                and rec.user_id
                and rec.company_id not in rec.user_id.company_ids
            ):
                raise ValidationError(
                    self.env._(
                        "Company '%(co)s' is not one of %(user)s's allowed "
                        "companies. Configure a signature identity only for a "
                        "company the user belongs to.",
                        co=rec.company_id.name,
                        user=rec.user_id.name,
                    )
                )

    @api.constrains("email")
    def _check_email_domain_authorized(self):
        """Warn (block) when the From domain has no authorized outgoing server
        or alias domain — it would route via the fallback server and likely
        fail SPF/DKIM."""
        servers = self.env["ir.mail_server"].sudo().search([])
        filters = set()
        for server in servers:
            for part in (server.from_filter or "").split(","):
                part = part.strip().lower()
                if part:
                    filters.add(part.rsplit("@", 1)[-1])
        alias_domains = {
            name.lower()
            for name in self.env["mail.alias.domain"].sudo().search([]).mapped("name")
        }
        for rec in self:
            if not rec.email or "@" not in rec.email:
                continue
            domain = rec.email.rsplit("@", 1)[-1].lower()
            if domain not in filters and domain not in alias_domains:
                raise ValidationError(
                    self.env._(
                        "The domain '%(domain)s' has no authorized outgoing mail "
                        "server or alias domain. Mail sent from this address may "
                        "fail delivery (SPF/DKIM).",
                        domain=domain,
                    )
                )

    @api.model
    def _get_or_create(self, user, company):
        """Find or create a per-company signature record for the given user+company."""
        record = self.search(
            [("user_id", "=", user.id), ("company_id", "=", company.id)],
            limit=1,
        )
        if not record:
            record = self.create(
                {
                    "user_id": user.id,
                    "company_id": company.id,
                }
            )
        return record

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
