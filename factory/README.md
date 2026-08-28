# Software Factory V1

Windows-first, cross-platform software-development factory using Herdr + Moshi as the human control plane and Orca as the execution/orchestration plane.

## Design rules

1. Orca owns job state, dependencies, retries and Git worktrees.
2. Herdr owns interactive agent panes only. A Herdr restart must not lose an Orca run.
3. Moshi is the remote/mobile operator surface.
4. Agents never write directly to the protected default branch.
5. Every implementation task runs in an isolated Git worktree/branch.
6. Merge eligibility is determined by deterministic quality gates, not by a single agent opinion.
7. Configuration and prompts are OS-neutral. Only bootstrap/runtime adapters are platform-specific.

## V1 flow

```text
Operator
  -> Moshi / Herdr
  -> Commander
  -> Orca MCP
  -> isolated worker runs
       -> implementation
       -> tests
       -> review
  -> candidate PR
```

V1 deliberately stops at PR creation. Production deployment, autonomous remediation and continuous monitoring are later phases.

## Layout

```text
factory/
  config/
    factory.yaml
  prompts/
    commander.md
    reviewer.md
    tester.md
  scripts/
    windows/
      bootstrap.ps1
      health.ps1
      start.ps1
```

## Windows requirements

- Windows 11 or Windows Server with PowerShell 7 recommended
- Git
- GitHub CLI (`gh`) recommended
- Orca CLI
- Herdr Windows preview
- At least one coding-agent CLI (Codex, Claude Code, OpenCode, etc.)

WSL2 is optional and is not part of the V1 runtime contract.

## Safety boundary

The default branch is read-only to worker agents. Workers may commit only to their assigned worktree branch. A release/merge role may propose a PR only after required checks pass.

## First milestone

Prove one complete job can move from request -> decomposition -> isolated worktree -> implementation -> tests -> review -> PR without manual shell choreography.
