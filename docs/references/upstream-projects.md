# Upstream Projects and Tools

Status: current

References provide comparison evidence and implementation ideas. They do not
override local code, contracts, domain language, accepted ADRs, or licensing
requirements.

## Reference catalogue

| Reference | Use it for | Do not infer from it |
| --- | --- | --- |
| [`basketikun/chatgpt2api`](https://github.com/basketikun/chatgpt2api) | Upstream ChatGPT Web protocol behavior, project ancestry, and deployment comparison | That a route, option, storage layout, or failure behavior still exists locally |
| [`basketikun/infinite-canvas`](https://github.com/basketikun/infinite-canvas) | Concise contributor guidance, documentation indexing, and explicit separation of implementation from pending verification | That its product boundaries, frontend architecture, task lifecycle, or release process applies here |
| [`colbymchenry/codegraph`](https://github.com/colbymchenry/codegraph) | Symbol lookup, caller/callee discovery, route indexing, and change-impact exploration | That a generated edge establishes domain ownership or that every dynamic dependency was found |
| [`DietrichGebert/ponytail`](https://github.com/DietrichGebert/ponytail) | A minimum-solution ladder and focused over-engineering review prompts | That its benchmark savings apply locally, or that shorter code permits removing validation, safety, accessibility, ownership, or lifecycle boundaries |
| [`yukkcat/nanocat-ui`](https://github.com/yukkcat/nanocat-ui) | Generic Vue controls, overlays, tokens, focus behavior, and interaction primitives consumed as an npm dependency | That product pages, domain workflows, charts, or responsive composition belong in the UI package |

## Reference workflow

1. State the local question and identify its current owner in code,
   [`../../CONTEXT.md`](../../CONTEXT.md), and accepted ADRs.
2. Inspect the smallest relevant upstream implementation or document. Record
   the exact behavior being compared, not a general claim that one project is
   "better".
3. Verify the proposed behavior against local contracts, persistence,
   concurrency, security, and UI ownership.
4. Adopt a pattern only when it fits the local boundary. Attribute copied or
   adapted code as required by its license.
5. Document a durable local decision in an ADR; do not turn the reference URL
   itself into the decision.

## CodeGraph workflow

The repository may be indexed locally with CodeGraph:

```powershell
codegraph status
codegraph query <symbol>
codegraph callers <symbol>
codegraph callees <symbol>
git diff --name-only | codegraph affected --stdin
```

Generated `.codegraph/` state is ignored. Before changing a boundary, confirm
query results by reading the referenced implementation, public contracts, and
tests. Dynamic imports, string-based dispatch, persistence coupling, and
business ownership still require manual verification.
