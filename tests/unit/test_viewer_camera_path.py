"""Display-only camera paths preserve saved poses and chronological ordering."""

import re
import subprocess
from pathlib import Path


def test_interface_has_no_tiny_text_sizes():
    root = Path("src/twinforge/viewer/static")
    for filename in ("styles.css", "library.css"):
        source = (root / filename).read_text()
        sizes = re.findall(r"(?:font-size:\s*|font:\s*)(\d+(?:\.\d+)?)px", source)
        assert sizes
        assert all(float(size) >= 13 for size in sizes), filename


def test_camera_path_uses_real_three_geometry_without_smoothing_or_bridging_missing_poses():
    script = r"""
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as THREE from './src/twinforge/viewer/static/vendor/three.module.min.js';
let source=readFileSync('src/twinforge/viewer/static/camera-path.js','utf8')
 .replace("import * as THREE from 'three';",'');
globalThis.THREE=THREE;
const {buildCameraPath,disposeGeometryGroup}=await import('data:text/javascript;base64,'+
 Buffer.from(source+'\n//# sourceURL=camera-path-test.js').toString('base64'));
const camera=(id,t,xyz)=>({frame_id:id,timestamp_seconds:t,camera_to_world:xyz?
 [[1,0,0,xyz[0]],[0,1,0,xyz[1]],[0,0,1,xyz[2]],[0,0,0,1]]:null});
const cameras=[camera(3,2,[1,1,1]),camera(1,0,[0,0,0]),camera(2,1,[1,0,0])];
const original=JSON.stringify(cameras);const path=buildCameraPath(cameras,10);
assert.equal(JSON.stringify(cameras),original,'Source camera records were mutated');
assert.equal(path.userData.sampleCount,3);assert.equal(path.userData.segmentCount,2);
assert.equal(path.userData.startFrameId,1);assert.equal(path.userData.endFrameId,3);
const segments=path.children.filter(node=>node.userData.kind==='camera_path_segment');
const endpoints=segment=>{
 segment.updateMatrix();return [new THREE.Vector3(0,-.5,0).applyMatrix4(segment.matrix),
  new THREE.Vector3(0,.5,0).applyMatrix4(segment.matrix)];};
for(const [i,segment] of segments.entries()){
 const [start,end]=endpoints(segment);const positions=[[0,0,0],[1,0,0],[1,1,1]];
 assert.ok(start.distanceTo(new THREE.Vector3(...positions[i]))<1e-10);
 assert.ok(end.distanceTo(new THREE.Vector3(...positions[i+1]))<1e-10);
 assert.ok(segment.geometry instanceof THREE.CylinderGeometry);
 assert.equal(segment.material.depthTest,true,'Path must not claim visibility through surfaces');
}
const nodes=path.children.filter(node=>node.userData.kind==='camera_path_node');
assert.deepEqual(nodes.map(node=>node.userData.frameId),[1,2,3]);
assert.notEqual(nodes[0].material.color.getHex(),nodes[2].material.color.getHex());
const gap=buildCameraPath([camera(1,0,[0,0,0]),camera(2,1,null),camera(3,2,[2,0,0])],10);
assert.equal(gap.userData.segmentCount,0);assert.equal(gap.userData.missingPoseCount,1);
const repeated=buildCameraPath([camera(1,0,[0,0,0]),camera(2,1,[0,0,0]),camera(3,2,[0,0,1])],1);
assert.equal(repeated.userData.segmentCount,1);
const single=buildCameraPath([camera(1,0,[0,0,0])],1);assert.equal(single.userData.segmentCount,0);
const empty=buildCameraPath([],1);assert.equal(empty.children.length,0);
for(const radius of [0,NaN,Infinity]){
 const group=buildCameraPath(cameras,radius);assert.ok(group.children.every(node=>node.scale.toArray().every(Number.isFinite)));
 disposeGeometryGroup(group);
}
const resources=new Set();path.traverse(node=>{if(node.geometry)resources.add(node.geometry);if(node.material)resources.add(node.material);});
const calls=new Map();for(const resource of resources)resource.addEventListener('dispose',()=>calls.set(resource,(calls.get(resource)||0)+1));
disposeGeometryGroup(path);assert.equal(calls.size,resources.size);assert.ok([...calls.values()].every(count=>count===1));
disposeGeometryGroup(gap);disposeGeometryGroup(repeated);disposeGeometryGroup(single);disposeGeometryGroup(empty);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-6000:]


def test_viewer_path_and_camera_markers_have_independent_controls():
    script = r"""
import assert from 'node:assert/strict';import {readFileSync} from 'node:fs';
import * as THREE from './src/twinforge/viewer/static/vendor/three.module.min.js';
globalThis.THREE=THREE;
const pathModule=readFileSync('src/twinforge/viewer/static/camera-path.js','utf8').replace("import * as THREE from 'three';",'');
const {buildCameraPath,disposeGeometryGroup}=await import('data:text/javascript;base64,'+Buffer.from(pathModule).toString('base64'));
const iconModule=readFileSync('src/twinforge/viewer/static/camera-markers.js','utf8').replace("import * as THREE from 'three';",'');
const {buildCameraMarkers}=await import('data:text/javascript;base64,'+Buffer.from(iconModule).toString('base64'));
const cameraIconTexture=new THREE.Texture();
const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,{checked:true});return nodes.get(id);};
const camera=(id,x)=>({frame_id:id,timestamp_seconds:id,camera_to_world:[[1,0,0,x],[0,1,0,0],[0,0,1,0],[0,0,0,1]]});
const metadata={cameras:[camera(2,1),camera(1,0)]};
const bounds=new THREE.Box3(new THREE.Vector3(-1,-1,-1),new THREE.Vector3(1,1,1));
const world=new THREE.Scene();const raycaster=new THREE.Raycaster();let cameraGroup,cameraPath,sourcePreview,cameraTargets=[];
const source=readFileSync('src/twinforge/viewer/static/app.js','utf8');let cameraPose,addCameras;
eval(source.slice(source.indexOf('function cameraPose('),source.indexOf('\nfunction selectFrame('))
 .replace(/^function (\w+)\(/gm,'$1 = function('));
addCameras();assert.equal(cameraPath.userData.segmentCount,1);assert.equal(cameraTargets.length,2);
assert.ok(byId('path-status').textContent.includes('start: frame 1 · end: frame 2'));
for(const id of ['show-path','show-cameras'])eval(source.split('\n').find(line=>line.includes(`byId('${id}').onchange =`)));
byId('show-cameras').onchange({target:{checked:false}});assert.equal(cameraGroup.visible,false);assert.equal(cameraPath.visible,true);
byId('show-path').onchange({target:{checked:false}});assert.equal(cameraPath.visible,false);
byId('show-cameras').onchange({target:{checked:true}});assert.equal(cameraGroup.visible,true);assert.equal(cameraPath.visible,false);
byId('show-path').checked=false;byId('show-cameras').checked=true;
world.remove(cameraGroup,cameraPath);disposeGeometryGroup(cameraGroup);disposeGeometryGroup(cameraPath);cameraTargets=[];
addCameras();assert.equal(cameraPath.visible,false);assert.equal(cameraGroup.visible,true);
assert.equal(cameraTargets.length,2);disposeGeometryGroup(world);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-6000:]
