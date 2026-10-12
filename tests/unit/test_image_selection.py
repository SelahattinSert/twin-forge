"""Source raster identity and editor lifecycle, exercised with the production JS."""

import subprocess
from pathlib import Path

STATIC = Path("src/twinforge/viewer/static")


def run_js(script):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_source_pixels_survive_fit_zoom_pan_resize_and_letterboxing():
    run_js(r"""
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {imageTransform,sourceToDisplay,displayToSource}=await import('data:text/javascript;base64,'+
Buffer.from(readFileSync('src/twinforge/viewer/static/image-selection.js')).toString('base64'));
for(const [width,height] of [[1600,900],[900,1600]]) {
  for(const viewport of [[800,600],[320,700],[1200,500]]) {
    for(const zoom of [1,2,5]) {
      const t=imageTransform(width,height,...viewport,zoom,[71,-24]);
      for(const pixel of [[0,0],[width-1,height-1],[width*.37,height*.63]]) {
        const round=displayToSource(sourceToDisplay(pixel,t),t);
        assert.ok(round && Math.abs(round[0]-pixel[0])<1e-9 && Math.abs(round[1]-pixel[1])<1e-9);
      }
    }
  }
}
const letterbox=imageTransform(100,200,500,400);
assert.equal(displayToSource([0,200],letterbox),null);
assert.deepEqual(displayToSource(sourceToDisplay([0,0],letterbox),letterbox),[0,0]);
assert.equal(displayToSource([letterbox.x-.01,200],letterbox),null);
""")


def test_endpoint_order_undo_cancel_confirm_and_locked_context():
    run_js(r"""
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {ImageSelection}=await import('data:text/javascript;base64,'+
Buffer.from(readFileSync('src/twinforge/viewer/static/image-selection.js')).toString('base64'));
const original=[[1,2],[9,8]], context={frame:17,reference:'ref',copy:1};
const editor=new ImageSelection(context,100,80,original);
editor.move(0,[3,4]); assert.deepEqual(editor.points,[[3,4],[9,8]]);
editor.undo(); assert.deepEqual(editor.points,original);
editor.move(1,[7,6]); assert.deepEqual(editor.cancel(),original);
editor.clear(); editor.place([10,11]); editor.place([20,21]); editor.place([30,31]);
assert.deepEqual(editor.points,[[10,11],[20,21]],'Third click silently replaced A/B');
editor.nudge(0,1,-1);assert.deepEqual(editor.points,[[11,10],[20,21]]);
assert.deepEqual(editor.confirm(context),[[11,10],[20,21]]);
assert.throws(()=>editor.confirm({...context,frame:3}),/context/);
assert.throws(()=>editor.move(0,[100,0]),/outside/);
assert.deepEqual(original,[[1,2],[9,8]],'Editor mutated confirmed selection');
editor.clear();assert.throws(()=>editor.confirm(context),/two/);
""")


def test_plain_result_summaries_distinguish_evidence_reasons():
    run_js(r"""
import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
const {measurementSummary}=await import('data:text/javascript;base64,'+
Buffer.from(readFileSync('src/twinforge/viewer/static/result-summary.js')).toString('base64'));
const value=(state,count,views,reasons=[],qualified=false)=>({record:{observations:[]},
 evidence:{state,observation_count:count,distinct_view_count:views,reasons,calibration_qualified:qualified}});
assert.match(measurementSummary(null),/Select two points/);
assert.match(measurementSummary(value('insufficient_evidence',2,1,['at_least_two_nonduplicate_source_views_required'])),/another image/);
assert.match(measurementSummary(value('consistent_observations',2,2,[],true)),/set scale/);
assert.match(measurementSummary(value('conflicting_observations',2,2)),/do not line up/);
assert.match(measurementSummary(value('consistent_observations',2,2,['pixel_sensitivity_unavailable'])),/pixel support/);
assert.match(measurementSummary(value('insufficient_evidence',2,2,['physical_endpoint_correspondence_unreviewed'])),/correspondence/);
assert.match(measurementSummary(value('future_state',2,2)),/unavailable/);
""")


def test_calibration_summary_counts_only_evaluated_physical_comparisons():
    run_js(r"""
import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
const {calibrationSummary}=await import('data:text/javascript;base64,'+
Buffer.from(readFileSync('src/twinforge/viewer/static/result-summary.js')).toString('base64'));
const calibration={control_id:'control',observations:[{frame_id:3},{frame_id:3},{frame_id:17}]};
const check=(reference_id,status,error_m=null)=>({reference_id,role:'check_only',status,
  physical_length_m:error_m===null?null:2,scaled_median_m:2.1,error_m});
assert.match(calibrationSummary(calibration,{excluded_control_id:'control',checks:[
  check('view','observed_check'),check('provisional','unmeasured_or_provisional',.1),
  check('control','observed_check',0),check('unknown','future_status',.1)
]}),/No evaluated independent/);
const result=calibrationSummary(calibration,{excluded_control_id:'control',checks:[
  check('view','observed_check',.1),check('history','frozen_historical_check',.2),
  check('control','observed_check',0),check('other','observed_check')
]});
assert.match(result,/2 source images/);assert.match(result,/2 evaluated physical-distance/);
assert.match(result,/1 use frozen historical selections/);assert.match(result,/recorded inspection limits/);
assert.match(result,/Shape accuracy is not verified/);
""")


def test_image_load_gate_and_matching_overlays_reject_stale_or_unmapped_views():
    run_js(r"""
import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
const {ImageLoadGate,matchingSelections}=await import('data:text/javascript;base64,'+
Buffer.from(readFileSync('src/twinforge/viewer/static/image-selection.js')).toString('base64'));
const gate=new ImageLoadGate(),context={frame:3,reference:'one',copy:0};
const old=gate.begin(context),next={...context,frame:17},fresh=gate.begin(next);
assert.equal(gate.valid(old,context),false);assert.equal(gate.valid(fresh,next),true);
for(const changed of [{...next,frame:3},{...next,reference:'two'},{...next,copy:1}])
  assert.equal(gate.valid(fresh,changed),false);
gate.cancel();assert.equal(gate.valid(fresh,next),false);
const pixels=[[1,2],[3,4]];
assert.deepEqual(matchingSelections([{frame_id:3,source_pixels:pixels},{frame_id:17,source_pixels:pixels},
  {frame_id:3,point_indices:[1,2]}],3),[{frame_id:3,source_pixels:pixels}]);
""")


def test_editor_stale_loading_cancellation_confirmation_and_keyboard_correction():
    run_js(r"""
import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
const pure='data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/image-selection.js')).toString('base64');
const code=readFileSync('src/twinforge/viewer/static/image-editor.js','utf8').replace("'/image-selection.js'",JSON.stringify(pure));
const nodes=new Map();
const element=()=>({disabled:false,hidden:false,open:false,checked:false,style:{},clientWidth:800,clientHeight:600,
  handlers:{},children:[],textContent:'',addEventListener(name,fn){this.handlers[name]=fn;},
  replaceChildren(...values){this.children=values;},append(...values){this.children.push(...values);},
  setAttribute(){},getBoundingClientRect(){return {left:0,top:0};},setPointerCapture(){},
  showModal(){this.open=true;},close(){this.open=false;},querySelectorAll(){return [];},
  focus(){document.activeElement=this;}});
const byId=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
globalThis.document={activeElement:element(),createElementNS:element};
const opener=document.activeElement;let focusReturns=0;opener.focus=()=>focusReturns++;
globalThis.ResizeObserver=class {observe(){}disconnect(){}};
const loaders=[];globalThis.Image=class {constructor(){loaders.push(this);this.naturalWidth=1600;this.naturalHeight=900;}};
const {ImageEditor}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
let context={frame:3,reference:'one',copy:0},saved=[];
const editor=new ImageEditor(byId,()=>context,(points,ctx,intent)=>saved.push({points,ctx,intent}));
const frame={frame_id:3,timestamp_seconds:1,image_url:'frame3.jpg'};
editor.open(frame);const obsolete=loaders.at(-1);editor.cancel();
editor.open(frame,[[10,20],[300,400]]);const current=loaders.at(-1);
obsolete.onload();assert.equal(editor.selection,null,'Obsolete image initialized the newer editor');
current.onload();assert.deepEqual(editor.selection.points,[[10,20],[300,400]]);
const preventDefault=()=>{};
const markerPointer=(clientX,clientY)=>({clientX,clientY,button:0,pointerId:1,preventDefault});
byId('editor-surface').handlers.pointerdown(markerPointer(5.25,85.25));
byId('editor-surface').handlers.pointermove(markerPointer(15.25,95.25));
byId('editor-surface').handlers.pointerup(markerPointer(15.25,95.25));
assert.deepEqual(editor.selection.points,[[30,40],[300,400]],'Marker drag moved the wrong endpoint');
byId('editor-undo').onclick();assert.deepEqual(editor.selection.points,[[10,20],[300,400]]);
byId('editor-surface').handlers.keydown({key:'ArrowRight',shiftKey:true,preventDefault});
assert.deepEqual(editor.selection.points,[[20,20],[300,400]]);
byId('editor-undo').onclick();assert.deepEqual(editor.selection.points,[[10,20],[300,400]]);
byId('editor-b').onclick();byId('editor-surface').handlers.keydown({key:'ArrowDown',preventDefault});
assert.deepEqual(editor.selection.points,[[10,20],[300,401]]);
byId('editor-cancel').onclick();assert.equal(saved.length,0);assert.equal(byId('image-editor').open,false);
assert.ok(focusReturns>0);
editor.open(frame,[[10,20],[300,400]]);loaders.at(-1).onload();byId('editor-confirm').onclick();
assert.deepEqual(saved[0].points,[[10,20],[300,400]]);assert.equal(saved.length,1);
const intent={id:'saved-one',revision:2};
editor.open(frame,[[10,20],[300,400]],null,false,intent);loaders.at(-1).onload();
byId('editor-cancel').onclick();assert.equal(saved.length,1);assert.equal(editor.intent,null);
editor.open(frame,[[10,20],[300,400]],null,false,intent);loaders.at(-1).onload();
byId('editor-confirm').onclick();assert.deepEqual(saved.at(-1).intent,intent);assert.equal(editor.intent,null);
saved.pop();
editor.open(frame);context={...context,copy:1};loaders.at(-1).onload();
assert.equal(byId('image-editor').open,false,'Programmatic context change left stale editor open');
assert.equal(saved.length,1);
editor.open(frame);loaders.at(-1).onload();
const surface=byId('editor-surface'),pointer=(clientX,clientY)=>({clientX,clientY,button:0,pointerId:1,preventDefault});
surface.handlers.pointerdown(pointer(0,0));surface.handlers.pointerup(pointer(0,0));
assert.equal(editor.selection.points.length,0,'Letterbox click placed an endpoint');
byId('editor-pan').checked=true;
surface.handlers.pointerdown(pointer(300,300));surface.handlers.pointermove(pointer(350,330));surface.handlers.pointerup(pointer(350,330));
assert.equal(editor.selection.points.length,0,'Pan created an endpoint');
assert.deepEqual(editor.pan,[50,30]);
byId('editor-pan').checked=false;byId('editor-fit').onclick();
surface.handlers.pointerdown(pointer(100,150));surface.handlers.pointerup(pointer(100,150));
surface.handlers.pointerdown(pointer(500,350));surface.handlers.pointerup(pointer(500,350));
assert.equal(editor.selection.points.length,2);const originalPixels=structuredClone(editor.selection.points);
byId('editor-zoom-in').onclick();byId('editor-fit').onclick();
assert.deepEqual(editor.selection.points,originalPixels,'Zoom or fit changed source pixels');
editor.dialog.handlers.cancel({preventDefault});assert.equal(saved.length,1,'Escape cancellation confirmed a selection');
editor.open(frame,[[10,20],[300,400]],null,true);loaders.at(-1).onload();
byId('editor-surface').handlers.keydown({key:'ArrowRight',preventDefault});
assert.deepEqual(editor.selection.points,[[10,20],[300,400]]);assert.equal(byId('editor-confirm').hidden,true);
""")


def test_main_photo_load_uses_frame_and_copy_identity_without_hiding_a_new_reference():
    run_js(r"""
import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
const {ImageLoadGate}=await import('data:text/javascript;base64,'+
Buffer.from(readFileSync('src/twinforge/viewer/static/image-selection.js')).toString('base64'));
const sourceLoadGate=new ImageLoadGate();
let selectedFrame,sceneCopyGeneration=0,referenceGeneration=0,imageEditor,timeline,sourcePreview,inspectTimer,measurement,pickMode=null,endpointPicks=[];
const workspace={loading:false},sceneVariant='source',cameraTargets=[];
const metadata={frames:[3,17].map(frame_id=>({frame_id,timestamp_seconds:1,image_url:`${frame_id}.jpg`})),
  cameras:[],pixel_provenance_available:true,point_provenance_available:true,
  source_to_model_mapping_available:true,pixel_transforms:[{frame_id:3},{frame_id:17}]};
const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,{value:'',hidden:false,
  replaceChildren(){},removeAttribute(name){delete this[name];}});return nodes.get(id);};
function clearEndpointPicks(){}function drawSourceSelections(){}
const loaders=[];globalThis.Image=class {constructor(){loaders.push(this);this.naturalWidth=1600;this.naturalHeight=900;}};
const code=readFileSync('src/twinforge/viewer/static/app.js','utf8');
let selectFrame;const start=code.indexOf('function selectFrame(');
eval(code.slice(start,code.indexOf('\nfunction lookFromCamera',start)).replace('function selectFrame(','selectFrame = function('));
selectFrame(3);const obsolete=loaders.at(-1);selectFrame(17);const current=loaders.at(-1);
obsolete.onload();assert.equal(byId('source-image').src,undefined);
current.onload();assert.equal(byId('source-image').src,'17.jpg');assert.equal(byId('source-image').hidden,false);
selectFrame(3);referenceGeneration++;loaders.at(-1).onload();
assert.equal(byId('source-image').src,'3.jpg','Changing reference hid the matching source photo');
selectFrame(17);sceneCopyGeneration++;loaders.at(-1).onload();
assert.equal(byId('source-image').src,'3.jpg','Obsolete copy load changed the photo');
selectFrame(null);assert.equal(byId('source-image').hidden,true);assert.equal(byId('source-image').src,undefined);
""")
