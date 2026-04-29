---
status: complete
priority: p2
issue_id: 006
tags: [code-review, types, llm]
dependencies: []
---

# `_AnthropicClient._client: object` throws away the type system

## Problem Statement

Both LLM client wrappers (`_AnthropicClient`, `_OpenAICompatClient`) have
an internal `_client: object` field with `# type: ignore[attr-defined]`
on every method call. This is the dataclass equivalent of `Any` — we've
disabled type checking at the only point where it would catch a
provider-API mismatch.

## Findings

From Kieran-Python review, Major M1.

**`src/signal_trck/llm/client.py:72,83,100,111`:** four `# type: ignore`
comments, all because `_client: object` doesn't tell mypy what it is.

```python
@dataclass
class _AnthropicClient:
    provider: Provider
    model: str
    _client: object  # ← Any-equivalent
    
    def analyze(self, ...) -> T:
        result = self._client.messages.create(  # type: ignore[attr-defined]
            ...
        )
        return result
```

## Proposed Solutions

**Option A — Type the field as `instructor.Instructor`**
```python
import instructor
@dataclass
class _AnthropicClient:
    _client: instructor.Instructor
```
- Pros: Removes all 4 `# type: ignore`s.
- Cons: Tightly couples to instructor's public type.
- Effort: Small.
- Risk: Low — `instructor.Instructor` is a stable public type.

**Option B — Define a Protocol matching the methods we use**
```python
class _InstructorMessages(Protocol):
    def create(self, *, model, max_tokens, temperature, response_model,
               system, messages) -> Any: ...

class _AnthropicInstructor(Protocol):
    messages: _InstructorMessages
```
- Pros: Decouples from instructor's exact type. Documents what we use.
- Cons: ~15 LOC of Protocol definitions.
- Effort: Small-Medium.
- Risk: Low.

## Recommended Action

**Option A** unless instructor's type proves unstable across versions.
Faster, less code, and `instructor` is a pinned dependency.

## Technical Details

**Affected files:** `src/signal_trck/llm/client.py`

**No tests need changes** — type-only fix. But adding a quick mypy run
to CI would catch regressions.

## Acceptance Criteria

- [ ] `_AnthropicClient._client` typed as `instructor.Instructor` (or
      similar concrete type).
- [ ] `_OpenAICompatClient._client` similarly typed.
- [ ] All four `# type: ignore[attr-defined]` comments removed.
- [ ] All 134 existing tests pass.
- [ ] If/when mypy is added: clean.

## Work Log

_Empty — not yet started._

## Resources

- Kieran-Python review: Major M1
- [instructor public API](https://github.com/instructor-ai/instructor)
