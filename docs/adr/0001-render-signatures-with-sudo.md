# Render signatures with sudo

**Status:** accepted

Signature templates (`signature.template`, inheriting `mail.render.mixin` with restricted
rendering) use bare context variables (`t-out="name"`, `t-out="company_name"`, …) that are
not in `mail_allowed_qweb_expressions()`. Rendering as a non-admin user therefore raises
`AccessError`, and this happens on hot paths (webclient store init, message_post notification),
making signatures unusable for regular users.

We render signatures with `sudo()` (equivalently, treat the template model as unrestricted).

## Trade-off

Because rendering runs privileged, anyone who can edit a signature template can author QWeb
that evaluates in a sudo context — a privilege-escalation surface. This is acceptable because
signature templates are **admin-managed only** (see spec §5): editing rights sit with trusted
administrators, the same trust level already granted to server actions and mail templates.
The alternative — keeping restricted rendering and maintaining an explicit allow-list of every
signature context variable — was rejected as more code and more ongoing maintenance for a
narrower blast radius we don't need given the admin-only editing constraint.
