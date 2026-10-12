"""Library presentation, availability and recovery contracts."""

import subprocess
from pathlib import Path


def test_scene_open_error_does_not_misdiagnose_a_server_failure_as_webgl():
    script = r"""
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
const source=readFileSync('src/twinforge/viewer/static/app.js','utf8');
const nodes=new Map();
const element=()=>({children:[],classList:{add(){}},append(...items){this.children.push(...items);},
 replaceChildren(...items){this.children=[...items];},setAttribute(){},textContent:''});
const byId=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
const document={createElement:element};
const console={error(){}};
const showError=eval('('+source.slice(source.indexOf('function showError('),source.indexOf('\nfunction display('))+')');
showError(new Error('Invalid request or source unavailable'));
const texts=node=>[node.textContent,...node.children.flatMap(texts)].join(' ');
const text=texts(byId('loading'));
assert.ok(!text.includes('requires browser WebGL'),'Server failure incorrectly blamed WebGL');
assert.ok(text.includes('Back to scenes'),'No visible scene recovery');
assert.ok(text.includes('Try again'),'No retry action');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_library_has_a_clear_primary_action_and_separate_utility_pages():
    html = Path("src/twinforge/viewer/static/library.html").read_text()
    assert 'id="add-video" class="primary"' in html
    for page in ("page-scenes", "page-imports", "page-settings", "activity-panel"):
        assert f'id="{page}"' in html
    assert "Local library</span>" not in html
    assert 'id="scene-count"' in html


def test_saved_versions_do_not_precede_the_workspace_tools():
    html = Path("src/twinforge/viewer/static/index.html").read_text()
    assert html.index('class="steps"') < html.index('id="version-actions"')
    assert 'class="back-link"' in html


def test_real_library_modules_navigate_and_offer_only_available_scene_links():
    script = r"""
import {readFileSync} from 'node:fs';
import assert from 'node:assert/strict';
class Element {
 constructor(tag='div'){this.tagName=tag;this.children=[];this.value='';this.textContent='';this.hidden=false;
  const classes=new Set();this.classList={add:name=>classes.add(name),remove:name=>classes.delete(name)};this.attributes={};}
 append(...items){this.children.push(...items);} prepend(...items){this.children.unshift(...items);}
 replaceChildren(...items){this.children=[...items];}
 setAttribute(name,value){this.attributes[name]=value;} removeAttribute(name){delete this.attributes[name];}
 addEventListener(name,fn){this['on'+name]=fn;} focus(){document.activeElement=this;} select(){} pause(){}
 scrollIntoView(){} click(){this.onclick?.();} remove(){}
}
const root='src/twinforge/viewer/static/';
const nodes=new Map();const html=readFileSync(root+'library.html','utf8');
for(const match of html.matchAll(/<([a-z][a-z0-9]*)\b([^>]*\bid="([^"]+)"[^>]*)>/g)){
 const node=new Element(match[1]);node.hidden=/\shidden(?:\s|$)/.test(match[2]);nodes.set(match[3],node);
}
globalThis.document={title:'',body:{dataset:{application:'library'}},createElement:tag=>new Element(tag),
 getElementById(id){assert.ok(nodes.has(id),'Unknown DOM id: '+id);return nodes.get(id);}};
const get=id=>document.getElementById(id);
get('status-scenes').value='all';get('sort-scenes').value='recent';get('video-profile').value='standard';
globalThis.Option=class extends Element {constructor(text,value){super('option');this.textContent=text;this.value=value;}};
globalThis.location={hash:''};globalThis.window={location:{href:''}};
globalThis.history={replaceState(_state,_title,hash){location.hash=hash;}};
const listeners=new Map();globalThis.addEventListener=(name,fn)=>listeners.set(name,fn);
globalThis.setTimeout=()=>1;globalThis.clearTimeout=()=>{};
const record={scene_id:'scene_ready',name:'Office',status:'ready',ready_available:true,source_kind:'linked',
 default_run_id:'run_ready',default_session_id:'session_ready',default_version_id:'version_ready',versions:[{label:'Source scene',version_id:'version_ready'}],
 archived:false,created_at:'2026-10-01',updated_at:'2026-10-01',scale_label:'Estimated metric',thumbnail_url:'/photo'};
const missing={...record,scene_id:'scene_missing',name:'Missing source',status:'source_unavailable',ready_available:false,
 availability_message:'The source folder is not enabled.'};
let records=[record,missing];const calls=[];
globalThis.sceneFetch=async(url,options={})=>{calls.push([url,options]);
 let value;
 if(url==='/api/library/scenes')value={scenes:records,issues:[]};
 else if(url==='/api/jobs')value={jobs:[]};
 else if(url==='/api/uploads')value={uploads:[],next_cursor:null};
 else if(url==='/api/storage')value={linked_original_bytes:0,managed_video_bytes:0,retained_scene_workspace_bytes:0,disposable_cache_bytes:0,retained_export_bytes:0,incomplete_upload_bytes:0};
 else if(url==='/api/readiness')value={processing_ready:false,reasons:[],backend:{installed:false},devices:{cpu:true},checkpoint:{state:'missing'},torch_repository:{state:'missing'},preparation:{state:'idle'}};
 else if(url==='/api/library/imports')value={scenes:[],workspaces:[],truncated:false};
 else if(url==='/api/library/scenes/scene_ready' && options.method==='PATCH'){
  records=[{...record,...JSON.parse(options.body)},missing];value=records[0];
 }else throw Error('Unexpected request: '+url);
 return {ok:true,json:async()=>value};};
const moduleURL=file=>'data:text/javascript;base64,'+Buffer.from(readFileSync(root+file,'utf8')+'\n//# sourceURL='+file).toString('base64');
let code=readFileSync(root+'library.js','utf8')
 .replace("import { sceneFetch, workspaceURL } from '/scene-client.js';", "const sceneFetch=globalThis.sceneFetch;const workspaceURL=record=>'/open/'+record.scene_id;")
 .replace("from '/upload-review.js'",'from '+JSON.stringify(moduleURL('upload-review.js')))
 .replace("from '/activity.js'",'from '+JSON.stringify(moduleURL('activity.js')));
await import('data:text/javascript;base64,'+Buffer.from(code+'\n//# sourceURL=library-redesign-test.js').toString('base64'));
const settle=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};await settle();
const descendants=node=>[node,...node.children.flatMap(descendants)];
const all=()=>descendants(get('scene-list'));const text=label=>all().find(node=>node.textContent===label);
assert.equal(get('scene-count').textContent,2);assert.equal(get('ready-count').textContent,1);
const open=text('Open scene');assert.equal(open.href,'/open/scene_ready');
assert.equal(all().filter(node=>node.tagName==='a' && node.href==='/open/scene_missing').length,0);
assert.ok(text('The source folder is not enabled.'));assert.ok(text('Reconnect source'));
get('nav-settings').click();assert.equal(get('page-scenes').hidden,true);assert.equal(get('page-settings').hidden,false);
assert.equal(get('nav-settings').attributes['aria-current'],'page');
assert.equal(location.hash,'#settings');
get('add-video').click();assert.equal(get('page-scenes').hidden,false);assert.equal(get('video-panel').hidden,false);
assert.equal(document.activeElement,get('video-file'));
get('cancel-video').click();assert.equal(get('video-panel').hidden,true);
get('show-activity').click();assert.equal(get('activity-panel').hidden,false);assert.equal(get('page-scenes').hidden,true);
get('close-activity').click();assert.equal(get('page-scenes').hidden,false);assert.equal(get('activity-panel').hidden,true);
assert.equal(document.activeElement,get('scene-list'));
await text('Reconnect source').onclick();assert.equal(get('page-imports').hidden,false);assert.equal(get('import-panel').hidden,false);
assert.ok(get('import-note').textContent.includes('--import-root'));
get('nav-scenes').click();
const readyCard=get('scene-list').children.find(card=>descendants(card).some(node=>node.href==='/open/scene_ready'));
const rename=descendants(readyCard).find(node=>node.textContent==='Rename');rename.click();
const form=descendants(readyCard).find(node=>node.tagName==='form');assert.equal(form.hidden,false);
const name=descendants(form).find(node=>node.tagName==='input');name.value='Renamed office';
await form.onsubmit({preventDefault(){}});await settle();assert.ok(text('Renamed office'));
assert.ok(calls.some(([url,options])=>url==='/api/library/scenes/scene_ready' && options.method==='PATCH'));
get('search-scenes').value='no such name';get('search-scenes').oninput();assert.ok(text('No scenes found'));
text('Clear filters').click();assert.equal(get('scene-list').children.length,2);
const firstCard=get('scene-list').children[0];const image=descendants(firstCard).find(node=>node.tagName==='img');
image.onerror();assert.equal(descendants(firstCard).find(node=>node.textContent==='Preview unavailable').hidden,false);
records=records.map(item=>({...item,archived:true}));await get('refresh-scenes').onclick();await settle();
assert.ok(text('Your scenes are archived'));text('Show archived scenes').click();
assert.equal(get('status-scenes').value,'archived');assert.equal(get('scene-list').children.length,2);
listeners.get('pagehide')();
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-6000:]
