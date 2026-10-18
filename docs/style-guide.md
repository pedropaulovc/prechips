# Documentation style guide

Write for the person trying to check a machining plan, read its findings, or maintain prechips. Give each page one purpose. Keep executable examples and reference details close to the implementation that defines them.

## Choose the page type

| Page type | Reader's question | Required content | Location |
| --- | --- | --- | --- |
| Overview | What can I do here? | Scope, limits, links by task | `docs/README.md` |
| Quickstart | Can I run it and see a result? | Prerequisites, one supported route, command, expected exit and artifacts, next step | `docs/manual/quickstart.md` |
| Tutorial | How do the pieces work together? | Learning goal, starting files, ordered steps, observations, explanation, completed result | `docs/manual/tutorial.md` |
| Demonstration | What input produces this output? | Named fixture, input excerpts, invocation, observed output excerpts, interpretation and limitations | `docs/manual/demo.md` |
| How-to | How do I finish this task? | Prerequisites, ordered actions, result check, relevant recovery path | `docs/manual/` |
| Troubleshooting | Why did this fail, and what should I do? | Symptom, cause, corrective action, verification | `docs/manual/troubleshooting.md` |
| FAQ | Does the product support this use? | Direct answer, boundary, link to the authoritative detail | `docs/manual/faq.md` |
| Input reference | What does this field mean? | Types, requiredness, defaults, units, constraints, unknown behavior, examples and consumers | Existing input-format pages in `docs/` |
| Rule reference | Why did this finding occur? | Scope, consumed inputs, pass/fail/unresolved conditions, limits and remedy | `docs/rules-*.md` |
| CLI catalog | What does this command accept and return? | Syntax, arguments, options, defaults, precedence, streams, files, exits and errors | `docs/reference/cli.md` |
| Python catalog | What can I import and call? | Support boundary, actual import paths, signatures, parameters, results, exceptions and side effects | `docs/reference/python-api.md` |
| Architecture | Where does this behavior belong? | Data flow, module responsibilities, boundaries and extension points | `docs/internals/architecture.md` |
| Development guide | How do I change and verify the project? | Environment, affected tests, native dependencies, fixtures, package validation and review | `docs/internals/development.md` |
| Internal design | What decision or unfinished work does this describe? | Status, current implementation, rationale, unresolved constraints and links to shipped contracts | `docs/design/` and `docs/module-split.md` |

The manual teaches tasks. The catalogs define interfaces. Architecture explains the implementation. Link between them instead of copying a function list into a tutorial or a tutorial into every reference page. Existing input and rule filenames remain in place so incoming links keep working; their navigation category is reference.

Do not add every page type as a heading on every page. A field catalog does not need an FAQ, and a quickstart does not need an architecture section. Split a page when its reader or task changes.

## Start with the outcome

Use one sentence-case H1. State the task or contract in the first paragraph. A prerequisite must appear before the step that needs it. Link to unfamiliar terms when the reader first needs them.

For a quickstart, use this order:

1. State what the reader will produce.
2. List the required environment and starting directory.
3. Give the installation and execution commands.
4. Show the expected exit, output files and a small recognizable result.
5. Explain the next action, including what an unresolved finding means.

Keep alternative installations and the complete option list in linked reference pages. A tutorial can use several stages; each stage should end with something the reader can inspect.

For a how-to, start the title with the action: "List measurement debt" or "Inspect a saved finding." Use numbered steps when order matters. Put the location or condition before the action. End with a result check, not a congratulatory sentence.

For troubleshooting, use a symptom the reader can recognize as the heading. State the likely cause only as strongly as the code or observed error supports. Give a specific supported action and explain how to confirm recovery. Do not recommend deleting inputs, bypassing stops, marking unmeasured facts as measured, or approving a report to hide debt.

## Write reference pages as contracts

### Input formats

Name the file's role and how paths resolve. Separate required fields from optional fields and explain omitted, empty and `"unknown"` values where they differ. Include units in field names or descriptions. State which rule consumes a field and what happens when the fact is missing.

Tables work for short field definitions. Use prose for dependencies, precedence and safety constraints. An example is either a complete valid document or an explicitly labeled fragment with its required context. Preserve supported enum spellings, precision, citations and identity rules.

### Rules

Retain the exact rule identifier in the section heading or an explicit anchor. For each rule, explain:

- Which operations, setups or features it evaluates, including exemptions.
- Which authored or kernel facts it consumes.
- What produces a pass, an error or unresolved debt, and any relevant warning or unsupported result.
- Which measurements or corrections can resolve the finding.
- What the rule cannot establish.

Keep equations and boundary cases where they affect the verdict. Do not replace a conservative sampled-geometry limitation with a claim of collision-free machining.

### CLI and Python catalogs

Describe the installed CLI independently of repository development commands. Include positional arguments, accepted flags, defaults, path bases, environment fallback and output behavior. Record nonzero exits that still produce usable output.

For Python, distinguish an importable implementation function from a promised public SDK. Document actual signatures and return types; do not invent a root export, wrapper or stability guarantee. Put the workflow in the manual and the callable details in the catalog. Do not list every private helper as a supported interface.

## Use plain technical prose

Address the reader as "you" when giving instructions. Use active verbs and concrete nouns. Keep shop-facing language understandable to a machinist; reserve developer terms for contributor documentation. The CLI command remains `traveler`; explanatory prose can call its printable output a setup sheet.

Use sentence-case headings and descriptive links. Format identifiers, paths, literal values, commands and environment variables as code. Use bold only when it helps identify a visible UI control or a genuine warning. Do not give every list item a bold label.

Cut greetings, staged introductions, repeated headings, slogan-like closers and unsupported claims of importance. Keep contrasts that explain a real distinction, such as an authored example value versus a physical measurement. Avoid em dashes and en dashes in prose. Punctuation inside code, commands, quotations and URLs stays intact.

A short sentence is useful when it adds a fact. A list of three is useful when there are three distinct items. Neither is a required rhythm. Apply the humanizer review to the whole paragraph, not only to isolated words.

## Make examples reproducible

Use existing shipped bundles for demonstrations. Name the plan and any override files, the working directory, required Python/native dependencies, the command and the output directory. State which shell a shell-specific command uses. Prefer commands that work unchanged from the repository root; use `uv` for Python environments and execution.

Show input and output together. Quote actual input bytes or clearly label a shortened excerpt. Quote actual output from the documented command; identify variable fields instead of inventing a stable transcript. A selected JSON excerpt must say what was omitted. Preserve Unicode finding symbols when quoting output.

Record exit codes explicitly. A valid demonstration can exit 2 or 4. Explain why that is expected and which artifacts still exist. Do not alter a plan, policy, assertion or example measurement to manufacture exit 0.

The files under `examples/` contain demonstration values. Preserve their disclosure and the real measurement metadata identified in the repository rules. A fixture that exercises the measured branch does not establish a physical shop measurement. Unknown means unresolved, never zero or approval.

Keep source citations beside the facts they support. Do not invent tolerances, cutting values, STEP identities, drawing revisions, source pages or acceptance evidence. Runtime examples must not load expected outputs as answers. A copied expected artifact may illustrate a format only when identified as such.

## Keep current behavior separate from history

The implementation and its behavior tests define the shipped interface. A design proposal or old delivery note does not override them. Mark internal designs as implemented, partly implemented or proposed, with an explanation of the remaining work. Avoid a bare "complete" when physical or live acceptance is still pending.

Keep one owner for each current contract. Link to example provenance in `examples/README.md`, delivery status in `PLAN.md`, output semantics in the report reference and function behavior in the API catalog. Remove chronological review narration from current reference prose after retaining its unique constraints. Git and linked issues retain the history.

Local tests, rendered PDFs and generated reports do not establish physical paper acceptance, first-article machining or live farm telemetry acceptance. State those limits where they change how a result should be used.

## Maintain navigation and links

Add each page to the documentation hub and link it from the relevant task or reference page. Use relative Markdown links for repository pages, except in the packaged root README: use absolute GitHub URLs there so navigation also works from PyPI and copied descriptions. See [PyPA's README guidance](https://packaging.python.org/en/latest/guides/making-a-pypi-friendly-readme/) for the package-description renderer and supported formats. Prefer descriptive link text over "click here."

Preserve meaningful incoming anchors when rewriting. If a heading changes its slug, update incoming links in the repository or retain an explicit anchor. Check local file and fragment targets after the rewrite. Do not move a large reference merely to make the folder tree look uniform.

Link to the module that currently owns a behavior. A deleted monolith or historical re-export is not a current source reference. Source line numbers are evidence for a review; ordinary user guidance should usually link to a stable module or section.

## Verify before publishing

Run documented commands and inspect their results. Exercise the Python example if the catalog includes one. Check local links, heading fragments, fences and example syntax. Use the affected-test selector and Ruff after the writers finish; a documentation-only selection is not a full-suite pass.

If prose changes an executable command or example, record the implementation evidence and observed result in the PR. Preserve code and data during purely editorial changes. If correcting a factual example requires changing code or fixture data, treat that as a separate reviewed change.

A reviewer should check technical accuracy, omitted boundary conditions, navigability and prose separately. Review every rewritten page. An automated link check proves target existence, not the truth of the linked claim. Keep detailed audit logs outside the user manual.

## Sources and adaptation

These sources informed the structure and review process:

| Source | Practice used here |
| --- | --- |
| [Microsoft: Writing step-by-step instructions](https://learn.microsoft.com/en-us/style-guide/procedures-instructions/writing-step-by-step-instructions) | Task headings, numbered ordered actions, imperative verbs, location before action and no repeated introduction. |
| [Microsoft: Quickstart using the Power Apps CLI](https://learn.microsoft.com/en-us/power-apps/developer/code-apps/how-to/create-an-app-from-scratch) | Prerequisites, a runnable sequence, observable results and a separate command-reference link. |
| [Microsoft: Azure for Python developers](https://learn.microsoft.com/en-us/azure/developer/python/) | A task-based landing page with distinct getting-started, tutorial and library sections. |
| [Tech Leads Club: docs-writer skill](https://agent-skills.techleads.club/skills/docs-writer/) | Read the implementation first, follow a project style guide and check incoming links. |
| [docs.page: review-doc skill](https://github.com/invertase/docs.page/blob/ef1a1fac22466f3883b1984ca466b9786a0234f0/skills/review-doc/SKILL.md) | Separate writing checks, explicit coverage and coordinated heading/link changes. Its MDX-specific formatting is not required here. |
| [Mem0 CLI agent skill](https://github.com/mem0ai/mem0/blob/0724291bd864cf807e88ee8981c8226644e8fb42/skills/mem0-cli/README.md) | Separate command catalog, configuration and workflows for a Python/Node CLI. Its installation commands and service assumptions do not apply to prechips. |
| [Sphinx documentation skill](https://github.com/a5c-ai/babysitter/blob/feb68abe397acc14f32b34984975c48fedba2b33/library/specializations/technical-documentation/skills/sphinx-docs/README.md) | Keep Python callable documentation tied to signatures and docstrings. This rewrite retains Markdown and adds no Sphinx dependency. |

External agent skills are research sources, not instructions to install or run third-party code. Apply their useful writing practices within this repository's offline, provenance and validation requirements.
