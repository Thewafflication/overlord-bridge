# WSP adoption and upgrade impact

**Content type:** Project adoption baseline and planned integration record
**Project:** Overlord Bridge
**Date:** 2026-10-10
**Pinned release:** WSP 1.4.0
**Pinned commit:** `f009399dd1406219571ac978bfee85e85bbdfeac`
**Submodule:** `wsp/`
**Authorization:** Owner requested moving WSP to the latest release.
**Integration status:** Baseline upgraded; full conformance is not claimed.

The GitHub latest-release API reported 1.4.0 on 2026-10-10. The annotated tag
resolves to the commit above. Previously the project pinned
`1592880d0db6ace5919fc578f3f6070251e6fb34` beyond release 1.1.0.

## Upgrade impact

1.2.0 adds UX and information-for-users profiles, native hardening, static
analysis, improved documentation verification, and upstream-workaround records.
1.3.0 adds native logging byte sinks. 1.4.0 adds source/language styles and
reproducible pre-commit and independent CI gates.

Overlord's Python, PowerShell, YAML/JSON, Telegram interface, Windows console,
provider execution, and packaging need applicability review. Native C/C++,
CMake, and logging requirements apply only where project-owned native artifacts
exist; using a Python dependency does not establish that applicability.

## Integration work allocated to OVL-M02 WP1

- Inventory all common and selected-profile requirements individually.
- Record applicable, tailored, not applicable, or deferred dispositions with
  rationale, owner, completion condition, and review references.
- Select UX, information for users, security/DFS, language/style, and common
  tools profiles as appropriate after reviewing the released requirements.
- Connect project requirements, tests, results, and retained verification reports.
- Add reproducible project checks, pre-commit integration, and independent CI.
- Add design, security, review, release-readiness, and closeout records.
- Validate the documentation toolchain and define which release PDFs are shipped.

This record identifies the new baseline and upgrade work. It is not the completed
requirement disposition matrix or a declaration that existing code satisfies
WSP 1.4.0. The planned integration remains a required increment gate.

## Baseline history

| Date | Baseline | Change |
| --- | --- | --- |
| 2026-10-10 | 1.4.0 / `f009399` | Pin release; plan OVL-M02 integration |

See [the increment plan](plans/next-increment.md) and
[the WSP release](https://github.com/Thewafflication/wsp/releases/tag/1.4.0).

## Controlled review inventory

[The numbered requirement inventory](wsp-inventory.json) records all 258 numbered requirements in the pinned baseline, including profiles awaiting applicability review. Each entry records its source, normalized-text SHA-256, title, owner, rationale, and completion condition. Every review remains pending; this is neither an approved deferral nor a conformance result. The common/profile disposition review and release gate remain open. Canonical lint rejects omitted, duplicated or changed requirements and mismatches between the controlled commit, checked-out submodule and Git index gitlink. Hosted checks initialize the pinned submodule and apply the same validation.
