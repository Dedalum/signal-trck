---
title: Pydantic schema-version errors must be raised pre-validation
category: integration-issues
component: chart_schema
problem_type: api_error_mapping
date: 2026-04-30
related:
  - plans/feat-phase-b-web-ui-fastapi.md (Decision 24)
  - src/signal_trck/chart_schema/models.py
  - src/signal_trck/chart_io.py
  - src/signal_trck/api/errors.py
tags: [pydantic, fastapi, error-handling, validation]
---

# Pydantic schema-version errors must be raised pre-validation

## Problem

We needed `chart.json` files with a wrong `schemaVersion` to surface to the
frontend as a dedicated `422 SCHEMA_MISMATCH` so the UI could open a
focused error modal — distinct from generic Pydantic
`ValidationError`s for typos, missing fields, or wrong types.

The naïve approach raises `SchemaVersionError` from a Pydantic
`@model_validator`. Pydantic wraps everything raised inside its
validators in a `ValidationError` — the API exception handler sees only
`pydantic.ValidationError` and can't distinguish "user has a future-version
file" from "user typo'd a field name."

```python
# This DOESN'T do what you'd expect:
class Chart(BaseModel):
    schema_version: int = Field(alias="schemaVersion")

    @model_validator(mode="after")
    def _validate_schema_version(self):
        if self.schema_version != 1:
            raise SchemaVersionError(self.schema_version, 1)
        return self
```

Calling `Chart.model_validate_json(payload)` with a v99 file raises
`pydantic.ValidationError`, not `SchemaVersionError`. The
`isinstance(exc, SchemaVersionError)` check in the FastAPI handler never
fires.

## Investigation

Tried registering a `ValidationError` handler that introspects
`exc.errors()` and looks for the field/message pattern — fragile, breaks
on Pydantic version bumps, mixes concerns.

Tried using `model_validator(mode="before")` — same wrapping behavior
applies, just at a different stage.

Tried catching `ValidationError` and re-raising — works but every caller
of `Chart.model_validate*` becomes responsible for the unwrap, leaks the
concern across the codebase.

## Root cause

Pydantic V2 catches all exceptions raised inside validators and
re-raises them as part of a `ValidationError`. This is by design — it
lets Pydantic accumulate multiple errors per validation pass — but it
means *any* exception subclass you raise from a validator loses its
identity at the public API.

Pydantic only treats its own `PydanticCustomError` specially in error
formatting; arbitrary `ValueError` subclasses do not survive.

## Solution

**Raise schema-version errors *before* invoking Pydantic.** Add a thin
parsing helper that peeks at the JSON structure and raises
`SchemaVersionError` directly if the version doesn't match, then hands
the payload to `Chart.model_validate` for the rest of the validation:

```python
# src/signal_trck/chart_io.py
def parse_chart_json(payload: str) -> Chart:
    """Parse a chart.json string into a ``Chart`` model.

    Schema-version check runs **before** Pydantic so callers get a clean
    ``SchemaVersionError`` rather than the wrapped ``ValidationError``
    that Pydantic's ``model_validator`` would produce.
    """
    raw: Any = json.loads(payload)
    if isinstance(raw, dict):
        version = raw.get("schemaVersion")
        if isinstance(version, int) and version != SCHEMA_VERSION:
            raise SchemaVersionError(version, SCHEMA_VERSION)
    return Chart.model_validate(raw)
```

Keep the Pydantic `@model_validator` as defense-in-depth — it catches
direct `Chart(...)` constructions that bypass `parse_chart_json`. But
the boundary that the API layer relies on is the helper, not the model.

The FastAPI exception handler then maps cleanly:

```python
# src/signal_trck/api/errors.py
@app.exception_handler(SchemaVersionError)
async def _schema_mismatch(_req, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc), "code": "SCHEMA_MISMATCH"},
    )
```

And the import route uses the helper:

```python
# src/signal_trck/api/routes.py
@router.post("/charts/import", response_model=Chart, status_code=201)
async def import_chart(file: UploadFile, store: Store = Depends(get_store)):
    payload = (await file.read()).decode("utf-8")
    chart = chart_io.parse_chart_json(payload)  # raises SchemaVersionError
    await store.create_chart(chart)
    return await store.get_chart(chart.slug)
```

## Prevention

- **Test with the actual exception type:** `pytest.raises(SchemaVersionError)`,
  not `pytest.raises(ValidationError)`. The test was the canary that
  surfaced this.
- **Don't rely on `ValidationError` introspection** for HTTP status mapping —
  it couples the API surface to Pydantic's error format.
- **Prefer pre-validation helpers** for any error class that needs
  distinct API treatment. The model_validator stays as a defense layer
  against direct construction; the helper is the contract.

## Generalization

This pattern applies to any error that needs a distinct HTTP status:

| Error class                     | Where to raise                         |
|----------------------------------|----------------------------------------|
| Schema-version mismatch          | Pre-validation helper                  |
| Required field missing           | Pydantic — generic 422 is fine          |
| Cross-field consistency          | `@model_validator` — generic 422 fine   |
| Permission / business-rule error | Pre-validation OR caller layer         |

**Rule of thumb:** if the API consumer needs to switch on the error
type to render a specific UI, raise pre-Pydantic. If the consumer
treats it as "your input was malformed," let Pydantic wrap it.

## Cross-references

- `plans/feat-phase-b-web-ui-fastapi.md` Decision 24 — schema-version error UX is a modal
- `tests/test_chart_io.py:test_read_rejects_unknown_schema_version` — assertion on the dedicated exception type
- `tests/api/test_routes.py:test_chart_import_422_on_schema_mismatch` — API contract test

## Related code

- `src/signal_trck/chart_schema/models.py:SchemaVersionError` — the exception class
- `src/signal_trck/chart_io.py:parse_chart_json` — the pre-validation helper
- `src/signal_trck/api/errors.py:_schema_mismatch` — the FastAPI handler
