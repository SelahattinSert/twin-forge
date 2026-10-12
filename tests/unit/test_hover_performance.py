"""Read-only camera icons and bounded, exact-row hover acceleration."""

from tests.unit.test_scene_exploration import DOM, run_js


def test_index_matches_brute_screen_search_and_invalidates_for_camera_and_geometry():
    run_js(r"""
const {HoverIndex}=await module('hover-index');
const camera=new THREE.PerspectiveCamera(50,1,.01,100);
camera.position.set(0,0,5);camera.lookAt(0,0,0);camera.updateMatrixWorld();
let seed=123;const rand=()=>((seed=(1664525*seed+1013904223)>>>0)/4294967296);
const xyz=new Float32Array(12000);for(let i=0;i<xyz.length;i++)xyz[i]=rand()*4-2;
const before=xyz.slice(),cloud=new THREE.Points(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(xyz,3)),new THREE.PointsMaterial());
cloud.geometry.setIndex(Array.from({length:2000},(_,i)=>i*2));
const index=new HoverIndex();let steps=0;
while(!index.prepare(cloud,camera,400,400,0)){steps++;assert.ok(steps<100);assert.equal(index.query(200,200),null);}
assert.ok(steps>1);assert.deepEqual(xyz,before);
assert.ok(index.byteLength<=16*2000+4*50*50);
function brute(x,y,radius){
 let best=null,depth=Infinity,distance=Infinity;
 for(const id of cloud.geometry.index.array){
  const p=new THREE.Vector3().fromArray(xyz,id*3).project(camera);
  const px=Math.fround((p.x+1)*200),py=Math.fround((1-p.y)*200),z=Math.fround(p.z),d=(px-x)**2+(py-y)**2;
  if(px>=0&&px<400&&py>=0&&py<400&&p.z>=-1&&p.z<=1&&d<=radius**2&&(z<depth||(z===depth&&d<distance))){best=id;depth=z;distance=d;}
 }return best;
}
for(let i=0;i<100;i++){const x=rand()*400,y=rand()*400;assert.equal(index.query(x,y,5),brute(x,y,5));}
const oldSignature=index.signature;camera.position.x=1;camera.lookAt(0,0,0);
assert.equal(index.prepare(cloud,camera,400,400,0),false);assert.notEqual(index.signature,oldSignature);
cloud.geometry.setIndex([1]);assert.equal(index.prepare(cloud,camera,400,400),true);assert.equal(index.count,1);
const p=new THREE.Vector3().fromArray(xyz,3).project(camera);assert.equal(index.query((p.x+1)*200,(1-p.y)*200),1);
index.reset();assert.equal(index.byteLength,0);assert.equal(index.geometry,null);assert.equal(index.positions,null);assert.equal(index.query(200,200),null);
cloud.geometry.dispose();cloud.material.dispose();
""")


def test_hover_uses_frontmost_rendered_point_and_excludes_offscreen_points():
    run_js(r"""
const {HoverIndex}=await module('hover-index');const camera=new THREE.PerspectiveCamera(50,1,.1,10);
camera.position.set(0,0,4);camera.lookAt(0,0,0);
const xyz=new Float32Array([0,0,0,0,0,1,0,0,5,100,0,0,0,0,-100]);
const cloud=new THREE.Points(new THREE.BufferGeometry().setAttribute('position',new THREE.BufferAttribute(xyz,3)),new THREE.PointsMaterial());
const index=new HoverIndex();while(!index.prepare(cloud,camera,200,200)){}
assert.equal(index.query(100,100),1);assert.equal(index.query(0,0),null);
cloud.geometry.setIndex([0,2,3,4]);while(!index.prepare(cloud,camera,200,200)){}
assert.equal(index.query(100,100),0);cloud.geometry.setIndex([]);assert.equal(index.prepare(cloud,camera,200,200),true);assert.equal(index.query(100,100),null);
cloud.geometry.dispose();cloud.material.dispose();index.reset();
""")


def test_camera_icons_share_one_texture_and_leave_saved_poses_untouched():
    run_js(r"""
const {buildCameraMarkers}=await module('camera-markers',{"import * as THREE from 'three';":''});
const texture=new THREE.Texture();const records=[{frame_id:7,camera_to_world:[[1,0,0,1],[0,1,0,2],[0,0,1,3],[0,0,0,1]]},{frame_id:8,camera_to_world:null}];
const before=JSON.stringify(records),group=buildCameraMarkers(records,texture);
assert.equal(group.children.length,1);const sprite=group.children[0];assert.ok(sprite.isSprite);
assert.deepEqual(sprite.position.toArray(),[1,2,3]);assert.equal(sprite.userData.frameId,7);
assert.equal(sprite.material.map,texture);assert.equal(sprite.material.sizeAttenuation,false);assert.equal(sprite.material.depthTest,true);
assert.equal(JSON.stringify(records),before);
const many=buildCameraMarkers([...records,records[0]],texture);assert.equal(many.children[0].material,many.children[1].material);
sprite.material.dispose();many.children[0].material.dispose();texture.dispose();
""")


def test_repeated_display_never_duplicates_or_transforms_point_geometry():
    run_js(
        DOM
        + r"""
const {visiblePoint}=await module('measurement-state');
const world=new THREE.Scene();let cloud,current,sourcePreview,measurement,clipVolume=null;
const visibility={hidden_frame_ids:[],hidden_rois:[]};metadata.pixel_transforms=[];
byId('point-size').value='2';byId('color-mode').value='rgb';
const bundle={header:{count:2,frame_id:null},xyz:new Float32Array([1,2,3,4,5,6]),rgb:new Uint8Array(6),valid:new Uint8Array([1,1]),frame_ids:new Uint32Array([3,4]),point_indices:new BigUint64Array([7n,8n])};
const before=bundle.xyz.slice(),code=readFileSync('src/twinforge/viewer/static/app.js','utf8');let display;
eval(code.slice(code.indexOf('function display('),code.indexOf('\nfunction fitScene(')).replace('function display(','display=function('));
for(let i=0;i<5;i++){
 let disposed=0;if(cloud)cloud.geometry.addEventListener('dispose',()=>disposed++);
 display(bundle,'Test');assert.equal(world.children.filter(child=>child.isPoints).length,1);
 if(i)assert.equal(disposed,1);assert.deepEqual(bundle.xyz,before);
 assert.equal(cloud.geometry.attributes.position.array,bundle.xyz);cloud.updateMatrixWorld();assert.ok(cloud.matrixWorld.equals(new THREE.Matrix4()));
}
visibility.hidden_frame_ids=[3];display(bundle,'Filtered');assert.deepEqual(Array.from(cloud.geometry.index.array),[1]);assert.deepEqual(bundle.xyz,before);
cloud.geometry.dispose();cloud.material.dispose();
"""
    )
