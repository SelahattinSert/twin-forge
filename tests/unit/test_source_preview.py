"""Hover/photo navigation and collapsed timeline contracts, without ML weights."""

from html.parser import HTMLParser

from tests.unit.test_scene_exploration import DOM, STATIC, run_js

PREVIEW = r"""
const {SourcePreview,sourcePreviewInfo,previewPosition}=await module('source-preview');
const {HoverIndex}=await module('hover-index');
const scene={frames:[{frame_id:4,timestamp_seconds:2,image_url:'/4.jpg'},{frame_id:3,timestamp_seconds:1,image_url:'/3.jpg'}],
 cameras:[{frame_id:3,camera_to_world:[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]}]};
"""

SURFACE = r"""
const canvas=new Node('canvas'),viewport=new Node();
viewport.getBoundingClientRect=()=>({left:0,top:0,right:800,bottom:600,width:800,height:600});
byId('hover-preview').hidden=true;
byId('hover-image').replaceWith=replacement=>nodes.set('hover-image',replacement);
const loaders=[];globalThis.Image=class extends Node {
 constructor(){super('img');loaders.push(this);}
 replaceWith(replacement){nodes.set('hover-image',replacement);}
};
const timers=new Map();let serial=0;
globalThis.setTimeout=(fn,delay)=>{timers.set(++serial,{fn,delay});return serial;};
globalThis.clearTimeout=id=>timers.delete(id);
function expire(delay){const due=[...timers].filter(([id,timer])=>timer.delay===delay);for(const [id,timer]of due){timers.delete(id);timer.fn();}}
"""


def test_hover_descriptor_uses_exact_provenance_not_a_nearby_frame():
    run_js(
        PREVIEW
        + r"""
const before=JSON.stringify(scene);
const camera=sourcePreviewInfo(scene,{kind:'camera',frameId:3});
assert.equal(camera.title,'View 1 of 2');assert.ok(camera.detail.includes('Frame 3 · 1.00s'));
assert.equal(camera.imageURL,'/3.jpg');assert.equal(camera.canLook,true);
const point=sourcePreviewInfo(scene,{kind:'point',frameId:4,pointIndex:'9876543210'});
assert.equal(point.title,'Point 9876543210');assert.equal(point.imageURL,'/4.jpg');assert.equal(point.canLook,false);
assert.ok(point.note.includes('pose unavailable'));assert.ok(point.detail.includes('View 2 of 2'));
const unknown=sourcePreviewInfo(scene,{kind:'point',frameId:99,pointIndex:'1'});
assert.equal(unknown.imageURL,null);assert.equal(unknown.frameId,null);assert.equal(unknown.canLook,false);
assert.equal(unknown.note,'No nearby photo is substituted.');assert.equal(JSON.stringify(scene),before);
"""
    )


def test_preview_card_position_stays_in_the_viewport():
    run_js(
        PREVIEW
        + r"""
for(const [x,y] of [[0,0],[400,300],[799,599],[0,599],[799,0]]){
 const p=previewPosition(x,y,800,600,264,265);assert.ok(p.left>=12&&p.left+264<=788);
 assert.ok(p.top>=12&&p.top+265<=588);
}
const right=previewPosition(790,200,800,600,264,265);assert.ok(right.left<790-264);
const small=previewPosition(250,200,300,300,264,265);assert.ok(small.left>=12&&small.top>=12);
"""
    )


def test_hover_photo_loading_is_race_safe_and_click_uses_its_own_pose():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
const looked=[];const preview=new SourcePreview(byId,canvas,viewport,{hit(){},look:id=>looked.push(id)});
const a=sourcePreviewInfo(scene,{kind:'camera',frameId:3}),b=sourcePreviewInfo(scene,{kind:'point',frameId:4,pointIndex:'12'});
preview.show(a,{clientX:200,clientY:200});const first=loaders.at(-1),stale=first.onload;
assert.equal(byId('hover-preview').hidden,false);assert.equal(byId('hover-look').disabled,false);assert.equal(byId('hover-marker').hidden,false);
preview.show(b,{clientX:300,clientY:200});const second=loaders.at(-1);assert.equal(first.onload,null);stale();
assert.equal(byId('hover-image').src,undefined);assert.equal(byId('hover-look').disabled,true);
second.onload();assert.equal(byId('hover-image').src,'/4.jpg');assert.equal(byId('hover-image').hidden,false);
byId('hover-look').click();assert.deepEqual(looked,[]);
const cachedCount=loaders.length;preview.hide();preview.show(b,{clientX:200,clientY:200});assert.equal(loaders.length,cachedCount);
assert.equal(byId('hover-image').src,'/4.jpg');preview.hide();assert.equal(byId('hover-preview').hidden,true);
preview.show(a,{clientX:200,clientY:200});const abandoned=loaders.at(-1),late=abandoned.onload;
preview.hide();assert.equal(abandoned.onload,null);late();assert.equal(preview.photos.has('/3.jpg'),false);
preview.show(a,{clientX:200,clientY:200});loaders.at(-1).onerror();assert.equal(byId('hover-photo-fallback').textContent,'Source photo unavailable');
byId('hover-look').click();assert.deepEqual(looked,[3]);assert.equal(byId('hover-preview').hidden,true);
assert.equal(byId('hover-marker').hidden,true);preview.dispose();assert.equal(Object.keys(canvas.handlers).length,0);
"""
    )


def test_hover_coalesces_pointer_events_without_a_fixed_delay_and_keeps_card_open():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
let hits=0;const info=sourcePreviewInfo(scene,{kind:'camera',frameId:3});
const preview=new SourcePreview(byId,canvas,viewport,{hit(){hits++;return {info};},look(){}});
for(let i=0;i<20;i++)canvas.handlers.pointermove({clientX:200+i,clientY:200,buttons:0,pointerType:'mouse'});
assert.equal(hits,0);assert.equal(timers.size,0);assert.equal(frames.size,1);flush();assert.equal(hits,1);
canvas.handlers.pointerleave({relatedTarget:byId('hover-preview')});assert.equal(timers.size,0);
canvas.handlers.pointerleave({relatedTarget:null});assert.equal(timers.size,1);
byId('hover-preview').handlers.pointerenter();expire(70);assert.equal(byId('hover-preview').hidden,false);
canvas.handlers.pointerdown();assert.equal(byId('hover-preview').hidden,true);
canvas.handlers.pointermove({clientX:200,clientY:200,buttons:1});flush();assert.equal(hits,1);
canvas.handlers.pointerup();canvas.handlers.pointermove({clientX:200,clientY:200,buttons:0,pointerType:'touch'});assert.equal(timers.size,0);
preview.show(info,{clientX:200,clientY:200});byId('hover-preview').append(byId('hover-look'));byId('hover-look').focus();
viewport.handlers.keydown({key:'Escape'});assert.equal(byId('hover-preview').hidden,true);assert.equal(document.activeElement,canvas);
canvas.handlers.pointermove({clientX:200,clientY:200,buttons:0});preview.dispose();flush();assert.equal(hits,1);
"""
    )


def test_actual_camera_and_point_hover_respects_visibility_and_clip():
    run_js(
        PREVIEW
        + r"""
const metadata={...scene,pixel_transforms:[]};const {visiblePoint}=await module('measurement-state');
const visibility={hidden_frame_ids:[],hidden_rois:[]};let clipVolume=null,pickMode=null;
const workspace={loading:false},camera=new THREE.PerspectiveCamera(50,1,.01,100);camera.position.set(0,0,4);camera.lookAt(0,0,0);camera.updateMatrixWorld();
const cameraGroup={visible:false,userData:{}},cameraTargets=[],cameraPath=new THREE.Group();
const sourcePreview={pointIndex:new HoverIndex()},byId=()=>({value:2});
const node=new THREE.Mesh(new THREE.SphereGeometry(.1,8,8),new THREE.MeshBasicMaterial());
node.userData={kind:'camera_path_node',frameId:3};cameraPath.add(node);cameraPath.updateMatrixWorld(true);
const current={xyz:new Float32Array([0,0,-1,1,0,-1]),frame_ids:new Uint32Array([4,4]),valid:new Uint8Array([1,1]),point_indices:new BigUint64Array([900n,901n])};
const cloud=new THREE.Points(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(current.xyz,3)),new THREE.PointsMaterial());cloud.updateMatrixWorld(true);
const rect={left:0,top:0,width:200,height:200};const renderer={domElement:{getBoundingClientRect:()=>rect}};
const raycaster=new THREE.Raycaster();raycaster.params.Points.threshold=.1;const pointer=new THREE.Vector2();
const code=readFileSync('src/twinforge/viewer/static/app.js','utf8');let previewHit,visibleCloudHit;
for(const [start,end] of [['function visibleCloudHit(','\nfunction focusAtPointer('],['function previewHit(','\nfunction setupSourcePreview(']])
 eval(code.slice(code.indexOf(start),code.indexOf(end)).replace(/^function (\w+)\(/gm,'$1 = function('));
const event={clientX:100,clientY:100};let hit=previewHit(event);assert.equal(hit.info.kind,'Camera position');assert.equal(hit.info.frameId,3);
cameraPath.visible=false;hit=previewHit(event);assert.equal(hit.info.kind,'Observed point');assert.equal(hit.info.title,'Point 900');assert.equal(hit.info.frameId,4);
assert.equal(previewHit(event,true),null,'A dense point must not replace a departing camera popup');
assert.ok(Math.abs(hit.anchor.clientX-100)<1e-9);
const icon=new THREE.Sprite(new THREE.SpriteMaterial());icon.position.set(0,0,1);icon.scale.set(.2,.2,1);icon.userData.frameId=3;icon.updateMatrixWorld();
cameraGroup.userData.iconTargets=[icon];cameraGroup.visible=true;hit=previewHit(event);
assert.equal(hit.info.kind,'Camera position');assert.equal(hit.info.frameId,3);
const calls=[];const selectFrame=id=>calls.push(id);let inspectClick;
eval(code.slice(code.indexOf('function inspectClick('),code.indexOf('\nfunction visibleCloudHit(')).replace('function inspectClick(','inspectClick=function('));
inspectClick(event);assert.deepEqual(calls,[3]);cameraGroup.visible=false;icon.material.dispose();
visibility.hidden_frame_ids=[4];assert.equal(previewHit(event),null);visibility.hidden_frame_ids=[];
clipVolume=new THREE.Box3(new THREE.Vector3(-1,-1,0),new THREE.Vector3(1,1,1));assert.equal(previewHit(event),null);
clipVolume=null;pickMode='3d';assert.equal(previewHit(event),null);pickMode=null;workspace.loading=true;assert.equal(previewHit(event),null);
cloud.geometry.dispose();cloud.material.dispose();node.geometry.dispose();node.material.dispose();
"""
    )


def test_photo_cache_is_bounded_and_dispose_cancels_work():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
const preview=new SourcePreview(byId,canvas,viewport,{hit(){return {pending:true};},look(){}});
for(let i=0;i<12;i++){
 const info={...sourcePreviewInfo(scene,{kind:'camera',frameId:3}),key:String(i),imageURL:`/${i}.jpg`};
 preview.show(info,{clientX:100,clientY:100});loaders.at(-1).onload();
}
assert.equal(preview.photos.size,8);assert.equal(preview.photos.has('/0.jpg'),false);
const count=loaders.length;preview.hide();preview.show({...sourcePreviewInfo(scene,{kind:'camera',frameId:3}),imageURL:'/11.jpg'},{clientX:100,clientY:100});
assert.equal(loaders.length,count);assert.equal(byId('hover-image'),preview.photos.get('/11.jpg'));
canvas.handlers.pointermove({clientX:200,clientY:200,buttons:0});flush();assert.equal(frames.size,1);
preview.show({...sourcePreviewInfo(scene,{kind:'camera',frameId:3}),imageURL:'/pending.jpg'},{clientX:100,clientY:100});
const pending=loaders.at(-1),late=pending.onload;preview.dispose();late();flush();
assert.equal(pending.onload,null);assert.equal(pending.src,undefined);assert.equal(preview.photos.size,0);assert.equal(frames.size,0);
"""
    )


def test_clicking_hover_photo_selects_frame_then_looks_from_camera():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
const calls=[];let sourcePreview;const renderer={domElement:canvas},workspace={loading:false};let pickMode=null;
const flags=[];function previewHit(point,cameraOnly){flags.push(cameraOnly);return null;}function selectFrame(id){calls.push(`select:${id}`);}function lookFromCamera(){calls.push('look');}
const code=readFileSync('src/twinforge/viewer/static/app.js','utf8');let setupSourcePreview;
eval(code.slice(code.indexOf('function setupSourcePreview('),code.indexOf('\nfunction addEndpoint(')).replace('function setupSourcePreview(','setupSourcePreview = function('));
setupSourcePreview();sourcePreview.show(sourcePreviewInfo(scene,{kind:'camera',frameId:3}),{clientX:100,clientY:100});
sourcePreview.callbacks.hit({clientX:100,clientY:100});assert.deepEqual(flags,[true]);assert.equal(sourcePreview.pointIndex,undefined);
byId('hover-look').click();assert.deepEqual(calls,['select:3','look']);
sourcePreview.show(sourcePreviewInfo(scene,{kind:'camera',frameId:3}),{clientX:100,clientY:100});workspace.loading=true;
byId('hover-look').click();assert.equal(calls.length,2);sourcePreview.dispose();
"""
    )


def test_camera_popup_closes_while_pointer_keeps_moving_without_extending_deadline():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
const preview=new SourcePreview(byId,canvas,viewport,{hit:()=>null,look(){}});
preview.show(sourcePreviewInfo(scene,{kind:'camera',frameId:3}),{clientX:200,clientY:200});
canvas.handlers.pointermove({clientX:500,clientY:300,buttons:0});flush();
assert.equal(timers.size,1);const deadline=[...timers.keys()][0];
for(let i=0;i<30;i++){canvas.handlers.pointermove({clientX:500+i,clientY:300,buttons:0});flush();assert.equal([...timers.keys()][0],deadline);}
expire(70);assert.equal(byId('hover-preview').hidden,true);assert.equal(byId('hover-marker').hidden,true);
preview.dispose();
"""
    )


def test_leaving_the_card_for_stationary_canvas_closes_without_an_extra_move():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
const preview=new SourcePreview(byId,canvas,viewport,{hit:()=>null,look(){}});
preview.show(sourcePreviewInfo(scene,{kind:'camera',frameId:3}),{clientX:200,clientY:200});
canvas.handlers.pointerleave({relatedTarget:byId('hover-preview')});byId('hover-preview').handlers.pointerenter();
assert.equal(timers.size,0);byId('hover-preview').handlers.pointerleave({relatedTarget:canvas});
expire(70);assert.equal(byId('hover-preview').hidden,true);preview.dispose();
"""
    )


def test_mouse_focus_does_not_pin_popup_but_keyboard_focus_is_preserved():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
const card=byId('hover-preview'),button=byId('hover-look');card.append(button);
const preview=new SourcePreview(byId,canvas,viewport,{hit:()=>null,look(){}});
const info=sourcePreviewInfo(scene,{kind:'camera',frameId:3});
preview.show(info,{clientX:200,clientY:200});button.focus();button.matches=()=>false;
card.handlers.pointerdown();card.handlers.focusin({target:button});preview.scheduleHide();expire(70);
assert.equal(card.hidden,true);assert.equal(document.activeElement,canvas);
preview.show(info,{clientX:200,clientY:200});button.focus();button.matches=()=>true;
card.handlers.focusin({target:button});preview.scheduleHide();expire(70);assert.equal(card.hidden,false);
document.activeElement=canvas;card.handlers.focusout({relatedTarget:canvas});expire(70);assert.equal(card.hidden,true);preview.dispose();
"""
    )


def test_fade_can_be_interrupted_and_stale_animation_cannot_close_reopened_card():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
const card=byId('hover-preview'),animations=[];
card.animate=(keyframes,options)=>{const animation={keyframes,options,cancelled:false,cancel(){this.cancelled=true;}};animations.push(animation);return animation;};
const preview=new SourcePreview(byId,canvas,viewport,{hit:()=>null,look(){}});
const info=sourcePreviewInfo(scene,{kind:'camera',frameId:3});preview.show(info,{clientX:200,clientY:200});
assert.equal(animations[0].options.duration,120);preview.show(info,{clientX:200,clientY:200});assert.equal(animations.length,1);
preview.scheduleHide();expire(70);assert.equal(animations[0].cancelled,true);assert.equal(card.hidden,false);
const fading=animations.at(-1),late=fading.onfinish;assert.equal(fading.options.duration,90);
card.handlers.pointerenter();assert.equal(fading.cancelled,true);late();assert.equal(card.hidden,false);
card.handlers.pointerleave({relatedTarget:canvas});expire(70);animations.at(-1).onfinish();assert.equal(card.hidden,true);
preview.dispose();assert.equal(timers.size,0);assert.equal(frames.size,0);
"""
    )


def test_reduced_motion_disables_preview_animations():
    run_js(
        DOM
        + PREVIEW
        + SURFACE
        + r"""
globalThis.matchMedia=()=>({matches:true});let animations=0;
byId('hover-preview').animate=()=>{animations++;};
const preview=new SourcePreview(byId,canvas,viewport,{hit:()=>null,look(){}});
preview.show(sourcePreviewInfo(scene,{kind:'camera',frameId:3}),{clientX:200,clientY:200});
preview.scheduleHide();expire(70);assert.equal(animations,0);assert.equal(byId('hover-preview').hidden,true);preview.dispose();
"""
    )


def test_collapsed_timeline_does_not_scroll_page_or_auto_reopen_on_selection():
    run_js(
        DOM
        + PREVIEW
        + r"""
const timeline=new exploration.CameraTimeline(byId,id=>timeline.sync(id),()=>{});
timeline.render(scene);assert.equal(byId('timeline-count').textContent,'2 views');
byId('source-views').open=false;timeline.choose(0);assert.equal(timeline.buttons[0].scrolled,undefined);
assert.equal(byId('source-views').open,false);byId('source-views').open=true;timeline.sync(4);
assert.equal(timeline.buttons[1].scrolled,true);timeline.render(scene);assert.equal(byId('source-views').open,true);
"""
    )


def test_collapsible_and_hover_controls_are_accessible_and_served():
    from twinforge.viewer.server import STATIC_FILES

    class Elements(HTMLParser):
        def __init__(self):
            super().__init__()
            self.elements = {}

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if "id" in attrs:
                self.elements[attrs["id"]] = (tag, attrs)

    parser = Elements()
    parser.feed((STATIC / "index.html").read_text())
    tag, attrs = parser.elements["source-views"]
    assert tag == "details"
    assert "open" not in attrs
    assert parser.elements["hover-look"][0] == "button"
    assert parser.elements["hover-look"][1]["aria-label"]
    assert parser.elements["hover-close"][1]["aria-label"]
    assert parser.elements["hover-marker"][1]["aria-hidden"] == "true"
    assert STATIC_FILES["/source-preview.js"] == "source-preview.js"
