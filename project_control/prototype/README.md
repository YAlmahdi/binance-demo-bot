# Futures AI Lab — Bot Development UI Prototype

Offline, read-only **UI DESIGN ONLY**. Every displayed milestone, timestamp, Source SHA, readiness state and verification statement is fictional **MOCK DATA**. Nothing is imported from actual project status, Git, Codex, research or financial evidence.

## Open locally

From the repository root, open `project_control/prototype/index.html` in a browser. The path is relative to the checkout; no machine-specific location is required.

Keep the four HTML/CSS/JavaScript assets together. Requires local JavaScript enabled. Works through `file://`; no server, build system, framework, installation or connection is needed.

Publication of this prototype does not implement the proposed data-integration contract, enable real project inputs or authorize automatic refresh. Optional browser verification must use an explicitly approved, trusted Playwright installation; the verifier does not install dependencies.

## Redesigned interface

The dark, responsive UI prioritizes bot readiness in this order:

1. **Project Health** — six distinct indicators: Engineering, AI/ML, Strategy, Financial Performance, Risk and GitHub/Publication. Each expands into Built/Tested, Missing, Blocked and Evidence Limitations.
2. **Development Roadmap** — compact, initially collapsed milestones distinguish past engineering, current engineering, exploratory research, future validation and eventual trading readiness. Each exposes Built, Tested, Missing, Blocked and Next; nested components disclose individual substeps.
3. **Current Milestone** — references the single active mock milestone; shows Building, Unresolved and Completion Requirements.
4. **Latest Codex Update** — Arabic explanation of the fictional change, its purpose, fictional verification limitations, five separate impact areas and optional technical details.
5. **Next Decision** — exactly one proposed approval-dependent decision. No authorization or operational controls.

A compact freshness area displays **Last Verified Update**, **Source SHA** and **Local / Published State**, all explicitly labeled MOCK. The Source SHA is a non-commit identifier starting with `MOCK-`. Publication is never inferred from engineering tests or roadmap status.

English is used for primary headings, navigation, milestones, state labels and technical terminology. Context and explanation use Arabic with explicit RTL. English headings and technical paths/identifiers use LTR. Native disclosures support keyboard navigation, visible focus, a skip link and reduced-motion preferences.

Activity History, its navigation link, search/filter controls and corresponding fixture entries have been removed. No completion percentages are displayed. Passing software checks does not establish predictive effectiveness, economic profitability or operational safety.

## Display contract v3

`mock-data.js` is the only fixture, recursively frozen as `PROJECT_CONTROL_MOCK`:

```text
schemaVersion: 3
mock: true
freshness: { lastVerifiedUpdate, sourceSha, localState, publishedState, note }
health: [{ category, status, value, description, tested, missing, blocked, limitations }]
roadmap: [{
  id, title, phase, status, description,
  readiness: { built, tested, missing, blocked, next },
  components: [{ title, status, description, steps: [{ title, status, description }] }]
}]
current: { milestoneId, building, unresolved, requirements: [string], limitations }
latest: { title, changed, why, verification, limitations,
          impacts: [{ category, description }], technical: [string] }
decision: { title, status, description, boundary }
```

The validator checks exact object shapes, bounded nonempty text/lists, unique identifiers/categories, all required phase/category groups, valid UTC timestamps and explicit mock identifiers. Every component now has an explicit fictional `status`, visible in its collapsed heading before its optional detail. Component status is provided by the fixture, not inferred from test results or substeps. Current Milestone must reference the only active roadmap entry. Latest verification must begin `MOCK ONLY:`; one decision must have `approval` status. Missing, malformed or internally contradictory display data clears every dynamic panel and shows an error. It does not substitute real project data.

States are contextual: roadmap uses `complete/active/planned/blocked/approval`; substeps use `built/tested/missing/blocked/next`; health uses `built/tested/blocked/not_evaluated/not_cleared/unverified`. Local state is `Local/Unverified`; publication is `Published/Unverified`. All values describe fictional display scenarios only.

`ProjectControlPrototype.validate(data)` and `.render(data)` separate schema validation from presentation, but accept only MOCK v3 data. Real-data integration, provenance handling and refresh require separate approval and are not implemented.

All dynamic text uses `textContent`. Fixture content cannot become HTML or navigation targets. The fixed links navigate within the page only. The page loads only its own assets and makes no service connections, project-file reads, Git queries, storage writes or operational calls. Restrictive CSP blocks connections, remote assets and form actions. Disclosure state resets on reload.

## Focused offline verification

```powershell
node project_control/prototype/verify.cjs
```

Uses Node built-ins and a small DOM double. Covers the revised schema, readiness distinctions, nested disclosures, five fixed navigation targets, literal rendering, invalid-data fail-closed handling, fictional freshness, deterministic rendering and absence of network/persistence dependencies. DOM-double checks do not establish browser or visual correctness.

Optional browser checks use an **already installed** Playwright package and Chrome:

```powershell
node project_control/prototype/verify.cjs --browser "C:\path\to\existing\node_modules\playwright" chrome
```

Omit `chrome` only if Playwright's bundled browser already exists; `msedge` may be used for an installed Edge browser. No browser is installed by the runner. The checks open the local file, block non-file requests, exercise keyboard disclosures and navigation, confirm RTL/LTR directions, test safe rendering/recovery, and check collapsed/expanded layouts at 1440, 1024, 768, 390 and 320px. No screenshots are saved.

## Historical redesign verification — 2026-10-13

- All 16 revised offline check groups passed, including 29 malformed/missing/contradictory cases that clear every dynamic panel.
- Installed Chrome passed local `file://` loading, keyboard health/roadmap/component/impact/technical disclosures, all five navigation anchors, literal-text injection handling, invalid-data recovery and reload reset.
- Computed direction checks passed for English headings, technical values and Arabic explanations. Zero page errors or non-file requests observed.
- Both collapsed and fully expanded layouts had no horizontal page overflow at 1440, 1024, 768, 390 and 320px widths.
- Desktop (1440px) full-page screenshot and mobile screenshots (320px health evidence; 390px nested roadmap and technical detail) visually inspected. Screenshots were not saved as files.
- No verification failures encountered in this redesign task. No installation, browser download or server used. Original prototype results remain historical and are not the verification basis for v2.
- Screen readers, other browser engines, physical mobile devices and other fonts/operating systems were not verified. These UI checks establish no bot, predictive, economic or risk-clearance conclusion.

## Boundaries and limitations

The interface does not inspect actual project evidence, resolve approval/risk questions, validate ML or financial claims, trade, train, evaluate research, authorize tasks or refresh automatically. Its fictional test descriptions are not actual executed receipts. Prototype tests check UI behavior only.

Screen readers, different browser engines, physical mobile devices and other font/OS combinations require separate review. Only the six existing prototype files are in scope; repository policy, status documents and project components are excluded. Nothing is staged, committed or published by this work.

## Final UI polish — 2026-10-13

The section order, dark visual style and display-only behavior are preserved. Arabic explanations now use at least 15px text with more line spacing and brighter contrast. Health cards distinguish the category, status, short explanation and expandable evidence, without a fixed explanation-height spacer. Tablet cards use two columns to give text more room; mobile keeps one column.

Roadmap readiness summaries are shortened into compact labeled rows, retaining Built, Tested, Missing, Blocked and Next. Components are visually nested and show explicit mock status before optional detail. Substeps remain independently labeled. These UI refinements add no progress percentages, real project evidence or operational controls.

**Automated checks executed:** all 17 focused offline groups passed, including 31 malformed/missing/contradictory fixture cases and the new component-status checks. Installed Chrome passed local `file://` loading, keyboard disclosures, navigation, safe rendering, fail-closed recovery, reload reset and RTL/LTR checks. Collapsed and fully expanded layouts had no horizontal page overflow at 320, 390, 768, 1024 and 1440px. Explanation font-size/line-height checks and sampled solid-background health/roadmap text and badge contrast checks (at least 4.5:1) passed at every requested width. No page errors or non-file requests were observed in the successful run. This is not a full accessibility audit.

**Failure and correction:** the first Chrome run failed the explanation-font check at 1440px because older, more specific CSS selectors retained 12px evidence text. The selector precedence was corrected; the complete focused offline and Chrome run then passed. No failure was hidden or treated as a passing result.

**Visual checks:** screenshots inspected at all five requested widths, including desktop health, mobile expanded health evidence and nested roadmap states. Arabic readability, contrast and spacing were inspected separately from automated assertions. No screenshots were saved as files. Screen readers, other browser engines, physical mobile devices and other font/OS combinations remain unverified.

All six existing prototype files were refined; no new files, dependencies or services were created. No project status, research/trading source or protected evidence was read or modified. No staging, commit, push or synchronization was performed. Historical redesign results above are retained as prior evidence only.
