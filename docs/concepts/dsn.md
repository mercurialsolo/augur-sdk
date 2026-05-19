# DSN

The **DSN** (Data Source Name) is the SDK's single credential. One env
var, one bearer token, no client-side config files.

## Shape

```
<scheme>://<host>/api/v1?token=<api_key>&tenant=<tenant_slug>
```

- `<scheme>` — `http` for local dev, `https` for anything public.
- `<host>` — your Augur server.
- `<api_key>` — the secret. 24 hex bytes (48 chars). Treat like a password.
- `<tenant_slug>` — informational; the server resolves the actual tenant
  from the api_key. Helps humans grep DSNs.

Example:

```text
https://augur.example/api/v1?token=05fea4d4936a6b9334fce70ebbd2acb622ad090075ff0fdc&tenant=staffai
```

## How the SDK uses it

The SDK auto-detects the DSN in this order:

1. `dsn=` argument passed to `DebugSession(...)`
2. `AUGUR_DSN` env var
3. Neither → streaming disabled; bundle is still written to `out_dir`

Each ingest call carries `Authorization: Bearer <api_key>`. The SDK also
spawns a 15-second heartbeat thread that keeps the server's connection
status indicator green between events. Network failures are non-fatal —
the local bundle is always complete even if the server is unreachable.

## How a DSN is issued

There's no self-serve signup. An admin runs:

```bash
augur admin dsn-issue --tenant <slug> --label <human-name>
```

The plaintext key is printed **once** and never recoverable; only a
bcrypt hash is stored server-side. If you lose it, issue a new one.

## Rotation

DSN keys can be rotated freely — each one is independent. Issue a new
one, deploy it to the CUA, then revoke the old (today via
`$AUGUR_DATA_DIR/dsns.json` edit, soon via `augur admin dsn-revoke`).

## Scoping

A DSN belongs to **one tenant**. Two tenants share zero data. Even with
the right DSN you cannot read another tenant's runs — ingest is
write-only and tenant-scoped at write time.

## Security checklist for production

- [ ] DSN stored in your secrets manager (not a checked-in env file)
- [ ] HTTPS only (use TLS termination at your reverse proxy)
- [ ] One DSN per environment / per CUA — easier to rotate
- [ ] No DSNs in client-side JS — this SDK is server-side only
- [ ] CI for your CUA project includes a check that the env var is set
      via the secrets backend, not a fallback default
