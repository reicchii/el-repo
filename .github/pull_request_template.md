<!--
Title: "<task ID> <what it does>", for example "T12 add visit stacks".
One task per pull request. Rules: AGENTS.md. Review: prompts/3-review.md.
-->

## Task

<!-- Task ID and its acceptance check, quoted from docs/PROJECT-CONTEXT.md section 12. -->

## What changed

## Acceptance check output

```
paste the output here
```

## Lint and tests

```
paste the output here
```

## New dependencies

<!-- Delete this section if there are none. -->

| Package | Reason, in one line | Licence |
|---|---|---|

## Definition of done (AGENTS.md section 7)

- [ ] The acceptance check passes and its output is above
- [ ] Lint and tests pass in the lane
- [ ] Every new interface string follows docs/PROJECT-CONTEXT.md section 5, and every number has a unit and an origin label
- [ ] Loading, empty, partial and error states exist for anything that fetches
- [ ] Every new dependency is listed above with its reason and licence
- [ ] The box in docs/PROJECT-CONTEXT.md section 12 is ticked and docs/ai-log.md has its line
- [ ] Any change to contracts/ has its line in docs/decisions.md and both sides change in this pull request

## Review

<!-- A session on another lane reviews with prompts/3-review.md and ends with "merge" or "do not merge". -->
