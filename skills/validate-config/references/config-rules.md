# Team config conventions

House rules for service configuration files. These are conventions, not
structural requirements — the structural validator script does not check
them. Every rule below must be evaluated against the config.

## RULE 1: service_name format

`service_name` must be kebab-case (lowercase, words separated by `-`) and
must start with the `svc-` prefix.

Valid: `svc-data-pipeline`, `svc-auth`. Invalid: `DataPipeline`, `data_pipeline`, `auth`.

## RULE 2: port range

`port` must be in the team's allocated range **9000–9999** (inclusive).
Ports outside this range collide with other teams' allocations.

## RULE 3: log_level allowed values

`log_level` must be exactly one of: `debug`, `info`, `warning`, `error`.
No other values (e.g. `verbose`, `trace`, `WARN`) are accepted.

## RULE 4: max_retries bound

`max_retries` must be between **0 and 5** (inclusive). Higher values mask
persistent failures and overload downstream services.

## RULE 5: cache TTL floor

When `features.cache_enabled` is `true`, `features.cache_ttl_seconds` must
be **at least 300**. Shorter TTLs cause cache stampedes. (If caching is
disabled, the TTL value is irrelevant.)
