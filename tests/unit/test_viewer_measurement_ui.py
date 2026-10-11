"""Pure UI state behavior is testable without an available WebGL browser."""

import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "message",
    [
        "Source pixel is outside the model crop. Choose points inside the supported area of the photo.",
        "Observation revision changed. Reopen the observation before correcting it.",
    ],
)
def test_measurement_save_displays_actionable_json_error(message):
    script = r"""import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
const code=readFileSync('src/twinforge/viewer/static/app.js','utf8');
const message=process.argv[1];const fetch=async()=>({ok:false,headers:{get:()=> 'application/json'},
 json:async()=>({error:{code:'safe_validation',message}}),text:async()=>JSON.stringify({error:{message}})});
const start=code.includes('async function responseError(')?code.indexOf('async function responseError('):code.indexOf('async function postWorkspace(');
const section=code.slice(start,code.indexOf('\nasync function refreshMeasurements()'));
const postWorkspace=eval('(async()=>{'+section+';return postWorkspace;})');
await assert.rejects((await postWorkspace())('/api/measurements',{}),error=>error.message===message);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, message],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("delayed", ["metadata", "preview", "error", "clearing", "archive"])
def test_copy_switch_commits_only_current_response_and_clears_frame_ui(delayed):
    script = r"""import {readFileSync} from 'node:fs';
const code = readFileSync(process.argv[1], 'utf8');
const {calibrationEligibility,resetReferenceState}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/workspace-ui.js','utf8')).toString('base64'));
const {ImageLoadGate,matchingSelections,imageTransform}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/image-selection.js')).toString('base64'));
const {measurementSummary}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/result-summary.js')).toString('base64'));
let imageEditor,timeline,exploration,sourcePreview,inspectTimer,sceneContext=null,correction=null,submissionKey=null,photoCleanups=[];
const sourceLoadGate=new ImageLoadGate();function drawOverlay(){}function annotatePhoto(){return ()=>{};}
const document={createElement(){return {append(){},textContent:''};}};
let workspace={loading:false,derivedAvailable:false}, referenceGeneration=0,sceneCopyGeneration=0;
const nodes = new Map();
const byId = id => {
  if (!nodes.has(id)) nodes.set(id, {value:'', disabled:false, hidden:false, textContent:'',
    childNodes:[],replaceChildren(){},append(){},
    removeAttribute(name) {delete this[name];}});
  return nodes.get(id);
};
const old = {name:'old', frames:[], cameras:[], pixel_transforms:[]};
let metadata=old, preview={name:'old'}, current=preview, sceneVariant='source', requestGeneration=0,
  selectedFrame={frame_id:3}, cameraTargets=[], bounds, cameraGroup={}, cameraPath={}, endpointPicks=[1], pickMode='image';
let measurement={record:{reference_id:'door',quantity:'width',observations:[{xyz:[[0,0,0],[2,0,0]], length:2, point_indices:[0,1],raw_confidence:[null,null]}]},evidence:{state:'consistent_observations',calibration_qualified:true,reasons:[],pixel_sensitivity_span_ratios:[0.01]}};
let measurementLines, calibrationScalar=0.41;
if(process.argv[2] === 'archive') {measurement.read_only=true; measurement.display_scalar=0.41; measurement.source_manifest_sha256='original-hash';}
const world={remove() {},add() {}};
const THREE={Box3:class {expandByPoint() {}}, Vector3:class {
  constructor(x=0,y=0,z=0) {this.x=x;this.y=y;this.z=z;}
  fromArray() {return this;}
  multiplyScalar(s) {this.x*=s;this.y*=s;this.z*=s;return this;}
}, Group:class {constructor() {this.children=[];} add(line) {this.children.push(line);}},
Line:class {constructor(geometry,material) {this.geometry=geometry;this.material=material;}},
BufferGeometry:class {setFromPoints(points) {this.points=points;return this;} dispose() {}},
LineBasicMaterial:class {dispose() {}}};
function addCameras() {cameraGroup={};}
function disposeGeometryGroup(){}
function display(value, label) {current=value; byId('view-label').textContent=label;}
function showSceneStatus() {}
function deferred() {let resolve,reject; const promise=new Promise((r,j)=>{resolve=r;reject=j;}); return {promise,resolve,reject};}
const derivedMetadata=deferred(), derivedPreview=deferred();
const source={name:'source', manifest_sha256:'source-hash', frames:[], cameras:[], pixel_transforms:[]};
const derived={...source,name:'derived',manifest_sha256:'derived-hash'};
const sourceBundle={name:'source', header:{count:0}, xyz:[]}, derivedBundle={...sourceBundle,name:'derived'};
async function fetchChecked(url) {return {json:()=>url.startsWith('/api/derived') ? derivedMetadata.promise : Promise.resolve(source)};}
async function loadBundle(url) {return url.startsWith('/api/derived') ? derivedPreview.promise : sourceBundle;}
const selectCode=code.slice(code.indexOf('function selectFrame('),code.indexOf('\nfunction ',code.indexOf('function selectFrame(')+1));
const handlerCode=code.slice(code.indexOf("byId('scene-variant').onchange ="),code.indexOf("  byId('camera-view').onclick"));
const measurementCode=code.slice(code.indexOf('function showMeasurement('),code.indexOf('\nasync function saveVisibility'));
const workspaceCode=code.slice(code.indexOf('function calibrationState('),code.indexOf('\nasync function fetchChecked'));
eval(workspaceCode + '\n' + selectCode + '\n' + measurementCode + '\n' + handlerCode);
byId('physical-length').value='2';
byId('source-image').src='old.jpg'; byId('image-link').href='old.jpg';
const first=byId('scene-variant').onchange({target:{value:'derived'}});
if(byId('physical-length').value !== '' || !byId('calibrate').disabled) throw Error('Copy switch retained stale calibration eligibility');
if(process.argv[2] === 'clearing') {derivedMetadata.resolve(derived); derivedPreview.resolve(derivedBundle); await first;}
if(process.argv[2] === 'preview') {
  derivedMetadata.resolve(derived); await new Promise(r=>setImmediate(r));
  if(metadata !== old) throw Error('Metadata committed before paired preview');
}
const second=byId('scene-variant').onchange({target:{value:'source'}}); await second;
if(process.argv[2] === 'error') derivedMetadata.reject(Error('obsolete response'));
else {derivedMetadata.resolve(derived); derivedPreview.resolve(derivedBundle);}
await first;
if(metadata !== source || current !== sourceBundle || sceneVariant !== 'source') throw Error('Obsolete copy response committed');
if(byId('endpoint-status').textContent.includes('Switching')) throw Error('Copy status remained loading after completion');
if(measurementLines.children[0].geometry.points[1].x !== (process.argv[2] === 'archive' ? .82 : 2)) throw Error('Measurement lines use another copy scale');
if(byId('calibration-report').textContent) throw Error('Obsolete error shown');
if(!byId('source-image').hidden || 'src' in byId('source-image') || 'href' in byId('image-link')) throw Error('Source frame image was not cleared');
if(byId('frame-details').textContent !== 'Choose a source frame.' || byId('image-note').textContent !== 'No source frame selected.') throw Error('Frame description was not cleared');
for(const id of ['camera-view','frame-points','hide-frame','hide-roi','pick-image']) if(!byId(id).disabled) throw Error('Stale enabled frame control: '+id);
"""
    result = subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            script,
            "src/twinforge/viewer/static/app.js",
            delayed,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_blank_frame_selection_clears_state_and_hidden_rois_filter_only_known_pixels():
    path = Path("src/twinforge/viewer/static/measurement-state.js")
    assert path.is_file(), "measurement UI state module missing"
    script = """import {readFileSync} from 'node:fs';
const code = readFileSync(process.argv[1], 'utf8');
const {frameSelection, visiblePoint} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
if(frameSelection('') !== null || frameSelection('  ') !== null || frameSelection('0') !== 0 || frameSelection('17') !== 17) throw Error('frame selection did not clear');
const state = {hidden_frame_ids:[3], hidden_rois:[{frame_id:17,bounds:[1,2,3,4]}]};
if(visiblePoint(3,null,state,[]) || visiblePoint(17,22,state,[{frame_id:17,crop_bbox:[0,0,10,10]}])) throw Error('hidden points visible');
if(!visiblePoint(17,null,state,[]) || !visiblePoint(21,22,state,[])) throw Error('unknown provenance was hidden');
"""
    subprocess.run(
        ["node", "--input-type=module", "-e", script, str(path)], check=True, capture_output=True
    )


def test_scene_status_refreshes_saved_counts_and_use_after_saving():
    script = r"""import {readFileSync} from 'node:fs';
const nodes = new Map();
function element() {
  return {textContent:'', children:[], append(...values) {this.children.push(...values)},
    replaceChildren(...values) {this.children = [...values]}};
}
globalThis.document = {getElementById(id) {
  if(!nodes.has(id)) nodes.set(id, element()); return nodes.get(id);
}, createElement:element};
globalThis.THREE = {Raycaster:class {}, Vector2:class {}, WebGLRenderer:class {
  constructor() {throw Error('Stop before unavailable WebGL');}
}};
globalThis.Option = class {constructor(text, value) {this.textContent=text; this.value=value;}};
globalThis.ImageLoadGate=class {};
let scene = {name:'Synthetic', scale:{type:'relative'}, geometry_evidence:'per_reference',
  observation_count:0, reference_count:0, usage_status:'visualization_only',
  original_point_count:4, frames:[], manifest_sha256:'hash', pixel_provenance_available:false};
globalThis.fetch = async url => ({ok:true, json:async () => url === '/api/scene' ? scene :
  url === '/api/measurements' ? ['door'] : {hidden_frame_ids:[], hidden_rois:[]}});
let code = readFileSync(process.argv[1], 'utf8').replace(/^import .*;\n/gm, '')
  .replace('init().catch(showError);', 'export {init, refreshMeasurements};');
const {init, refreshMeasurements} = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
try {await init();} catch(error) {
  if(error.cause?.message !== 'Stop before unavailable WebGL') throw error;
  if(!error.message.includes('Enable WebGL')) throw Error('Missing actual graphics failure guidance');
}
function rows() {
  const children = nodes.get('scene-status').children, result = {};
  for(let i=0;i<children.length;i+=2) result[children[i].textContent]=children[i+1].textContent;
  return result;
}
const initial = rows();
if(initial['Saved observations'] !== '0' || initial['Saved references'] !== '0') throw Error('Missing truthful saved counts');
if(initial['Per-reference evidence'] !== 'See individual saved measurements') throw Error('Evidence lacks per-reference scope');
scene = {...scene, observation_count:3, reference_count:2, usage_status:'partially_checked'};
await refreshMeasurements();
const saved = rows();
if(saved['Saved observations'] !== '3' || saved['Saved references'] !== '2') throw Error('Saved counts did not refresh');
if(saved.Use !== 'partially_checked') throw Error('Use status did not refresh after save');
if(saved['Per-reference evidence'] !== 'See individual saved measurements') throw Error('Scene evidence became qualified');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, "src/twinforge/viewer/static/app.js"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
