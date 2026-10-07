# Tattler reasoning-surface results — 2026-10-07

Status: RUNTIME INTEGRATION EVIDENCE / NO PROVIDER PROMOTION

## Shared experiment result

On 2026-10-07, the same repository stress-test prompt was run through three ChatGPT surfaces while WorkLaptop was instrumented with Tattler plus a companion Codex process/network tracer.

Observed controlled windows:

- Desktop Chat, GPT-5.6 Sol High: **0 MXC launches** and **2 new established Codex TLS connections** in the companion tracer.
- ChatGPT Desktop Work, Ultra: **59 MXC launches** and **73 new established Codex TLS connections** using the same companion-tracer definitions.
- Firefox cloud Work, Max: browser-side traffic was observable locally, but the provider's server-side worker topology was not.

The bounded conclusion is that Desktop Work used materially different local orchestration from ordinary High Chat in this runtime. It does **not** establish that sockets or MXC processes equal agents, that connection fanout grants a reasoning tier, or that a client can promote High into Ultra/Max by imitating transport behavior.

Canonical detailed evidence is being preserved in `thebrazenbeard/tattler` PR #7 and the reasoning interpretation in `thebrazenbeard/rezon` PR #103.


## Why vera-mono needs this result

vera-mono contains the absorbed reasoning kernel and the host-composed Vera runtime. External model/provider APIs remain legitimate external execution dependencies, so this experiment directly informs the provider-adapter boundary.

The runtime should treat:
- selected provider/model/surface as explicit adapter metadata;
- reasoning requirements as Rezon/runtime policy;
- Tattler process/network data as diagnostic evidence only.

```text
observed MXC/socket fanout != provider identity
provider identity != authority
reasoning label != Vera identity
stronger worker != automatic final authority
```

## Integration consequence

If vera-mono later adds an adapter for a supported high-reasoning Work surface, it should consume a bounded request and return a structured receipt. The originating Vera runtime remains the coordinator and authority holder.

The experiment does not justify implementing an undocumented Ultra/Max connector or changing provider routing based on transport signatures.
