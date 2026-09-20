---
name: contract-capsule
description: Use the ContractCapsule MCP gateway to discover, compile, inspect, and safely activate evidence-grounded views.
---

# ContractCapsule

Use the MCP gateway for all live capsule data and authorization decisions.

- Discover candidates with `discover_capsules`.
- Compile a task-scoped view with `compile_view`.
- Expand evidence only through `expand_evidence` after checking the returned
  handle and current permission.
- Compare candidates with `compare_capsules` before requesting activation.
- Use `activate_capsule` and `rollback_capsule` only with the returned receipt
  and safe boundary; never set an active pointer directly.

The Skill contains no capsule payloads or approval keys. High-risk tool calls
must carry a current view/contract receipt and pass the repository pre-tool
hook; a denial is final for that action.
