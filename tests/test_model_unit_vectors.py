"""An authored inspection view's up and toward must be unit vectors, within the kernel's
pose tolerance (trig residue passes)."""

import math

import pytest
from pydantic import ValidationError

from prechips.model import InspectionView

MARK = [{"label": "datum A", "at_mm": [0.0, 0.0, 0.0]}]


def _view(up, toward=(1.0, 0.0, 0.0)):
    return InspectionView(title="side", up=list(up), toward=list(toward), marks=MARK)


def test_a_unit_up_with_trig_residue_is_accepted():
    angle = math.radians(30)
    _view((0.0, math.sin(angle), math.cos(angle)))


@pytest.mark.parametrize("up", [(0.0, 0.0, 2.0), (0.0, 0.0, 0.0), (0.0, 0.1, 1.0)])
def test_an_up_that_is_not_a_unit_vector_is_refused(up):
    with pytest.raises(ValidationError, match="'side' up must be a unit vector"):
        _view(up)
