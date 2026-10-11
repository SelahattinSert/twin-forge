"""Viewing tools tested against real bundled Three.js and production UI modules."""

import subprocess
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path("src/twinforge/viewer/static")

MODULES = r"""
import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';
import * as THREE from './src/twinforge/viewer/static/vendor/three.module.min.js';
globalThis.THREE=THREE;
async function module(name, replacements={}){
 let source=readFileSync(`src/twinforge/viewer/static/${name}.js`,'utf8');
 for(const [before,after] of Object.entries(replacements))source=source.replace(before,after);
 return import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
}
const state=await module('view-state');Object.assign(globalThis,state);
const exploration=await module('scene-exploration',{
 "import * as THREE from 'three';":'',"import { validClipRanges } from '/view-state.js';":''});
const snapshot=await module('scene-snapshot');Object.assign(globalThis,snapshot);
const {ExplorationUI}=await module('exploration-ui',{
 "import { fullClipRanges, validView, ViewStore, viewStorageKey } from '/view-state.js';":'',
 "import { canvasPNG, downloadBlob } from '/scene-snapshot.js';":''});
"""

DOM = r"""
class Node {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.checked=false;
 this.disabled=false;this.hidden=false;this.open=false;this.attrs={};this.handlers={};this.style={};this.firstChild={textContent:''};
 this.classList={contains:name=>this.className?.split(' ').includes(name)};}
 append(...items){this.children.push(...items);}
 replaceChildren(...items){this.children=items;this.value='';}
 setAttribute(key,value){this.attrs[key]=value;}
 addEventListener(key,handler){this.handlers[key]=handler;}
 removeEventListener(key,handler){if(this.handlers[key]===handler)delete this.handlers[key];}
 removeAttribute(key){delete this[key];}
 contains(node){return node===this||this.children.some(child=>child===node||child.contains?.(node));}
 focus(){document.activeElement=this;}
 scrollIntoView(){this.scrolled=true;}
 showModal(){this.open=true;}
 close(){this.open=false;this.handlers.close?.();}
 remove(){}
 click(){this.onclick?.();}
}
const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,new Node());return nodes.get(id);};
globalThis.document={activeElement:null,createElement:tag=>new Node(tag),body:new Node('body')};
globalThis.Option=class extends Node {constructor(text,value){super('option');this.textContent=text;this.value=value;}};
const local=new Map();globalThis.localStorage={getItem:key=>local.get(key)??null,setItem:(key,value)=>local.set(key,value)};
let nextFrame=0;const frames=new Map();globalThis.requestAnimationFrame=callback=>{frames.set(++nextFrame,callback);return nextFrame;};
globalThis.cancelAnimationFrame=id=>frames.delete(id);
const flush=()=>{const work=[...frames.values()];frames.clear();work.forEach(callback=>callback());};
const metadata={manifest_sha256:'manifest-a',point_cloud_sha256:'points-a'};
const view={position:[1,2,3],target:[0,0,0],up:[0,0,1],fov:50,near:.01,far:1000,frameId:7,clipEnabled:false,clipRanges:[[0,100],[0,100],[0,100]]};
"""


def run_js(script):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", MODULES + script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-7000:]


def test_view_storage_scope_validation_limit_and_camera_roundtrip():
    run_js(
        DOM
        + r"""
const key=state.viewStorageKey(metadata,'session-a','source');
for(const other of [state.viewStorageKey(metadata,'session-b','source'),state.viewStorageKey(metadata,'session-a','derived'),
 state.viewStorageKey({...metadata,point_cloud_sha256:'different'},'session-a','source')])assert.notEqual(key,other);
const store=new state.ViewStore(localStorage,key);assert.deepEqual(store.list(),[]);
store.add('Entrance',view,'one');store.rename('one',' New name ');assert.equal(store.list()[0].name,'New name');
const camera=new THREE.PerspectiveCamera(50,1,.01,1000);camera.position.set(1,2,3);camera.up.set(0,0,1);
const controls={target:new THREE.Vector3()};
const captured=state.captureView(camera,controls,7,false,state.fullClipRanges());assert.deepEqual(captured,view);
camera.position.set(9,9,9);camera.up.set(0,1,0);camera.fov=70;controls.target.set(1,0,0);
state.restoreCamera(captured,camera,controls);assert.deepEqual(camera.position.toArray(),view.position);
assert.deepEqual(camera.up.toArray(),view.up);assert.equal(camera.fov,50);assert.deepEqual(controls.target.toArray(),view.target);
for(const bad of [{...view,position:[NaN,0,0]},{...view,up:[0,0,0]},{...view,target:view.position},
 {...view,fov:0},{...view,far:0},{...view,clipRanges:[[90,10],[0,100],[0,100]]}]){
 assert.equal(state.validView(bad),false);assert.throws(()=>store.add('Invalid',bad,'bad'));}
assert.throws(()=>store.add('',view,'blank'));assert.throws(()=>store.add('x'.repeat(81),view,'long'));
for(let i=1;i<20;i++)store.add(`View ${i}`,view,`id-${i}`);
assert.throws(()=>store.add('Overflow',view,'overflow'),/limit is 20/);store.remove('one');assert.equal(store.list().length,19);
local.set(key,'not JSON');assert.throws(()=>store.list());assert.throws(()=>store.add('No overwrite',view,'no'));
assert.equal(local.get(key),'not JSON');
localStorage.setItem=()=>{throw Error('Quota exceeded');};assert.throws(()=>new state.ViewStore(localStorage,'other').add('View',view,'x'),/Quota/);
"""
    )


def test_clip_planes_are_correct_and_focus_preserves_view_offset():
    run_js(r"""
const bounds=new THREE.Box3(new THREE.Vector3(-10,-20,-30),new THREE.Vector3(10,20,30));
const before=JSON.stringify(bounds);const box=exploration.makeClipBox(bounds,[[25,75],[10,90],[0,50]]);
assert.deepEqual(box.min.toArray(),[-5,-16,-30]);assert.deepEqual(box.max.toArray(),[5,16,0]);assert.equal(JSON.stringify(bounds),before);
const planes=exploration.boxPlanes(box);
for(const xyz of [[0,0,-5],[-5,-16,-30],[5,16,0]])assert.ok(planes.every(plane=>plane.distanceToPoint(new THREE.Vector3(...xyz))>=0));
for(const xyz of [[-6,0,-5],[6,0,-5],[0,-17,-5],[0,17,-5],[0,0,-31],[0,0,1]])assert.ok(planes.some(plane=>plane.distanceToPoint(new THREE.Vector3(...xyz))<0));
assert.throws(()=>exploration.makeClipBox(bounds,[[50,50],[0,100],[0,100]]));
const flat=exploration.makeClipBox(new THREE.Box3(new THREE.Vector3(),new THREE.Vector3()),state.fullClipRanges());
assert.ok(flat.containsPoint(new THREE.Vector3()));assert.ok(flat.getSize(new THREE.Vector3()).toArray().every(value=>value>0));
const camera=new THREE.PerspectiveCamera();camera.position.set(4,-5,6);camera.up.set(0,0,1);
const controls={target:new THREE.Vector3(1,2,3),update(){}};const offset=camera.position.clone().sub(controls.target);
const up=camera.up.clone(),xyz=[7,8,9];assert.equal(exploration.focusPoint(camera,controls,xyz),true);
assert.deepEqual(controls.target.toArray(),xyz);assert.ok(camera.position.clone().sub(controls.target).distanceTo(offset)<1e-12);
assert.ok(camera.up.equals(up));assert.equal(exploration.focusPoint(camera,controls,[NaN,0,0]),false);
""")


def test_timeline_orders_views_syncs_selection_and_supports_keyboard_and_missing_photos():
    run_js(
        DOM
        + r"""
const selected=[];let looked=0,timeline;
timeline=new exploration.CameraTimeline(byId,id=>{selected.push(id);timeline.sync(id);},()=>looked++);
timeline.render({frames:[{frame_id:9,timestamp_seconds:2,image_url:'/9.jpg'},{frame_id:3,timestamp_seconds:0,image_url:'/3.jpg'},
 {frame_id:7,timestamp_seconds:1,image_url:'/7.jpg'}],cameras:[{frame_id:3,camera_to_world:[[1]]}]});
assert.deepEqual(timeline.frames.map(frame=>frame.frame_id),[3,7,9]);assert.equal(timeline.buttons.length,3);
timeline.buttons[0].click();assert.deepEqual(selected,[3]);assert.equal(byId('timeline-previous').disabled,true);
assert.equal(byId('timeline-look').disabled,false);byId('timeline-look').click();assert.equal(looked,1);
byId('timeline-next').click();assert.equal(timeline.selected,7);assert.equal(byId('timeline-look').disabled,true);
let prevented=false;byId('camera-timeline').onkeydown({key:'End',target:timeline.buttons[1],preventDefault(){prevented=true;}});
assert.equal(prevented,true);assert.equal(timeline.selected,9);assert.equal(document.activeElement,timeline.buttons[2]);
assert.equal(byId('timeline-next').disabled,true);assert.equal(timeline.buttons[2].attrs['aria-pressed'],'true');
const [image,fallback]=timeline.buttons[0].children;image.onerror();assert.equal(image.hidden,true);assert.equal(fallback.hidden,false);
timeline.render({frames:[],cameras:[]});assert.equal(byId('timeline-next').disabled,true);assert.equal(byId('timeline-previous').disabled,true);
assert.equal(byId('timeline-look').disabled,true);assert.ok(byId('timeline-status').textContent.includes('0 saved views'));
"""
    )


def test_exploration_ui_saves_restores_clips_and_handles_storage_failure():
    run_js(
        DOM
        + r"""
let clips=0,restored=null;const ui=new ExplorationUI(byId,{clipChanged:()=>clips++,captureView:()=>({...view,clipEnabled:ui.enabled,clipRanges:ui.ranges}),restoreView:value=>restored=value});
ui.setScene(metadata,'session-a','source');assert.equal(byId('open-saved-view').disabled,true);
byId('saved-view-name').value='Entrance';byId('save-view').click();const id=byId('saved-views').value;
assert.ok(id);assert.equal(ui.store.list().length,1);assert.equal(byId('open-saved-view').disabled,false);
byId('saved-view-name').value='Overview';byId('rename-saved-view').click();assert.equal(ui.store.list()[0].name,'Overview');
byId('clip-enabled').onchange({target:{checked:true}});assert.equal(ui.enabled,true);
byId('clip-x-min').oninput({target:{value:'99'}});byId('clip-x-max').oninput({target:{value:'1'}});
assert.deepEqual(ui.ranges[0],[99,100]);assert.equal(frames.size,1);flush();assert.ok(clips>=3);
byId('open-saved-view').click();assert.equal(ui.enabled,false);assert.deepEqual(restored.position,view.position);
byId('clip-enabled').onchange({target:{checked:true}});byId('clip-reset').click();assert.equal(ui.enabled,false);
assert.deepEqual(ui.ranges,state.fullClipRanges());assert.equal(byId('clip-z-min').disabled,true);
ui.setScene(metadata,'session-a','derived');assert.equal(ui.store.list().length,0);
ui.setScene(metadata,'session-a','source');assert.equal(ui.store.list().length,1);
byId('saved-views').value=id;byId('saved-views').onchange();byId('delete-saved-view').click();assert.equal(ui.store.list().length,0);
local.set(ui.store.key,'bad JSON');ui.setScene(metadata,'session-a','source');assert.equal(ui.store,null);
assert.equal(byId('open-saved-view').disabled,true);assert.ok(byId('saved-view-status').textContent.includes('invalid'));
ui.dispose();assert.equal(frames.size,0);
"""
    )


def test_snapshot_composition_is_bounded_and_contains_context_not_accuracy_claims():
    run_js(r"""
const context={scene_name:'Example room',scene_copy:'source',scale:{type:'estimated_metric',meters_per_unit:1},
 display_label:'All source frames',display_count:'500 rendered',color_mode:'rgb',selected_frame_id:4,
 clip:{enabled:true},hidden_frame_count:2,hidden_roi_count:1,path_visible:true,cameras_visible:false,
 reference_id:'example-reference',manifest_sha256:'a'.repeat(64),point_cloud_sha256:'b'.repeat(64),captured_at:'2026-10-11T00:00:00Z'};
const lines=snapshot.snapshotLines(context,'Overview','Check the doorway');
for(const text of ['estimated_metric','view cropped','Hidden views: 2','Check the doorway','not a metric accuracy certificate','a'.repeat(64)])
 assert.ok(lines.some(line=>line.includes(text)),text);
let drawn,texts=[];const drawing={measureText:text=>({width:text.length*8}),fillRect(){},drawImage(...args){drawn=args;},fillText:text=>texts.push(text)};
const create=()=>({getContext:()=>drawing});const source={width:7680,height:4320};
const canvas=snapshot.composeSnapshot(source,context,'Overview','Note',create);
assert.equal(canvas.width,1920);assert.equal(drawn[3],1920);assert.equal(drawn[4],1080);assert.ok(canvas.height>1080);
texts=[];const tall=snapshot.composeSnapshot({width:50,height:10000},context,'Overview','x'.repeat(500),create);
assert.equal(tall.width,640);assert.equal(drawn[4],1440);assert.ok(tall.height<4000);assert.ok(texts.every(text=>text.length<=75));
assert.throws(()=>snapshot.composeSnapshot({width:0,height:10},context,'','',create),/not ready/);
assert.throws(()=>snapshot.composeSnapshot(source,context,'x'.repeat(81),'',create),/at most/);
assert.throws(()=>snapshot.composeSnapshot(source,context,'','x'.repeat(501),create),/at most/);
const blob=new Blob(['png'],{type:'image/png'});assert.equal(await snapshot.canvasPNG({toBlob:callback=>callback(blob)}),blob);
await assert.rejects(()=>snapshot.canvasPNG({toBlob:callback=>callback(null)}),/encode/);
""")


def test_screenshot_cancel_or_copy_switch_prevents_stale_download():
    run_js(
        DOM
        + r"""
let finish,downloads=0;globalThis.canvasPNG=()=>new Promise(resolve=>finish=resolve);globalThis.downloadBlob=()=>downloads++;
const ui=new ExplorationUI(byId,{clipChanged(){},captureView:()=>view,restoreView(){},screenshot:()=>({})});
ui.setScene(metadata,'session-a','source');byId('capture-view').focus();byId('capture-view').click();
assert.equal(byId('snapshot-dialog').open,true);const pending=byId('snapshot-download').onclick();
byId('snapshot-cancel').click();finish(new Blob(['png']));await pending;assert.equal(downloads,0);
assert.equal(document.activeElement,byId('capture-view'));
byId('capture-view').click();const changed=byId('snapshot-download').onclick();ui.setScene(metadata,'session-a','derived');
finish(new Blob(['png']));await changed;assert.equal(downloads,0);
byId('capture-view').click();const success=byId('snapshot-download').onclick();finish(new Blob(['png']));await success;
assert.equal(downloads,1);assert.equal(byId('snapshot-download').disabled,false);
ui.dispose();
"""
    )


def test_clip_and_focus_use_visible_original_points_without_mutating_xyz():
    run_js(
        DOM
        + r"""
const {visiblePoint}=await module('measurement-state');
const code=readFileSync('src/twinforge/viewer/static/app.js','utf8');
let cloud,current,clipVolume=null,measurement=null,sourcePreview;
const world=new THREE.Scene(),visibility={hidden_frame_ids:[],hidden_rois:[]};metadata.pixel_transforms=[];
byId('point-size').value='2';byId('color-mode').value='rgb';
let display;eval(code.slice(code.indexOf('function display('),code.indexOf('\nfunction fitScene(')).replace('function display(','display = function('));
const bundle={header:{count:4,frame_id:null},xyz:new Float32Array([-2,0,0,0,0,0,2,0,0,NaN,0,0]),
 rgb:new Uint8Array(12),valid:new Uint8Array([1,1,1,1]),frame_ids:new Uint32Array([1,1,2,2]),point_indices:new BigUint64Array([0n,1n,2n,3n])};
const before=Buffer.from(bundle.xyz.buffer).toString('hex');display(bundle,'All source frames');
assert.deepEqual(Array.from(cloud.geometry.index.array),[0,1,2]);
clipVolume=new THREE.Box3(new THREE.Vector3(-1,-1,-1),new THREE.Vector3(1,1,1));display(bundle,'Clipped');
assert.deepEqual(Array.from(cloud.geometry.index.array),[1]);assert.ok(byId('display-count').textContent.startsWith('1 rendered'));
const raycaster={intersectObject:()=>[{index:0},{index:1},{index:2}]};let visibleCloudHit;
eval(code.slice(code.indexOf('function visibleCloudHit('),code.indexOf('\nfunction focusAtPointer(')).replace('function visibleCloudHit(','visibleCloudHit = function('));
assert.equal(visibleCloudHit().index,1);visibility.hidden_frame_ids=[1];assert.equal(visibleCloudHit(),undefined);
visibility.hidden_frame_ids=[];clipVolume=null;display(bundle,'Reset');assert.deepEqual(Array.from(cloud.geometry.index.array),[0,1,2]);
assert.equal(Buffer.from(bundle.xyz.buffer).toString('hex'),before);cloud.geometry.dispose();cloud.material.dispose();
"""
    )


def test_actual_workspace_wires_tools_and_renders_before_screenshot_copy():
    run_js(
        DOM
        + r"""
const {makeClipBox,boxPlanes,CameraTimeline}=exploration;const {captureView,restoreCamera}=state;const {composeSnapshot}=snapshot;
const {disposeGeometryGroup}=await module('camera-path',{"import * as THREE from 'three';":''});
let timeline,explorationUI,sourcePreview,cloud,current,clipVolume=null,clipOutline,resetCount=0,selectedFrame=null;
// Production uses the name exploration for its UI controller.
const code=readFileSync('src/twinforge/viewer/static/app.js','utf8');
const sceneVariant='source',sceneContext={apiPrefix:'scene-session'},workspace={loading:false};
const bounds=new THREE.Box3(new THREE.Vector3(-2,-2,-2),new THREE.Vector3(2,2,2)),world=new THREE.Scene();
const camera=new THREE.PerspectiveCamera(50,1,.01,1000);camera.position.set(1,2,3);camera.up.set(0,0,1);
const controls={target:new THREE.Vector3(),update(){}};
const visibility={hidden_frame_ids:[],hidden_rois:[]},cameraPath={visible:true},cameraGroup={visible:true},measurement=null;
Object.assign(metadata,{name:'Example room',scale:{type:'relative'},frames:[{frame_id:7,timestamp_seconds:1,image_url:'/7.jpg'}],
 cameras:[{frame_id:7,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}]});
byId('loading').hidden=true;byId('display-count').textContent='4 rendered';byId('view-label').textContent='All source frames';byId('color-mode').value='rgb';
const order=[];const canvas={width:600,height:400};const renderer={domElement:canvas,render(){order.push('render');}};
const create=document.createElement;document.createElement=tag=>tag==='canvas'?{getContext:()=>({measureText:text=>({width:text.length*8}),
 fillRect(){},drawImage(source){assert.equal(source,canvas);order.push('copy');},fillText(){}})}:create(tag);
function display(){}function resetControlsForUp(){resetCount++;}function lookFromCamera(){}
function selectFrame(id){selectedFrame=metadata.frames.find(frame=>frame.frame_id===id);timeline?.sync(id);}
let applyViewingClip,setupExploration,previewHit,setupSourcePreview;
const section=code.slice(code.indexOf('function applyViewingClip('),code.indexOf('\nfunction addEndpoint('))
 .replaceAll('exploration','explorationUI');
eval(section.replace(/^function (\w+)\(/gm,'$1 = function('));
setupExploration();assert.equal(timeline.buttons.length,1);assert.equal(renderer.clippingPlanes.length,0);
byId('saved-view-name').value='Overview';byId('save-view').click();const id=byId('saved-views').value;
camera.position.set(9,9,9);byId('open-saved-view').click();assert.deepEqual(camera.position.toArray(),[1,2,3]);
assert.equal(resetCount,1);assert.equal(selectedFrame,undefined);
byId('clip-enabled').onchange({target:{checked:true}});assert.equal(renderer.clippingPlanes.length,6);assert.ok(clipOutline);
byId('capture-view').click();globalThis.canvasPNG=async()=>new Blob(['PNG']);globalThis.downloadBlob=()=>order.push('download');
await byId('snapshot-download').onclick();assert.deepEqual(order,['render','copy','download']);
workspace.loading=true;byId('save-view').click();assert.equal(explorationUI.store.list().length,1);
assert.ok(byId('saved-view-status').textContent.includes('Wait for the scene'));
workspace.loading=false;explorationUI.setScene({...metadata,point_cloud_sha256:'new'},'scene-session','derived');
assert.equal(explorationUI.store.list().length,0);assert.equal(renderer.clippingPlanes.length,0);assert.equal(clipOutline,null);
explorationUI.dispose();
"""
    )


def test_double_click_cancels_inspection_without_changing_measurement_picks():
    run_js(
        DOM
        + r"""
const code=readFileSync('src/twinforge/viewer/static/app.js','utf8');
let pickMode=null,inspectTimer,disposed=false,inspected=0,focused=0;
const workspace={loading:false};function inspectClick(){inspected++;}function focusAtPointer(){if(pickMode!=='3d')focused++;}
const handlers={};const renderer={domElement:{addEventListener:(name,handler)=>handlers[name]=handler}};
const timers=new Map();let sequence=0;globalThis.setTimeout=callback=>{timers.set(++sequence,callback);return sequence;};
globalThis.clearTimeout=id=>timers.delete(id);
eval(code.slice(code.indexOf('  let down;'),code.indexOf('  const remembered = loadView();')));
const click={clientX:10,clientY:10};handlers.pointerdown(click);handlers.pointerup(click);
assert.equal(inspected,0);assert.equal(timers.size,1);
handlers.pointerdown(click);handlers.pointerup(click);handlers.dblclick(click);
assert.equal(timers.size,0);assert.equal(focused,1);assert.equal(inspected,0);
pickMode='3d';handlers.pointerdown(click);handlers.pointerup(click);assert.equal(inspected,1);
handlers.dblclick(click);assert.equal(focused,1,'Focus changed the scene during measurement picking');
pickMode=null;handlers.pointerdown(click);handlers.pointerup({clientX:20,clientY:20});assert.equal(timers.size,0);
handlers.pointerdown(click);handlers.pointerup(click);handlers.pointercancel();assert.equal(timers.size,0);
"""
    )


def test_exploration_assets_and_accessible_controls_are_served():
    from twinforge.viewer.server import STATIC_FILES

    for name in ["view-state", "scene-exploration", "scene-snapshot", "exploration-ui"]:
        assert STATIC_FILES[f"/{name}.js"] == f"{name}.js"

    class Controls(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = {}
            self.labels = set()

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                assert attrs["id"] not in self.ids
                self.ids[attrs["id"]] = (tag, attrs)
            if tag == "label":
                self.labels.add(attrs.get("for"))

    parser = Controls()
    parser.feed((STATIC / "index.html").read_text())
    for axis in "xyz":
        for side in ["min", "max"]:
            key = f"clip-{axis}-{side}"
            assert key in parser.labels
            assert parser.ids[key][1]["type"] == "range"
    assert parser.ids["snapshot-dialog"][1]["aria-labelledby"] == "snapshot-heading"
    assert parser.ids["snapshot-title"][1]["maxlength"] == "80"
    assert parser.ids["snapshot-note"][1]["maxlength"] == "500"
    assert parser.ids["saved-view-name"][1]["maxlength"] == "80"
    assert parser.ids["camera-timeline"][1]["aria-label"]
