# The baseline: champion version 0

Champion version 0 is the upstream serving engine, unchanged, with the best built-in settings. It has no
author and earns nothing; until a miner beats it by the margin, the miner allocation goes to the owner's UID
and the chain burns it.

| What | Value |
|---|---|
| Engine | `vllm-project/vllm` v0.29.0, commit `98dff2a81d747d1dba01a47f939f48c3526d4206` |
| Model | `Qwen/Qwen3.8-27B-FP8`, revision `017b9c7af6b5689d5dd426a76e0bc077eb5ca20a` |
| GPU | one NVIDIA H100 SXM 80 GB, whole device |
| Settings | [`engine_args.json`](engine_args.json), provisional until the Stage 1 tuning sweep |
| Paths a miner may change | `vllm/v1/core/**`, `vllm/v1/attention/**`, `vllm/v1/kv_offload/**` |

The full profile, including the gates and the replacement rule, is `config/profiles/ramcove-p1@1.0.0.json`
and the `/docs/rules` page of the site.

## Build on the current champion

A challenger is a patch on top of the **current champion's stack**: the baseline plus every champion patch
in its line, oldest first. After the first promotion, the champion's code is public.

```
ramcove-miner champion-code --out champion/     # the champion's patches, numbered, oldest first
baseline/fetch.sh vllm champion/                # vLLM at the pinned commit, with those patches applied
cd vllm && git checkout -b my-change            # make your change inside the allowed paths
git diff > ../patch.diff                        # your patch, relative to the champion's stack
baseline/serve.sh vllm                          # optional: serve it locally with the published settings
```

While version 0 holds the crown, `champion-code` writes no patches and `fetch.sh` gives you the baseline
itself. The same information is available without the tool at `GET /v1/baseline` and each champion's code at
`GET /v1/champions/<version>/artifact` (a `tar.gz` with `manifest.json` and `patch.diff`).

## What this folder is not

It does not contain the vLLM source: `fetch.sh` downloads it at the pinned commit. The measurement workers in
this build do not run it either; they use the labelled simulator until the VM isolation backend exists.
