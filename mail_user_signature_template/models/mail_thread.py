# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from markupsafe import Markup

from odoo import models


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _signature_sending_company(self, default=None):
        """Resolve the company that drives the From address and signature:
        forced "Send As" context → ``default`` → record company → env.company.

        ``default`` lets a caller preserve core's own company resolution (e.g.
        the signature hook passes ``render_values["company"]``, which already
        honors ``force_email_company`` and is sudo'd) as the fallback when no
        "Send As" company is forced.
        """
        forced = self.env.context.get("force_sending_company_id")
        if forced:
            # SECURITY: only honor a forced "Send As" company if it is one of
            # the acting user's OWN identities (home company + configured
            # identity companies). A crafted context could otherwise ask us to
            # render a sudo'd signature/From for ANY company, bypassing the
            # res.company record rule. If the force is not allowed, ignore it
            # (do NOT raise — sends must never break) and fall through to the
            # normal default/record/env resolution below.
            identity_ids = self.env.user._identity_company_ids().ids
            if forced in identity_ids:
                # sudo() so the signature/From rendering can read the forced
                # company's fields even when the acting user's active-company
                # context does not include it. This mirrors core, which passes
                # a sudo'd company in render_values["company"].
                return self.env["res.company"].browse(forced).sudo()
        if default:
            return default
        if "company_id" in self._fields and self.company_id:
            return self.company_id
        return self.env.company

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

        # Determine the correct company for this notification (honoring a
        # forced "Send As" company from the composer, if any). Fall back to
        # core's resolved company (render_values["company"]) so the prior
        # behavior — honoring force_email_company, sudo'd — is preserved when
        # nothing is forced.
        company = self._signature_sending_company(
            default=render_values.get("company")
        )

        company_signature = author_user._get_company_signature(company)
        if company_signature:
            render_values["signature"] = (
                Markup("<div>-- <br/>%s</div>") % company_signature
            )

        return render_values

    def _notify_by_email_get_base_mail_values(
        self, message, recipients_data, additional_values=None
    ):
        """Set the per-company From so the notification routes via the right
        outgoing mail server (from_filter) and does not leak the home company.

        Keyed on the Sending Company resolved by ``_signature_sending_company``
        (forced "Send As" context → record company → env.company). Never sets
        reply_to (handled by Odoo's per-company alias domains).
        """
        vals = super()._notify_by_email_get_base_mail_values(
            message, recipients_data, additional_values=additional_values
        )
        # A context-forced From must not be stomped (symmetric with the
        # composer's _compute_authorship guard).
        if self.env.context.get("default_email_from"):
            return vals
        # Resolve the author's user like core does (main_user_id), so a partner
        # with multiple users does not cause a From/signature mismatch.
        author_user = message.author_id.main_user_id
        if not author_user:
            return vals
        # Only override when the posted message still carries the author's
        # NATURAL From. If message.email_from was explicitly set to something
        # else (a template / server action forced it), leave it untouched.
        natural = author_user.email_formatted
        if message.email_from and message.email_from != natural:
            return vals
        company = self._signature_sending_company()
        company_email = author_user._get_company_email(company)
        if company_email and company_email != author_user.email:
            vals["email_from"] = author_user._get_company_email_formatted(company)
        return vals
