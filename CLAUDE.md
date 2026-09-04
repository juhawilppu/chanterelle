# Project instructions

## Commit messages

This repo uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary>
```

Common types here:

- `feat` — a new capability (e.g. a new scoring factor, a new output format)
- `fix` — correcting a bug in the scoring or map generation
- `data` — changes related to source data (refreshing a download, adding a dataset)
- `docs` — README/comments only
- `refactor` — code restructuring with no behavior change
- `chore` — tooling, dependencies, `.gitignore`, etc.

Scope is optional and usually the script or area affected, e.g.
`fix(scoring): correct esker buffer distance` or `data: refresh Karkkila stand download`.
Keep the summary imperative and under ~72 characters; add a body paragraph
below a blank line when the "why" needs more explanation.
