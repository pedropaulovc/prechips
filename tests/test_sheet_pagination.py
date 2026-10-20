"""Continuous traveler pagination, exercised in Chromium and on physical PDF pages."""

from __future__ import annotations

import json

import pytest
from test_sheet_ops import printed_sheet as printed_sheet
from test_sheet_print import LABEL, printed_pages

from prechips._sheet_pagination import JOB_PRINT_JS
from prechips.sheet import _CSS, _writing_field

PART = "Ownership boundary part"
JOB_TITLE = "Human-readable boundary job"
DRAWING = "Ownership drawing 204"
SETUP_ONE = "S1 first hold"
SETUP_TWO = "S2 second hold"
IMAGE = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "width='240'%20height='120'%20viewBox='0%200%20240%20120'%3E"
    "%3Cpath%20d='M20%2020H220V100H20Z%20M120%2020V100'%20"
    "fill='none'%20stroke='black'/%3E%3C/svg%3E"
)


def _job(source, *, detail="hobby", after_load=""):
    """Use production styles/script with one job, never one section per setup."""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{_CSS}</style><script>{JOB_PRINT_JS}</script></head>"
        f'<body data-detail="{detail}"><section class="page" data-sheet="job" '
        f'data-job-title="{JOB_TITLE}" data-part="{PART}" data-drawing="{DRAWING}" '
        'data-revision="C" '
        'data-example-only="true" data-continuation-label="EXAMPLE ONLY">'
        f'<div class="meta"><span>{PART}</span><span>{DRAWING} · rev C</span></div>'
        '<div class="banner">EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT · PLANNED</div>'
        f"{source}</section>"
        + (
            f"<script>addEventListener('load', () => {{{after_load}}});</script>"
            if after_load
            else ""
        )
        + "</body></html>"
    )


def _setup(title, setup_id, workpiece, body):
    return (
        f'<div class="setup" data-setup-title="{title}" data-setup-id="{setup_id}" '
        f'data-workpiece="{workpiece}"><h2>{title}</h2>{body}</div>'
    )


def _short_setups():
    return _setup(SETUP_ONE, "S1", "nut1", "<p>FIRST-HOLD-WORK: face to 12.700 mm.</p>") + _setup(
        SETUP_TWO, "S2", "nut2", "<p>SECOND-HOLD-WORK: drill to 7.938 mm.</p>"
    )


def _words(prefix, count):
    return " ".join(f"{prefix}{index:04d}" for index in range(count))


def _positioned_words(prefix, count):
    return " ".join(
        f'<span data-source-position="{prefix}{index:04d}">{prefix}{index:04d}</span>'
        for index in range(count)
    )


_OWNER_SOURCE_POSITIONS = r"""pageOf => {
  const section = document.querySelector('section.page');
  const original = node => !node.closest(
    '[data-job-print],.record-continuation,.fixed-locator-reference');
  const positions = [...section.querySelectorAll('[data-source-position]')];
  return {
    positions: positions.filter(original).map(node => ({
      key: node.dataset.sourcePosition, text: node.textContent, page: pageOf(node),
      setup: node.closest('[data-setup-id]').dataset.setupId
    })),
    copiedPositions: positions.filter(node => !original(node)).length,
    headings: [...section.querySelectorAll('[data-original-heading]')].filter(original)
      .map(node => ({key: node.dataset.originalHeading, text: node.textContent,
        page: pageOf(node), visible: node.getClientRects().length > 0
          && getComputedStyle(node).visibility === 'visible'})),
    heads: [...section.querySelectorAll('.cont-head')].map(head => ({
      page: pageOf(head), setup: head.dataset.setupId, member: head.dataset.member ?? '',
      workpiece: head.dataset.workpiece ?? '',
      title: head.querySelector('.cont-title').textContent,
      context: head.querySelector('.cont-context')?.textContent ?? '',
      copiedDestinations: head.querySelectorAll('[data-locator-target],.writing-blank').length
    })),
    fields: [...section.querySelectorAll('[data-locator-target]')].map(blank => ({
      label: blank.closest('.field').querySelector('.field-label').textContent,
      setup: blank.closest('[data-setup-id]').dataset.setupId,
      member: blank.closest('[data-member]')?.dataset.member ?? '',
      workpiece: blank.closest('[data-workpiece]').dataset.workpiece,
      page: pageOf(blank), original: original(blank)
    }))
  };
}"""


def _nested_work():
    inspection = (
        '<ol><li data-page-context="S2 op 20 inspection" data-op-id="20">'
        '<h3 class="page-context"><span data-title-source="S2-inspection">'
        "S2 op 20 inspection — opposite-face size</span></h3>"
        f"<p>{_words('InspectBefore', 450)}</p>"
        '<figure class="fixture-render"><figcaption>Original inspection diagram</figcaption>'
        f'<img src="{IMAGE}" width="240" height="120" '
        'style="display:block;width:240px;height:120px" alt="Original datum diagram"></figure>'
        f"<p>{_words('InspectAfter', 450)} "
        + _writing_field("opposite-face observed")
        + "</p></li></ol>"
    )
    rows = "".join(
        f'<tbody><tr><td>MOVE{index:03d}</td><td class="num">{index}.125</td>'
        f'<td class="num">{index}.250</td></tr></tbody>'
        for index in range(72)
    )
    contour = (
        '<div class="contour" data-page-context="S2 op 30 contour" data-op-id="30">'
        '<h3 class="page-context"><span data-title-source="S2-contour">'
        "S2 op 30 contour — outside path</span></h3>"
        '<p class="contour-context">Follow the complete XY path at each specified depth.</p>'
        '<p class="path-progress">'
        + _writing_field("level")
        + _writing_field("last completed #")
        + '</p><table class="coords"><thead><tr class="repeat"><th colspan="3">'
        '<span data-title-repeat="S2-contour">S2 op 30 contour — outside path</span> · '
        "<span data-continuation-locator>Use the original progress fields</span>"
        "</th></tr><tr><th>#</th><th>X</th><th>Y</th></tr></thead>" + rows + "</table></div>"
    )
    return _setup(
        SETUP_ONE, "S1", "nut1", "<p>FIRST-HOLD-WORK remains before the second hold.</p>"
    ) + _setup(SETUP_TWO, "S2", "nut2", inspection + contour)


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_two_short_setups_share_one_physical_page(tmp_path, detail):
    pages = printed_pages(_job(_short_setups(), detail=detail), tmp_path)
    assert len(pages) == 1
    assert "FIRST-HOLD-WORK" in pages[0] and "SECOND-HOLD-WORK" in pages[0]
    assert SETUP_ONE in pages[0] and SETUP_TWO in pages[0]
    assert "PRINT LAYOUT ERROR" not in pages[0]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_second_setup_nested_continuations_keep_setup_member_and_inner_owner(printed_sheet, detail):
    source = _nested_work()
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page[data-sheet="job"]');
          const own = section.cloneNode(true);
          own.querySelectorAll('[data-job-print],.record-continuation,.fixed-locator-reference')
            .forEach(node => node.remove());
          const targets = [...section.querySelectorAll('[data-locator-target]')];
          const starts = [section.getBoundingClientRect().top,
            ...[...section.querySelectorAll('.cont-head')]
              .map(node => node.getBoundingClientRect().top)];
          const cap = Number(document.documentElement.dataset.pageCapacity);
          const inside = node => {
            const rect = node.getBoundingClientRect(), page = pageOf(node);
            return rect.top >= starts[page]-.1 && rect.bottom <= starts[page]+cap+.1;
          };
          return {
            jobs: document.querySelectorAll('section.page[data-sheet]').length,
            pages: Number(section.dataset.pages),
            words: own.textContent.match(/Inspect(?:Before|After)\d{4}/g),
            moves: own.textContent.match(/MOVE\d{3}/g),
            heads: [...section.querySelectorAll('.cont-head')].map(head => ({
              title: head.querySelector('.cont-title').textContent,
              setup: head.dataset.setupId, workpiece: head.dataset.workpiece,
              inner: head.dataset.pageContext,
              context: head.querySelector('.cont-context')?.textContent ?? '',
              copiedDestinations: head
                .querySelectorAll('[data-locator-target],.writing-blank').length
            })),
            fields: targets.map(blank => ({
              label: blank.closest('.field,.result-field,.authored-blank')
                .querySelector('.field-label').textContent,
              setup: blank.closest('[data-setup-id]').dataset.setupId,
              workpiece: blank.closest('[data-workpiece]').dataset.workpiece,
              context: blank.closest('[data-page-context]').dataset.pageContext,
              original: !blank.closest('[data-job-print]'), fits: inside(blank)
            })),
            references: [...section.querySelectorAll('[data-locator-ref]')].map(ref => {
              const target = targets.find(
                blank => blank.dataset.locatorTarget === ref.dataset.locatorRef);
              const key = JSON.parse(ref.dataset.locatorRef);
              const members = key.includes('progress pair')
                ? [...section.querySelectorAll('.path-progress [data-locator-target]')] : [target];
              return { text: ref.textContent,
                page: Number(ref.querySelector('.fixed-locator-ink').textContent),
                destinationPages: members.map(node => pageOf(node)+1),
                original: members.every(node => !node.closest('[data-job-print]')) };
            }),
            figures: [...section.querySelectorAll('figure')].map(figure => ({
              setup: figure.closest('[data-setup-id]').dataset.setupId,
              workpiece: figure.closest('[data-workpiece]').dataset.workpiece,
              inner: figure.closest('[data-page-context]').dataset.pageContext,
              original: !figure.closest('[data-job-print]'), fits: inside(figure)
            }))
          };
        }""",
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    assert details["jobs"] == 1
    assert 3 <= details["pages"] < 20
    assert (
        details["words"]
        == _words("InspectBefore", 450).split() + _words("InspectAfter", 450).split()
    )
    assert details["moves"] == [f"MOVE{index:03d}" for index in range(72)]
    assert details["heads"]
    assert {head["inner"] for head in details["heads"]} == {
        "S2 op 20 inspection",
        "S2 op 30 contour",
    }
    for head in details["heads"]:
        assert head["setup"] == "S2" and head["workpiece"] == "nut2"
        if detail == "pedantic":
            assert SETUP_TWO in head["title"] and SETUP_ONE not in head["title"]
            assert "boundary drawing" in head["title"] and "rev A" in head["title"]
        else:
            assert head["title"] == JOB_TITLE
            assert SETUP_ONE not in head["title"] and SETUP_TWO not in head["title"]
        assert head["inner"] in head["context"]
        assert head["copiedDestinations"] == 0
    assert len(details["fields"]) == 3
    for field in details["fields"]:
        assert field["setup"] == "S2" and field["workpiece"] == "nut2"
        assert field["original"] and field["fits"]
        assert field["context"] == (
            "S2 op 20 inspection"
            if field["label"] == "opposite-face observed"
            else "S2 op 30 contour"
        )
    assert details["references"]
    for reference in details["references"]:
        assert SETUP_TWO in reference["text"] and "nut2" in reference["text"]
        assert "JOB, page" not in reference["text"]
        assert reference["original"]
        assert reference["destinationPages"] and all(
            page == reference["page"] for page in reference["destinationPages"]
        )
    assert details["figures"] == [
        {
            "setup": "S2",
            "workpiece": "nut2",
            "inner": "S2 op 20 inspection",
            "original": True,
            "fits": True,
        }
    ]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_nested_owners_and_job_identity_print_on_actual_continuation_pages(tmp_path, detail):
    pages = printed_pages(_job(_nested_work(), detail=detail), tmp_path)
    assert 3 <= len(pages) < 20
    assert all(text.strip() and "PRINT LAYOUT ERROR" not in text for text in pages)
    assert DRAWING in pages[0] and "rev C" in pages[0]
    labels = [LABEL.search(page) for page in pages[1:]]
    assert all(labels), pages
    assert [(int(label[1]), int(label[2])) for label in labels] == [
        (page, len(pages)) for page in range(2, len(pages) + 1)
    ]
    for text in pages[1:]:
        if detail == "pedantic":
            assert PART in text and DRAWING in text and "rev C" in text
            assert SETUP_TWO in text
        else:
            assert JOB_TITLE in text
        assert "EXAMPLE ONLY" in text
        assert "S2 op 20 inspection" in text or "S2 op 30 contour" in text
    assert sum("Original inspection diagram" in text for text in pages) == 1


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_job_title_and_local_owners_distinguish_fresh_headings_from_tails(
    printed_sheet, detail
):
    rows = "".join(
        f"<tbody><tr><td>EDGE{index:03d}</td><td>Deburr this member only.</td></tr></tbody>"
        for index in range(72)
    )
    source = (
        '<div class="banner">EXAMPLE ONLY — NOT FOR EXECUTION IN A REAL ENVIRONMENT '
        "· PLANNED</div>"
        + _setup(
            "Earlier saw family",
            "B1",
            "stock",
            '<p style="height:800px;margin:0">EarlierSawSource</p>',
        )
        + _setup(
            SETUP_ONE,
            "S1",
            "nut1",
            f"<p>{_words('SawTail', 650)} " + _writing_field("saw tail observed") + "</p>",
        )
        + '<section class="setup-family" data-setup-title="E1–E4" data-setup-id="">'
        "<h2>Edge family (E1–E4)</h2>"
        '<p style="height:850px;margin:0">OriginalFamilyPrelude</p>'
        '<div class="setup-variant" data-setup-title="Setup E1 — nut1" '
        'data-setup-id="E1" data-member="edge-one" data-workpiece="nut1">'
        '<p class="variant-label">E1 — nut1</p>'
        "<table><thead><tr><th>Edge</th><th>Action</th></tr></thead>"
        + rows
        + "</table><p>OriginalEdgeRecord "
        + _writing_field("edge observed")
        + "</p></div></section>"
        + _setup("Later drill family", "D1", "nut2", "<p>LaterFamilySource</p>")
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const original = section.cloneNode(true);
          original.querySelectorAll('[data-job-print],.fixed-locator-reference')
            .forEach(node => node.remove());
          const starts = [section, ...section.querySelectorAll('.cont-head')];
          const onPage = (node, page) => pageOf(node) === page;
          return {
            part: section.dataset.part,
            words: original.textContent.match(/SawTail\d{4}/g),
            edges: original.textContent.match(/EDGE\d{3}/g),
            later: original.textContent.includes('LaterFamilySource'),
            heads: [...section.querySelectorAll('.cont-head')].map(head => {
              const page = starts.indexOf(head), context = head.querySelector('.cont-context');
              const freshHeading = [...section.querySelectorAll('h2,.variant-label')]
                .find(node => onPage(node, page) && !node.closest('[data-job-print]')
                  && node.closest('[data-setup-id]')?.dataset.setupId === head.dataset.setupId);
              return {title: head.querySelector('.cont-title').textContent,
                setup: head.dataset.setupId, member: head.dataset.member ?? '',
                workpiece: head.dataset.workpiece ?? '', context: context?.textContent ?? '',
                freshHeading: freshHeading?.textContent ?? '',
                copies: head.querySelectorAll(
                  '[data-locator-target],.writing-blank,figure').length};
            }),
            fields: [...section.querySelectorAll('[data-locator-target]')].map(blank => ({
              setup: blank.closest('[data-setup-id]').dataset.setupId,
              member: blank.closest('[data-member]')?.dataset.member ?? '',
              workpiece: blank.closest('[data-workpiece]').dataset.workpiece,
              original: !blank.closest('[data-job-print]')
            }))
          };
        }""",
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          const section = document.querySelector('section.page');
          section.dataset.jobTitle = {json.dumps(JOB_TITLE)};
          section.dataset.quantity = '4';
          section.dataset.continuationLabel = 'EXAMPLE ONLY';
        }}""",
    )
    assert details["part"] == "boundary part"
    assert details["words"] == _words("SawTail", 650).split()
    assert details["edges"] == [f"EDGE{index:03d}" for index in range(72)]
    assert details["later"]
    assert details["heads"]
    for head in details["heads"]:
        assert head["title"] == JOB_TITLE + " · qty 4 · EXAMPLE ONLY · PLANNED"
        assert head["copies"] == 0
    for setup in ("S1", "E1"):
        owned = [head for head in details["heads"] if head["setup"] == setup]
        assert any(head["freshHeading"] and not head["context"] for head in owned)
        tails = [head for head in owned if not head["freshHeading"]]
        assert tails
        for head in tails:
            assert setup in head["context"] and head["context"].endswith(" (continued)")
            assert head["workpiece"] in head["context"]
            if setup == "E1":
                assert head["member"] == "edge-one" and "edge-one" in head["context"]
                assert head["context"] != "E1–E4 (continued)"
    assert details["fields"] == [
        {"setup": "S1", "member": "", "workpiece": "nut1", "original": True},
        {"setup": "E1", "member": "edge-one", "workpiece": "nut1", "original": True},
    ]


def test_compact_nested_owner_is_not_suppressed_by_physical_identity(printed_sheet):
    owner = "S1 first hold · nut1"
    source = _setup(
        SETUP_ONE,
        "S1",
        "nut1",
        f'<div data-page-context="{owner}"><h3 class="page-context">{owner}</h3>'
        f"<p>{_words('NestedOwner', 650)}</p></div>",
    )
    _, contexts = printed_sheet(
        source,
        r"""() => [...document.querySelectorAll('.cont-head')].map(head => ({
          title: head.querySelector('.cont-title').textContent,
          context: head.querySelector('.cont-context')?.textContent ?? '',
          owner: head.dataset.pageContext
        }))""",
        prepare=f"""() => {{
          document.body.dataset.detail = 'hobby';
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    assert contexts
    assert all(head == {"title": JOB_TITLE, "context": owner, "owner": owner} for head in contexts)


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_production_nested_setup_starts_fresh_despite_display_title_difference(
    printed_sheet, detail
):
    source = (
        _setup(
            "Earlier saw family",
            "B1",
            "stock",
            '<p style="height:800px;margin:0">EarlierSawSource</p>',
        )
        + '<section class="setup-flow" data-setup-title="S2" data-setup-id="S2" '
        'data-workpiece=""><h2 data-original-heading="setup">S2</h2>'
        '<div class="setup-variant" data-setup-title="Setup S2" data-setup-id="S2" '
        'data-workpiece=""><p>'
        + _positioned_words("NestedS2Source", 650)
        + " "
        + _writing_field("S2 original result")
        + "</p></div></section>"
    )
    _, details = printed_sheet(
        source,
        _OWNER_SOURCE_POSITIONS,
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    positions = details["positions"]
    assert [position["key"] for position in positions] == _words("NestedS2Source", 650).split()
    assert all(
        position["text"] == position["key"] and position["setup"] == "S2" for position in positions
    )
    assert details["copiedPositions"] == 0
    first_page = positions[0]["page"]
    source_pages = {position["page"] for position in positions}
    assert first_page > 0 and len(source_pages) > 1
    assert details["headings"] == [
        {"key": "setup", "text": "S2", "page": first_page, "visible": True}
    ]
    heads = {head["page"]: head for head in details["heads"]}
    assert heads[first_page]["context"] == ""
    for page in source_pages - {first_page}:
        assert "S2" in heads[page]["context"]
        assert heads[page]["context"].endswith(" (continued)")
    assert all(
        head["setup"] == "S2" and head["title"] == JOB_TITLE and head["copiedDestinations"] == 0
        for head in heads.values()
    )
    (field,) = details["fields"]
    assert field["label"] == "S2 original result"
    assert field["setup"] == "S2" and field["workpiece"] == "" and field["member"] == ""
    assert field["original"] and field["page"] >= positions[-1]["page"]


@pytest.mark.parametrize(
    ("detail", "label"),
    [
        pytest.param("pro", "visible-label", id="pro-visible-label"),
        pytest.param("pro", "no-label", id="pro-no-label"),
        pytest.param("pro", "hidden-label", id="pro-hidden-label"),
        pytest.param("hobby", "visible-label", id="hobby-visible-label"),
        pytest.param("hobby", "no-label", id="hobby-no-label"),
        pytest.param("hobby", "hidden-label", id="hobby-hidden-label"),
    ],
)
def test_compact_fresh_family_member_identity_is_not_a_continuation(printed_sheet, detail, label):
    member_label = (
        '<p class="variant-label" data-original-heading="member"'
        + (' style="visibility:hidden"' if label == "hidden-label" else "")
        + ">E1 — nut1</p>"
        if label != "no-label"
        else ""
    )
    source = (
        _setup(
            "Earlier saw family",
            "B1",
            "stock",
            '<p style="height:800px;margin:0">EarlierSawSource</p>',
        )
        + '<section class="setup-family" data-setup-title="E1–E4" data-setup-id="">'
        '<h2 data-original-heading="family">Edge family (E1–E4)</h2>'
        '<div class="setup-variant" data-setup-title="Setup E1 — nut1" '
        'data-setup-id="E1" data-member="edge-one" data-workpiece="nut1">'
        + member_label
        + "<p>"
        + _positioned_words("FirstE1Source", 650)
        + " "
        + _writing_field("E1 original result")
        + "</p></div></section>"
    )
    _, details = printed_sheet(
        source,
        _OWNER_SOURCE_POSITIONS,
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    positions = details["positions"]
    assert [position["key"] for position in positions] == _words("FirstE1Source", 650).split()
    assert all(
        position["text"] == position["key"] and position["setup"] == "E1" for position in positions
    )
    assert details["copiedPositions"] == 0
    first_page = positions[0]["page"]
    source_pages = {position["page"] for position in positions}
    assert first_page > 0 and len(source_pages) > 1
    expected_headings = [
        {"key": "family", "text": "Edge family (E1–E4)", "page": first_page, "visible": True}
    ]
    if label != "no-label":
        expected_headings.append(
            {
                "key": "member",
                "text": "E1 — nut1",
                "page": first_page,
                "visible": label == "visible-label",
            }
        )
    assert details["headings"] == expected_headings
    heads = {head["page"]: head for head in details["heads"]}
    fresh_context = heads[first_page]["context"]
    assert "(continued)" not in fresh_context
    if label == "visible-label":
        assert fresh_context == ""
    else:
        assert all(owner in fresh_context for owner in ("E1", "nut1", "edge-one"))
    for page in source_pages - {first_page}:
        assert all(owner in heads[page]["context"] for owner in ("E1", "nut1", "edge-one"))
        assert heads[page]["context"].endswith(" (continued)")
    assert all(
        head["setup"] == "E1"
        and head["member"] == "edge-one"
        and head["workpiece"] == "nut1"
        and head["title"] == JOB_TITLE
        and head["copiedDestinations"] == 0
        for head in heads.values()
    )
    (field,) = details["fields"]
    assert field["label"] == "E1 original result"
    assert field["setup"] == "E1" and field["workpiece"] == "nut1" and field["member"] == "edge-one"
    assert field["original"] and field["page"] >= positions[-1]["page"]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_interior_h2_on_a_real_setup_tail_does_not_restart_its_owner(printed_sheet, detail):
    source = (
        '<section class="setup-flow" data-setup-title="S2" data-setup-id="S2" '
        'data-workpiece=""><h2 data-original-heading="setup">S2</h2>'
        '<div class="setup-variant" data-setup-title="Setup S2" data-setup-id="S2" '
        'data-workpiece=""><p style="height:800px;margin:0">'
        '<span data-source-position="S2Opening">S2Opening</span></p></div>'
        '<div class="setup-variant" data-setup-title="Setup S2" data-setup-id="S2" '
        'data-workpiece=""><h2 data-original-heading="interior">READINGS</h2><p>'
        + _positioned_words("S2TailSource", 650)
        + " "
        + _writing_field("S2 tail original result")
        + "</p></div></section>"
    )
    _, details = printed_sheet(
        source,
        _OWNER_SOURCE_POSITIONS,
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    positions = details["positions"]
    assert [position["key"] for position in positions] == [
        "S2Opening",
        *_words("S2TailSource", 650).split(),
    ]
    assert all(
        position["text"] == position["key"] and position["setup"] == "S2" for position in positions
    )
    assert details["copiedPositions"] == 0
    opening_page = positions[0]["page"]
    tail_page = positions[1]["page"]
    tail_pages = {position["page"] for position in positions[1:]}
    assert opening_page == 0 and tail_page > opening_page and len(tail_pages) > 1
    assert details["headings"] == [
        {"key": "setup", "text": "S2", "page": opening_page, "visible": True},
        {"key": "interior", "text": "READINGS", "page": tail_page, "visible": True},
    ]
    heads = {head["page"]: head for head in details["heads"]}
    for page in tail_pages:
        assert "S2" in heads[page]["context"]
        assert heads[page]["context"].endswith(" (continued)")
    assert all(
        head["setup"] == "S2" and head["title"] == JOB_TITLE and head["copiedDestinations"] == 0
        for head in heads.values()
    )
    (field,) = details["fields"]
    assert field["label"] == "S2 tail original result"
    assert field["setup"] == "S2" and field["workpiece"] == "" and field["member"] == ""
    assert field["original"] and field["page"] >= positions[-1]["page"]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_long_authored_continuation_context_does_not_displace_its_original_source(
    printed_sheet, detail
):
    words = _words("OwnerSource", 650)
    title = "S1 op 50 inspection: " + words
    source = _setup(
        SETUP_ONE,
        "S1",
        "nut1",
        f'<ol><li data-page-context="{title}"><h3 class="page-context">'
        'S1 op <span class="reading">50</span> inspection: '
        + words
        + "</h3><p>Record the original observed result "
        + _writing_field("owner source observed")
        + "</p></li></ol>",
    )
    _, details = printed_sheet(
        source,
        r"""() => {
          const section = document.querySelector('section.page');
          const headings = [...section.querySelectorAll('.page-context')]
            .filter(node => !node.closest('[data-job-print]'));
          const sourceText = node => {
            const copy = node.cloneNode(true);
            copy.querySelectorAll('.fixed-locator-reference').forEach(ref => ref.remove());
            return copy.textContent;
          };
          return {
            source: headings.map(sourceText).join(''),
            font: getComputedStyle(headings[0]).fontSize,
            contexts: [...section.querySelectorAll('.cont-head .cont-context')].map(node => ({
              text: node.textContent, font: getComputedStyle(node).fontSize,
              readings: [...node.querySelectorAll('.reading')].map(reading => reading.textContent),
              copiedDestinations: node.querySelectorAll(
                '[data-locator-target],.writing-blank').length
            })),
            fields: [...section.querySelectorAll('[data-locator-target]')].map(blank => ({
              label: blank.closest('.field').querySelector('.field-label').textContent,
              setup: blank.closest('[data-setup-id]').dataset.setupId,
              workpiece: blank.closest('[data-workpiece]').dataset.workpiece,
              original: !blank.closest('[data-job-print]')
            }))
          };
        }""",
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    assert details["source"] == title
    assert details["contexts"]
    assert any(len(context["text"]) < len(title) for context in details["contexts"])
    for context in details["contexts"]:
        assert context["text"].startswith("S1 op 50")
        assert context["font"] == details["font"] and context["readings"] == ["50"]
        assert context["copiedDestinations"] == 0
    assert details["fields"] == [
        {"label": "owner source observed", "setup": "S1", "workpiece": "nut1", "original": True}
    ]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("has_part", [True, False])
def test_compact_running_title_without_human_job_title_retains_manual_part_fallback(
    printed_sheet, detail, has_part
):
    source = _setup(SETUP_ONE, "S1", "nut1", f"<p>{_words('ManualJob', 650)}</p>")
    _, titles = printed_sheet(
        source,
        "() => [...document.querySelectorAll('.cont-title')].map(node => node.textContent)",
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.quantity = '2';
          if (!{json.dumps(has_part)}) delete document.querySelector('section.page').dataset.part;
        }}""",
    )
    expected = "boundary part · qty 2" if has_part else "boundary drawing · rev A · qty 2"
    assert titles and all(title == expected for title in titles)


def test_repeated_beforeprint_restores_loaded_diagram_and_original_destinations(printed_sheet):
    _, details = printed_sheet(
        _nested_work(),
        r"""() => {
          const root = document.documentElement, section = document.querySelector('section.page');
          const snapshot = () => ({html: section.innerHTML, pages: section.dataset.pages,
            backs: document.querySelectorAll('.blank-side').length,
            originals: [...section.querySelectorAll('[data-locator-target]')]
              .every(node => !node.closest('[data-job-print]')),
            images: [...section.querySelectorAll('img,svg image')].map((image, index) => ({
              same: image === window.canonicalImages[index], width: image.getAttribute('width'),
              height: image.getAttribute('height'), opacity: image.style.opacity,
              complete: image instanceof HTMLImageElement
                ? image.complete && image.naturalWidth > 0 : true
            }))});
          const first = snapshot();
          for (const image of window.canonicalImages) {
            image.setAttribute('width','1'); image.setAttribute('height','1');
            image.style.opacity='0';
            image.setAttribute('data-mutated-image','');
          }
          const height = root.style.getPropertyValue('--page-content-height');
          root.style.setProperty('--page-content-height','40in');
          dispatchEvent(new Event('beforeprint'));
          const large = snapshot();
          if (height) root.style.setProperty('--page-content-height',height);
          else root.style.removeProperty('--page-content-height');
          dispatchEvent(new Event('beforeprint'));
          const second = snapshot();
          dispatchEvent(new Event('beforeprint'));
          const third = snapshot();
          return {restored: JSON.stringify(first) === JSON.stringify(second),
            stable: JSON.stringify(second) === JSON.stringify(third),
            pages: Number(third.pages), backs: third.backs, originals: third.originals,
            largePages: Number(large.pages), images: third.images,
            restoredAttributes: !section.querySelector('[data-mutated-image]')};
        }""",
        prepare="""() => {
          window.canonicalImages = [
            ...document.querySelectorAll('section.page img,section.page svg image')];
        }""",
    )
    assert details["restored"] and details["stable"]
    assert details["pages"] > details["largePages"]
    assert details["backs"] == 0 and details["originals"] and details["restoredAttributes"]
    assert details["images"] == [
        {"same": True, "width": "240", "height": "120", "opacity": "", "complete": True}
    ]


def test_compact_operation_continuation_preserves_physical_warning_and_number_owner(printed_sheet):
    def operation(setup, instruction, *, warning=""):
        return (
            '<table class="operations"><thead><tr><th>Operation</th></tr></thead>'
            f'<tbody class="operation" data-setup-id="{setup}" data-op="10" '
            f'data-operation-context="Setup {setup} op 10"><tr class="operation-main"><td>'
            '<div class="op-head"><h3><span class="op-number">10</span> Face</h3></div>'
            f'<div class="op-action"><p>{instruction}</p></div>'
            '<dl class="op-details"><div class="op-tool"><dt>Tool</dt><dd>T1</dd></div>'
            '<div class="op-target"><dt>Target</dt><dd>12.700 mm</dd></div></dl></td></tr>'
            + (
                f'<tr class="warn"><td><div class="box">{warning}</div></td></tr>'
                if warning
                else ""
            )
            + "</tbody></table>"
        )

    source = _setup(SETUP_ONE, "S1", "nut1", operation("S1", "FirstMemberOnly action.")) + _setup(
        SETUP_TWO,
        "S2",
        "nut2",
        operation(
            "S2",
            _words("SecondMember", 900),
            warning="STOP actual fixture collision at X 12.700 mm.",
        ),
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const copy = section.cloneNode(true);
          copy.querySelectorAll('[data-job-print],.record-continuation,.fixed-locator-reference')
            .forEach(node => node.remove());
          return {words: copy.textContent.match(/SecondMember\d{4}/g),
            warnings: [...section.querySelectorAll('.box')]
              .filter(node => !node.closest('[data-job-print]'))
              .map(node => ({
                text:node.textContent,setup:node.closest('[data-setup-id]').dataset.setupId})),
            continuations: [...section.querySelectorAll('.operation-continuation')].map(row => ({
              setup: row.closest('[data-setup-id]').dataset.setupId, text: row.textContent,
              number: row.querySelector('.op-number')?.textContent,
              marks: row.querySelectorAll('.writing-blank,.performed-mark').length,
              fits: row.getBoundingClientRect().bottom <=
                [section.getBoundingClientRect().top,...[...section.querySelectorAll('.cont-head')]
                  .map(head => head.getBoundingClientRect().top)][pageOf(row)]
                + Number(document.documentElement.dataset.pageCapacity)+.1
            }))};
        }""",
    )
    assert details["words"] == _words("SecondMember", 900).split()
    assert details["warnings"] == [
        {"text": "STOP actual fixture collision at X 12.700 mm.", "setup": "S2"}
    ]
    assert details["continuations"]
    for row in details["continuations"]:
        assert row["setup"] == "S2" and "FirstMemberOnly" not in row["text"]
        assert row["number"].startswith("10") and row["marks"] == 0 and row["fits"]


def test_grouped_final_results_remain_one_full_size_horizontal_row(printed_sheet):
    results = "".join(
        f'<div class="checkpoint-result" data-setup-id="F1{letter}" data-op-id="10" '
        f"data-workpiece=\"nut{index}\" data-inspection-ids='{json.dumps([f'physical-{index}'])}'>"
        + _writing_field(f"nut{index} overall result", "result-field")
        + "</div>"
        for index, letter in enumerate("abcd", 1)
    )
    source = _setup(
        "F1 final batch checks",
        "F1a",
        "batch",
        '<p>Original final checkpoint criteria.</p><div style="height:780px"></div>'
        '<div class="checkpoint-results">' + results + "</div>",
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const starts = [section.getBoundingClientRect().top,
            ...[...section.querySelectorAll('.cont-head')]
              .map(head => head.getBoundingClientRect().top)];
          const cap = Number(document.documentElement.dataset.pageCapacity);
          return [...section.querySelectorAll('.checkpoint-result')].map(cell => {
            const blank = cell.querySelector('.writing-blank'),
              rect = blank.getBoundingClientRect();
            const style = getComputedStyle(blank), field = cell.querySelector('.result-field');
            return {workpiece:cell.dataset.workpiece, setup:cell.dataset.setupId,
              ids:JSON.parse(cell.dataset.inspectionIds), page:pageOf(cell),
              top:cell.getBoundingClientRect().top, left:rect.left, right:rect.right,
              labelAbove:field.querySelector('.field-label').getBoundingClientRect().bottom
                <= rect.top,
              width:rect.width-parseFloat(style.borderLeftWidth)-parseFloat(style.borderRightWidth),
              height:rect.height-parseFloat(style.borderTopWidth)-parseFloat(style.borderBottomWidth),
              fits:rect.bottom <= starts[pageOf(cell)]+cap+.1,
              original:!cell.closest('[data-job-print]')};
          });
        }""",
    )
    assert len(details) == 4 and len({cell["page"] for cell in details}) == 1
    assert max(cell["top"] for cell in details) - min(cell["top"] for cell in details) < 0.1
    for index, cell in enumerate(details, 1):
        assert cell["workpiece"] == f"nut{index}" and cell["ids"] == [f"physical-{index}"]
        assert cell["width"] >= 35 * 96 / 25.4 - 0.1 and cell["height"] >= 20 * 96 / 25.4 - 0.1
        assert cell["labelAbove"] and cell["fits"] and cell["original"]
    assert all(
        left["right"] <= right["left"] for left, right in zip(details, details[1:], strict=False)
    )
