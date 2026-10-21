"""Continuous traveler pagination, exercised in Chromium and on physical PDF pages."""

from __future__ import annotations

import json
import re

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
                setup: head.dataset.setupId ?? '', member: head.dataset.member ?? '',
                workpiece: head.dataset.workpiece ?? '', context: context?.textContent ?? '',
                freshHeading: freshHeading?.textContent ?? '',
                familyHeading: [...section.querySelectorAll('.setup-family > h2')]
                  .some(node => onPage(node, page) && !node.closest('[data-job-print]')),
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
    unowned = [head for head in details["heads"] if not head["setup"]]
    for head in unowned:
        assert head["familyHeading"] or "E1–E4" in head["context"]
        assert head["member"] == head["workpiece"] == ""
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


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_running_range_tracks_mixed_source_owners_and_continued_tails(
    printed_sheet, detail
):
    source = (
        '<div class="setup" data-setup-title="S1 first hold" data-setup-id="S1" '
        'data-workpiece="nut1" style="display:contents">'
        '<h2>S1 first hold</h2><p data-source-position="first">First original hold.</p>'
        '<p style="break-before:page" data-source-position="tail">First hold tail.</p>'
        "<h2>NOT-A-PHYSICAL-SETUP</h2></div>"
        + _setup(
            SETUP_TWO, "S2", "nut2", '<p data-source-position="second">Second original hold.</p>'
        )
        + _setup(
            "S3 third hold",
            "S3",
            "nut3",
            f"<p>Third hold initial source.</p><p>{_positioned_words('Third', 750)}</p>",
        )
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const original = node => !node.closest('[data-job-print],.record-continuation');
          return {
            positions: [...section.querySelectorAll('[data-source-position]')]
              .filter(original).map(node => ({key:node.dataset.sourcePosition,
                page:pageOf(node), setup:node.closest('[data-setup-id]').dataset.setupId})),
            heads: [...section.querySelectorAll('.cont-head')].map(head => {
              const slot = head.querySelector('.cont-page-owners');
              const range = document.createRange();
              range.selectNodeContents(slot);
              const ink = range.getBoundingClientRect(), box = slot.getBoundingClientRect();
              return {page:pageOf(head), owners:JSON.parse(head.dataset.pageOwners),
                continued:head.dataset.ownerContinued === 'true', range:slot.textContent,
                ink:[ink.left,ink.top,ink.right,ink.bottom],
                reserved:[box.left,box.top,box.right,box.bottom],
                fits:ink.left >= box.left-.1 && ink.right <= box.right+.1
                  && ink.top >= box.top-.1 && ink.bottom <= box.bottom+.1,
                copies:head.querySelectorAll('figure,.writing-blank,[data-locator-target]').length};
            })
          };
        }""",
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    positions = details["positions"]
    assert [position["key"] for position in positions] == [
        "first",
        "tail",
        "second",
        *[f"Third{index:04d}" for index in range(750)],
    ]
    mixed_page = next(position["page"] for position in positions if position["key"] == "tail")
    assert next(position["page"] for position in positions if position["key"] == "second") == (
        mixed_page
    )
    assert next(position["page"] for position in positions if position["key"] == "first") < (
        mixed_page
    )
    mixed = next(head for head in details["heads"] if head["page"] == mixed_page)
    assert [owner["setup"] for owner in mixed["owners"]] == ["S1", "S2", "S3"]
    assert mixed["continued"]
    assert mixed["range"].index("S1") < mixed["range"].index("S3")
    tails = [head for head in details["heads"] if head["page"] > mixed_page]
    assert tails
    assert all(
        [owner["setup"] for owner in head["owners"]] == ["S3"] and head["continued"]
        for head in tails
    )
    for head in details["heads"]:
        assert head["fits"], head
        assert not head["copies"] and "NOT-A-PHYSICAL-SETUP" not in head["range"], head


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_range_uses_shared_physical_metadata_without_inventing_unknown_owners(
    printed_sheet, detail
):
    identities = [
        {"setup_id": setup, "op_id": 10, "workpiece": workpiece}
        for setup, workpiece in (("Q1", None), ("Q2", "nut2"), ("Q4", None))
    ]
    source = (
        '<p>Original job introduction.</p><div data-setup-title="Facing holds" '
        'data-setup-id="" data-setup-members=\'["Q1","Q2","Q4"]\' style="break-before:page">'
        "<h2>NOT-AN-OWNER</h2><div data-physical-ops='"
        + json.dumps(identities)
        + "'><p>Common original operation.</p></div>"
        '<div data-physical-ops="invalid"><p>Unresolved owner.</p></div>'
        '<div data-setup-id=""><p>Unknown owner.</p></div></div>'
    )
    _, details = printed_sheet(
        source,
        r"""() => [...document.querySelectorAll('.cont-head')].map(head => ({
          owners:JSON.parse(head.dataset.pageOwners),
          continued:head.dataset.ownerContinued === 'true',
          text:head.querySelector('.cont-page-owners').textContent,
          copies:head.querySelectorAll('figure,.writing-blank,[data-locator-target]').length
        }))""",
        prepare=f"""() => {{
          document.body.dataset.detail = {json.dumps(detail)};
          document.querySelector('section.page').dataset.jobTitle = {json.dumps(JOB_TITLE)};
        }}""",
    )
    assert len(details) == 1
    assert details[0]["owners"] == [
        {"setup": item["setup_id"], "member": "", "workpiece": item["workpiece"] or ""}
        for item in identities
    ]
    assert not details[0]["continued"] and details[0]["copies"] == 0
    assert details[0]["text"].index("Q1") < details[0]["text"].index("Q4")
    assert "NOT-AN-OWNER" not in details[0]["text"] and "Job" not in details[0]["text"]


@pytest.mark.parametrize("picture_first", [True, False])
def test_compact_range_orders_relocated_picture_and_shared_owners_by_authored_route(
    printed_sheet, picture_first
):
    identities = [
        {"setup_id": setup, "op_id": 10, "workpiece": None if setup != "Q2" else "nut2"}
        for setup in ("Q1", "Q2", "Q3", "Q4")
    ]
    picture = (
        '<figure data-setup-id="Q2" data-member="nut2" data-workpiece="nut2">'
        "<figcaption>Selected second hold view.</figcaption>"
        f'<img src="{IMAGE}" width="240" height="120" '
        'style="display:block;width:240px;height:120px" alt="Original second hold"></figure>'
    )
    shared = (
        "<div data-physical-ops='" + json.dumps(identities) + "'><p>Common facing cycle.</p></div>"
    )
    source = (
        "<p>Original job introduction.</p>"
        '<section class="setup-family" data-setup-title="Facing holds" data-setup-id="" '
        'data-setup-members=\'["Q1","Q2","Q3","Q4"]\' style="break-before:page">'
        "<h2>Facing holds</h2>"
        + (picture + shared if picture_first else shared + picture)
        + '<div data-setup-id="Q2" data-workpiece="nut2" data-physical-ops=\''
        + json.dumps([identities[1]])
        + f"'><p>{_positioned_words('Q2Tail', 650)}</p></div></section>"
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => ({
          figures:[...document.querySelectorAll('figure')].map(node => ({
            page:pageOf(node), original:!node.closest('[data-job-print]')})),
          heads:[...document.querySelectorAll('.cont-head')].map(head => ({
            page:pageOf(head), owners:JSON.parse(head.dataset.pageOwners),
            start:head.dataset.ownerRangeStart, end:head.dataset.ownerRangeEnd,
            continued:head.dataset.ownerContinued === 'true',
            text:head.querySelector('.cont-page-owners').textContent
          }))
        })""",
        prepare="() => { document.body.dataset.detail = 'hobby'; }",
    )
    assert len(details["figures"]) == 1 and details["figures"][0]["original"]
    first, *tails = details["heads"]
    assert first["page"] == details["figures"][0]["page"]
    assert (first["start"], first["end"]) == ("Q1", "Q4")
    assert first["text"].index("Q1") < first["text"].index("Q4")
    assert [owner["setup"] for owner in first["owners"]] == ["Q1", "Q2", "Q3", "Q4"]
    assert first["owners"][1] == {"setup": "Q2", "member": "", "workpiece": "nut2"}
    assert not first["continued"]
    assert tails and all(
        head["start"] == head["end"] == "Q2"
        and head["owners"] == [{"setup": "Q2", "member": "", "workpiece": "nut2"}]
        and head["continued"]
        for head in tails
    )


def test_compact_reference_records_and_fresh_same_label_do_not_create_continuations(printed_sheet):
    source = (
        '<div class="checkpoint-result" data-setup-id="F1" data-member="nut1" '
        'data-workpiece="nut1"><p>Front-page result reference.</p></div>'
        '<div class="setup" data-setup-title="F1 final hold" data-setup-id="F1" '
        'data-workpiece="nut1" style="break-before:page"><h2>F1 final hold</h2>'
        '<div data-setup-id="F1" data-physical-ops=\''
        + json.dumps([{"setup_id": "F1", "op_id": 10, "workpiece": "nut1"}])
        + "'><p>First fresh physical hold.</p></div></div>"
        '<div class="setup" data-setup-title="F1 final hold" data-setup-id="F1" '
        'data-workpiece="nut1" style="break-before:page"><h2>F1 final hold</h2>'
        "<p>Another fresh physical hold with the same source labels.</p></div>"
        '<div style="break-before:page"><h2>NOT-A-SETUP</h2>'
        '<div data-physical-ops="invalid"><p>Unresolved source owner.</p></div>'
        '<div data-setup-id=""><p>Unknown source owner.</p></div></div>'
    )
    _, details = printed_sheet(
        source,
        r"""() => [...document.querySelectorAll('.cont-head')].map(head => ({
          owners:JSON.parse(head.dataset.pageOwners),
          start:head.dataset.ownerRangeStart, end:head.dataset.ownerRangeEnd,
          continued:head.dataset.ownerContinued === 'true',
          text:head.querySelector('.cont-page-owners').textContent
        }))""",
        prepare="() => { document.body.dataset.detail = 'hobby'; }",
    )
    assert len(details) == 3
    for fresh in details[:2]:
        assert fresh["start"] == fresh["end"] == "F1"
        assert fresh["owners"] == [{"setup": "F1", "member": "", "workpiece": "nut1"}]
        assert not fresh["continued"]
    unknown = details[2]
    assert unknown["owners"] == []
    assert unknown["start"] == unknown["end"] == unknown["text"] == ""
    assert not unknown["continued"]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_compact_setup_continues_when_page_opens_on_its_first_member_record(printed_sheet, detail):
    operation_owners = json.dumps([{"setup_id": "S1", "op_id": 10, "workpiece": None}])
    source = (
        '<section class="setup-flow" data-setup-title="S1 batch hold" data-setup-id="S1" '
        'data-setup-members=\'["S1"]\' data-workpiece="" style="display:contents">'
        '<h2>S1 batch hold</h2><div data-setup-id="S1" data-physical-ops=\''
        + operation_owners
        + "'><p>Original shared operations before the record.</p></div>"
        '<div data-setup-id="S1" data-member="nut2" data-workpiece="nut2" '
        'style="break-before:page"><p>Original second member record '
        + _writing_field("nut2 observed")
        + '</p></div><div data-setup-id="S1" data-physical-ops=\''
        + operation_owners
        + "'><p>Original shared operations after the record.</p></div></section>"
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => ({
          heads:[...document.querySelectorAll('.cont-head')].map(head => ({
            owners:JSON.parse(head.dataset.pageOwners),
            start:head.dataset.ownerRangeStart, end:head.dataset.ownerRangeEnd,
            continued:head.dataset.ownerContinued === 'true', page:pageOf(head)
          })),
          fields:[...document.querySelectorAll('[data-locator-target]')].map(node => ({
            member:node.closest('[data-member]').dataset.member, page:pageOf(node),
            original:!node.closest('[data-job-print]')
          }))
        })""",
        prepare=f"() => {{ document.body.dataset.detail = {json.dumps(detail)}; }}",
    )
    assert len(details["heads"]) == 1
    head = details["heads"][0]
    assert head["start"] == head["end"] == "S1" and head["continued"]
    assert head["owners"] == [
        {"setup": "S1", "member": "", "workpiece": "nut2"},
        {"setup": "S1", "member": "", "workpiece": ""},
    ]
    assert details["fields"] == [{"member": "nut2", "page": head["page"], "original": True}]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_hoisted_final_reference_keeps_records_but_not_physical_setup_ranges(printed_sheet, detail):
    source = (
        '<section class="setup-family" data-setup-title="Final inspection after B2" '
        'data-setup-id="" data-setup-members=\'["F1a","F1b"]\' '
        'data-page-reference="final-inspection" style="display:contents">'
        "<h2>Final inspection after B2</h2>"
        '<div class="setup-variant" data-setup-title="F1a final inspection after B2" '
        'data-setup-id="F1a" data-member="nut1" data-workpiece="nut1" style="display:contents">'
        '<p class="variant-label">F1a final inspection after B2</p>'
        "<p>Original hoisted record "
        + _writing_field("reference observed")
        + '</p><p data-source-position="reference-only" style="break-before:page">'
        "Original final-reference continuation.</p>"
        '<p data-source-position="reference-mixed" style="break-before:page">'
        "Original reference tail before the physical route.</p></div></section>"
        + _setup("B0 stock cutoff", "B0", "stock", "<p>Original cutoff instruction.</p>")
        + _setup("Q4 facing hold", "Q4", "nut4", "<p>Original facing instruction.</p>")
        + '<section class="setup-flow" data-setup-title="F1a chronological final hold" '
        'data-setup-id="F1a" data-workpiece="nut1" style="break-before:page">'
        '<h2>F1a chronological final hold</h2><p data-source-position="chronological-final">'
        "Original final record in route order "
        + _writing_field("final observed")
        + "</p></section>"
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => ({
          positions:[...document.querySelectorAll('[data-source-position]')].map(node => ({
            key:node.dataset.sourcePosition,page:pageOf(node)
          })),
          heads:[...document.querySelectorAll('.cont-head')].map(head => ({
            page:pageOf(head),owners:JSON.parse(head.dataset.pageOwners),
            start:head.dataset.ownerRangeStart,end:head.dataset.ownerRangeEnd,
            continued:head.dataset.ownerContinued === 'true',
            range:head.querySelector('.cont-page-owners')?.textContent ?? '',
            local:head.querySelector('.cont-context')?.textContent ?? '',
            copies:head.querySelectorAll('[data-locator-target],.writing-blank').length
          })),
          fields:[...document.querySelectorAll('[data-locator-target]')].map(node => ({
            label:node.closest('.field').querySelector('.field-label').textContent,
            setup:node.closest('[data-setup-id]').dataset.setupId,
            workpiece:node.closest('[data-workpiece]').dataset.workpiece,
            reference:!!node.closest('[data-page-reference="final-inspection"]'),
            original:!node.closest('[data-job-print]')
          }))
        })""",
        prepare=f"() => {{ document.body.dataset.detail = {json.dumps(detail)}; }}",
    )
    pages = {position["key"]: position["page"] for position in details["positions"]}
    heads = {head["page"]: head for head in details["heads"]}
    reference_only = heads[pages["reference-only"]]
    assert reference_only["owners"] == []
    assert reference_only["start"] == reference_only["end"] == reference_only["range"] == ""
    assert not reference_only["continued"] and "after B2" in reference_only["local"]
    mixed = heads[pages["reference-mixed"]]
    assert [owner["setup"] for owner in mixed["owners"]] == ["B0", "Q4"]
    assert (mixed["start"], mixed["end"]) == ("B0", "Q4")
    assert mixed["range"].index("B0") < mixed["range"].index("Q4")
    assert not mixed["continued"] and "after B2" in mixed["local"]
    chronological = heads[pages["chronological-final"]]
    assert chronological["owners"] == [{"setup": "F1a", "member": "", "workpiece": "nut1"}]
    assert chronological["start"] == chronological["end"] == "F1a"
    assert not chronological["continued"]
    assert all(not head["copies"] for head in details["heads"])
    assert details["fields"] == [
        {
            "label": label,
            "setup": "F1a",
            "workpiece": "nut1",
            "reference": reference,
            "original": True,
        }
        for label, reference in (("reference observed", True), ("final observed", False))
    ]


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("container_class", ["inspection-method", "mixed-prose"])
def test_mixed_direct_prose_keeps_every_reading_and_tail_on_counted_pages(
    tmp_path, printed_sheet, detail, container_class
):
    words = _words("Method", 520).split()
    prose = " ".join(
        f'{word} <span class="reading">{index}.125 mm</span>' if index % 40 == 0 else word
        for index, word in enumerate(words)
    )
    expected = [
        token
        for index, word in enumerate(words)
        for token in ([word, f"{index}.125 mm"] if index % 40 == 0 else [word])
    ]
    source = _setup(
        SETUP_ONE,
        "S1",
        "nut1",
        '<p style="height:760px">Original inspection prelude.</p>'
        f'<div class="{container_class}" data-page-context="Inspection:">'
        '<span class="page-context">Inspection:</span> '
        + prose
        + " SafetyTailDoNotCut.</div><p>Original following work.</p>",
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const original = section.cloneNode(true);
          original.querySelectorAll('[data-job-print],.record-continuation')
            .forEach(node => node.remove());
          const starts = [section, ...section.querySelectorAll('.cont-head')]
            .map(node => node.getBoundingClientRect().top);
          const cap = Number(document.documentElement.dataset.pageCapacity);
          const walker = document.createTreeWalker(section, NodeFilter.SHOW_TEXT);
          const range = document.createRange(), escaped = [];
          let node;
          while ((node = walker.nextNode())) {
            if (!node.textContent.trim() || node.parentElement.closest(
              '[data-job-print],.record-continuation')) continue;
            range.selectNodeContents(node);
            for (const rect of range.getClientRects()) {
              const page = starts.findLastIndex(top => top <= rect.top + .1);
              if (rect.bottom > starts[page] + cap + .1) escaped.push(node.textContent);
            }
          }
          return {tokens:original.textContent.match(/Method\d{4}|\d+\.125 mm/g), escaped,
            tails:original.textContent.match(/SafetyTailDoNotCut/g),
            readings:[...original.querySelectorAll('.reading')].map(n => n.textContent)};
        }""",
        prepare=f"() => {{ document.body.dataset.detail = {json.dumps(detail)}; }}",
    )
    assert details["tokens"] == expected
    assert details["readings"] == [f"{index}.125 mm" for index in range(0, len(words), 40)]
    assert details["tails"] == ["SafetyTailDoNotCut"] and not details["escaped"]
    pages = printed_pages(_job(source, detail=detail), tmp_path)
    assert len(pages) > 1
    text = " ".join(" ".join(pages).split())
    assert re.findall(r"Method\d{4}|\d+\.125 mm", text) == expected
    assert text.count("SafetyTailDoNotCut") == 1


def test_worksheet_shaped_inspection_method_still_splits_its_readings_table(
    tmp_path, printed_sheet
):
    rows = "".join(
        f"<tbody><tr><td>Worksheet{index:03d}</td><td>12.700 mm</td></tr></tbody>"
        for index in range(90)
    )
    source = _setup(
        SETUP_ONE,
        "S1",
        "nut1",
        '<div class="inspection-method worksheet" data-page-context="Inspection readings"'
        ' data-worksheet-title="Inspection readings" data-reading-context="[]">'
        '<span class="page-context">Inspection readings</span>'
        '<table class="readings"><thead><tr><th>READINGS</th><th>Target</th></tr></thead>'
        + rows
        + "</table></div>",
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const tables = [...document.querySelectorAll('table.readings')];
          return {words:tables.flatMap(table => [...table.tBodies].flatMap(
            body => [...body.rows].map(row => row.cells[0].textContent))),
            pages:tables.map(pageOf),
            headers:tables.map(table => table.tHead.textContent)};
        }""",
        prepare="() => { document.body.dataset.detail = 'hobby'; }",
    )
    assert details["words"] == [f"Worksheet{index:03d}" for index in range(90)]
    assert len(set(details["pages"])) > 1
    assert all("READINGS" in header for header in details["headers"])
    pages = printed_pages(_job(source), tmp_path)
    assert re.findall(r"Worksheet\d{3}", " ".join(pages)) == details["words"]
    assert all("READINGS" in page for page in pages)


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
@pytest.mark.parametrize("page_count", [10, 18])
def test_final_page_total_fits_its_reserved_header_and_keeps_warnings_whole(
    tmp_path, printed_sheet, detail, page_count
):
    blocks = []
    for index in range(page_count):
        start = ' style="break-before:page"' if index else ""
        blocks.append(
            f'<div{start}><p style="height:{780 if index else 600}px">'
            f"OriginalPage{index:02d}</p>"
            f'<div class="decision stop"><p>Warning{index:02d}: '
            "STOP: preserve the complete holding and zero checks before cutting."
            "</p></div></div>"
        )
    source = _setup(SETUP_ONE, "S1", "nut1", "".join(blocks))
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const starts = [section, ...section.querySelectorAll('.cont-head')];
          const cap = Number(document.documentElement.dataset.pageCapacity);
          return {pages:Number(section.dataset.pages),
            headers:starts.slice(1).map(head => {
              const total = head.querySelector('.cont-page-total'), value = total.textContent;
              const geometry = () => ({height:head.getBoundingClientRect().height,
                width:total.getBoundingClientRect().width});
              const filled = geometry();
              total.textContent = '';
              const empty = geometry();
              total.textContent = value;
              const restored = geometry(), range = document.createRange();
              range.selectNodeContents(total);
              const ink = range.getBoundingClientRect(), box = total.getBoundingClientRect();
              return {value,filled,empty,restored,
                contained:ink.left >= box.left-.01 && ink.right <= box.right+.01
                  && ink.top >= box.top-.01 && ink.bottom <= box.bottom+.01};
            }),
            warnings:[...section.querySelectorAll('.decision.stop')].map(warning => {
              const page = pageOf(warning), bounds = warning.getBoundingClientRect();
              return {text:warning.textContent, page,
                fits:bounds.bottom <= starts[page].getBoundingClientRect().top+cap+.1};
            })};
        }""",
        prepare=f"() => {{ document.body.dataset.detail = {json.dumps(detail)}; }}",
    )
    assert details["pages"] == page_count
    assert len(details["headers"]) == page_count - 1
    for head in details["headers"]:
        assert head["value"] == str(page_count) and head["contained"]
        assert head["filled"] == head["empty"] == head["restored"]
        assert head["filled"]["width"] > 0
    assert [warning["page"] for warning in details["warnings"]] == list(range(page_count))
    assert all(warning["fits"] for warning in details["warnings"])
    pages = printed_pages(_job(source, detail=detail), tmp_path)
    assert len(pages) == page_count
    for index, page in enumerate(pages):
        assert re.findall(r"Warning\d{2}", page) == [f"Warning{index:02d}"]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_five_checkpoint_results_keep_order_and_full_size_counted_rows(
    tmp_path, printed_sheet, detail
):
    from prechips.sheet import _checkpoint_results, _Inspection

    records = [
        _Inspection(
            text="Original final acceptance criterion.",
            features=(f"feature-{index}",),
            requirement="length",
            subjects=(f"physical-{index}",),
            setup_id="S1",
            op_id=10,
            workpiece=f"checkpoint-nut-{index}",
        )
        for index in range(5)
    ]
    source = _setup(
        SETUP_ONE,
        "S1",
        "batch",
        '<p style="height:780px">Original final checkpoint criteria.</p>'
        + _checkpoint_results(records),
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const starts = [section, ...section.querySelectorAll('.cont-head')];
          const cap = Number(document.documentElement.dataset.pageCapacity);
          return [...section.querySelectorAll('.checkpoint-results')].map(row =>
            [...row.children].map(cell => {
              const blank = cell.querySelector('.writing-blank');
              const bounds = blank.getBoundingClientRect(), style = getComputedStyle(blank);
              const page = pageOf(cell), label = cell.querySelector('.field-label');
              return {ids:JSON.parse(cell.dataset.inspectionIds), feature:cell.dataset.feature,
                setup:cell.dataset.setupId, op:cell.dataset.opId, workpiece:cell.dataset.workpiece,
                page,top:cell.getBoundingClientRect().top,left:bounds.left,right:bounds.right,
                width:bounds.width-parseFloat(style.borderLeftWidth)-parseFloat(style.borderRightWidth),
                height:bounds.height-parseFloat(style.borderTopWidth)-parseFloat(style.borderBottomWidth),
                labelAbove:label.getBoundingClientRect().bottom <= bounds.top,
                fits:bounds.bottom <= starts[page].getBoundingClientRect().top+cap+.1,
                original:!cell.closest('[data-job-print]')};
            }));
        }""",
        prepare=f"() => {{ document.body.dataset.detail = {json.dumps(detail)}; }}",
    )
    cells = [cell for row in details for cell in row]
    assert [cell["ids"] for cell in cells] == [[f"physical-{index}"] for index in range(5)]
    for index, cell in enumerate(cells):
        assert cell["feature"] == f"feature-{index}"
        assert (cell["setup"], cell["op"], cell["workpiece"]) == (
            "S1",
            "10",
            f"checkpoint-nut-{index}",
        )
        assert cell["width"] >= 35 * 96 / 25.4 - 0.1
        assert cell["height"] >= 20 * 96 / 25.4 - 0.1
        assert cell["labelAbove"] and cell["fits"] and cell["original"]
    for row in details:
        assert 1 <= len(row) <= 4 and len({cell["page"] for cell in row}) == 1
        assert max(cell["top"] for cell in row) - min(cell["top"] for cell in row) < 0.1
        assert all(
            left["right"] <= right["left"] for left, right in zip(row, row[1:], strict=False)
        )
    pages = printed_pages(_job(source, detail=detail), tmp_path)
    assert len(pages) > 1
    text = " ".join(pages)
    assert all(f"checkpoint-nut-{index}" in text for index in range(5))


@pytest.mark.parametrize("detail", ["pro", "hobby"])
@pytest.mark.parametrize("word_count,counter_size", [(20, 16), (4200, 22)])
def test_first_page_and_continuations_share_actual_total_after_reflow(
    tmp_path, printed_sheet, detail, word_count, counter_size
):
    source = (
        '<p class="job-identity"><strong>Original compact identity</strong>'
        f'<span class="cont-count first-page-count" style="font-size:{counter_size}px;'
        'line-height:1.2"> · page 1 of <span class="cont-page-total"></span></span></p>'
        + _setup(
            SETUP_ONE,
            "S1",
            "nut1",
            f"<p>{_words('ReflowSource', word_count)}</p>",
        )
    )
    _, details = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const cap = Number(document.documentElement.dataset.pageCapacity);
          const starts = [section, ...section.querySelectorAll('.cont-head')]
            .map(node => node.getBoundingClientRect().top);
          const walker = document.createTreeWalker(section, NodeFilter.SHOW_TEXT);
          const range = document.createRange(), escaped = [];
          let node;
          while ((node = walker.nextNode())) {
            if (!node.textContent.trim() || node.parentElement.closest(
              '[data-job-print],.record-continuation')) continue;
            range.selectNodeContents(node);
            for (const rect of range.getClientRects()) {
              const page = starts.findLastIndex(top => top <= rect.top + .1);
              if (page < 0 || rect.bottom > starts[page]+cap+.1) {
                escaped.push(node.textContent);
              }
            }
          }
          return {pages:Number(section.dataset.pages),
            boundaries:starts.length, escaped,
            firstCounts:section.querySelectorAll('.first-page-count').length,
            counts:[...section.querySelectorAll('.cont-count')].map(count => {
              const total = count.querySelector('.cont-page-total'), value = total.textContent;
              const owner = count.closest('.job-identity,.cont-head'), page = pageOf(count);
              const geometry = () => ({width:total.getBoundingClientRect().width,
                height:owner.getBoundingClientRect().height});
              const filled = geometry();
              total.textContent = '';
              const empty = geometry();
              total.textContent = value;
              const restored = geometry(), range = document.createRange();
              range.selectNodeContents(total);
              const ink = range.getBoundingClientRect(), box = total.getBoundingClientRect();
              return {text:count.textContent, page, filled, empty, restored,
                fontSize:getComputedStyle(total).fontSize,
                contained:ink.left >= box.left-.01 && ink.right <= box.right+.01
                  && ink.top >= box.top-.01 && ink.bottom <= box.bottom+.01
                  && ink.top >= starts[page]-.1 && ink.bottom <= starts[page]+cap+.1};
            })};
        }""",
        prepare=f"() => {{ document.body.dataset.detail = {json.dumps(detail)}; }}",
    )
    assert details["firstCounts"] == 1
    assert not details["escaped"]
    assert details["boundaries"] == details["pages"] == len(details["counts"])
    assert details["counts"][0]["fontSize"] == f"{counter_size}px"
    for index, counter in enumerate(details["counts"], 1):
        match = re.search(r"\bpage\s+(\d+)\s+of\s+(\d+)\b", counter["text"])
        assert match and tuple(map(int, match.groups())) == (index, details["pages"])
        assert counter["page"] == index - 1 and counter["contained"]
        assert counter["filled"] == counter["empty"] == counter["restored"]
        assert counter["filled"]["width"] > 0
    pages = printed_pages(_job(source, detail=detail), tmp_path)
    if word_count == 20:
        assert len(pages) == 1
    else:
        assert len(pages) >= 10
    for index, page in enumerate(pages, 1):
        match = LABEL.search(page)
        assert match and tuple(map(int, match.groups())) == (index, len(pages))
    assert (
        re.findall(r"ReflowSource\d{4}", " ".join(pages))
        == _words("ReflowSource", word_count).split()
    )


@pytest.mark.parametrize("placement", ["duplicate", "later-page", "outside-identity"])
def test_malformed_first_page_count_prints_visible_refusal(tmp_path, printed_sheet, placement):
    count = (
        '<span class="cont-count first-page-count"> · page 1 of '
        '<span class="cont-page-total"></span></span>'
    )
    identity = '<p class="job-identity">Original compact identity' + count + "</p>"
    if placement == "duplicate":
        source = identity + identity
    elif placement == "later-page":
        prelude = f"<p>{_words('EarlierSource', 700)}</p>"
        source = prelude + identity
        control = prelude + '<p class="job-identity">ControlLaterIdentity</p>'
        _, placement_details = printed_sheet(
            control,
            """pageOf => ({
              identityPage:pageOf(document.querySelector('.job-identity')),
              boundaries:document.querySelectorAll('.cont-head').length
            })""",
            prepare="() => { document.body.dataset.detail = 'pro'; }",
        )
        assert placement_details["boundaries"] > 0
        assert placement_details["identityPage"] > 0
        control_pages = printed_pages(_job(control, detail="pro"), tmp_path)
        assert len(control_pages) > 1
        assert "ControlLaterIdentity" not in control_pages[0]
        assert sum("ControlLaterIdentity" in page for page in control_pages[1:]) == 1
    else:
        source = "<p>Not an identity" + count + "</p>"
    error = "A first-page count must be a single original identity on page 1."
    printed_sheet(
        source,
        "() => ({})",
        prepare="() => { document.body.dataset.detail = 'pro'; }",
        expected_error=error,
    )
    pages = printed_pages(_job(source, detail="pro"), tmp_path, expect_pagination_error=True)
    text = " ".join(" ".join(pages).split())
    assert "PRINT LAYOUT ERROR" in text and error in text


@pytest.mark.parametrize("detail", ["pro", "hobby"])
def test_first_page_total_is_reserved_before_boundary_fitting(tmp_path, detail):
    source = (
        '<p class="job-identity"><strong style="display:inline-block">Boundary identity</strong>'
        '<span class="cont-count first-page-count"> · page 1 of '
        '<span class="cont-page-total"></span></span></p>'
        '<div class="boundary-fill" style="height:0">Original boundary prelude.</div>'
        '<div class="decision stop boundary-tail"><p>'
        "BoundaryTailMustStayWhole: STOP before cutting.</p></div>"
    )
    prepare = r"""() => {
      const section = document.querySelector('section.page'),
        identity = section.querySelector('.job-identity'),
        title = identity.querySelector('strong'),
        count = identity.querySelector('.first-page-count'),
        filler = section.querySelector('.boundary-fill'),
        tail = section.querySelector('.boundary-tail');
      document.documentElement.classList.add('print-measuring');
      document.body.style.cssText =
        'max-width:none;width:var(--page-content-width);margin:0;padding:0';
      const measure = document.createElement('div');
      measure.style.cssText = 'position:absolute;width:var(--page-content-width);'
        + 'height:var(--page-content-height)';
      document.body.append(measure);
      const capacity = measure.getBoundingClientRect().height
        - parseFloat(getComputedStyle(document.documentElement)
          .getPropertyValue('--page-rounding'));
      measure.remove();
      // With an empty total the complete count fits on the identity's first line.
      // Reserving even one digit forces a measured extra line before source fit.
      title.style.width = (identity.getBoundingClientRect().width
        - count.getBoundingClientRect().width - 1) + 'px';
      filler.style.height = (capacity - .25
        - (tail.getBoundingClientRect().bottom - section.getBoundingClientRect().top)
        - parseFloat(getComputedStyle(tail).marginBottom)) + 'px';
    }"""
    html = _job(source, detail=detail).replace(
        "</body>", f"<script>addEventListener('DOMContentLoaded', {prepare});</script></body>"
    )
    pages = printed_pages(html, tmp_path)
    assert len(pages) == 2
    assert "BoundaryTailMustStayWhole" not in pages[0]
    assert "BoundaryTailMustStayWhole" in pages[1]
    for index, page in enumerate(pages, 1):
        match = LABEL.search(page)
        assert match and tuple(map(int, match.groups())) == (index, len(pages))


def _semantic_operation_source(*, oversized=False, steps=False, step_words=170):
    """Authored operation-card structure, with identities on source units only."""
    action = _words("Action", 1500) if oversized else "Advance across the supported face."
    details = (
        '<div class="op-speed" data-semantic-unit="speed"><dt>RPM</dt>'
        "<dd>420 rpm<br>Reduce to 260 rpm for the final interrupted cut.</dd></div>"
        '<div class="op-feed" data-semantic-unit="feed"><dt>Feed</dt>'
        '<dd><span class="box">STOP: no starting feed</span></dd></div>'
        '<div class="op-direction" data-semantic-unit="direction"><dt>Direction</dt>'
        "<dd>Clockwise viewed from the spindle nose.<br>"
        "Verify rotation before engaging the work.</dd></div>"
        '<div class="op-target" data-semantic-unit="feature"><dt>Feature</dt>'
        "<dd>North bearing relief<br>Leave the adjacent shoulder untouched.<br>"
        "Measure between the two indicated datum faces.</dd></div>"
    )
    note = ""
    if steps:
        items = "".join(
            f'<li data-semantic-unit="step-{index}">{_words(f"Step{index}Word", step_words)}'
            + (
                " Return to the first setup before recording the final result. "
                + _writing_field("step four result")
                if index == 4
                else ""
            )
            + "</li>"
            for index in range(1, 5)
        )
        note = (
            '<tr class="inspection-procedure" data-page-context="Inspection:"><td>'
            '<div class="inspection-method" data-page-context="Inspection:">'
            f'<span class="page-context">Inspection:</span><ol class="steps">{items}</ol>'
            "</div></td></tr>"
        )
    else:
        action += " " + _writing_field("operation observed")
    return _setup(
        SETUP_ONE,
        "S1",
        "nut1",
        "<div data-semantic-filler></div>"
        '<table class="operations"><thead><tr><th>Operation</th></tr></thead>'
        '<tbody class="operation" data-setup-id="S1" data-op="10" '
        'data-operation-context="S1 op 10 radial facing">'
        '<tr class="operation-main"><td>'
        '<div class="op-head" data-semantic-unit="heading">'
        '<h3><span class="op-number">10</span> Face at 0.35 mm radial per pass</h3></div>'
        f'<div class="op-action"><p data-semantic-unit="action">{action}</p></div>'
        f'<dl class="op-details">{details}</dl></td></tr>'
        + note
        + '<tr><td><figure class="fixture-render"><figcaption>Original setup diagram</figcaption>'
        f'<img src="{IMAGE}" width="240" height="120" '
        'style="display:block;width:240px;height:120px" alt="Radial facing datum">'
        "</figure></td></tr></tbody></table>",
    )


def _semantic_prepare(detail, remaining, *, authored_display=False):
    return f"""() => {{
      document.body.dataset.detail = {json.dumps(detail)};
      const root = document.documentElement, section = document.querySelector('section.page');
      if ({json.dumps(authored_display)}) {{
        section.style.setProperty('display', 'block', 'important');
      }}
      root.classList.add('print-measuring');
      document.body.style.cssText =
        'max-width:none;width:var(--page-content-width);margin:0;padding:0';
      const words = text => text.trim().split(/\\s+/).filter(Boolean);
      window.semanticExpected = [...section.querySelectorAll('[data-semantic-unit]')]
        .map(node => ({{key:node.dataset.semanticUnit, words:words(node.textContent)}}));
      window.semanticImages = [...section.querySelectorAll('figure img')];
      const measure = document.createElement('div');
      measure.style.cssText = 'position:absolute;width:var(--page-content-width);'
        + 'height:var(--page-content-height)';
      document.body.append(measure);
      const capacity = measure.getBoundingClientRect().height
        - parseFloat(getComputedStyle(root).getPropertyValue('--page-rounding'));
      measure.remove();
      const row = section.querySelector('.operation-main');
      const unit = {json.dumps(remaining)} === 'card'
        ? row : row.querySelector('.op-head');
      const filler = section.querySelector('[data-semantic-filler]');
      // Leave a nonempty prefix budget, but not enough for the measured unit.
      filler.style.height = Math.max(0, capacity
        - (row.getBoundingClientRect().top - section.getBoundingClientRect().top)
        - unit.getBoundingClientRect().height * .65) + 'px';
    }}"""


_SEMANTIC_SOURCE_LAYOUT = r"""pageOf => {
  const root = document.documentElement, section = document.querySelector('section.page');
  const snapshot = () => {
    const starts = [section, ...section.querySelectorAll('.cont-head')]
      .map(node => node.getBoundingClientRect().top);
    const cap = Number(root.dataset.pageCapacity);
    const sheetBounds = section.getBoundingClientRect();
    const original = node => !node.closest(
      '[data-job-print],.record-continuation,.fixed-locator-reference');
    const words = text => text.trim().split(/\s+/).filter(Boolean);
    const units = [...section.querySelectorAll('[data-semantic-unit]')].filter(original);
    const fragments = units.map(node => {
      const copy = node.cloneNode(true);
      copy.querySelectorAll('[data-job-print],.record-continuation,.fixed-locator-reference')
        .forEach(child => child.remove());
      return {key:node.dataset.semanticUnit, words:words(copy.textContent),
        page:pageOf(node), list:node.closest('ol') !== null};
    });
    const escaped = [], sourcePages = [];
    for (const unit of units) {
      const walker = document.createTreeWalker(unit, NodeFilter.SHOW_TEXT);
      const range = document.createRange();
      let node;
      while ((node = walker.nextNode())) {
        if (!node.textContent.trim() || !original(node.parentElement)) continue;
        range.selectNodeContents(node);
        for (const rect of range.getClientRects()) {
          const page = starts.findLastIndex(top => top <= rect.top + .1);
          sourcePages.push(page);
          if (page < 0 || rect.bottom > starts[page] + cap + .1
              || rect.left < sheetBounds.left - .1 || rect.right > sheetBounds.right + .1) {
            escaped.push(unit.dataset.semanticUnit);
          }
        }
      }
    }
    const atoms = (selector, canonical = null) =>
      [...section.querySelectorAll(selector)].map(node => {
      const rect = node.getBoundingClientRect(), page = pageOf(node);
      return {original:original(node), same:canonical ? canonical.includes(node) : null, page,
        fits:page >= 0 && rect.top >= starts[page] - .1
          && rect.bottom <= starts[page] + cap + .1
          && rect.left >= sheetBounds.left - .1 && rect.right <= sheetBounds.right + .1};
    });
    return {fragments, escaped, sourcePages, expected:window.semanticExpected,
      pages:Number(section.dataset.pages), boundaries:starts.length,
      display:{value:section.style.getPropertyValue('display'),
        priority:section.style.getPropertyPriority('display')},
      controls:atoms('.writing-blank'),
      images:atoms('figure img', window.semanticImages),
      figures:atoms('figure'),
      mainRows:[...section.querySelectorAll('.operation-main')].filter(original).length,
      contextCopies:[...section.querySelectorAll('[data-job-print] [data-semantic-unit]')].length};
  };
  return snapshot();
}"""


def _assert_semantic_source(layout, *, oversized=False, oversized_steps=()):
    expected = layout["expected"]
    fragments = layout["fragments"]
    assert [word for unit in fragments for word in unit["words"]] == [
        word for unit in expected for word in unit["words"]
    ]
    assert 1 < layout["pages"] < 30
    assert layout["boundaries"] == layout["pages"]
    assert not layout["escaped"]
    assert all(0 <= page < layout["pages"] for page in layout["sourcePages"])
    assert len(layout["controls"]) == len(layout["images"]) == len(layout["figures"]) == 1
    assert all(
        atom["original"] and atom["fits"]
        for atom in layout["controls"] + layout["images"] + layout["figures"]
    )
    assert all(image["same"] for image in layout["images"])
    for unit in expected:
        parts = [part for part in fragments if part["key"] == unit["key"]]
        if oversized and unit["key"] == "action":
            assert len(parts) > 1
            assert len({part["page"] for part in parts}) > 1
            assert all(part["words"] for part in parts)
        elif unit["key"] in oversized_steps:
            assert parts and all(part["words"] for part in parts)
            if len(parts) > 1:
                assert len({part["page"] for part in parts}) > 1
        else:
            assert len(parts) == 1, (unit["key"], parts)
            assert parts[0]["words"] == unit["words"]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_fitting_original_radial_heading_and_detail_card_move_whole(printed_sheet, detail):
    _, layout = printed_sheet(
        _semantic_operation_source(),
        _SEMANTIC_SOURCE_LAYOUT,
        prepare=_semantic_prepare(detail, "card"),
    )
    _assert_semantic_source(layout)
    assert layout["mainRows"] == 1
    card = [unit for unit in layout["fragments"] if not unit["key"].startswith("step-")]
    assert len({unit["page"] for unit in card}) == 1
    assert card[0]["page"] > 0


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_oversized_action_keeps_original_stop_and_multiline_detail_units(printed_sheet, detail):
    _, layout = printed_sheet(
        _semantic_operation_source(oversized=True),
        _SEMANTIC_SOURCE_LAYOUT,
        prepare=_semantic_prepare(detail, "heading"),
    )
    _assert_semantic_source(layout, oversized=True)
    # A full copied context must not satisfy the complete-original-unit assertions.
    assert layout["contextCopies"] > 0


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
@pytest.mark.parametrize("step_words", [140, 170])
def test_numbered_original_step_tail_keeps_its_result_destination(
    printed_sheet, detail, step_words
):
    _, layout = printed_sheet(
        _semantic_operation_source(steps=True, step_words=step_words),
        _SEMANTIC_SOURCE_LAYOUT,
        prepare=_semantic_prepare(detail, "card"),
    )
    # Independent measured layouts establish that only these 170-word pedantic
    # steps exceed a fresh page after mandatory context; 140-word steps fit.
    oversized_steps = ("step-1", "step-4") if detail == "pedantic" and step_words == 170 else ()
    _assert_semantic_source(layout, oversized_steps=oversized_steps)
    steps = [unit for unit in layout["fragments"] if unit["key"].startswith("step-")]
    assert {unit["key"] for unit in steps} == {f"step-{index}" for index in range(1, 5)}
    assert all(unit["list"] for unit in steps)
    if oversized_steps:
        assert len(steps) > 4
    assert len({unit["page"] for unit in steps}) > 1
    assert layout["controls"][0]["page"] == steps[-1]["page"]


@pytest.mark.parametrize("detail", ["pro", "hobby", "pedantic"])
def test_semantic_fragments_restore_original_units_across_repeated_beforeprint(
    printed_sheet, detail
):
    probe = _SEMANTIC_SOURCE_LAYOUT.replace(
        "return snapshot();",
        """const first = snapshot(), html = section.innerHTML;
  const height = root.style.getPropertyValue('--page-content-height');
  root.style.setProperty('--page-content-height', '40in');
  dispatchEvent(new Event('beforeprint'));
  const large = snapshot();
  root.style.setProperty('--page-content-height', '0.5in');
  dispatchEvent(new Event('beforeprint'));
  const refusal = {error:root.dataset.paginationError || null,
    display:{value:section.style.getPropertyValue('display'),
      priority:section.style.getPropertyPriority('display')}};
  if (height) root.style.setProperty('--page-content-height', height);
  else root.style.removeProperty('--page-content-height');
  dispatchEvent(new Event('beforeprint'));
  const second = snapshot(), restored = section.innerHTML === html;
  dispatchEvent(new Event('beforeprint'));
  const third = snapshot();
  return {first, large, refusal, second, third, restored,
    stable:JSON.stringify(first) === JSON.stringify(second)
      && JSON.stringify(second) === JSON.stringify(third)};""",
    )
    _, replay = printed_sheet(
        _semantic_operation_source(oversized=True),
        probe,
        prepare=_semantic_prepare(detail, "heading", authored_display=True),
    )
    assert replay["restored"] and replay["stable"]
    assert replay["large"]["pages"] < replay["first"]["pages"]
    assert replay["refusal"]["error"]
    assert replay["refusal"]["display"] == {"value": "block", "priority": "important"}
    for key in ("first", "second", "third"):
        _assert_semantic_source(replay[key], oversized=True)


@pytest.mark.parametrize("nested_owner", [False, True], ids=["co-located", "nested-owner-contract"])
def test_pedantic_long_later_setup_title_reserves_room_before_source_fitting(
    printed_sheet, nested_owner
):
    long_title = (
        "S2 secondary holding arrangement for the north bearing shoulder and south relief "
        "using protected jaws against the finished datum while supporting the free end "
        "through alignment verification radial clearance checks spindle direction confirmation "
        "tool approach inspection measured trial passes final size recording and release approval"
    )
    short_source = f"<p>{_positioned_words('ShortOwner', 700)}</p>"
    long_source = (
        f"<p>{_positioned_words('LongOwner', 1600)} "
        + _writing_field("long hold observed")
        + "</p>"
    )
    if nested_owner:
        # Integration contract: ownership attributes may live on different
        # ancestors, even though the current native producer co-locates them.
        # The forced-page origin is deliberately anonymous, not the title owner.
        source = _setup(
            SETUP_ONE,
            "S1",
            "nut1",
            short_source
            + '<div style="break-before:page">'
            + f'<div data-setup-title="{long_title}" data-member="nested-member" '
            'data-workpiece="nested-blank">' + long_source + "</div></div>",
        )
    else:
        source = _setup(SETUP_ONE, "S1", "nut1", short_source) + _setup(
            long_title, "S2", "nut2", long_source
        )
    _, layout = printed_sheet(
        source,
        r"""pageOf => {
          const section = document.querySelector('section.page');
          const heads = [...section.querySelectorAll('.cont-head')];
          const starts = [section, ...heads].map(node => node.getBoundingClientRect().top);
          const cap = Number(document.documentElement.dataset.pageCapacity);
          const bounds = section.getBoundingClientRect(), escaped = [];
          const original = node => !node.closest(
            '[data-job-print],.record-continuation,.fixed-locator-reference');
          const contained = (node, owner, source = false) => {
            const range = document.createRange();
            range.selectNodeContents(node);
            const box = owner.getBoundingClientRect();
            for (const rect of range.getClientRects()) {
              const page = starts.findLastIndex(top => top <= rect.top + .1);
              const top = source && page > 0
                ? heads[page - 1].getBoundingClientRect().bottom : starts[page];
              if (page < 0 || rect.top < top - .1 || rect.bottom > starts[page] + cap + .1
                  || rect.left < bounds.left - .1 || rect.right > bounds.right + .1
                  || (!source && (rect.top < box.top - .1 || rect.bottom > box.bottom + .1))) {
                escaped.push(node.textContent);
              }
            }
          };
          const positions = [...section.querySelectorAll('[data-source-position]')]
            .filter(original).map(node => {
              contained(node, node, true);
              return {key:node.dataset.sourcePosition, text:node.textContent, page:pageOf(node)};
            });
          const headers = heads.map(head => {
            const walker = document.createTreeWalker(head, NodeFilter.SHOW_TEXT);
            let node;
            while ((node = walker.nextNode())) {
              if (node.textContent.trim()) contained(node, head);
            }
            return {setup:head.dataset.setupId, page:pageOf(head),
              title:head.querySelector('.cont-title').textContent.replace(/\s+/g, ' ').trim(),
              height:head.getBoundingClientRect().height};
          });
          const controls = [...section.querySelectorAll('.writing-blank')].map(node => {
            const rect = node.getBoundingClientRect(), page = pageOf(node);
            return {original:original(node), page,
              fits:page >= 0 && rect.top >= starts[page] - .1
                && rect.bottom <= starts[page] + cap + .1};
          });
          return {positions, headers, controls, escaped, capacity:cap,
            pages:Number(section.dataset.pages), boundaries:starts.length};
        }""",
        prepare="() => { document.body.dataset.detail = 'pedantic'; }",
    )
    expected = _words("ShortOwner", 700).split() + _words("LongOwner", 1600).split()
    assert [position["key"] for position in layout["positions"]] == expected
    assert [position["text"] for position in layout["positions"]] == expected
    assert 2 < layout["pages"] < 30
    assert layout["boundaries"] == layout["pages"]
    assert not layout["escaped"]
    assert all(0 <= position["page"] < layout["pages"] for position in layout["positions"])
    long_pages = {
        position["page"]
        for position in layout["positions"]
        if position["key"].startswith("LongOwner")
    }
    short_heads = [
        head
        for head in layout["headers"]
        if head["setup"] == "S1" and head["page"] not in long_pages
    ]
    long_heads = [
        head
        for head in layout["headers"]
        if head["page"] in long_pages and (nested_owner or head["setup"] == "S2")
    ]
    assert short_heads and long_heads
    assert all(SETUP_ONE in head["title"] for head in short_heads)
    assert all(long_title in head["title"] for head in long_heads)
    if nested_owner:
        expected_identity = f"{long_title} · S1 · nested-member · nested-blank"
        assert all(
            head["setup"] == "S1" and expected_identity in head["title"] for head in long_heads
        )
    assert all(0 < head["height"] < layout["capacity"] for head in layout["headers"])
    assert len(long_pages) > 1
    assert len(layout["controls"]) == 1
    assert layout["controls"][0]["original"] and layout["controls"][0]["fits"]
    assert layout["controls"][0]["page"] in long_pages
