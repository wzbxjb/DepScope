# Security

## Deployment scope

DepScope is designed as a local, single-user investigation workspace. Its default Docker Compose configuration binds published ports to loopback. It does not provide authentication, tenant administration, or an internet-facing access-control layer. Keep the default network bindings when running the supplied configuration.

The mutation origin check is an additional browser boundary; it does not authenticate API callers. A public or shared deployment needs a separate security design before exposing the API or database.

## Data and external services

Keep `.env`, `data/runtime/`, and `artifacts/private/` out of version control. Runtime storage may contain uploaded dependency inventories, original source records, generated responses, signing keys, and usage information.

Public-resolution and advisory refresh operations contact PyPI, deps.dev, and OSV. An explicitly requested AI investigation sends its selected evidence context to the configured generation provider; configure and use it only with data you intend to share with that provider. Generation remains optional for the core graph workflows.

An advisory match identifies a record associated with a package version. It does not establish that an application is exploitable. Generated explanations and upgrade comparisons require the evidence checks described in the application and documentation.

## Report a vulnerability

Use the repository's **Security → Advisories → Report a vulnerability** entry when private reporting is enabled. Include the affected revision, reproduction steps, expected boundary, and observed impact, with credentials and personal data removed.

If private reporting is unavailable, open a public issue requesting a private reporting channel without including exploit details or sensitive files. No response-time or supported-version commitment is currently published.
