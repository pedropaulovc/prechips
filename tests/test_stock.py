import pytest
from test_cad import PLAN, prepare
from test_cli import PLAN as LITERAL_PLAN
from test_cli import stock_free_profile, with_diagram

from prechips.cli import main
from prechips.profiles import ProfileError, load_profile


def test_exact_fit_default_pro_writes_without_stock_report(tmp_path, capsys):
    plan, _ = prepare(tmp_path)
    out = tmp_path / "traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 0
    assert capsys.readouterr().err == ""
    html = out.read_text(encoding="utf-8")
    assert "Drawing" in html
    assert "stock_fit" not in html
    assert "certificate" not in html.lower()


@pytest.mark.parametrize(
    ("axis", "old", "new", "required_mm"),
    [
        ("length", "17.32", "17.319999", "439.928"),
        ("width", "5.5", "5.49", "139.7"),
        ("thickness", "0.47", "0.46", "11.938"),
    ],
)
def test_undersized_axis_preserves_existing_output(
    tmp_path, capsys, axis, old, new, required_mm
):
    text = PLAN.replace(f"blank_{axis}_in = {old}", f"blank_{axis}_in = {new}")
    plan, _ = prepare(tmp_path, plan_text=text)
    out = tmp_path / "traveler.html"
    out.write_bytes(b"Keep existing output")
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    error = capsys.readouterr().err
    assert f"stock_fit: {axis}:" in error
    assert f"declared {new} in" in error
    assert f"CAD requires {required_mm} mm" in error
    assert "Traceback" not in error
    assert out.read_bytes() == b"Keep existing output"


def test_stock_axes_are_not_rotated_even_when_volume_is_sufficient(tmp_path, capsys):
    text = PLAN.replace("blank_length_in = 17.32", "blank_length_in = 5.5")
    text = text.replace("blank_width_in = 5.5", "blank_width_in = 17.32")
    plan, _ = prepare(tmp_path, plan_text=text)
    out = tmp_path / "out/traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    assert "stock_fit: length:" in capsys.readouterr().err
    assert not out.parent.exists()


@pytest.mark.parametrize("profile", ["pro", "hobby"])
def test_builtin_profiles_require_cad_before_output(tmp_path, capsys, profile):
    plan = tmp_path / "plan.toml"
    plan.write_text(LITERAL_PLAN, encoding="utf-8")
    out = tmp_path / "out/traveler.html"
    assert main(["traveler", str(plan), "--out", str(out), "--profile", profile]) == 2
    assert "stock_fit: CAD is required" in capsys.readouterr().err
    assert not out.parent.exists()


@pytest.mark.parametrize(
    ("axis", "line"),
    [
        ("length", "blank_length_in = 17.32\n"),
        ("width", "blank_width_in = 5.5\n"),
        ("thickness", "blank_thickness_in = 0.47\n"),
    ],
)
def test_missing_blank_dimension_names_required_axis(tmp_path, capsys, axis, line):
    plan, _ = prepare(tmp_path, plan_text=PLAN.replace(line, ""))
    out = tmp_path / "traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    error = capsys.readouterr().err
    assert f"stock_fit: {axis}:" in error
    assert f"parameters.blank_{axis}_in" in error
    assert "inches; CAD requires" in error
    assert not out.exists()


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "true"])
def test_blank_dimension_must_be_finite_positive_number(tmp_path, capsys, value):
    text = PLAN.replace("blank_width_in = 5.5", f"blank_width_in = {value}")
    plan, _ = prepare(tmp_path, plan_text=text)
    out = tmp_path / "traveler.html"
    assert main(["traveler", str(plan), "--out", str(out)]) == 2
    assert "parameters.blank_width_in" in capsys.readouterr().err
    assert not out.exists()


def test_custom_profile_explicitly_omits_stock_fit(tmp_path):
    plan = tmp_path / "plan.toml"
    plan.write_text(LITERAL_PLAN, encoding="utf-8")
    profile = stock_free_profile(tmp_path)
    out = tmp_path / "traveler.html"
    assert main(["traveler", str(plan), "--out", str(out), "--profile", profile]) == 0
    assert "Bracket &lt;trial&gt;" in out.read_text(encoding="utf-8")


def test_hobby_exact_fit_still_requires_diagrams(tmp_path, capsys):
    plan, _ = prepare(tmp_path)
    out = tmp_path / "traveler.html"
    args = ["traveler", str(plan), "--out", str(out), "--profile", "hobby"]
    assert main(args) == 2
    assert "diagram" in capsys.readouterr().err
    (tmp_path / "setup.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8"
    )
    plan.write_text(with_diagram(PLAN, file="setup.svg"), encoding="utf-8")
    assert main(args) == 0
    assert "<img " in out.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("features", "enforce", "error"),
    [
        ([], ["stock_fit"], None),
        (["setup_diagrams"], ["stock_fit", "setup_diagrams"], None),
        (["stock_fit"], [], "profile.features: unknown requirement"),
        ([], ["setup_diagrams"], "must also be enabled"),
        ([], ["unknown"], "profile.enforce: unknown requirement"),
    ],
)
def test_custom_profile_requirements(tmp_path, features, enforce, error):
    profile = tmp_path / "profile.toml"
    profile.write_text(
        f'name = "Custom"\nfeatures = {features!r}\nenforce = {enforce!r}\n',
        encoding="utf-8",
    )
    if error:
        with pytest.raises(ProfileError, match=error):
            load_profile(str(profile))
    else:
        loaded = load_profile(str(profile))
        assert loaded.features == set(features)
        assert loaded.enforce == set(enforce)
