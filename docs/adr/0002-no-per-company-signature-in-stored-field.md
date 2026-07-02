# Do not store the per-company signature in res.users.signature

**Status:** accepted

`res.users.signature` is a single stored HTML field. An early version of the multi-company
work tried to make it represent the *current* Sending Company's signature by rewriting it on
every company switch (`_init_store_data`). This caused a write on every page load (raw-vs-
sanitized comparison never matched) and cross-user poisoning when a stored `_compute_signature`
rendered other users' signatures with the editor's active company.

The stored `signature` field remains the user's **default-company** signature (used only for
the Preferences preview). The **per-company** signature is rendered **on demand at send time**
via `_get_company_signature(company)` in the composer and notification paths — never stored.

## Consequence

A future reader who sees only the single stored field will wonder how per-company signatures
work; they are computed at send time, not persisted. One stored field structurally cannot
hold N per-company values, so the source of truth for a company-specific signature is the
`user.signature.company` row plus the template, resolved at send time.
