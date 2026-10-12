"""Recovery controls exercised against application browser modules without WebGL."""

import subprocess


def test_upload_reload_lists_finish_discard_restart_and_more_controls():
    script = r"""
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const {mountUploadReview}=await import('data:text/javascript;base64,'+Buffer.from(readFileSync('src/twinforge/viewer/static/upload-review.js')).toString('base64'));
class Element { constructor(tag='div'){this.tagName=tag;this.children=[];this.hidden=false;this.value='';}
 append(...values){this.children.push(...values);} replaceChildren(...values){this.children=[...values];}
 focus(){this.focused=true;} pause(){} }
const nodes=new Map();globalThis.document={createElement:tag=>new Element(tag),getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);}};
globalThis.addEventListener=()=>{};
const readiness={processing_ready:false,reasons:[],backend:{installed:false},devices:{cpu:true},checkpoint:{state:'missing'},torch_repository:{state:'missing'},preparation:{state:'idle'}};
let discarded=false,finished=false;const calls=[];
const scene={scene_id:'scene_fixture',name:'Recovered',status:'ready_to_start',media:{inspection:{duration_seconds:1,width:2,height:2,display_width:2,display_height:2,codec:'test',decode_ready:true,preprocessing:{color:{policy:'sdr'}}},review_settings:{profile:'standard',device:'cpu'}}};
const request=async(url,method,value)=>{calls.push([url,method,value]);
 if(url==='/api/readiness')return readiness;
 if(url.endsWith('/discard')){discarded=true;return {};}
 if(url.endsWith('/complete')){finished=true;return {scene};}
 return {uploads:[...(!discarded?[{upload_id:'upload_created',client_name:'First.mp4',state:'created',received_bytes:0,expected_bytes:4}]:[]),...(!finished?[{upload_id:'upload_transferred',client_name:'Second.mp4',state:'transferred',received_bytes:4,expected_bytes:4}]:[])],next_cursor:'upload_page'};};
const errors=[];mountUploadReview({request,refresh:async()=>{},report:error=>errors.push(error.message)});
await new Promise(resolve=>setImmediate(resolve));
const descendants=root=>[root,...root.children.flatMap(descendants)];
const find=text=>descendants(document.getElementById('incomplete-transfers')).find(node=>node.textContent===text);
assert.ok(find('First.mp4 · created · 0.0 MiB of 0.0 MiB'));
assert.ok(find('Second.mp4 · transferred · 0.0 MiB of 0.0 MiB'));
await find('Finish inspection').onclick();assert.ok(finished);assert.equal(nodes.get('video-name').value,'Recovered');
await find('Discard and restart').onclick();assert.ok(discarded);assert.ok(nodes.get('video-file').focused);
assert.equal(nodes.get('video-review').hidden,true);
assert.ok(nodes.get('transfer-recovery-status').textContent.includes('Choose the original file'));
await nodes.get('more-transfers').onclick();assert.ok(calls.some(([url])=>url==='/api/uploads?after=upload_page'));
assert.deepEqual(errors,[]);
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_library_status_actions_filter_and_older_ready_navigation():
    script = r"""
import {readFileSync} from 'node:fs';import assert from 'node:assert/strict';
class Element {constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';}
 append(...items){this.children.push(...items);} replaceChildren(...items){this.children=[...items];} setAttribute(){} }
const nodes=new Map();const byId=id=>{if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);};
const document={createElement:tag=>new Element(tag)};const element=(tag,text)=>{const result=new Element(tag);result.textContent=text;return result;};
const dateFormat={format:()=> 'today'};const workspaceURL=record=>'/older/'+record.scene_id;
const Option=class {constructor(label,value){this.textContent=label;this.value=value;}};
let viewed=null;const activity={show:async id=>{viewed=id;}};const uploads={review(){}};function patch(){}function report(){}function openImport(){}
const base={created_at:'2026-01-01',updated_at:'2026-01-01',archived:false,source_kind:'managed_video',scale_label:'Estimated scale',versions:[]};
const records=[{...base,scene_id:'scene_first',name:'Kitchen',status:'running',latest_job:{job_id:'job_first'},default_run_id:null},
 {...base,scene_id:'scene_second',name:'Hallway',status:'failed',latest_job:{job_id:'job_second'},default_run_id:'run_older',ready_available:true}];
byId('status-scenes').value='all';byId('sort-scenes').value='name';
const code=readFileSync('src/twinforge/viewer/static/library.js','utf8');
const render=eval('('+code.slice(code.indexOf('function render()'),code.indexOf('\nasync function refresh()'))+')');
render();const descendants=root=>[root,...root.children.flatMap(descendants)];
const find=text=>descendants(byId('scene-list')).find(node=>node.textContent===text);
assert.ok(find('Running · Estimated scale'));assert.ok(find('Failed · Estimated scale'));
find('View progress').onclick();assert.equal(viewed,'job_first');
find('Review issue').onclick();assert.equal(viewed,'job_second');
assert.equal(find('Open saved scene').href,'/older/scene_second');
byId('status-scenes').value='failed';render();assert.equal(byId('scene-list').children.length,1);assert.ok(find('Hallway'));
const html=readFileSync('src/twinforge/viewer/static/library.html','utf8');for(const state of ['queued','running','validating_output','cancelling','failed','cancelled','interrupted'])assert.ok(html.includes(`value="${state}"`));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
