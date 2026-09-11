# Copyright 2025 OCA Contributors
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.orm.identifiers import NewId
from odoo.tools import is_html_empty


class ResUsers(models.Model):
    _inherit = "res.users"

    # Both fields below are shown on My Profile, and both are user-settable
    # there. `res.users.read()` elevates a user's read of their OWN record only
    # when EVERY requested field is self-accessible
    # (odoo/addons/base/models/res_users.py:564-569) — one unregistered field
    # silently drops the whole read to non-sudo, and any `hr.employee`-related
    # field in the same payload then raises AccessError.
    #
    # That is what broke My Profile for every non-HR user at Steen: the error
    # named `hr.employee.private_street`, but these two fields were part of the
    # cause. `mail_partner_forwarding` in this repo already does this correctly.

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + [
            "use_signature_template",
            "signature_template_id",
        ]

    @property
    def SELF_WRITEABLE_FIELDS(self):
        # Both are user preferences edited from My Profile, so they must be
        # writable there too, or saving the dialog fails the same way.
        return super().SELF_WRITEABLE_FIELDS + [
            "use_signature_template",
            "signature_template_id",
        ]

    use_signature_template = fields.Boolean(
        compute="_compute_use_signature_template",
        inverse="_inverse_use_signature_template",
        store=True,
        readonly=False,
        help="Use company signature template instead of custom signature",
    )
    _use_signature_template = fields.Boolean(
        string="Use Signature Template (stored)",
        help="Internal field to store user preference",
    )

    signature_template_id = fields.Many2one(
        "signature.template",
        string="Signature Template",
        compute="_compute_signature_template_id",
        inverse="_inverse_signature_template_id",
        store=True,
        readonly=False,
        domain="[('company_id', '=', company_id)]",
        help="Select a signature template to use",
    )
    _signature_template_id = fields.Many2one(
        "signature.template",
        string="Signature Template (stored)",
        help="Internal field to store user selection",
    )

    @api.depends(
        "company_id",
        "company_id.force_signature_template",
        "company_id.use_signature_templates",
        "_use_signature_template",
    )
    def _compute_use_signature_template(self):
        """Compute whether to use signature template based on company settings."""
        for user in self:
            if not user.company_id.use_signature_templates:
                user.use_signature_template = False
            elif user.company_id.force_signature_template:
                user.use_signature_template = True
            else:
                # Use stored preference or default to True for new users
                user.use_signature_template = (
                    user._use_signature_template
                    if user._use_signature_template is not None
                    else True
                )

    def _inverse_use_signature_template(self):
        """Store user preference for use_signature_template."""
        for user in self:
            if not user.company_id.force_signature_template:
                user._use_signature_template = user.use_signature_template

    @api.depends(
        "company_id",
        "company_id.use_signature_templates",
        "company_id.default_signature_template_id",
        "company_id.force_signature_template",
        "_signature_template_id",
    )
    def _compute_signature_template_id(self):
        """Compute signature template based on company settings."""
        for user in self:
            if (
                user.company_id.force_signature_template
                and user.company_id.default_signature_template_id
            ):
                user.signature_template_id = (
                    user.company_id.default_signature_template_id
                )
            elif user._signature_template_id and (
                not user._signature_template_id.company_id
                or user._signature_template_id.company_id == user.company_id
            ):
                # A twin from another company is treated as absent rather than
                # rendered: constraints only fire on writes, so a row stored
                # before this rule existed must not become live here.
                user.signature_template_id = user._signature_template_id
            elif (
                user.company_id.default_signature_template_id
                and not user._signature_template_id
            ):
                # Use company default if user hasn't selected one
                user.signature_template_id = (
                    user.company_id.default_signature_template_id
                )
            else:
                user.signature_template_id = False

    def _inverse_signature_template_id(self):
        """Store user selection for signature_template_id.

        The company rule is NOT enforced here. The field's
        ``domain="[('company_id', '=', company_id)]"`` is a view domain — a UI
        convenience, not an authorization boundary — and now that the public
        field is self-writeable a user's own-record write is elevated. The rule
        therefore lives in ``_check_signature_template_company`` on the STORED
        twin, which every path funnels through.
        """
        for user in self:
            if not user.company_id.force_signature_template:
                user._signature_template_id = user.signature_template_id

    @api.constrains("_signature_template_id", "company_id")
    def _check_signature_template_company(self):
        """A user may only hold a signature template of their own company.

        On the stored twin rather than the public field, so it also covers a
        direct write to ``_signature_template_id`` and so a selection stored
        while the company forced a template cannot become live later by turning
        the force off. Constraints run as superuser and fire on any ORM path
        touching the listed fields, so the client cannot skip it.
        """
        for user in self:
            template = user._signature_template_id
            if (
                template
                and template.company_id
                and template.company_id != user.company_id
            ):
                raise ValidationError(
                    _(
                        "Signature template %(template)s belongs to "
                        "%(owner)s and cannot be used by a user of "
                        "%(company)s.",
                        template=template.display_name,
                        owner=template.company_id.display_name,
                        company=user.company_id.display_name,
                    )
                )

    @api.depends("signature_template_id", "use_signature_template", "name")
    def _compute_signature(self):
        """Override signature computation to use templates."""
        for user in self:
            # Skip signature rendering for unsaved records (NewIds)
            # Template rendering requires a real database ID
            if not user.id or isinstance(user.id, NewId):
                user.signature = ""
                continue

            if (
                user.use_signature_template
                and user.signature_template_id
                and user.company_id.use_signature_templates
            ):
                # Use template
                user.signature = user.signature_template_id._render_signature(user)
            elif (
                not user.use_signature_template
                and user.name
                and is_html_empty(user.signature)
            ):
                # Default signature only if no custom signature exists
                user.signature = f"<p>--<br />{user.name}</p>"
            # If signature already has value and not using template,
            # keep existing value (this is the custom signature)

    @api.model_create_multi
    def create(self, vals_list):
        """Set default values for new users."""
        for vals in vals_list:
            # Set default internal values if not provided
            if "_use_signature_template" not in vals:
                vals["_use_signature_template"] = True
            if "_signature_template_id" not in vals:
                company_id = vals.get("company_id") or self.env.company.id
                company = self.env["res.company"].browse(company_id)
                if (
                    company.use_signature_templates
                    and company.default_signature_template_id
                ):
                    vals["_signature_template_id"] = (
                        company.default_signature_template_id.id
                    )
        return super().create(vals_list)

    @api.onchange("company_id")
    def _onchange_company_id(self):
        """Update signature template when company changes."""
        if self.company_id:
            # Trigger recomputation of computed fields
            self._compute_use_signature_template()
            self._compute_signature_template_id()

    def write(self, vals):
        """Handle signature updates.

        Three things this deliberately does NOT do any more:

        * It does not map the public fields onto their stored twins before
          ``super()``. Each public field has an ``inverse=`` that stores the
          twin, and those run INSIDE ``super().write()`` — after core has
          decided whether to elevate a user's write of their OWN record
          (``odoo/addons/base/models/res_users.py:596-617``). Assigning the
          twins here was a nested write of a field that is NOT in
          ``SELF_WRITEABLE_FIELDS``, so a plain user hit "You are not allowed
          to modify 'User'" before any of this ran, and My Profile could not
          be saved at all.
        * It does not blank ``signature``. ``vals["signature"] = False`` stored
          an empty signature rather than retriggering the compute; ``signature``
          already depends on both public fields, so the ORM recomputes it. With
          the save path repaired, keeping that line would wipe a user's
          signature on every profile save.
        * It does not silently discard a deliberate opt-out. Commit 233cb7b
          replaced the raise below with an unconditional ``pop`` because
          ``web_save`` echoes unchanged computed values back and that blocked
          every save. The echo and the override are distinguishable: under an
          active force the compute yields True, so an echo carries True and is
          accepted, while False can only be a real opt-out.
        """
        for user in self:
            company = user.company_id
            if not (
                company.force_signature_template and company.use_signature_templates
            ):
                continue
            if "use_signature_template" in vals and not vals["use_signature_template"]:
                raise ValidationError(
                    _(
                        "Cannot disable the signature template: "
                        "%(company)s requires using signature templates.",
                        company=company.display_name,
                    )
                )
            # Unchanged echoes of the forced values: nothing to store, the
            # compute pins both public fields while the force is active.
            vals.pop("use_signature_template", None)
            vals.pop("signature_template_id", None)

        return super().write(vals)

    @api.model
    def _get_signature_access_fields(self):
        """Fields that users can modify on their own signature settings."""
        fields = []
        if hasattr(super(), "_get_signature_access_fields"):
            fields = super()._get_signature_access_fields()
        return fields + [
            "use_signature_template",
            "_use_signature_template",
            "signature_template_id",
            "_signature_template_id",
        ]

    def action_preview_signature(self):
        """Preview the current signature."""
        self.ensure_one()
        return {
            "name": "Signature Preview",
            "type": "ir.actions.act_window",
            "res_model": "signature.template.preview",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_user_id": self.id,
                "default_template_id": self.signature_template_id.id
                if self.signature_template_id
                else False,
            },
        }

    @api.model
    def mail_allowed_qweb_expressions(self):
        """Extend allowed QWeb expressions to include signature template variables.

        This is necessary for QWeb security - variables that are not in this list
        will cause the template to be rendered using regex fallback instead of
        the full QWeb engine, which doesn't have access to custom context variables.
        """
        # Get the base allowed expressions
        expressions = list(super().mail_allowed_qweb_expressions())

        # Don't add our custom variables here - they're not fields on res.users
        # They are context variables passed via add_context
        return tuple(expressions)

    def action_recompute_signature(self):
        """Manually trigger signature recomputation."""
        self._compute_signature()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Success"),
                "message": _("Signature recomputed for %s user(s).") % len(self),
                "type": "success",
            },
        }
