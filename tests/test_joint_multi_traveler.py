"""Emitted traveler wording for sequential bench joins, through-sockets and compound cure."""

import dataclasses
import html
import re

import pytest
from test_bench_routed_screens import NO_KERNEL, SCREENS
from test_joint_multi import compound, loaded_plan, three_component_plan

from prechips.sheet import render_traveler


def bench_plan(**unknown):
    """Body + boss braze at the bench (J), then the crank's spigot exterior is bonded through
    a through-socket on the body, adding the crank to that assembly at the bench (J2)."""
    plan = three_component_plan()
    plan["joint_features"]["crank_socket"]["thru"] = True
    for setup in plan["setups"]:
        if setup["id"] in {"J", "J2"}:
            setup["machine"] = "bench"
    compound(plan["setups"][-1]["joint"]).update(unknown)
    return plan


def traveler(tmp_path, plan):
    bundle = loaded_plan(tmp_path, plan)
    machines = {**bundle.inventory.get("machines", {}), "bench": {"kind": "bench"}}
    bundle = dataclasses.replace(
        bundle,
        inventory={**bundle.inventory, "machines": machines},
        kernel=dict(NO_KERNEL),
    )
    findings = [row for screen in SCREENS for row in screen.evaluate(bundle)]
    return findings, render_traveler(bundle, findings, {})


def paragraphs(page, sid):
    """Unescaped paragraph text of one setup's traveler page."""
    section = next(
        part for part in page.split('<section class="page">') if f"<h2>SETUP {sid} " in part
    )
    return [
        (css, html.unescape(text))
        for css, text in re.findall(r'<p(?: class="([^"]*)")?>(.*?)</p>', section, re.S)
    ]


def starts_from(page, sid):
    (line,) = [text for _, text in paragraphs(page, sid) if text.startswith("Starts from:")]
    return line


def test_sequential_bench_join_names_assembly_input_and_compound_cure(tmp_path):
    findings, page = traveler(tmp_path, bench_plan())
    # The declared bench fit keeps every DRO / spindle / travel screen inapplicable.
    for sid in ("J", "J2"):
        rows = [row for row in findings if row.subject == sid]
        assert len(rows) == len(SCREENS)
        assert all(row.status == "not_applicable" for row in rows)
    line = starts_from(page, "J2")
    # The two received references: an existing two-component assembly plus one component.
    for required in (
        "body + boss assembly",
        "Setup J",
        "crank from Setup C",
        "retaining compound",
        "through-socket crank socket",
        "clearance 0 to 0.25 mm diametral",
        "degrease and dry both mating surfaces",
        "cure time 1440 min",
        "do not disturb until cured",
    ):
        assert required in line
    assert not any(css == "stop" and "joint facts" in text for css, text in paragraphs(page, "J2"))


def test_through_socket_and_spigot_exterior_labels_keep_existing_kinds(tmp_path):
    _, page = traveler(tmp_path, bench_plan())
    text = html.unescape(page)
    assert "crank socket (through-socket bore on body): TEMPORARY JOINT FEATURE" in text
    assert "socket (socket bore on body): TEMPORARY JOINT FEATURE" in text
    assert "crank spigot (spigot exterior on crank): TEMPORARY JOINT FEATURE" in text


@pytest.mark.parametrize(
    "field, shown, name",
    [
        ("clearance_mm", "clearance ? mm diametral.", "clearance band"),
        ("surface_prep", "Surface prep: ? UNKNOWN (not declared).", "surface prep"),
        ("cure_time_min", "do not disturb until cured: cure time ? min UNKNOWN", "cure time"),
    ],
)
def test_unknown_compound_fact_stays_visible_debt(tmp_path, field, shown, name):
    _, page = traveler(tmp_path, bench_plan(**{field: "unknown"}))
    line = starts_from(page, "J2")
    assert shown in line
    assert "do not disturb until cured" in line
    stops = [text for css, text in paragraphs(page, "J2") if css == "stop"]
    assert any(name in text and "do not assemble" in text for text in stops)
    # The declared facts that are known still print; the unknown one never passes as a value.
    if field != "cure_time_min":
        assert "cure time 1440 min." in line
    else:
        assert "1440" not in line
    if field != "surface_prep":
        assert "degrease and dry both mating surfaces" in line
