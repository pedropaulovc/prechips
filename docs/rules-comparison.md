# Construction and stock-form comparison

M2 implements the authored-candidate comparison in PLAN §4.5, lines 573–577.
It lists alternatives; it does not select a winner, invent stock on hand, estimate
net part volume from feature geometry, or certify a fixture's measured clearance.

## `construction`

Subject: the plan's part name. Evidence contains `plan_construction` and
`drawing_construction`, with PLAN §4.5 and the manifest's construction citations.
The candidate must explicitly declare `construction = "one_piece"`,
`"built_up"`, or `"unknown"`; omission remains unknown, never one-piece.

The construction-permission rule has one prerequisite: the drawing manifest
must explicitly declare `construction = "built_up_permitted"`, carried from a
drawing-side permission note. Missing permission is not permission. Without the
explicit value, the drawing permits one-piece construction only. Passing this
permission rule does not prove a physical assembly: every `stock_in` array also
requires the declared joint and prepared geometry described in
[the plan format](plan.md) and [geometry rules](rules-geometry.md).

- A built-up candidate passes only when the manifest explicitly declares
  `construction = "built_up_permitted"`.
- Any other manifest value refuses a built-up candidate. That includes
  `"one_piece"`, any other string, `"unknown"`, blank, or an omitted key. The
  refusal is an `error` whose entire sentence is
  **`drawing permits one-piece only`**.
- A one-piece candidate needs no permission, so it passes whatever the manifest
  says, including unknown or omitted.
- Only unknown or omitted candidate construction gives `unknown` (`?`).

The rule participates in the same evaluator, required-policy selectors and
error-before-required-unknown exit gate as every other rule. It applies to
`check` and `traveler`, not just `compare`; a comparison cannot waive it.

## `prechips compare PLAN [PLAN ...]`

Every plan is independently loaded, validated, evaluated and bound to its own
operative inputs. Candidates may have the same part name. `plan` identifies each
row by its plan-file path relative to the common directory of the candidates;
input order is retained. Cross-volume Windows paths have no common relative
root and are displayed as normalized absolute paths instead.

Both the terminal table and canonical `compare.json` show setup counts, required
fixture identities, waste ratio and findings. The terminal adds a rule/subject
matrix with one column per candidate and the full message in each cell. It uses
the existing finding markers: `✗` for errors, `!` for warnings, and `?` for unknown
or unsupported findings. Other messages remain plain; `—` denotes a finding not
present in that candidate. A refused built-up column reads
`✗ drawing permits one-piece only`.
JSON preserves complete `rule_findings` including numeric evidence, messages and
citations, alongside the existing `findings` status counts and candidate `exit`.
`inputs` preserves each candidate's source-path/digest records. This is a
comparison summary, not an approval artifact.

Required fixtures are the union of the authored holds: primary fixture,
parallels, singular support, support-list strings and `{ref = ...}` records,
riser, and `hold.index.fixture` (including a machine inventory identity such as
`BS-0`). Existing selected-reference conventions also retain named clamps;
clamp, stop, locator and jaw-protection values that resolve to inventory fixtures
are included even when their names do not use the selected-reference spelling.
Explicit `none` and `not_applicable` are not fixtures. Unknown primary fixtures
or explicitly unknown support/index references remain unknown; missing optional
supports are not invented. Each identity is the `(category, key)` the reference
selects, so two spellings of one item list it once. It lists by key alone,
unless another listed item has the same key in another category (a
`holders.holder` collet and a `fixtures.holder` plate); then each prints as
`category.key`. The list is sorted, without claiming presence or measurement:
the normal rule findings decide those facts.

## Volume arithmetic and numerical provenance

Stock volumes describe solid authored blanks, in cubic millimetres:

- `form = "round_bar"` (or `"round"`): `π × dia_mm² × length_mm / 4`.
- `form = "flat_bar"`, `"rectangular_bar"`, `"rectangular_blank"`,
  `"prepared_blank"`, `"square_bar"`, or `"rectangular"`: the two authored
  `section_mm` dimensions multiplied by `length_mm`. A square still needs both
  dimensions; no width is copied or guessed.
- An authored nonempty `stock.components` list replaces the enclosing stock's
  dimensions for this calculation. Each leaf uses the same formulas; component
  volumes are summed once. An unknown component makes the total unknown.

Unrecognized/unknown forms, missing dimensions, unknown dimensions, or explicit
`components = "unknown"` cannot produce a stock volume. No rectangular section
is inferred from a round diameter or vice versa. Each component's serialized
volume evidence cites its precise plan fields, plus its authored `cite` when
provided; the enclosing stock's `cite` is also preserved. These are the author's
candidate blank dimensions, not a claim of measured stock or actual inventory.

Net volume requires **both** a numeric `features.volume_mm3` and a nonempty
`features.volume_cite` string/list naming its source. Empty/whitespace-only or
`"unknown"` citations do not supply a source. An uncited number is not promoted
to a sourced net volume. `volume_mm3` is explicitly mm³ even when the manifest's
other dimensions use a different unit. There is no geometric net-volume fallback.

The dimensionless waste ratio is exactly:

```text
(stock_volume_mm3 - net_volume_mm3) / stock_volume_mm3
```

It is not stock/net, net/stock, or a percentage. Equality gives zero waste;
explicitly sourced zero net volume gives ratio one. JSON retains unrounded
`stock_volume_mm3`, `net_volume_mm3` and `waste_ratio`, plus `volume_evidence`
(component dimensions/volumes/citations, net citations and formula) and row
`cite`. The terminal rounds only the ratio's display to six significant digits.
Missing/unsourced inputs yield literal `"unknown"` in JSON and `?` on screen.

Every authored known `dia_mm`, `length_mm` and `section_mm` entry must be finite
and positive; an authored section list must contain two dimensions. This applies
even to unknown forms, extra dimensions unused by the selected shape, and the
enclosing stock when components supply its volume. Explicit unknown dimensions
remain unknown and never provide a fallback. An empty component list,
negative/nonfinite net volume, nonfinite or underflowed-zero stock-volume
arithmetic, or a sourced net volume
larger than known stock volume is bad input (exit 3), not a clamped result.
Net greater than stock is checked only when both usable volumes are known.

## Determinism, safety and exits

JSON uses the shared canonical serialization (sorted keys, finite numeric
values, UTF-8, LF). The same ordered candidates and source bytes produce identical
`compare.json`; telemetry does not alter it. All candidates and their volume
arithmetic are resolved before any output is replaced. The shared output guard
checks **every** candidate's input paths, including non-first candidates;
collisions, escaping output symlinks, filesystem refusals and invalid inputs
leave prior inputs/outputs intact.

Exit precedence remains **3 > 2 > 4 > 0**: any invalid candidate/input/output
prevents comparison writes (3); otherwise any rule error wins (2), then any
candidate with a required unresolved finding (4), otherwise 0. Waste is an
informational comparison metric, not an additional shop-required rule: an
unknown waste ratio by itself does not change a candidate's readiness exit.
