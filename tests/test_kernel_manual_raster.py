"""Independent OCC controls for authored manual raster motion; no generated toolpaths.

The source trough and volume oracle use elementary cylinders, not the kernel's
sweep builders. Run only in the coordinated native gate; collection needs no OCC.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from prechips import kernel


_PROBE = r"""
import copy, hashlib, importlib.util, json, math, os, sys
import FreeCAD, Part
V = FreeCAD.Vector
out = sys.argv[sys.argv.index('--') + 1]
spec = importlib.util.spec_from_file_location('kernel_under_test', os.environ['KERNEL_SOURCE'])
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
runners = []
NativeSetup = job._Setup
class CaptureSetup(NativeSetup):
    def run(self):
        result = super().run()
        runners.append(self)
        return result
job._Setup = CaptureSetup
IDENTITY = {'origin': [0,0,0], 'x': [1,0,0], 'y': [0,1,0], 'z': [0,0,1]}
stock = Part.makeBox(10, 6, 4, V(0,-3,-4))
# An independently modeled semicircular trough, radius 1, length 10.
channel = Part.makeCylinder(1, 10, V(0,0,0), V(1,0,0))
target = stock.cut(channel).removeSplitter()
source = out + '/trough.step'
target.exportStep(source)
source_digest = hashlib.sha256(open(source, 'rb').read()).hexdigest()
live_ops = []

def rounded_channel(y, depth, corner=.2):
    # Independent boxes plus quarter cylinders, not a revolved cutter/silhouette.
    flat = 1-corner
    pieces = [
        Part.makeBox(10,2*flat,depth,V(0,y-flat,-depth)),
        Part.makeBox(10,2,depth-corner,V(0,y-1,-depth+corner)),
    ]
    for side in [-1,1]:
        centre = V(0,y+side*flat,-depth+corner)
        cylinder = Part.makeCylinder(corner,10,centre,V(1,0,0))
        clip = Part.makeBox(10,corner,corner,
            V(0,y+flat if side==1 else y-1,-depth))
        pieces.append(cylinder.common(clip))
    return pieces[0].multiFuse(pieces[1:]).removeSplitter()

stair_removal = rounded_channel(0,1).fuse(rounded_channel(2,2))
stair_target = stock.cut(stair_removal).removeSplitter()
process_target = Part.makeBox(10,6,2,V(0,-3,-4))
process_plane = {'kind':'end_face','label':'plan.process_features.waste',
                 'at_mm':[0,0,-1],'axis':[0,0,-1]}

def initialize(rotated=False, planar=False, stair=False, process=False):
    path = source
    frame = copy.deepcopy(IDENTITY)
    raw = {'shape':'box', 'origin_mm':[0,-3,-4], 'axis':[1,0,0],
           'section_axis':[0,1,0], 'length_mm':10, 'section_mm':[6,4]}
    if planar:
        path = out + '/planar.step'
        stock.exportStep(path)
    if stair:
        path = out + '/stair.step'
        stair_target.exportStep(path)
    if process:
        path = out + '/process.step'
        process_target.exportStep(path)
    if rotated:
        # Source stays immutable; setup and raw-stock coordinates transform together.
        frame.update(origin=[2,5,0], x=[0,1,0], y=[-1,0,0])
    payload = {'version':1, 'step_path':path,
               'step_sha256':hashlib.sha256(open(path,'rb').read()).hexdigest(),
               'features':{}, 'as_is_faces':[], 'stock':raw,
               'setups':[{'id':'S1', 'stock_in':'stock', 'frame':frame, 'ops':[]}]}
    if process:
        payload['process_features'] = {'waste':copy.deepcopy(process_plane)}
    result = job.run(payload)
    assert result['status'] == 'ok', result
    runner = runners[-1]
    assert runner.protection_reason is None
    # Explicit empty obstacle scene for these isolated geometry controls.
    runner.fixture_ready = True
    runner.fixture_reason = None
    runner.fixture_gaps = []
    runner.fixture_possible = []
    runner.fixture = []
    indices = [i for i,f in enumerate(runner.faces)
               if isinstance(f.Surface, Part.Cylinder)]
    if planar:
        indices = [i for i,f in enumerate(runner.faces)
                   if abs(f.BoundBox.ZMin) < 1e-7 and abs(f.BoundBox.ZMax) < 1e-7]
    if stair:
        indices = [i for i,f in enumerate(runner.faces)
                   if isinstance(f.Surface,Part.Plane)
                   and abs(f.BoundBox.ZMax-f.BoundBox.ZMin)<1e-7
                   and abs(f.BoundBox.ZMin+1)<1e-7]
    if process:
        indices = runner.owner.process_indices['waste']
    assert len(indices) == 1, indices
    return runner, indices[0]

def operation(runner, index, x0=-2, x1=12, tip=-1):
    points = [[x0,0,3], [x0,0,tip], [x1,0,tip], [x1,0,3]]
    points = [[v.x,v.y,v.z] for v in [runner.matrix.multVec(V(*p)) for p in points]]
    op = {'subject':'S1:raster'+str(len(live_ops)), 'do':'finish_profile', 'finishing':True,
          'contour_method':'manual_raster', 'tool_kind':'ball_endmill',
          'faces':[runner.owner.labels[index]], 'radius_mm':1, 'nose_radius_mm':1,
          'flute_len_mm':4, 'shank_radius_mm':1, 'shank_from_mm':4,
          'projection_mm':6, 'holder_radius_mm':2, 'holder_gauge_len_mm':2, 'oal_mm':10,
          'shank_geometry':'cylinder',
          'rough_allowance_mm':0,
          'manual_raster':{'start_mm':points[0], 'safe_z_mm':3,
                           'moves':[{'to_mm':p, 'mode':m} for p,m in
                                    zip(points[1:], ['clear','cut','clear'])]}}
    live_ops.append(op)
    return op

def build(runner, ops):
    runner.ops = ops
    runner.built = runner._build()
    return [runner._op(op) for op in ops]

def coverage(runner):
    runner.owner.manual_raster_portions = {'cut':{}, 'finish':{}}
    runner.owner._collect_manual_raster_portions(runner)
    return {kind:runner.owner._manual_raster_coverage(records)
            for kind,records in runner.owner.manual_raster_portions.items()}

def difference(a,b):
    return a.cut(b).Volume + b.cut(a).Volume

result = {'positive':{}}
for name, rotated in [('identity',False), ('rotated',True)]:
    runner,index = initialize(rotated)
    op = operation(runner,index)
    facts = build(runner,[op])[0]
    after = runner.cuts[id(op)][1]
    expected = target.copy()
    expected.transformShape(runner.matrix)
    result['positive'][name] = {
        'facts':facts, 'reason':runner.built[1],
        'difference':difference(after,expected),
        'removed':runner.cuts[id(op)][0].Volume-after.Volume,
        'coverage':coverage(runner), 'index':index,
        'source_unchanged':hashlib.sha256(open(source,'rb').read()).hexdigest()==source_digest,
        'source_target_difference':difference(runner.owner.solid,target),
    }

runner,index = initialize()
op = operation(runner,index)
del op['oal_mm']
result['optional_oal'] = {
    'facts':build(runner,[op])[0],
    'difference':difference(runner.cuts[id(op)][1],target),
    'coverage':coverage(runner), 'index':index,
}

# Exact rounded-flat stair geometry differs physically from the same ball path.
result['stairs'] = {}
for kind,corner in [('endmill',.2),('ball_endmill',1)]:
    runner,index = initialize(stair=True)
    op = operation(runner,index)
    floors = [i for i,f in enumerate(runner.faces)
              if isinstance(f.Surface,Part.Plane)
              and abs(f.BoundBox.ZMax-f.BoundBox.ZMin)<1e-7
              and any(abs(f.BoundBox.ZMin+z)<1e-7 for z in [1,2])]
    assert len(floors)==2, floors
    op.update(tool_kind=kind,nose_radius_mm=corner,
              faces=[runner.owner.labels[i] for i in floors])
    op['manual_raster']['moves'].extend([
        {'to_mm':[12,2,3],'mode':'clear'},
        {'to_mm':[12,2,-2],'mode':'clear'},
        {'to_mm':[-2,2,-2],'mode':'cut'},
        {'to_mm':[-2,2,3],'mode':'clear'},
    ])
    facts = build(runner,[op])[0]
    before,after,_ = runner.cuts[id(op)]
    result['stairs'][kind] = {
        'facts':facts,'removed':before.Volume-after.Volume,
        'difference':difference(after,stair_target),
        'coverage':coverage(runner),'floors':floors,
    }

profile = job._raster_rounded_profile(1,.2,4)
rounded = job._raster_rounded(1,.2,4,[-2,0,-1],[12,0,-1],profile)
vertical_rounded = job._raster_rounded(1,.2,4,[-2,0,3],[-2,0,-1],profile)
pose_volume = math.pi*((.8**2)*.2 + .8*math.pi*(.2**2)/2 + 2*(.2**3)/3 + 3.8)
silhouette_area = 8+(math.pi/2-2)*(.2**2)
result['rounded_shape'] = {
    'valid':rounded.isValid(),'volume':rounded.Volume,
    'expected':pose_volume+14*silhouette_area,
    'vertical_volume':vertical_rounded.Volume,'vertical_expected':pose_volume+4*math.pi,
}

# Non-unit geometry control, not a claim that any physical cutter was measured.
r,c,flute,length = 19.05/2,.127,33.3,40
profile = job._raster_rounded_profile(r,c,flute)
scaled = job._raster_rounded(r,c,flute,[-10,0,-1],[30,0,-1],profile)
pose_volume = math.pi*((r-c)**2*c + (r-c)*math.pi*c*c/2 + 2*c**3/3 + r*r*(flute-c))
silhouette_area = 2*r*flute + (math.pi/2-2)*c*c
result['scaled_rounded_shape'] = {
    'valid':scaled.isValid(), 'volume':scaled.Volume,
    'expected':pose_volume+length*silhouette_area,
}

result['process'] = {}
for case in ['valid','missing_plane','placement_mismatch','nonzero_leave','unknown_leave','missing_leave','negative_leave','nonfinite_leave','boolean_leave','finished_claim','below_plane']:
    runner,index = initialize(process=True)
    op = operation(runner,index)
    op.pop('faces')
    op.update(feature='waste',do='profile',tool_kind='endmill',nose_radius_mm=.2,
              process_cut={'process_feature':'waste','action':'profile',**copy.deepcopy(process_plane)})
    if case=='missing_plane': del runner.owner.job['process_features']['waste']
    elif case=='placement_mismatch': op['process_cut']['at_mm'][2]=-.5
    elif case=='nonzero_leave': op['rough_allowance_mm']=.1
    elif case=='unknown_leave': op['rough_allowance_mm']='unknown'
    elif case=='missing_leave': op.pop('rough_allowance_mm')
    elif case=='negative_leave': op['rough_allowance_mm']=-.1
    elif case=='nonfinite_leave': op['rough_allowance_mm']=float('nan')
    elif case=='boolean_leave': op['rough_allowance_mm']=False
    elif case=='finished_claim': op['faces']=[runner.owner.labels[0]]
    elif case=='below_plane': op['process_cut']['at_mm'][2]=0; runner.owner.job['process_features']['waste']['at_mm'][2]=0
    facts = build(runner,[op])[0]
    before,after,_ = runner.cuts[id(op)]
    result['process'][case] = {
        'facts':facts,'reason':runner.built[1],
        'difference':difference(after,stock.cut(rounded_channel(0,1))),
        'unchanged':difference(before,after),'coverage':coverage(runner),
        'source_loss':process_target.cut(after).Volume,
        'remote_stock_left':Part.makeBox(10,1,1,V(0,-3,-1)).common(after).Volume,
    }

# Independent full occupied-volume arithmetic, not just an in-stock cross-section.
a,b = [-2,0,-1],[12,0,-1]
sweep = job._raster_ball(1,4,a,b)
# Swept lower hemisphere = half cylinder + sphere; upper flute = planar capsule * 3.
expected_volume = math.pi*14/2 + 2*math.pi/3 + (2*14+math.pi)*3
# A point below the hemisphere skirt is in a flat-end proxy but not in the real cutter.
result['shape'] = {'volume':sweep.Volume, 'expected_volume':expected_volume,
                   'flat_skirt_inside':sweep.isInside(V(5,.95,-.9),1e-7,True)}
vertical = job._raster_ball(1,4,[-2,0,3],[-2,0,-1])
result['shape']['vertical_volume'] = vertical.Volume
result['shape']['vertical_expected'] = 2*math.pi/3 + math.pi*7

runner,index = initialize()
op = operation(runner,index,tip=-1.2)
result['gouge'] = build(runner,[op])[0]
result['gouge']['unchanged'] = difference(*runner.cuts[id(op)][:2])

result['rough'] = {}
for name, tip in [('clear',-.5),('normal_leave_intrusion',-1)]:
    runner,index = initialize()
    op = operation(runner,index,tip=tip)
    op['rough_allowance_mm'] = .1
    op['do'] = 'rough_profile'
    op['finishing'] = False
    result['rough'][name] = build(runner,[op])[0]

runner,index = initialize()
op = operation(runner,index)
op.update(flute_len_mm=1, shank_from_mm=1, shank_radius_mm=2)
raised_stock = Part.makeBox(1,1,3,V(4,1.2,0))
runner._use(runner.part.fuse(raised_stock))
result['shank_stock'] = build(runner,[op])[0]
result['shank_stock']['swept_volume'] = sum(
    pieces['shank'].Volume for _,pieces in runner.manual_rasters[id(op)]['sweeps'])
runner,index = initialize()
op = operation(runner,index)
op.update(flute_len_mm=1, shank_from_mm=1, shank_radius_mm=2,
          shank_geometry='enclosing_cylinder',shank_envelope_radius_mm=2)
runner._use(runner.part.fuse(raised_stock))
result['shank_bound_stock'] = build(runner,[op])[0]
result['shank_bound_stock']['swept_volume'] = sum(
    pieces['shank'].Volume for _,pieces in runner.manual_rasters[id(op)]['sweeps'])
result['shank_bound_stock']['unchanged'] = difference(*runner.cuts[id(op)][:2])

result['shank_bound_fixture'] = {}
for exact_holder_hit in [False,True]:
    runner,index = initialize()
    op = operation(runner,index)
    op.update(flute_len_mm=1, shank_from_mm=1, shank_radius_mm=2,
              shank_geometry='enclosing_cylinder',shank_envelope_radius_mm=2)
    obstacles = [('possible neck obstruction',Part.makeBox(1,1,1,V(4,1.2,2)))]
    if exact_holder_hit:
        obstacles.append(('certain holder obstruction',Part.makeBox(1,1,1,V(4,1.2,5.5))))
    runner.fixture = [{'name':name,'envelope':shape,'envelope_bbox':job._bbox(shape)}
                      for name,shape in obstacles]
    result['shank_bound_fixture'][str(exact_holder_hit)] = build(runner,[op])[0]

runner,index = initialize()
op = operation(runner,index)
op.update(shank_geometry='enclosing_cylinder',shank_envelope_radius_mm=1)
result['shank_bound_clear'] = build(runner,[op])[0]

runner,index = initialize()
op = operation(runner,index)
fixture = Part.makeBox(1,1,1,V(4,1.2,5.5))
runner.fixture = [{'name':'independent clamp', 'envelope':fixture,
                   'envelope_bbox':job._bbox(fixture)}]
result['fixture'] = build(runner,[op])[0]

# A clear descent into stock must fail even though the FUTURE cut sweeps that stock.
runner,index = initialize()
op = operation(runner,index,x0=5)
result['entry'] = build(runner,[op])[0]
result['entry']['unchanged'] = difference(*runner.cuts[id(op)][:2])

# Entire safe-Z index is physical motion too, not just its endpoints.
runner,index = initialize()
op = operation(runner,index)
op['manual_raster']['moves'].append({'to_mm':[-2,0,3], 'mode':'clear'})
fixture = Part.makeBox(.5,.5,1,V(4,1.2,9.5))
runner.fixture = [{'name':'lifted bridge', 'envelope':fixture,
                   'envelope_bbox':job._bbox(fixture)}]
result['lifted_fixture'] = build(runner,[op])[0]

# A partially cut trough retains debt; complementary source-face portions union exactly.
runner,index = initialize()
first, second = operation(runner,index,x1=5), operation(runner,index,x0=12,x1=5)
facts = build(runner,[first])[0]
result['partial'] = {'facts':facts, 'coverage':coverage(runner), 'index':index}
runner,index = initialize()
first, second = operation(runner,index,x1=5), operation(runner,index,x0=12,x1=5)
facts = build(runner,[first,second])
result['union'] = {'facts':facts, 'coverage':coverage(runner), 'index':index,
                   'difference':difference(runner.cuts[id(second)][1],target)}

# Summed patch areas exceed the whole face, but duplicate/overlap portions do not.
runner,index = initialize()
overlapping = [operation(runner,index,x1=end) for end in [5,5,7]]
facts = build(runner,overlapping)
result['overlap'] = {
    'facts':facts, 'coverage':coverage(runner), 'index':index,
    'duplicate_stock_change':difference(*runner.cuts[id(overlapping[1])][:2]),
}

# Tangent contact with a plane is a curve: no projected-disc/full-face coverage.
runner,index = initialize(planar=True)
op = operation(runner,index,tip=0)
result['tangent'] = {'facts':build(runner,[op])[0], 'coverage':coverage(runner), 'index':index}

result['unknown'] = {}
for name in ['dimension','nose','missing_nose','missing_shank_geometry','missing_body_bound','undersized_body_bound','undersized_transition_bound','short_oal','diagonal','nonfinite','unknown_method','retired_method','missing_path','hand_action','unknown_fixture','unknown_kind','missing_kind','idealized_corner','oversized_corner','endmill_ball_corner']:
    runner,index = initialize()
    op = operation(runner,index)
    if name=='dimension': del op['shank_radius_mm']
    elif name=='nose': op['nose_radius_mm']=.5
    elif name=='missing_nose': op.pop('nose_radius_mm')
    elif name=='missing_shank_geometry': op.pop('shank_geometry')
    elif name=='missing_body_bound': op['shank_geometry']='enclosing_cylinder'
    elif name=='undersized_body_bound':
        op.update(shank_geometry='enclosing_cylinder',shank_radius_mm=2,
                  shank_envelope_radius_mm=1.5)
    elif name=='undersized_transition_bound':
        op.update(shank_geometry='enclosing_cylinder',radius_mm=2,nose_radius_mm=2,
                  shank_envelope_radius_mm=1)
    elif name=='short_oal': op['oal_mm']=5
    elif name=='diagonal': op['manual_raster']['moves'][1]['to_mm'][1]=1
    elif name=='nonfinite': op['manual_raster']['start_mm'][0]=float('nan')
    elif name=='unknown_method': op['contour_method']='unsupported'; op.pop('manual_raster')
    elif name=='retired_method': op['contour_method']='manual_ball_raster'
    elif name=='missing_path': op.pop('manual_raster')
    elif name=='hand_action': op['do']='hand_file'
    elif name=='unknown_fixture': runner.fixture_gaps=['unmeasured clamp']
    elif name=='unknown_kind': op['tool_kind']='bullnose'
    elif name=='missing_kind': op.pop('tool_kind')
    elif name=='idealized_corner': op.update(tool_kind='endmill',nose_radius_mm=0)
    elif name=='oversized_corner': op.update(tool_kind='endmill',nose_radius_mm=1.2)
    elif name=='endmill_ball_corner': op.update(tool_kind='endmill',nose_radius_mm=1)
    facts=build(runner,[op])[0]
    result['unknown'][name]={'facts':facts, 'reason':runner.built[1],
                              'unchanged':difference(*runner.cuts[id(op)][:2])}

# Earlier unproven stock does not suppress a later independent fixture collision.
runner,index=initialize()
first,second=operation(runner,index),operation(runner,index)
del first['shank_radius_mm']
fixture=Part.makeBox(1,1,1,V(4,1.2,5.5))
runner.fixture=[{'name':'independent clamp','envelope':fixture,'envelope_bbox':job._bbox(fixture)}]
result['independent_after_unknown']=build(runner,[first,second])[1]

with open(out+'/manual-raster.json','w',encoding='utf-8') as handle:
    json.dump(result,handle)
"""


@pytest.fixture(scope="module")
def raster_native(tmp_path_factory, freecad_kernel):
    directory = tmp_path_factory.mktemp("manual-raster")
    script = directory / "probe.py"
    script.write_text(_PROBE, encoding="utf-8")
    source = Path(kernel.__file__).with_name("freecad_job.py")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(directory)],
        capture_output=True,
        text=True,
        errors="replace",
        timeout=300,
        env={**os.environ, "KERNEL_SOURCE": str(source)},
    )
    report = directory / "manual-raster.json"
    assert report.exists(), process.stdout[-4000:] + process.stderr[-4000:]
    return json.loads(report.read_text(encoding="utf-8"))


@pytest.mark.parametrize("scene", ["identity", "rotated"])
def test_actual_ball_cut_matches_independent_trough(raster_native, scene):
    row = raster_native["positive"][scene]
    assert row["reason"] is None
    assert row["facts"]["manual_raster_status"] == "pass"
    assert row["facts"]["manual_raster_checked_moves"] == 3
    assert row["difference"] == pytest.approx(0, abs=1e-6)
    assert row["removed"] == pytest.approx(5 * 3.141592653589793, abs=1e-6)
    assert row["source_unchanged"]
    assert row["source_target_difference"] == pytest.approx(0, abs=1e-6)
    assert row["coverage"]["finish"]["complete_indices"] == [row["index"]]


def test_measured_visible_envelope_does_not_require_unmeasured_oal(raster_native):
    row = raster_native["optional_oal"]
    assert row["facts"]["manual_raster_status"] == "pass"
    assert row["facts"]["manual_raster_checked_moves"] == 3
    assert row["difference"] == pytest.approx(0, abs=1e-6)
    assert row["coverage"]["finish"]["complete_indices"] == [row["index"]]


def test_rounded_flat_sweep_matches_independent_profile_integrals(raster_native):
    row = raster_native["rounded_shape"]
    assert row["valid"]
    assert row["volume"] == pytest.approx(row["expected"], abs=1e-6)
    assert row["vertical_volume"] == pytest.approx(row["vertical_expected"], abs=1e-6)
    scaled = raster_native["scaled_rounded_shape"]
    assert scaled["valid"]
    assert scaled["volume"] == pytest.approx(scaled["expected"], rel=1e-9, abs=1e-5)


def test_rounded_flat_stairs_and_ball_have_distinct_exact_removal_and_coverage(raster_native):
    rounded, ball = raster_native["stairs"]["endmill"], raster_native["stairs"]["ball_endmill"]
    assert rounded["facts"]["manual_raster_status"] == ball["facts"]["manual_raster_status"] == "pass"
    assert rounded["difference"] == pytest.approx(0, abs=1e-6)
    assert rounded["removed"] == pytest.approx(60+20*(3.141592653589793/2-2)*.2**2, abs=1e-6)
    assert ball["removed"] == pytest.approx(20+10*3.141592653589793, abs=1e-6)
    assert ball["difference"] > 8
    assert rounded["coverage"]["finish"]["complete_indices"] == sorted(rounded["floors"])
    assert ball["coverage"]["finish"]["complete_indices"] == []
    assert len(ball["coverage"]["finish"]["gaps"]) == 2


def test_transient_end_plane_raster_removes_only_authored_stock_without_source_credit(raster_native):
    row = raster_native["process"]["valid"]
    assert row["reason"] is None
    assert row["facts"]["manual_raster_status"] == "pass"
    assert row["facts"]["claimed_indices"] == []
    assert row["facts"]["manual_raster_process_feature"] == "waste"
    assert row["difference"] == row["source_loss"] == pytest.approx(0, abs=1e-6)
    assert row["remote_stock_left"] == pytest.approx(10, abs=1e-6)
    assert row["coverage"] == {
        kind: {"complete_indices": [], "gaps": [], "unknown": []}
        for kind in ("cut", "finish")
    }


def test_transient_plane_identity_and_allowance_do_not_borrow_source_ownership(raster_native):
    for name, row in raster_native["process"].items():
        if name == "valid":
            continue
        assert row["reason"], name
        assert row["facts"]["manual_raster_status"] == "unknown", name
        assert row["unchanged"] == pytest.approx(0, abs=1e-6), name
        assert row["facts"]["claimed_indices"] == "unknown", name


def test_hemisphere_and_cylindrical_flute_not_flat_fallback(raster_native):
    row = raster_native["shape"]
    assert row["volume"] == pytest.approx(row["expected_volume"], abs=1e-6)
    assert row["vertical_volume"] == pytest.approx(row["vertical_expected"], abs=1e-6)
    assert not row["flat_skirt_inside"]


@pytest.mark.parametrize("name", ["gouge", "entry"])
def test_real_material_collision_never_clears_stock(raster_native, name):
    row = raster_native[name]
    assert row["manual_raster_status"] == "error"
    assert row["min_hits"]["tool"] > 0
    assert row["stock_removal_error"]
    assert row["unchanged"] == pytest.approx(0, abs=1e-6)
    if name == "entry":
        assert row["manual_raster_checked_moves"] == 1


@pytest.mark.parametrize("name", ["fixture", "lifted_fixture", "independent_after_unknown"])
def test_holder_fixture_collision_is_independent_and_continuous(raster_native, name):
    row = raster_native[name]
    assert row["manual_raster_status"] == "error"
    assert row["min_hits"]["holder"] > 0
    assert row["obstacles"]["holder"]


def test_partial_face_credit_is_exact_and_complementary_portions_union(raster_native):
    partial, union = raster_native["partial"], raster_native["union"]
    assert partial["facts"]["manual_raster_status"] == "pass"
    assert partial["facts"]["claimed_indices"] == []
    assert partial["facts"]["manual_raster_partial_indices"] == [partial["index"]]
    assert partial["coverage"]["cut"]["complete_indices"] == []
    assert partial["coverage"]["cut"]["gaps"][0]["uncovered_area_mm2"] > 1
    assert all(row["claimed_indices"] == [] for row in union["facts"])
    assert union["coverage"]["finish"]["complete_indices"] == [union["index"]]
    assert union["difference"] == pytest.approx(0, abs=1e-6)


def test_duplicate_and_overlapping_passes_never_sum_into_full_face_credit(raster_native):
    row = raster_native["overlap"]
    assert all(fact["manual_raster_status"] == "pass" for fact in row["facts"])
    assert all(fact["claimed_indices"] == [] for fact in row["facts"])
    assert row["duplicate_stock_change"] == pytest.approx(0, abs=1e-6)
    assert row["coverage"]["finish"]["complete_indices"] == []
    assert row["coverage"]["finish"]["unknown"] == []
    assert row["coverage"]["finish"]["gaps"][0]["uncovered_area_mm2"] == pytest.approx(
        3 * 3.141592653589793, abs=1e-5
    )


def test_tangent_curve_is_not_surface_coverage(raster_native):
    row = raster_native["tangent"]
    assert row["facts"]["manual_raster_status"] == "pass"
    assert row["facts"]["claimed_indices"] == []
    assert row["facts"]["manual_raster_coverage"][0]["covered_area_mm2"] == 0
    assert row["coverage"]["finish"]["gaps"][0]["uncovered_area_mm2"] == pytest.approx(60)


def test_incomplete_or_unsupported_geometry_fails_closed(raster_native):
    for name, row in raster_native["unknown"].items():
        assert row["reason"], name
        assert row["facts"]["claimed_indices"] == "unknown", name
        assert row["unchanged"] == pytest.approx(0, abs=1e-6), name
        assert not row["facts"].get("stock_removal_error"), name


def test_curved_claim_normal_leave_uses_exact_offset_skin(raster_native):
    assert raster_native["rough"]["clear"]["manual_raster_status"] == "pass"
    intrusion = raster_native["rough"]["normal_leave_intrusion"]
    assert intrusion["manual_raster_status"] == "error"
    assert intrusion["min_hits"]["tool"] > 0
    assert "normal leave" in intrusion["stock_removal_error"]


def test_noncutting_shank_checks_actual_predecessor_stock(raster_native):
    row = raster_native["shank_stock"]
    assert row["manual_raster_status"] == "error"
    assert row["min_hits"]["shank"] > 0
    assert "part" in row["obstacles"]["shank"]


def test_enclosing_shank_overlap_is_unknown_not_a_certain_collision(raster_native):
    bound, exact = raster_native["shank_bound_stock"], raster_native["shank_stock"]
    assert bound["manual_raster_status"] == "unknown"
    assert bound["min_hits"]["shank"] == 0
    assert bound["shank_envelope_hits"] > 0
    assert bound["possible_shank_obstacles"] == ["part"]
    assert not bound.get("stock_removal_error")
    assert bound["swept_volume"] == pytest.approx(exact["swept_volume"], abs=1e-6)
    assert bound["unchanged"] == pytest.approx(0, abs=1e-6)
    fixture = raster_native["shank_bound_fixture"]["False"]
    assert fixture["manual_raster_status"] == "unknown"
    assert fixture["min_hits"]["shank"] == 0
    assert fixture["possible_shank_obstacles"]
    certain = raster_native["shank_bound_fixture"]["True"]
    assert certain["manual_raster_status"] == "error"
    assert certain["min_hits"]["holder"] > 0
    assert certain["min_hits"]["shank"] == 0


def test_enclosing_shank_zero_overlap_proves_clearance(raster_native):
    row = raster_native["shank_bound_clear"]
    assert row["manual_raster_status"] == "pass"
    assert row["shank_geometry"] == "enclosing_cylinder"
    assert row["shank_hits"] == row["shank_envelope_hits"] == 0


_PLACED_COVERAGE = r"""
import hashlib
from types import SimpleNamespace
source_file = out / 'immutable-source.step'
source.exportStep(str(source_file))
digest = hashlib.sha256(source_file.read_bytes()).hexdigest()
runner = module['_Setup'].__new__(module['_Setup'])
runner.owner = SimpleNamespace(
    job={}, raster_source_solid=source, raster_placement_facts=facts, face_solids={}
)
runner.matrix = App.Matrix()
runner.state = {}
rows = []
for item in facts[0]['provenance']:
    if item['change'] != 'translated':
        continue
    index = item['index']
    portion = placed.Faces[index].common(Part.makeBox(30,40,13.5,V(-15,0,-11)))
    if portion.isNull() or portion.Area < 1e-6:
        continue
    mapped = runner._manual_raster_source_portion(index, portion)
    expected_portion = source.Faces[index].common(Part.makeBox(30,40,13.5,V(-15,0,-11)))
    rows.append({
        'index':index,
        'extra':mapped.cut(expected_portion).Area,
        'missing':expected_portion.cut(mapped).Area,
        'area':mapped.Area,
    })
assert rows and any(row['area'] > 1 for row in rows)
refused = []
for item in facts[0]['provenance']:
    if item['change'] != 'retrimmed':
        continue
    try:
        runner._manual_raster_source_portion(item['index'], placed.Faces[item['index']])
    except module['_Unknown'] as exc:
        refused.append(str(exc))
    else:
        raise AssertionError('retrimmed source face earned fabricated identity transfer')
assert refused
runner.owner.job['aimed_faces'] = [{'face':'changed'}]
try:
    runner._manual_raster_source_portion(rows[0]['index'], placed.Faces[rows[0]['index']])
except module['_Unknown'] as exc:
    aimed_reason = str(exc)
else:
    raise AssertionError('unsupported aimed-face transfer earned source coverage')
(out/'raster-placement.json').write_text(json.dumps({
    'rows':rows, 'refused':refused, 'aimed_reason':aimed_reason,
    'source_unchanged':hashlib.sha256(source_file.read_bytes()).hexdigest()==digest,
    'material_unchanged':source.cut(before).Volume+before.cut(source).Volume,
}))
"""


def test_proved_axis_translation_maps_exact_source_portions_not_retrimmed_faces(
    tmp_path, freecad_kernel
):
    from test_axis_placements import _NATIVE_AXIS

    source = Path(kernel.__file__).with_name("freecad_job.py")
    probe = _NATIVE_AXIS.replace("__NATIVE_PATH__", repr(str(source)))
    probe = probe.replace("__MODE__", repr("plain")) + _PLACED_COVERAGE
    script = tmp_path / "placement-probe.py"
    script.write_text(probe, encoding="utf-8")
    process = subprocess.run(
        [freecad_kernel, str(script), "--", str(tmp_path)],
        capture_output=True, text=True, errors="replace", timeout=300,
    )
    report = tmp_path / "raster-placement.json"
    assert report.exists(), process.stdout[-4000:] + process.stderr[-4000:]
    result = json.loads(report.read_text(encoding="utf-8"))
    assert result["source_unchanged"]
    assert result["material_unchanged"] == pytest.approx(0, abs=1e-7)
    assert all(row["extra"] + row["missing"] < 1e-6 for row in result["rows"])
    assert result["refused"] and result["aimed_reason"]
