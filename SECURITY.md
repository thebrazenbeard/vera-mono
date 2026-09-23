# Security and Data Boundary

This repository is public. Treat every committed file as publicly readable.

## Never commit

- Live Supabase rows or database dumps
- Raw Vera Memory Ledger snapshots
- Conversation exports or private relational records
- Credentials, API keys, access tokens, cookies, or connection strings
- Personal identifiers not already intended for public release
- Generated checkpoints containing private memory content

## Permitted content

- Database schemas and migrations that contain no live data
- Validation code and tests using synthetic fixtures
- Architectural documentation
- Public release manifests and checksums
- Runtime rules that are safe for public disclosure

## Incident response

If sensitive content is committed, removing it in a later commit is insufficient because Git history preserves it. Revoke exposed credentials immediately and rewrite repository history before treating the incident as resolved.
