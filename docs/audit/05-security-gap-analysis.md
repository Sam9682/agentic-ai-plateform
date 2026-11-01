# 05 — Security Gap Analysis

- **Title:** Security Gap Analysis
- **Audit date:** 2026-10-31
- **Requirement coverage:** R5.1, R5.2, R5.3, R5.4, R11.1, R11.2
- **Method:** Read-only review of the authentication, authorization, MCP-surface, and credential-handling modules. For each module the current behavior and identified limitations are summarized, and every limitation is tagged with the source file in which it occurs. Credential handling was reviewed for how secrets are stored, encrypted at rest, passed to runtimes, and logged, cross-checked against a repository-wide grep for `token|secret|password|credential|vault`. No secret values are reproduced in this artifact; secrets are referenced by key name only (e.g. `ZAF_SECRET_KEY`, `password_hash`).

## Inspected Sources

Each file below was read in full and is recorded as inspected for the purposes of R11.1:

- `src/auth.py`
- `src/authz.py`
- `src/mcp_interface.py`
- `src/zaf/credential_vault.py`

Additional credential-handling references located via the `token|secret|password|credential|vault` grep and consulted for context (storage, runtime passing, and logging concerns): `src/config_postgres.py`, `src/database_postgres.py`, `src/sandbox_manager.py`, `src/create_gitea_repo.py`, `src/routes/genai_routes.py`, `src/routes/sso_routes.py`, `src/routes/security_routes.py`, `src/aro/event_service.py`, `src/aro/adapters/shai_http_sse.py`. The inbound-import evidence (which components have no `src/` consumer) is taken from `docs/audit/02-dependency-map.md`.

---

## `src/auth.py` — SSO token authentication

### Current behavior

`auth.py` implements the platform's SSO token lifecycle against PostgreSQL (`db_manager`):

- `generate_sso_token(user_id)` creates a random token via `secrets.token_urlsafe(32)`, stores only its SHA-256 hash (`token_hash`) in the `auth_tokens` table, sets an expiry one week out, and deletes any pre-existing tokens for that user before inserting the new one. The clear token is returned to the caller once and never persisted.
- `invalidate_sso_token(token)` deletes the matching hashed row.
- `validate_sso_token(token)` hashes the presented token and joins `auth_tokens` to `users`, returning identity fields only when the token exists and `expires_at > NOW()`.

The design is reasonable at its core: clear tokens are never stored, lookups are by hash, and expiry is enforced in SQL.

### Limitations

- **Unsalted, fast-hash token storage.** Tokens are stored as a plain `hashlib.sha256` digest with no salt or keyed MAC. Because the token itself is high-entropy (`token_urlsafe(32)`), this is far less severe than for passwords, but the hash is a fast digest and offers no defense-in-depth (e.g. HMAC with a server key) if the `auth_tokens` table leaks.
- **No throttling / brute-force protection.** `validate_sso_token` performs an unauthenticated lookup with no rate limiting, lockout, or audit of repeated failures at this layer.
- **Fixed one-week TTL, no sliding or rotation.** Expiry is hard-coded to one week; there is no rotation-on-use, no short-lived access/refresh split, and no server-side way to expire all sessions other than per-user deletion on the next `generate_sso_token`.
- **No binding to device/IP/tenant.** Tokens are bearer tokens with no contextual binding; a leaked token is fully replayable until expiry.

Related surface observed via grep (not in `auth.py` itself, recorded for traceability): `src/routes/sso_routes.py` places the SSO token directly into a redirect URL query string (`?token=...`), which exposes it to browser history, referrer headers, and server logs — tagged against that file below.

---

## `src/authz.py` — tenant scoping and role authorization

### Current behavior

`authz.py` provides the newer multi-tenant authorization layer for the ARO/ZAF/OBS surface:

- A **pure core** (`resolve_tenant`, `role_satisfies`) holds all decision logic with no Flask or DB dependency, so it is unit- and property-testable. `role_satisfies` uses a fixed rank (`viewer < operator < admin`) and denies unknown/missing roles by default. `resolve_tenant` selects the membership for an explicitly requested tenant, else the `is_default` membership, else the sole membership, else `None` (ambiguous → caller must pass an explicit tenant).
- **Flask decorators** (`login_required`, `tenant_scoped`, `role_required`) read `session`, load memberships through an injectable `membership_loader` (default queries `tenant_members`/`tenants`), and attach `g.tenant_id` / `g.tenant_role` / `g.tenant_slug`. All three deny by default: 401 when unauthenticated, 403 when the tenant cannot be resolved or the role is insufficient.
- The requested tenant is read from the `X-Tenant-Id` header or `tenant_id` query arg; invalid values fall back to the default-membership path.

The module's stated design principles — deny by default, pure testable core — are sound and well documented.

### Limitations

- **Only applied to new blueprints; legacy routes unprotected.** The module docstring states the decorators are applied only to the new ARO/ZAF/OBS blueprints, while existing routes keep inline checks — a magic `username == 'admin'` string comparison plus `if 'user_id' not in session: 401`. This leaves two divergent authorization models in the codebase; the legacy inline model has no tenant scoping and a hard-coded admin identity. Migrating the legacy routes is explicitly deferred ("tracked as follow-up").
- **No object-level / resource ownership checks.** Authorization is tenant+role coarse-grained; there is no per-resource ownership enforcement (e.g. "operator may act only on their own application") within this module.
- **Tenant selection trusts request-supplied header/arg.** `_requested_tenant_id` reads `X-Tenant-Id`/`tenant_id` from the request; safety depends entirely on `resolve_tenant` rejecting non-member tenants. This is handled correctly today, but there is no audit event emitted on a denied tenant switch, so probing is not observable from this layer.
- **Coarse three-level role model.** Only `viewer/operator/admin` exist; there is no finer separation (e.g. security-admin vs tenant-admin), so least-privilege cannot be expressed for sensitive operations.

---

## `src/mcp_interface.py` — MCP (stdio) tool surface

### Current behavior

`mcp_interface.py` exposes platform capabilities as a spec-compliant MCP server over the **stdio** transport using `FastMCP`. It registers thin tool wrappers over the same shared services used by the Dashboard/REST/CLI (`agent_control_service`, `TemplateCatalog`/`TemplateDeployService`, `database_postgres`): `list_applications`, `add_application`, `list_users`, `deploy_template`, `agent_control_containers`, the six operator actions (`start`, `stop`, `ps`, `logs`, `backup`, `restore`), and `modify_code`. Heavy imports are deferred to call time, and every tool catches exceptions and returns a structured `{"error": ...}` payload so failures never cross the protocol boundary as transport errors. `list_users` deliberately selects no password/secret columns.

### Limitations

- **No authentication or authorization on the MCP surface.** The tools accept `user_id` as a plain integer argument and act on behalf of that user with no verification that the caller is entitled to that identity. Any client able to speak to the stdio server can invoke privileged operations (deploy, start/stop, backup/restore, `modify_code`) for an arbitrary `user_id`. None of the `authz.py` decorators apply here, and no ZAF policy engine / approval check is consulted.
- **Hard-coded Gitea credential in a constructed URL.** `_run_developer_action` builds `repo_gitea_url` as a URL that embeds a static `gitadmin` username and a hard-coded password component. The same pattern appears in `src/routes/genai_routes.py`. Embedding credentials in a URL risks them being written into `modification_history`, logs, and the engine prompt. (Tagged against both files below; no value is reproduced here.)
- **Secret-bearing URL stored in deployment history.** On a clean `modify_code` run the constructed Gitea URL is persisted into `deployments.modification_history` and `gitea_branch_url`, so the embedded credential travels into the database unredacted.
- **No per-tool rate limiting or quota.** Operator actions run the agentic engine with a 1800s timeout and no concurrency/quota control at this layer; a client could launch many long-running engine runs.
- **Trusts resolved folder/path values.** `_resolve_app_and_user` falls back to a convention-built filesystem path; there is no validation that the path is within an allowed root before the engine is pointed at it.

---

## `src/zaf/credential_vault.py` — credential storage and scoped tokens

### Current behavior

`credential_vault.py` is the ZAF credential broker. Reviewed specifically for storage, encryption at rest, runtime passing, and logging:

- **Encrypted at rest.** Credentials are stored as Fernet AEAD ciphertext (from the `cryptography` package) in the `agent_credentials` table; plaintext is never written to the database. `store`/`rotate` encrypt before insert/update; `get` decrypts on read and returns the plaintext only to the caller, with a docstring instruction that callers must treat it as a secret and never log it unredacted.
- **Key management.** The Fernet key is derived from the `ZAF_SECRET_KEY` environment variable via `_derive_fernet_key` (SHA-256 of the secret, urlsafe-base64 encoded). `_get_secret` **fails closed**: if `ZAF_SECRET_KEY` is unset it raises `VaultError` rather than operating with a default/empty key.
- **Scoped-token minting.** `mint_scoped_token` issues a short-lived (`ttl_seconds`, default 300s) random token bound to a credential + scope; only the token's SHA-256 hash is persisted in `agent_scoped_tokens`, and the clear token is returned exactly once. `verify_token` validates by hash and fails closed on missing/revoked/expired. `revoke` revokes the credential and all tokens minted from it. This gives agents an expiring capability rather than the raw secret — a sound at-rest and handoff design.
- **Audit/logging posture.** The module itself logs nothing and the companion `src/aro/event_service.py` redacts secret-like keys/values (`redact`, mask-on-suspicion) before events are persisted, so credentials routed through the event stream are masked.

### Limitations

- **Key derivation is unsalted single-round SHA-256.** `_derive_fernet_key` hashes `ZAF_SECRET_KEY` with one SHA-256 pass and no salt or KDF (e.g. no PBKDF2/scrypt/argon2). A low-entropy `ZAF_SECRET_KEY` is therefore weakly protected, and there is no key-versioning to support rotating `ZAF_SECRET_KEY` without re-encrypting every row (the derivation is deterministic, so changing the env var invalidates all existing ciphertext).
- **Broker is not wired into any runtime (not integrated).** Per `docs/audit/02-dependency-map.md`, `credential_vault.py` has **no inbound `src/` import** — only `database_postgres.py` is downstream of it, and its only callers are its own test (`tests/test_zaf_credential_vault.py`) and a script import check. No adapter, orchestrator, or route calls `mint_scoped_token`/`get`, so the "pass a scoped token to the runtime instead of the raw secret" path is not actually exercised anywhere. The secure broker exists but is effectively unused by the execution flow.
- **Decrypted plaintext returned by value.** `get` returns the decrypted plaintext in a dict; safe handling depends entirely on caller discipline (the docstring warning). There is no wrapper type, zeroization, or enforced redaction at the boundary, so a careless caller could log it.
- **No at-rest protection for non-vault secrets.** Secrets outside this vault are not encrypted: `src/config_postgres.py` defaults `POSTGRES_PASSWORD` and Flask `SECRET_KEY` to hard-coded development values, and `database_postgres.py` seeds `admin`/`demo` users with a known default password hash. These bypass the vault entirely.

---

## Identified Limitations

Each limitation is tagged with the source file in which it occurs (R5.4). Severity is the reviewer's High/Medium/Low rating of security impact.

| Limitation | Source File | Severity (H/M/L) | Notes |
|------------|-------------|------------------|-------|
| MCP stdio tools perform no authentication/authorization; `user_id` is a trusted argument for privileged ops | `src/mcp_interface.py` | H | Deploy/start/stop/backup/restore/`modify_code` can be invoked for any `user_id`; no `authz.py` or ZAF check applies |
| Hard-coded Gitea credential embedded in a constructed repo URL | `src/mcp_interface.py` | H | Same pattern in `genai_routes.py`; value not reproduced here |
| Same hard-coded Gitea credential embedded in a constructed repo URL | `src/routes/genai_routes.py` | H | Also streamed into an SSE `data:` chunk, widening exposure |
| Secret-bearing Gitea URL persisted unredacted into `deployments.modification_history` / `gitea_branch_url` | `src/mcp_interface.py` | H | Credential travels into the database on a clean `modify_code` run |
| ARO/ZAF/OBS `authz.py` decorators not applied to legacy routes; legacy auth uses a magic `username == 'admin'` check | `src/authz.py` | H | Two divergent authz models; legacy path has no tenant scoping (migration deferred) |
| Fernet key derived from `ZAF_SECRET_KEY` via unsalted single-round SHA-256; no KDF, no key versioning/rotation | `src/zaf/credential_vault.py` | M | Weak protection for a low-entropy secret; rotating the env var invalidates all ciphertext |
| Credential broker has no inbound `src/` consumer — scoped-token handoff to runtimes is not wired end-to-end | `src/zaf/credential_vault.py` | M | Evidence: `docs/audit/02-dependency-map.md`; secure path exists but unused |
| SSO token stored as unsalted fast SHA-256 digest (no HMAC/keyed MAC) | `src/auth.py` | M | High-entropy token mitigates, but no defense-in-depth if `auth_tokens` leaks |
| SSO token placed in redirect URL query string (`?token=...`) | `src/routes/sso_routes.py` | M | Exposed via browser history, referrer headers, and access logs |
| Decrypted credential plaintext returned by value with no wrapper/zeroization; safe handling relies on caller discipline | `src/zaf/credential_vault.py` | M | Only a docstring warning guards against logging the secret |
| Hard-coded default `POSTGRES_PASSWORD` and Flask `SECRET_KEY` fallbacks; secrets outside the vault are unencrypted | `src/config_postgres.py` | M | `SECRET_KEY` default literally flags "change-in-production" |
| Default `admin`/`demo` users seeded with a known default password | `src/database_postgres.py` | M | Bootstrap accounts ship with a predictable credential |
| No rate limiting / brute-force protection / failure auditing on SSO token validation | `src/auth.py` | L | Unauthenticated lookup with fixed one-week TTL and no rotation-on-use |
| No denied-tenant-switch audit event; request-supplied `X-Tenant-Id`/`tenant_id` trusted (rejection correct, but probing not observable) | `src/authz.py` | L | Coarse `viewer/operator/admin` model limits least-privilege expression |
| MCP operator tools have no per-tool rate limit/quota; long (1800s) engine runs; convention-built paths not validated against an allowed root | `src/mcp_interface.py` | L | Resource-exhaustion and path-trust concerns on the stdio surface |

### Severity summary

- **High (6):** unauthenticated/unauthorized MCP surface, hard-coded Gitea credentials (two files) and their persistence into the DB, and the split/legacy authorization model.
- **Medium (7):** credential-vault key-derivation and integration gaps, SSO token hashing and query-string exposure, plaintext-by-value return, and hard-coded/default secrets outside the vault.
- **Low (3):** missing throttling/auditing on token validation and tenant switches, and MCP rate-limit/path-trust hardening.

These findings feed `docs/audit/09-gap-matrix.md` (ZAF credential broker, PEP/PDP wiring) and `docs/audit/10-implementation-plan.md` (Phase 3 — ZAF security hardening).
