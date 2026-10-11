"""Generic workspace contracts, executed against the production presentation module."""

import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

STATIC = Path("src/twinforge/viewer/static")


REFERENCE_HANDLER_HARNESS = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {calibrationEligibility,resetReferenceState}=await import('data:text/javascript;base64,'+
  Buffer.from(readFileSync(process.argv[2],'utf8')).toString('base64'));
const code=readFileSync(process.argv[1],'utf8');
const {visiblePoint}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/measurement-state.js')).toString('base64'));
let clipVolume=null;const visibility={hidden_frame_ids:[],hidden_rois:[]};
const {ImageLoadGate,matchingSelections,imageTransform}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/image-selection.js')).toString('base64'));
const {measurementSummary}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/result-summary.js')).toString('base64'));
let imageEditor,timeline,exploration,sourcePreview,inspectTimer,sceneContext=null,correction=null,submissionKey=null,submitting=false,photoCleanups=[];
let mutationTail=Promise.resolve(),measurementOperation=0,acceptedMeasurementOperation=0;
const sourceLoadGate=new ImageLoadGate();function drawOverlay(){} function annotatePhoto(){return ()=>{};}
const nodes=new Map();
const element=()=>({value:'',disabled:false,checked:false,hidden:false,textContent:'',children:[],
  focus(){},removeAttribute(name){delete this[name];},
  get childNodes(){return this.children;},
  replaceChildren(...children){this.children=children;},append(...children){this.children.push(...children);}});
const byId=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const document={createElement:element};const Option=class {constructor(text,value){this.textContent=text;this.value=value;}};
let measurement=null,measurementLines,endpointPicks=[],pickMode=null,referenceGeneration=0,
  requestGeneration=0,sceneCopyGeneration=0,sceneVariant='source',calibrationScalar=1,
  workspace={loading:false,derivedAvailable:false},cameraTargets=[],cameraGroup={},cameraPath={},bounds;
const scene={name:'Synthetic',scale:{type:'relative'},frames:[],cameras:[],pixel_transforms:[],
  original_point_count:4,observation_count:0,reference_count:0,usage_status:'visualization_only'};
let metadata=scene,preview={header:{count:0},xyz:[]},current=preview,
  selectedFrame={frame_id:0,points_url:'/api/frames/0/points'};
const world={remove(){},add(){}};
const THREE={Box3:class {expandByPoint(){}},Vector3:class {
  constructor(...xyz){this.xyz=xyz;}fromArray(){return this;}multiplyScalar(){return this;}},
  Group:class {constructor(){this.children=[];}add(line){this.children.push(line);}},
  Line:class {constructor(geometry,material){this.geometry=geometry;this.material=material;}},
  BufferGeometry:class {setFromPoints(){return this;}dispose(){}},LineBasicMaterial:class {dispose(){}}};
function display(bundle){current=bundle;}function addCameras(){cameraGroup={};}
function disposeGeometryGroup(){}
function deferred(){let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j;});return {promise,resolve,reject};}
let response=deferred(),refreshResponse=null,posts=0,payloads=[];
const urls=[];
async function fetchChecked(url){urls.push(url);return {json:()=>url.startsWith('/api/measurements/')?
  response.promise:url==='/api/measurements'?Promise.resolve(['ref']):
  refreshResponse?.promise??Promise.resolve({...scene,observation_count:2,reference_count:1,usage_status:'partially_checked'})};}
async function postWorkspace(path,value){posts++;payloads.push(value);return response.promise;}
async function loadBundle(){return preview;}function showError(error){throw error;}
const record={record:{reference_id:'ref',quantity:'segment',observations:[]},evidence:{
  state:'consistent_observations',observation_count:2,distinct_view_count:2,calibration_qualified:true,
  length_spread_ratio:0.01,endpoint_spread_ratio:0.01,pixel_sensitivity_span_ratios:[],reasons:[],support_note:'Synthetic evidence'}};
let calibrationState,updateCalibration,clearEndpointPicks,clearActiveReference,selectFrame,
  showMeasurement,refreshMeasurements,showSceneStatus,addEndpoint,
  imageContext,drawSourceSelections,previousObservation,startMeasurement,renderObservations,
  enqueueMeasurementMutation,confirmImageSelection,responseError;
const functions=[['function calibrationState(','\nasync function fetchChecked'],
  ['function selectFrame(','\nfunction lookFromCamera'],['function addEndpoint(','\nasync function postWorkspace'],
  ['async function refreshMeasurements(','\nasync function saveVisibility']];
for(const [start,end] of functions) eval(code.slice(code.indexOf(start),code.indexOf(end,code.indexOf(start)))
  .replace(/^(async )?function (\w+)\(/gm,'$2 = $1function('));
const handlers=[['byId(\'save-observation\').onclick =','  byId(\'color-mode\').onchange'],
  ['byId(\'scene-variant\').onchange =','  byId(\'camera-view\').onclick'],
  ['byId(\'frame-points\').onclick =','  let down;']];
for(const [start,end] of handlers) eval(code.slice(code.indexOf(start),code.indexOf(end,code.indexOf(start))));
eval(code.split('\n').find(line=>line.includes("byId('all').onclick =")));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function begin(operation){
  if(operation==='open')return byId('saved-measurements').onchange({target:{value:'ref'}});
  byId('reference-id').value='ref';byId('quantity').value='segment';
  endpointPicks=[{index:0,frameId:0},{index:1,frameId:0}];pickMode='3d';
  return byId('save-observation').onclick();
}
function rows(){const children=byId('scene-status').children,result={};
  for(let i=0;i<children.length;i+=2)result[children[i].textContent]=children[i+1].textContent;return result;}
"""


def test_submission_guard_retry_identity_and_explicit_correction_revision():
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
const pending=begin('save');await byId('save-observation').onclick();
assert.equal(posts,1,'Double click submitted another observation');
response.reject(Error('Network unavailable'));await pending;
const retryKey=payloads[0].idempotency_key;
assert.ok(retryKey);assert.equal(byId('save-observation').disabled,false);
response=deferred();const retried=byId('save-observation').onclick();
await tick();
assert.equal(payloads[1].idempotency_key,retryKey,'Retry generated another submission identity');
response.resolve(record);await retried;
endpointPicks=[{sourcePixel:[1,2],frameId:3},{sourcePixel:[3,4],frameId:3}];pickMode='image';
correction={id:'existing-observation',revision:2};submissionKey=null;
byId('correction-reason').value='';await byId('save-observation').onclick();
assert.equal(posts,2,'Correction without a reason was saved');
byId('correction-reason').value='A was selected on the wrong physical corner.';
response=deferred();const corrected=byId('save-observation').onclick();
await tick();
const payload=payloads.at(-1);
assert.equal(payload.correction_id,'existing-observation');assert.equal(payload.expected_revision,2);
assert.equal(payload.correction_reason,byId('correction-reason').value);
assert.deepEqual(payload.source_pixels,[[1,2],[3,4]]);assert.equal(payload.frame_id,3);
assert.notEqual(payload.idempotency_key,retryKey,'Deliberate correction reused the original submission');
response.resolve(record);await corrected;
assert.equal(correction,null);assert.equal(byId('correction-panel').hidden,true);
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_first_3d_hit_from_all_frames_keeps_a_and_picking_mode():
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
const frame={frame_id:3,timestamp_seconds:1,image_url:'3.jpg'};
metadata={...scene,frames:[frame]};selectedFrame=null;pickMode='3d';
globalThis.Image=class {};
current={xyz:new Float32Array([0,0,0,1,0,0]),frame_ids:[3,3],point_indices:[12,13],valid:[1,1]};
let hitIndex=0;const raycaster={setFromCamera(){},intersectObject(){return [{index:hitIndex}];}};
const pointer={set(){}};const renderer={domElement:{getBoundingClientRect(){return {left:0,top:0,width:100,height:100};}}};
const cloud={};cameraGroup.visible=false;const camera={};
let inspectClick;const start=code.indexOf('function inspectClick(');
eval(code.slice(start,code.indexOf('\nfunction addEndpoint',start)).replace('function inspectClick(','inspectClick = function('));
inspectClick({clientX:10,clientY:10});
assert.deepEqual(endpointPicks,[{index:12,frameId:3}],'Selecting the first hit frame erased A');
assert.equal(pickMode,'3d','First hit exited 3D picking');
assert.equal(selectedFrame.frame_id,3);hitIndex=1;inspectClick({clientX:20,clientY:10});
assert.deepEqual(endpointPicks,[{index:12,frameId:3},{index:13,frameId:3}]);
assert.equal(byId('save-observation').disabled,false);
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_same_frame_correction_cancel_preserves_confirmed_draft_and_intent():
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
const frame={frame_id:3,timestamp_seconds:1,image_url:'3.jpg'};
metadata={...scene,frames:[frame]};selectedFrame=frame;globalThis.Image=class {};
const confirmed=[{sourcePixel:[7,8],frameId:3},{sourcePixel:[19,20],frameId:3}];
endpointPicks=structuredClone(confirmed);pickMode='image';submissionKey='retry-draft';
byId('save-observation').disabled=false;byId('correspondence-reviewed').checked=true;
byId('correction-panel').hidden=true;
imageEditor={open(...args){this.args=args;},cancel(){}};
renderObservations({record:{observations:[{frame_id:3,source_pixels:[[1,2],[3,4]],observation_id:'saved-one',revision:2}]}});
const card=byId('observation-list').children[0];
card.children.find(node=>node.textContent==='Correct observation').onclick();
imageEditor.cancel();
assert.deepEqual(endpointPicks,confirmed,'Correction Cancel discarded the prior confirmed selection');
assert.equal(pickMode,'image');assert.equal(submissionKey,'retry-draft');
assert.equal(byId('save-observation').disabled,false);assert.equal(byId('correspondence-reviewed').checked,true);
assert.equal(correction,null,'Unconfirmed correction intent became active');
assert.equal(byId('correction-panel').hidden,true);
card.children.find(node=>node.textContent==='Correct observation').onclick();
const intent=imageEditor.args[4];
confirmImageSelection([[1,2],[3,4]],imageContext(),intent);
assert.deepEqual(correction,{id:'saved-one',revision:2});
assert.deepEqual(endpointPicks,[{sourcePixel:[1,2],frameId:3},{sourcePixel:[3,4],frameId:3}]);
assert.equal(byId('correction-panel').hidden,false);assert.equal(byId('correspondence-reviewed').checked,false);
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("following", ["save", "correction", "rename"])
def test_same_reference_mutations_are_serialized_and_keep_latest_record(following):
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
const original={...record,record:{...record.record,display_name:'Original'},evidence:{...record.evidence,observation_count:1}};
measurement=original;byId('reference-id').value='ref';byId('quantity').value='segment';
byId('measurement-name').value='First name';
const firstResponse=deferred(),secondResponse=deferred(),calls=[];
let serverRecord=structuredClone(original);
postWorkspace=async(path,value)=>{
  calls.push(value);
  if(value.action==='rename')serverRecord={...serverRecord,record:{...serverRecord.record,display_name:value.display_name}};
  else serverRecord={...serverRecord,record:{...serverRecord.record,display_name:value.display_name,change:value.correction_id?'corrected':'added'},
    evidence:{...serverRecord.evidence,observation_count:value.correction_id?1:2,state:value.correction_id?'conflicting_observations':'consistent_observations'}};
  const snapshot=structuredClone(serverRecord);await (calls.length===1?firstResponse.promise:secondResponse.promise);return snapshot;
};
const first=byId('measurement-name').onchange();await tick();
let next;
if(process.argv[3]==='rename'){
  byId('measurement-name').value='Latest name';next=byId('measurement-name').onchange();
}else{
  endpointPicks=[{index:0,frameId:3},{index:1,frameId:3}];pickMode='3d';
  if(process.argv[3]==='correction'){correction={id:'saved-one',revision:2};byId('correction-reason').value='Reviewed physical corner.';}
  next=byId('save-observation').onclick();
}
await tick();assert.equal(calls.length,1,'Later mutation was sent while the rename response was pending');
firstResponse.resolve();await first;await tick();assert.equal(calls.length,2);
assert.equal(measurement.evidence.observation_count,1,'Confirmed rename changed observation evidence');
if(process.argv[3]==='rename')assert.equal(byId('measurement-name').value,'Latest name','Earlier acknowledgement erased the pending name');
secondResponse.resolve();await next;
assert.deepEqual(measurement,serverRecord,'Latest saved record/evidence was not retained');
if(process.argv[3]==='rename')assert.equal(measurement.record.display_name,'Latest name');
if(process.argv[3]==='save')assert.equal(measurement.evidence.observation_count,2);
if(process.argv[3]==='correction'){
  assert.equal(measurement.evidence.state,'conflicting_observations');
  assert.equal(calls[1].correction_id,'saved-one');assert.equal(calls[1].expected_revision,2);
}
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
            following,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("submission", ["save", "correction"])
def test_failed_submission_remains_actionable_after_successful_queued_rename(submission):
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
measurement=record;byId('reference-id').value='ref';byId('quantity').value='segment';
const draft=[{index:0,frameId:3},{index:1,frameId:3}];endpointPicks=structuredClone(draft);pickMode='3d';
if(process.argv[3]==='correction'){
  correction={id:'saved-one',revision:2};byId('correction-reason').value='Reviewed physical corner.';
}
const saveResponse=deferred(),renameResponse=deferred(),calls=[];
const renamed={...record,record:{...record.record,display_name:'New name'}};
postWorkspace=async(path,value)=>{calls.push(value);return value.action==='rename'?renameResponse.promise:saveResponse.promise;};
const pendingSave=byId('save-observation').onclick();await tick();
const retryKey=calls[0].idempotency_key;
byId('measurement-name').value='New name';const pendingRename=byId('measurement-name').onchange();await tick();
assert.equal(calls.length,1,'Rename bypassed the pending submission');
saveResponse.reject(Error('Selected endpoint is unsupported.'));await pendingSave;await tick();
assert.equal(calls.length,2);renameResponse.resolve(renamed);await pendingRename;
assert.match(byId('endpoint-status').textContent,/Could not save: Selected endpoint is unsupported\./,
  'Queued rename hid the failed observation submission');
assert.ok(!byId('endpoint-status').textContent.includes('Saving observation'));
assert.equal(byId('save-observation').disabled,false,'Failed selection cannot be retried');
assert.deepEqual(endpointPicks,draft);assert.equal(submissionKey,retryKey);
assert.equal(measurement,renamed);assert.equal(measurement.evidence,record.evidence);
if(process.argv[3]==='correction'){
  assert.deepEqual(correction,{id:'saved-one',revision:2});
  assert.equal(byId('correction-reason').value,'Reviewed physical corner.');
}
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
            submission,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_failed_rename_releases_queued_save_and_preserves_latest_evidence():
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
measurement=record;byId('reference-id').value='ref';byId('quantity').value='segment';
byId('measurement-name').value='Renamed';const firstResponse=deferred(),calls=[];
const saved={...record,record:{...record.record,display_name:'Renamed',change:'saved'},
  evidence:{...record.evidence,observation_count:3}};
postWorkspace=async(path,value)=>{calls.push(value);if(value.action==='rename')return firstResponse.promise;return saved;};
const first=byId('measurement-name').onchange();await tick();
endpointPicks=[{index:0,frameId:3},{index:1,frameId:3}];pickMode='3d';
const next=byId('save-observation').onclick();await tick();assert.equal(calls.length,1);
firstResponse.reject(Error('Rename transport failed'));await first;await next;
assert.equal(calls.length,2,'Rejected mutation poisoned the queue');
assert.equal(measurement,saved);assert.equal(measurement.evidence.observation_count,3);
assert.ok(byId('endpoint-status').textContent.startsWith('Observation saved.'));
assert.equal(byId('save-observation').disabled,true);
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("display_action", ["all", "frame-points"])
@pytest.mark.parametrize("operation", ["open", "save"])
def test_point_display_changes_preserve_pending_reference_operations(display_action, operation):
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
const operation=process.argv[3],displayAction=process.argv[4];
const pending=begin(operation);await tick();
await byId(displayAction).onclick();response.resolve(record);await pending;
assert.equal(measurement,record,'Display navigation discarded the successful reference result');
assert.ok(!byId('measurement-summary').textContent.includes('Opening'));
if(operation==='save'){
  assert.ok(byId('endpoint-status').textContent.startsWith('Observation saved.'));
  assert.equal(rows()['Saved observations'],'2');assert.equal(rows()['Saved references'],'1');
  assert.equal(rows().Use,'partially_checked');
  pickMode='3d';addEndpoint({index:2,frameId:1});addEndpoint({index:3,frameId:1});
  assert.equal(byId('save-observation').disabled,false,'Future observations remain disabled');
  response=deferred();const next=byId('save-observation').onclick();
  response.resolve(record);await next;assert.equal(posts,2);
}
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
            operation,
            display_action,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("display_action", ["all", "frame-points"])
def test_point_display_during_saved_count_refresh_finishes_save(display_action):
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
refreshResponse=deferred();const pending=begin('save');response.resolve(record);await tick();
assert.ok(urls.includes('/api/scene'),'Save did not reach metadata refresh');
selectedFrame={frame_id:0,points_url:'/api/frames/0/points'};
await byId(process.argv[3]).onclick();
refreshResponse.resolve({...scene,observation_count:2,reference_count:1,usage_status:'partially_checked'});
await pending;
assert.equal(rows()['Saved observations'],'2','Display navigation discarded refreshed counts');
assert.ok(byId('endpoint-status').textContent.startsWith('Observation saved.'));
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
            display_action,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("change", ["copy", "new-reference", "another-reference"])
@pytest.mark.parametrize("operation", ["open", "save"])
def test_actual_identity_changes_reject_pending_reference_results(change, operation):
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
const pending=begin(process.argv[3]);await tick();
if(process.argv[4]==='copy')await byId('scene-variant').onchange({target:{value:'derived'}});
else if(process.argv[4]==='new-reference')byId('new-reference').onclick();
else {byId('reference-id').value='another';byId('reference-id').oninput();}
response.resolve(record);await pending;
assert.equal(measurement,null,'Obsolete result replaced the current identity');
assert.equal(urls.includes('/api/measurements'),false,'Obsolete save refreshed the active workspace');
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
            operation,
            change,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_copy_switch_clears_cancelled_reference_loading_status():
    script = (
        REFERENCE_HANDLER_HARNESS
        + r"""
const pending=begin('open');await tick();
assert.equal(byId('measurement-summary').textContent,'Opening saved reference…');
await byId('scene-variant').onchange({target:{value:'derived'}});
assert.ok(byId('measurement-summary').textContent.startsWith('No examined reference.'),
  'Scene switch left the cancelled reference open showing a loading status');
assert.equal(byId('saved-measurements').value,'');
response.resolve(record);await pending;
assert.equal(measurement,null,'Cancelled response reopened the old reference');
assert.ok(!byId('measurement-summary').textContent.includes('Opening'));
"""
    )
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("archive_status", ["available", "unavailable"])
def test_direct_calibrated_scene_shows_frozen_report_without_enabling_calibration(archive_status):
    script = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {calibrationEligibility,resetReferenceState,formatCalibrationReport}=await import(
  'data:text/javascript;base64,'+Buffer.from(readFileSync(process.argv[2],'utf8')).toString('base64'));
const {calibrationSummary}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/result-summary.js')).toString('base64'));
const code=readFileSync(process.argv[1],'utf8');
const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:false,
  textContent:id==='calibration-report'?'No calibration saved.':'',options:[{},{}],replaceChildren(){},append(){}});return nodes.get(id);};
const Option=class {};let workspace={loading:false,derivedAvailable:false},sceneVariant='source',
  metadata={scale:{type:'calibrated_metric'},derived_available:false},measurement=null,calibrationScalar=1;
const calibration={control_id:'frozen-control',scalar:0.4123456789,physical_length_m:2.37,
  reconstructed_median:5.747604916,observations:[{},{}]};
const report={excluded_control_id:'frozen-control',checks:[{reference_id:'independent-check',
  status:'checked',scaled_median_m:1.4321,error_m:-0.0679,
  local_regions:{edge:{scaled_length_m:null,reason:'missing pixels'}}}]};
const archive={status:process.argv[3],reason:'Frozen check report disagrees with retained records/calibration',
  calibration,check_report:report,measurements:[],validation_scope:'Validated frozen archive',display_scalar:calibration.scalar};
const urls=[];async function fetchChecked(url){urls.push(url);return {json:async()=>
  url==='/api/archive'?archive:url==='/api/calibration'?calibration:report};}
let calibrationState,updateCalibration;
const helperStart=code.indexOf('function calibrationState(');
eval(code.slice(helperStart,code.indexOf('\nfunction clearEndpointPicks',helperStart))
  .replace(/^function (\w+)\(/gm,'$1 = function('));
const start=code.indexOf("  const archive = await");
const presentation=code.slice(start,code.indexOf("  byId('calibrate').onclick =",start));
await eval('(async()=>{'+presentation+'})()');
const text=byId('calibration-report').textContent;
assert.equal(byId('physical-length').value,'','Frozen control length became an entry default');
assert.equal(byId('calibrate').disabled,true);
assert.equal(measurement,null,'Frozen control became an active reference');
assert.equal(byId('calibration-reference').textContent,'No active reference');
assert.ok(!text.includes('No calibration saved'),'Calibrated artifact claimed no saved calibration');
if(archive.status==='available'){
  assert.match(text,/Frozen archived control: frozen-control/);assert.match(text,/s = 0\.412345679/);
  assert.match(text,/Excluded from check statistics: frozen-control/);
  assert.match(text,/independent-check: checked; scaled median 1\.4321 m; error -0\.0679 m/);
  assert.match(text,/edge: missing pixels; same physical reference/);
  assert.match(byId('archive-status').textContent,/Validated frozen archive/);
  assert.ok(!urls.includes('/api/calibration')&&!urls.includes('/api/check-report'));
  assert.equal(text,formatCalibrationReport(calibration,report,{archived:true}));
  metadata={scale:{type:'relative'},derived_available:true};
  await eval('(async()=>{'+presentation+'})()');
  assert.equal(byId('calibration-report').textContent,formatCalibrationReport(calibration,report));
}else{
  assert.match(text,/Frozen calibration report unavailable/);
  assert.ok(text.includes(archive.reason),'Validated archive failure reason was lost');
  assert.ok(!byId('calibration-eligibility').textContent.includes('remains below'));
}
"""
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
            archive_status,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = {}
        self.stack = []
        self.text = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            assert attrs["id"] not in self.ids, "Duplicate HTML ID"
            self.ids[attrs["id"]] = (tag, attrs, tuple(self.stack))
        if tag not in {"meta", "link", "input", "img", "br"}:
            self.stack.append(attrs.get("id", tag))

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        for key in self.stack:
            self.text[key] = self.text.get(key, "") + data


def test_generic_form_and_separate_workflow_sections():
    html = Elements()
    html.feed((STATIC / "index.html").read_text())
    assert not html.ids["reference-id"][1].get("value")
    assert not html.ids["physical-length"][1].get("value")
    assert 'value="segment" selected' in (STATIC / "index.html").read_text()
    for step in ("inspect", "measure", "calibrate"):
        tag, attrs, _ = html.ids[f"step-{step}"]
        assert tag == "button"
        assert step.capitalize() in html.text[f"step-{step}"]
        assert attrs["aria-controls"] == f"panel-{step}"
        assert attrs["aria-pressed"] == ("true" if step == "inspect" else "false")
    assert "Optional" in html.text["step-calibrate"]
    assert "saved-scene-section" in html.ids["saved-measurements"][2]
    assert "archive-section" in html.ids["archived-measurements"][2]
    assert "disabled" in html.ids["calibrate"][1]
    assert html.ids["endpoint-status"][1]["aria-live"] == "polite"


def test_production_eligibility_and_reference_transitions():
    module = STATIC / "workspace-ui.js"
    assert module.is_file(), "Workspace presentation module is missing"
    script = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {calibrationEligibility, resetReferenceState, selectWorkspaceStep} = await import(
  'data:text/javascript;base64,' + Buffer.from(readFileSync(process.argv[1], 'utf8')).toString('base64'));
const qualified = {record:{reference_id:'reference-1',quantity:'segment'},
  evidence:{calibration_qualified:true}};
const base = {referenceId:'reference-1',quantity:'segment',physicalLength:'2.5',
  measurement:qualified,sceneVariant:'source'};
assert.equal(calibrationEligibility(base).eligible, true);
assert.equal(calibrationEligibility(base).physicalValue, 2.5);
for(const length of ['', ' ', '0', '-1', 'NaN', 'Infinity', '-Infinity', 'abc']) {
  const result=calibrationEligibility({...base,physicalLength:length});
  assert.equal(result.eligible,false,length); assert.ok(result.reason);
}
for(const patch of [{measurement:null},{measurement:{...qualified,read_only:true}},
  {sceneVariant:'derived'},{derivedAvailable:true},{calibratedScene:true},{loading:true},{referenceId:'another'}, {quantity:'width'},
  {measurement:{...qualified,evidence:{calibration_qualified:false}}}]) {
  assert.equal(calibrationEligibility({...base,...patch}).eligible,false,JSON.stringify(patch));
}
for(const patch of [{referenceId:'another'}, {measurement:{...qualified,read_only:true}},
  {sceneVariant:'derived'}, {}]) {
  const next = resetReferenceState(base,patch);
  assert.equal(next.physicalLength,'');
  assert.equal(calibrationEligibility(next).eligible,false);
  assert.equal(base.physicalLength,'2.5','must not mutate earlier state');
}
assert.equal(resetReferenceState(base).measurement,null);
assert.equal(resetReferenceState(base).referenceId,'');
assert.equal(resetReferenceState(base).quantity,'segment');
const nodes=new Map();
const byId=id=> {if(!nodes.has(id)) nodes.set(id,{hidden:false,attrs:{},setAttribute(k,v){this.attrs[k]=v;}});return nodes.get(id);};
selectWorkspaceStep('measure',byId);
assert.equal(byId('panel-inspect').hidden,true);
assert.equal(byId('panel-measure').hidden,false);
assert.equal(byId('step-measure').attrs['aria-pressed'],'true');
selectWorkspaceStep('calibrate',byId);
assert.equal(byId('panel-measure').hidden,true);
assert.equal(byId('panel-calibrate').hidden,false);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(module)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_calibration_action_uses_live_eligibility_and_keeps_copy_busy_state():
    script = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {calibrationEligibility}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync(process.argv[2],'utf8')).toString('base64'));
const code=readFileSync(process.argv[1],'utf8');
const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:false,options:[{},{}]});return nodes.get(id);};
let workspace={loading:false,derivedAvailable:false},sceneVariant='source';
const qualified={record:{reference_id:'reference-1',quantity:'segment'},evidence:{calibration_qualified:true}};
let measurement=qualified;
let calibrationState,updateCalibration;
const start=code.indexOf('function calibrationState(');
eval(code.slice(start,code.indexOf('\nfunction clearEndpointPicks',start)).replace(/^function (\w+)\(/gm,'$1 = function('));
let writes=[];let release;
async function postWorkspace(path,value){writes.push({path,value});await new Promise(resolve=>release=resolve);}
async function showCalibration(){}
const handler=code.indexOf("byId('calibrate').onclick =");
eval(code.slice(handler,code.indexOf("  byId('scene-variant').onchange",handler)));
byId('reference-id').value='reference-1';byId('quantity').value='segment';byId('physical-unit').value='cm';
for(const length of ['', '0','-1','NaN','Infinity']){byId('physical-length').value=length;await byId('calibrate').onclick();}
byId('physical-length').value='4';measurement={...qualified,read_only:true};await byId('calibrate').onclick();
measurement={...qualified,evidence:{calibration_qualified:false}};await byId('calibrate').onclick();
measurement=qualified;sceneVariant='derived';await byId('calibrate').onclick();sceneVariant='source';
byId('reference-id').value='edited';await byId('calibrate').onclick();byId('reference-id').value='reference-1';
assert.equal(writes.length,0,'Ineligible action posted calibration');
const pending=byId('calibrate').onclick();
assert.equal(writes.length,1);assert.equal(byId('scene-variant').disabled,true);
assert.deepEqual(writes[0].value,{reference_id:'reference-1',physical_value:4,physical_unit:'cm'});
workspace.loading=true;release();await pending;
assert.equal(workspace.loading,true,'Calibration completion cleared another pending copy operation');
assert.equal(workspace.derivedAvailable,true);assert.equal(byId('calibrate').disabled,true);
workspace.loading=false;await byId('calibrate').onclick();assert.equal(writes.length,1,'Repeated export posted');
"""
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_app_reference_handlers_clear_inputs_and_ignore_obsolete_selection():
    script = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const ui=await import('data:text/javascript;base64,'+Buffer.from(readFileSync(process.argv[2],'utf8')).toString('base64'));
const {calibrationEligibility,resetReferenceState,selectWorkspaceStep}=ui;
const code=readFileSync(process.argv[1],'utf8');
const nodes=new Map();
const byId=id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:false,checked:false,textContent:'',
  replaceChildren(){},focus(){},setAttribute(){},click(){this.onclick?.();}});return nodes.get(id);};
let imageEditor,correction=null,submissionKey=null,photoCleanups=[];
let measurement, measurementLines, endpointPicks=[],pickMode=null,referenceGeneration=0,
  workspace={loading:false,derivedAvailable:false},sceneVariant='source',requestGeneration=0,sceneCopyGeneration=0;
let current=null,metadata=null,selectedFrame=null;
const world={remove(){}};
function display(){} function selectFrame(){}
let responses=[];
async function fetchChecked(){return {json:()=>new Promise(resolve=>responses.push(resolve))};}
function showMeasurement(value){measurement=value;byId('reference-id').value=value.record.reference_id;byId('quantity').value=value.record.quantity;updateCalibration();}
const start=code.indexOf('function calibrationState(');
assert.ok(start>=0,'Missing wired calibration state');
let calibrationState,updateCalibration,clearEndpointPicks,clearActiveReference,
  imageContext,drawSourceSelections,previousObservation,startMeasurement,renderObservations,
  enqueueMeasurementMutation,confirmImageSelection;
eval(code.slice(start,code.indexOf('\nasync function fetchChecked',start)).replace(/^function (\w+)\(/gm,'$1 = function('));
const handlers=code.indexOf("byId('new-reference').onclick =");
assert.ok(handlers>=0,'Missing new reference action');
eval(code.slice(handlers,code.indexOf("  byId('color-mode').onchange",handlers)));
const qualified={record:{reference_id:'reference-1',quantity:'segment'},evidence:{calibration_qualified:true}};
measurement=qualified;byId('reference-id').value='reference-1';byId('quantity').value='segment';byId('physical-length').value='2';
updateCalibration();assert.equal(byId('calibrate').disabled,false);
byId('reference-id').value='another';byId('reference-id').oninput();
assert.equal(measurement,null);assert.equal(byId('physical-length').value,'');assert.equal(byId('calibrate').disabled,true);
measurement=qualified;byId('physical-length').value='2';byId('quantity').value='width';byId('quantity').onchange();
assert.equal(measurement,null);assert.equal(byId('physical-length').value,'');
byId('new-reference').onclick();assert.match(byId('reference-id').value,/^measurement-/);assert.equal(byId('quantity').value,'segment');
const first=byId('saved-measurements').onchange({target:{value:'reference-1'}});
await new Promise(resolve=>setImmediate(resolve));
byId('new-reference').onclick();responses.shift()(qualified);await first;
assert.equal(measurement,null,'Old response reopened a reference after New reference');
assert.match(byId('reference-id').value,/^measurement-/);
byId('physical-length').value='8';
const second=byId('saved-measurements').onchange({target:{value:'reference-1'}});
assert.equal(byId('physical-length').value,'');
await new Promise(resolve=>setImmediate(resolve));responses.shift()(qualified);await second;
assert.equal(measurement,qualified);assert.equal(byId('calibrate').disabled,true);
const archive={measurements:[qualified],display_scalar:0.5};
const archiveSelect=byId('archived-measurements');
const archiveStart=code.indexOf('archiveSelect.onchange =');
eval(code.slice(archiveStart,code.indexOf("    byId('archive-status').textContent",archiveStart)));
byId('physical-length').value='7';archiveSelect.onchange({target:{value:'0'}});
assert.equal(byId('physical-length').value,'');assert.equal(measurement.read_only,true);
assert.equal(byId('calibrate').disabled,true);
"""
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            str(STATIC / "app.js"),
            str(STATIC / "workspace-ui.js"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_measurement_refresh_does_not_replace_a_newer_scene_copy():
    script = r"""import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const code=readFileSync(process.argv[1],'utf8');
let sceneVariant='source',requestGeneration=0,sceneCopyGeneration=0,metadata={name:'source'},measurement=null;
const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,{value:'',replaceChildren(){},append(){}});return nodes.get(id);};
const Option=class {};function showSceneStatus(){}
let release;const pending=new Promise(resolve=>release=resolve);
const urls=[];
async function fetchChecked(url){urls.push(url);return {json:async()=>url==='/api/measurements'?['ref']:url==='/api/scene'?pending:{name:'derived fresh'}};}
let refreshMeasurements;
const start=code.indexOf('async function refreshMeasurements(');
eval(code.slice(start,code.indexOf('\nfunction showSceneStatus',start)).replace('async function refreshMeasurements(','refreshMeasurements = async function('));
const first=refreshMeasurements();await new Promise(resolve=>setImmediate(resolve));
sceneVariant='derived';requestGeneration++;sceneCopyGeneration++;metadata={name:'derived'};
release({name:'obsolete source'});await first;
assert.equal(metadata.name,'derived','Source refresh overwrote a newer displayed copy');
await refreshMeasurements();
assert.equal(metadata.name,'derived fresh');assert.ok(urls.includes('/api/derived/scene'));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, str(STATIC / "app.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
