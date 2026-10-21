"""Exercise the same report helpers and Markdown parser used by the offline viewer."""

import json
import shutil
import subprocess
from importlib.resources import files

import pytest


def run_js(tmp_path, assertions):
    if not shutil.which("node"):
        pytest.skip("Node is required for JavaScript viewer tests")
    package = files("multi_agent_research")
    html = package.joinpath("viewer.html").read_text()
    helpers = html.split("// Report helpers", 1)[1].split("// End report helpers.", 1)[0]
    renderer = str(package.joinpath("vendor", "markdown-it", "markdown-it.min.js"))
    code = (
        "const assert=require('node:assert/strict');\n"
        f"global.window={{markdownit:require({json.dumps(renderer)})}};\n"
        "// Report helpers" + helpers + "\n" + assertions
    )
    path = tmp_path / "report-test.js"
    path.write_text(code)
    result = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_report_selects_accepted_lead_and_final_workers(tmp_path):
    run_js(tmp_path, """
const events=[
 {event_id:'draft',event_type:'tool.request',agent_id:'lead',
  payload:{name:'complete_task',args:{report:'unvalidated request'}}},
 {event_type:'tool.error',agent_id:'lead',parent_event_ids:['draft'],payload:{error:'rejected'}},
 {event_type:'worker.finished',payload:{assignment_id:'batch1-worker1',findings:'early'}},
];
assert.equal(collectReport({events}).report,null);
assert.equal(collectReport({events}).workers[0][1].findings,'early');
assert.equal(collectReport({events}).final,false);
events.push(
 {event_id:'accepted',event_type:'tool.request',agent_id:'lead',payload:{name:'complete_task'}},
 {event_type:'tool.result',agent_id:'lead',parent_event_ids:['accepted'],
  payload:{completed:{report:'# Accepted report'}}},
 {event_type:'tool.result',agent_id:'batch1-worker1',parent_event_ids:['accepted'],
  payload:{completed:{report:'worker text must not replace lead report'}}},
 {event_type:'run.finished',payload:{worker_results:{
   'batch1-worker10':{findings:'ten'},
   'batch1-worker2':{findings:'',status:'failed',stop_reason:'TimeoutError'},
   'batch1-worker1':{findings:'final'}
 }}}
);
const result=collectReport({events});
assert.equal(result.report,'# Accepted report');
assert.equal(result.final,true);
assert.deepEqual(result.workers.map(([id])=>id),['batch1-worker1','batch1-worker2','batch1-worker10']);
assert.equal(result.workers[0][1].findings,'final');
assert.equal(result.workers[1][1].status,'failed');
assert.deepEqual(collectReport({events:[]}),{report:null,citationReport:null,workers:[],final:false});
""")


def test_markdown_formatting_and_untrusted_content(tmp_path):
    run_js(tmp_path, r"""
const md=createReportMarkdown();
const text='# Title\n\n**Strong** and *emphasis* with <code>.\n\n- first\n- second\n\n'
 +'| Name | Value |\n| --- | --- |\n| A | B |\n\n'
 +'~~~python\nprint("test")\n~~~\n\n> Quoted\n\n[Source](https://example.org)\n';
const output=md.render(text);
for(const tag of ['<h1>','<strong>','<em>','<code','<ul>','<table>','<blockquote>'])
 assert.ok(output.includes(tag),tag);
assert.ok(output.includes('rel="noopener noreferrer"'));
const unsafe=md.render('<script>alert(1)</script>\n\n[bad](javascript:alert(1)) '
 +'[local](file:///etc/passwd) ![image](https://example.org/tracker.png)');
assert.ok(!unsafe.includes('<script>'));
assert.ok(!unsafe.includes('<img'));
assert.ok(!unsafe.includes('href="javascript:'));
assert.ok(!unsafe.includes('href="file:'));
assert.ok(unsafe.includes('&lt;script&gt;'));
""")


def test_tabs_switch_and_restore_graph_layout(tmp_path):
    run_js(tmp_path, """
const nodes=Object.fromEntries(['tab-graph','tab-report','graph-panel','report-panel'].map(id=>[id,{
 hidden:false,attributes:{},setAttribute(k,v){this.attributes[k]=v}
}]));
global.$=selector=>nodes[selector.slice(1)];
let draws=0;
global.drawArrows=()=>draws++;
global.requestAnimationFrame=callback=>callback();
selectTab('report');
assert.equal(nodes['graph-panel'].hidden,true);
assert.equal(nodes['report-panel'].hidden,false);
assert.equal(nodes['tab-report'].attributes['aria-selected'],'true');
assert.equal(nodes['tab-graph'].tabIndex,-1);
selectTab('graph');
assert.equal(nodes['graph-panel'].hidden,false);
assert.equal(nodes['report-panel'].hidden,true);
assert.equal(draws,1);
""")


def test_citation_report_requires_validation_and_matches_response(tmp_path):
    run_js(tmp_path, """
const response={event_id:'citation-response',agent_id:'citation',event_type:'model.response',
 payload:{content:'# Final report [[cite:s123:p1]]'}};
const events=[response];
assert.equal(collectReport({events}).citationReport,null);
events.push({event_type:'citation.validated',agent_id:'citation',parent_event_ids:['unrelated']});
assert.equal(collectReport({events}).citationReport,null);
events.push({event_type:'citation.validated',agent_id:'citation',parent_event_ids:['citation-response']});
assert.equal(collectReport({events}).citationReport,response.payload.content);
events.push({event_type:'citation.failed',agent_id:'citation',payload:{error:'Invalid source'}});
assert.equal(collectReport({events}).citationReport,null);
events.push(
 {event_id:'blocks',agent_id:'citation',event_type:'model.response',
  payload:{content:[{type:'thinking',thinking:'private'},{type:'text',text:'Final '},{type:'text',text:'text'}]}},
 {event_type:'citation.validated',agent_id:'citation',parent_event_ids:['citation-response','blocks']}
);
assert.equal(collectReport({events}).citationReport,'Final text');
""")


def test_result_report_renders_citation_first(tmp_path):
    run_js(tmp_path, """
function element(tag,cls='',text=''){
 return {tag,className:cls,textContent:text,children:[],append(...nodes){this.children.push(...nodes)},
 replaceChildren(...nodes){this.children=nodes}};
}
global.el=element;
const panel=element('section');
global.$=()=>panel;
const events=[
 {event_id:'lead-request',event_type:'tool.request',agent_id:'lead',payload:{name:'complete_task'}},
 {event_type:'tool.result',agent_id:'lead',parent_event_ids:['lead-request'],
  payload:{completed:{report:'Draft'}}},
 {event_id:'citation-response',event_type:'model.response',agent_id:'citation',payload:{content:'Final'}},
 {event_type:'citation.validated',agent_id:'citation',parent_event_ids:['citation-response']},
 {event_type:'run.finished',payload:{worker_results:{'batch1-worker1':{findings:'Findings'}}}}
];
renderReport({events});
let articles=panel.children.filter(n=>n.tag==='article');
assert.deepEqual(articles.map(n=>n.children[0].textContent),
 ['Citation agent final report','Lead researcher draft','batch1-worker1']);
assert.ok(articles[0].className.includes('report-citation'));
assert.ok(articles[0].children.find(n=>n.className==='markdown-body').innerHTML.includes('Final'));
renderReport({events:events.filter(e=>e.event_type!=='citation.validated')});
articles=panel.children.filter(n=>n.tag==='article');
assert.equal(articles[0].children[0].textContent,'Lead researcher draft');
""")
