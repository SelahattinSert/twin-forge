"""Activity polling and keyboard continuity against the actual UI module."""

import shutil
import subprocess

import pytest

HARNESS = r"""
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const { mountActivity } = await import('data:text/javascript;base64,' +
  Buffer.from(readFileSync('src/twinforge/viewer/static/activity.js')).toString('base64'));
class Element {
  constructor(tag='div') { this.tagName=tag; this.children=[]; this.hidden=false;
    this.textContent=''; this.open=false; this.disabled=false; this.parentNode=null; }
  append(...nodes) { for (const node of nodes) { node.remove(); node.parentNode=this; this.children.push(node); } }
  prepend(...nodes) { for (const node of nodes.toReversed()) { node.remove(); node.parentNode=this; this.children.unshift(node); } }
  replaceChildren(...nodes) { for(const child of [...this.children]) child.remove(); this.append(...nodes); }
  remove() { if(this.parentNode) { this.parentNode.children=this.parentNode.children.filter(child=>child!==this); this.parentNode=null; }
    if(document.activeElement===this)document.activeElement=null; }
  focus() { document.activeElement=this; }
  scrollIntoView() {}
}
const nodes=new Map();
globalThis.document={activeElement:null,createElement:tag=>new Element(tag),
  getElementById(id) { if(!nodes.has(id)) nodes.set(id,new Element()); return nodes.get(id); }};
const timers=new Map();let timerId=0;
globalThis.setTimeout=(callback,delay)=>{assert.ok(delay>=1000 && delay<=5000);timers.set(++timerId,callback);return timerId;};
globalThis.clearTimeout=id=>timers.delete(id);
let onPageHide;globalThis.addEventListener=(event,callback)=>{if(event==='pagehide')onPageHide=callback;};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
async function nextPoll(){assert.equal(timers.size,1,'Expected exactly one retry timer');
  const [id,callback]=timers.entries().next().value;timers.delete(id);callback();await tick();}
function descendants(root){return [root,...root.children.flatMap(descendants)];}
const find=(tag,text)=>descendants(nodes.get('activity-list')).find(node=>node.tagName===tag && (text==null || node.textContent===text));
const job={job_id:'job_fixture',settings:{label:'Standard'},state:'running',stage:'reconstructing',
  elapsed_seconds:1,events:[{sequence:1,timestamp:'now',message_code:'reconstructing',details:{}}],worker_alive:true};
const errors=[];let refreshes=0;
"""


@pytest.mark.parametrize(
    "case",
    [
        "transient",
        "refresh",
        "focus",
        "single_timer",
        "identity",
        "retry_queued",
        "cross_tab_queued",
    ],
)
def test_activity_polling_and_focus(case):
    if not shutil.which("node"):
        pytest.skip("Node required for UI behavior checks")
    scripts = {
        "retry_queued": r"""
const failed={...job,state:'failed',stage:'failed'};
const retried={...job,job_id:'job_retry',state:'queued',stage:'queued',worker_alive:false};
let jobs=[failed],libraryState='failed';
mountActivity({request:async(url,method)=>{if(method==='POST'){
  assert.equal(url,'/api/jobs/job_fixture/retry');jobs=[failed,retried];return retried;}
  return {jobs};},refresh:async()=>{refreshes++;libraryState=jobs.at(-1).state;},report:error=>errors.push(error.message)});
await tick();assert.equal(refreshes,0);
await find('button','Retry as new run').onclick();
assert.ok(find('button','Cancel'),'Retried queued job is absent from Activity');
assert.equal(refreshes,1,'Retry did not refresh library for its new queued job');
assert.equal(libraryState,'queued','Scene card and queued filter retain the failed state');
await nextPoll();assert.equal(refreshes,1,'Unchanged jobs repeatedly refresh library');
assert.deepEqual(errors,[]);onPageHide();
""",
        "cross_tab_queued": r"""
let jobs=[],libraryState='ready_to_start';
mountActivity({request:async()=>({jobs}),refresh:async()=>{refreshes++;libraryState=jobs.at(-1).state;},report:error=>errors.push(error.message)});
await tick();assert.equal(refreshes,0);
jobs=[{...job,job_id:'job_other_tab',state:'queued',stage:'queued',worker_alive:false}];
await nextPoll();assert.ok(find('button','Cancel'));
assert.equal(refreshes,1,'New queued job from another tab did not refresh library');
assert.equal(libraryState,'queued');
await nextPoll();assert.equal(refreshes,1,'Unchanged cross-tab job repeatedly refreshes library');
assert.deepEqual(errors,[]);onPageHide();
""",
        "identity": r"""
const named={...job,scene_name:'Kitchen',run_id:'run_first'};
const other={...job,job_id:'job_other',scene_name:'Hallway',run_id:'run_second',state:'failed',stage:'failed'};
const activity=mountActivity({request:async()=>({jobs:[named,other]}),refresh:async()=>{refreshes++;},report:error=>errors.push(error)});
await tick();assert.ok(find('h3','Kitchen · Standard · run un_first · job _fixture'));
assert.ok(find('h3','Hallway · Standard · run n_second · job ob_other'));
await activity.show('job_other');assert.equal(document.activeElement,find('h3','Hallway · Standard · run n_second · job ob_other'));
assert.equal(nodes.get('activity-panel').hidden,false);onPageHide();
""",
        "transient": r"""
let calls=0;
mountActivity({request:async()=>{calls++;if(calls===2)throw Error('Transient HTTP failure');
  return {jobs:[calls<3?job:{...job,state:'ready',stage:'ready',open_url:'/ready'}]};},
  refresh:async()=>{refreshes++;},report:error=>errors.push(error.message)});
await tick();assert.ok(find('button','Cancel'));await nextPoll();
assert.ok(find('button','Cancel'),'Failure erased last valid state');
assert.deepEqual(errors,['Transient HTTP failure']);await nextPoll();
assert.equal(find('a','Open scene').href,'/ready');assert.equal(refreshes,1);
assert.equal(timers.size,1);onPageHide();assert.equal(timers.size,0);
""",
        "refresh": r"""
mountActivity({request:async()=>({jobs:[{...job,state:'ready',stage:'ready',open_url:'/ready'}]}),
  refresh:async()=>{refreshes++;if(refreshes===1)throw Error('Transient library refresh');},
  report:error=>errors.push(error.message)});
await tick();assert.ok(find('a','Open scene'));assert.equal(refreshes,1);
await nextPoll();assert.equal(refreshes,2,'Ready library refresh was not retried');
assert.deepEqual(errors,['Transient library refresh']);assert.equal(timers.size,1);onPageHide();
""",
        "focus": r"""
let state='running';
mountActivity({request:async()=>({jobs:[{...job,state,stage:state}]}),refresh:async()=>{},report:error=>errors.push(error)});
await tick();const details=find('details');details.open=true;const cancel=find('button','Cancel');cancel.focus();
await nextPoll();assert.ok(find('details').open,'Polling closed Details');
assert.equal(document.activeElement,find('button','Cancel'),'Polling lost Cancel focus');
state='failed';await nextPoll();const retry=find('button','Retry as new run');retry.focus();
await nextPoll();assert.equal(document.activeElement,find('button','Retry as new run'));
const summary=find('summary','Details');summary.focus();await nextPoll();
assert.equal(document.activeElement,find('summary','Details'));assert.ok(find('details').open);onPageHide();
""",
        "single_timer": r"""
let release,calls=0;
const response=new Promise(resolve=>release=resolve);
const activity=mountActivity({request:async(url,method)=>{if(method==='POST')return job;
  calls++;return response;},refresh:async()=>{},report:error=>errors.push(error)});
await tick();assert.equal(calls,1);assert.equal(timers.size,0);
nodes.get('show-activity').onclick();nodes.get('show-activity').onclick();
const start=activity.start({scene_id:'scene_fixture'},'key');await tick();
assert.equal(calls,1,'Submission started a duplicate poll while one was pending');
release({jobs:[job]});await start;await tick();assert.equal(timers.size,1);
onPageHide();assert.equal(timers.size,0);
""",
    }
    result = subprocess.run(
        ["node", "--input-type=module", "-e", HARNESS + scripts[case]],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
