"""Version actions keep global export routes and navigate to saved sessions."""

import subprocess


def test_global_routes_and_saved_version_actions():
    script = r"""
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const load=async name=>import('data:text/javascript;base64,'+Buffer.from(readFileSync(`src/twinforge/viewer/static/${name}.js`)).toString('base64'));
const client=await load('scene-client');
const context={apiPrefix:'/api/scenes/example/runs/run/sessions/session'};
for(const path of ['/api/exports','/api/packages/open','/api/storage']) assert.equal(client.apiURL(path,context),path);
const {mountVersionActions}=await load('version-actions');
class E {constructor(tag){this.tag=tag;this.children=[];this.value='';this.textContent='';}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=nodes;}setAttribute(){}}
globalThis.document={createElement:tag=>new E(tag)};
const host=new E('section'), requests=[], navigated=[];
const version={version_id:'v2',session_id:'s2',run_id:'r1',label:'Scale two',frozen:true};
const record={scene_id:'scene1',default_version_id:'v1',versions:[{version_id:'v1',session_id:'s1',run_id:'r1',label:'Source'},version]};
const request=async(url,method,value)=>{requests.push({url,method,value});if(url==='/api/exports')return {status:'unavailable',message:'No GLB'};if(url.endsWith('/calibration'))return method==='POST'?{version:{run_id:'r1',session_id:'s3'}}:{control_id:'width',reconstructed_median:2,observations:[{frame_id:3},{frame_id:17}]};return record;};
await mountVersionActions(host,{version,default_version_id:'v1'},{sceneId:'scene1',request,go:url=>navigated.push(url)});
const flat=node=>[node,...node.children.flatMap(flat)];
const button=text=>flat(host).find(n=>n.tag==='button'&&n.textContent===text);
await button('Make default').onclick();assert.equal(requests.at(-1).value.default_version_id,'v2');
await button('Download GLB').onclick();assert.equal(requests.at(-1).url,'/api/exports');assert.equal(requests.at(-1).value.version_id,'v2');
const select=flat(host).find(n=>n.tag==='select');select.value='v1';select.onchange();assert.equal(navigated.at(-1),'/scenes/scene1/runs/r1/sessions/s1');
const form=flat(host).find(n=>n.tag==='form');assert.ok(form,'Frozen versions need an explicit repeat-calibration action');
const length=flat(form).find(n=>n.type==='number');assert.equal(length.value,'');length.value='1.64';
await form.onsubmit({preventDefault(){}});assert.equal(requests.at(-1).value.physical_value,1.64);assert.equal(navigated.at(-1),'/scenes/scene1/runs/r1/sessions/s3');
"""
    subprocess.run(["node", "--input-type=module", "-e", script], check=True, capture_output=True)
