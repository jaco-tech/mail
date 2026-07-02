# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from markupsafe import Markup

from odoo import models


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _notify_by_email_prepare_rendering_context(
        self, message, msg_vals=False,
        model_description=False,
        force_email_company=False,
        force_email_lang=False,
        force_record_name=False,
    ):
        """Override to render signature with the correct company context."""
        render_values = super()._notify_by_email_prepare_rendering_context(
            message,
            msg_vals=msg_vals,
            model_description=model_description,
            force_email_company=force_email_company,
            force_email_lang=force_email_lang,
            force_record_name=force_record_name,
        )

        # Re-render signature with company-aware logic
        author_user = render_values.get("author_user")
        email_add_signature = render_values.get("email_add_signature")
        if not author_user or not email_add_signature:
            return render_values

        # Determine the correct company for this notification
        company = render_values.get("company") or self.env.company

        company_signature = author_user._get_company_signature(company)
        if company_signature:
            render_values["signature"] = (
                Markup("<div>-- <br/>%s</div>") % Markup(company_signature)
            )

        return render_values
