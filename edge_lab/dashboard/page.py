"""The dashboard's single self-contained HTML page (served by the local server)."""

from __future__ import annotations

PAGE_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>DreamDEX Edge Lab</title>
<style>
  :root { color-scheme: light dark; --bg:#f6f7f9; --card:#fff; --ink:#111827; --mut:#6b7280;
          --line:#e5e7eb; --grn:#059669; --blu:#2563eb; --amb:#b45309; --red:#dc2626; --gray:#6b7280; }
  @media (prefers-color-scheme: dark){ :root{ --bg:#0d1117; --card:#161b22; --ink:#e6edf3; --mut:#9198a1; --line:#30363d; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; }
  header { padding:14px 20px; border-bottom:1px solid var(--line); display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
  header h1 { font-size:16px; margin:0; font-weight:700; }
  .src { font-size:11px; padding:2px 8px; border-radius:999px; border:1px solid var(--line); color:var(--mut); }
  .src.sim { color:var(--amb); border-color:var(--amb); }
  button { font:inherit; cursor:pointer; border:1px solid var(--line); background:var(--card); color:var(--ink);
           border-radius:8px; padding:6px 12px; }
  button:hover { border-color:var(--mut); }
  .spacer { flex:1; }
  #meta { color:var(--mut); font-size:12px; }
  main { padding:20px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; }
  .card h2 { font-size:15px; margin:0 0 2px; }
  .card .sub { color:var(--mut); font-size:12px; margin-bottom:10px; }
  .rows { display:grid; grid-template-columns:auto 1fr; gap:3px 10px; font-size:13px; }
  .rows .k { color:var(--mut); } .rows .v { text-align:right; font-variant-numeric:tabular-nums; }
  .badge { display:inline-block; font-size:11px; font-weight:700; padding:3px 9px; border-radius:999px; color:#fff; }
  .b-BUY_UP{background:var(--grn);} .b-BUY_DOWN{background:var(--blu);}
  .b-NO_EDGE,.b-MARKET_NOT_TRADING{background:var(--gray);}
  .b-LOW_CONFIDENCE,.b-TOO_CLOSE_TO_EXPIRY,.b-INSUFFICIENT_LIQUIDITY{background:var(--amb);}
  .b-DATA_STALE{background:var(--red);}
  .cardfoot { margin-top:12px; display:flex; align-items:center; justify-content:space-between; }
  .note { color:var(--mut); font-size:12px; margin-top:16px; }
  #empty { color:var(--mut); padding:30px 0; }
  dialog { border:1px solid var(--line); border-radius:14px; background:var(--card); color:var(--ink);
           width:min(640px,92vw); padding:0; }
  dialog::backdrop { background:rgba(0,0,0,.4); }
  .dlg-h { padding:14px 18px; border-bottom:1px solid var(--line); display:flex; justify-content:space-between; align-items:center; }
  .dlg-b { padding:16px 18px; max-height:70vh; overflow:auto; }
  .sec { margin:0 0 14px; } .sec h3 { font-size:12px; text-transform:uppercase; letter-spacing:.04em; color:var(--mut); margin:0 0 6px; }
  table { width:100%; border-collapse:collapse; font-size:13px; font-variant-numeric:tabular-nums; }
  td,th { text-align:left; padding:2px 8px 2px 0; } th { color:var(--mut); font-weight:600; }
  .chk { display:flex; gap:8px; align-items:baseline; font-size:12px; }
  .ok{color:var(--grn);} .no{color:var(--red);}
  .expl { font-size:13px; color:var(--ink); }
  .disc { color:var(--mut); font-size:11px; }
</style>
</head>
<body>
<header>
  <h1>DreamDEX Edge Lab</h1>
  <span class="src" id="srcBadge">…</span>
  <div class="spacer"></div>
  <span id="meta"></span>
  <button id="refresh">Refresh</button>
</header>
<main>
  <div id="empty">Loading live DreamDEX Event Contracts… (a live scan can take ~30–45s)</div>
  <div class="grid" id="grid"></div>
  <p class="note">Model estimates (realized-volatility Gaussian, no LLM) — not profit guarantees.
     Ranked by edge × confidence × liquidity. Execution is CLI-only, behind explicit confirmation.</p>
</main>
<dialog id="dlg"><div class="dlg-h"><strong id="dlgTitle"></strong><button id="dlgClose">Close</button></div>
  <div class="dlg-b" id="dlgBody"></div></dialog>
<script>
const $ = (s,r=document)=>r.querySelector(s);
const fmt = (v)=> v===null||v===undefined ? "–" : v;
const pct = (v)=> v===null||v===undefined ? "–" : (parseFloat(v)*100).toFixed(1)+"%";
const bps = (v)=> v===null||v===undefined ? "–" : parseFloat(v).toFixed(0)+" bps";
let NOW = Math.floor(Date.now()/1000);
function tte(expiry){ if(!expiry) return "–"; const s=expiry-NOW; if(s<0) return "expired";
  const m=Math.floor(s/60), r=s%60; return m>0? m+"m "+String(r).padStart(2,"0")+"s" : s+"s"; }

async function load(){
  $("#empty").style.display="block"; $("#empty").textContent="Loading… (a live scan can take ~30–45s)";
  $("#grid").innerHTML="";
  let data;
  try { data = await (await fetch("/api/scan")).json(); }
  catch(e){ $("#empty").textContent="Failed to reach the dashboard server."; return; }
  if(data.error){ $("#empty").textContent="Error: "+data.error; return; }
  NOW = data.generated_at || NOW;
  const sim = data.source==="SIMULATED";
  const sb=$("#srcBadge"); sb.textContent = sim?"SIMULATED FIXTURE":"LIVE · Shannon testnet"; sb.className="src"+(sim?" sim":"");
  $("#meta").textContent = "updated "+new Date(NOW*1000).toLocaleTimeString()+" · "+data.signals.length+" markets";
  if(!data.signals.length){ $("#empty").textContent="No live markets right now."; return; }
  $("#empty").style.display="none";
  for(const s of data.signals) $("#grid").appendChild(card(s));
}

function card(s){
  const m=s.market, p=s.probability, up=s.edge.up, r=s.risk;
  const el=document.createElement("div"); el.className="card";
  el.innerHTML =
    '<h2>'+m.asset+' · '+fmt(m.window)+'</h2>'+
    '<div class="sub">'+m.status+' · '+m.market_id.slice(0,10)+'…</div>'+
    '<div class="rows">'+
      row("Time remaining", tte(m.expiry))+
      row("Opening ref", fmt(m.opening_reference))+
      row("Current ref", fmt(p.inputs.current_price))+
      row("DreamDEX Up ask", fmt(up.top_ask))+
      row("Model P(Up)", pct(p.p_up))+
      row("Executable edge", bps(r.edge_bps))+
      row("Confidence", pct(p.confidence))+
    '</div>'+
    '<div class="cardfoot"><span class="badge b-'+s.state+'">'+s.state+'</span>'+
      '<button data-id="'+m.market_id+'">Inspect</button></div>';
  el.querySelector("button").onclick=()=>inspect(m.market_id, m.asset+" · "+fmt(m.window));
  return el;
}
function row(k,v){ return '<div class="k">'+k+'</div><div class="v">'+v+'</div>'; }

async function inspect(id, title){
  $("#dlgTitle").textContent=title; $("#dlgBody").innerHTML="Loading…"; $("#dlg").showModal();
  const d = await (await fetch("/api/inspect?market_id="+encodeURIComponent(id))).json();
  if(d.error){ $("#dlgBody").textContent="Error: "+d.error; return; }
  const p=d.probability, e=d.edge, ob=d.order_book||{up_asks:[],down_asks:[]};
  const inputs = Object.entries(p.inputs).map(([k,v])=>row(k,fmt(v))).join("");
  const bookRows=(a)=> a.length? a.map(l=>'<tr><td>'+l[0]+'</td><td>'+l[1]+'</td></tr>').join("") : '<tr><td class="disc">empty</td><td></td></tr>';
  const side=(x)=> 'top '+fmt(x.top_ask)+' · exec '+fmt(x.executable_ask)+' · edge '+bps(x.executable_edge_bps);
  const checks = d.risk.checks.map(c=>'<div class="chk"><span class="'+(c.passed?"ok":"no")+'">'+(c.passed?"✓":"✗")+'</span> <b>'+c.name+'</b> <span class="disc">'+c.detail+'</span></div>').join("");
  $("#dlgBody").innerHTML =
    '<div class="sec"><h3>Signal</h3><span class="badge b-'+d.state+'">'+d.state+'</span> '+
      '<span class="disc">rank '+d.rank_score+'</span></div>'+
    '<div class="sec"><h3>Model — '+p.model_version+'</h3><div class="rows">'+inputs+
      row("P(Up)",pct(p.p_up))+row("P(Down)",pct(p.p_down))+row("Confidence",pct(p.confidence))+'</div></div>'+
    '<div class="sec"><h3>Executable edge</h3><div class="rows">'+row("UP",side(e.up))+row("DOWN",side(e.down))+
      row("Buffers",bps(e.buffer_bps))+'</div></div>'+
    '<div class="sec"><h3>Order book</h3><table><tr><th>Up asks</th><th></th><th>Down asks</th><th></th></tr>'+
      zipBooks(ob.up_asks, ob.down_asks)+'</table></div>'+
    '<div class="sec"><h3>Risk checks</h3>'+checks+'</div>'+
    '<div class="sec"><h3>Why</h3><div class="expl">'+d.explanation+'</div></div>';
}
function zipBooks(a,b){ const n=Math.max(a.length,b.length,1); let out="";
  for(let i=0;i<n;i++){ const x=a[i]||["",""], y=b[i]||["",""];
    out+='<tr><td>'+(x[0]||"")+'</td><td class="disc">'+(x[1]||"")+'</td><td>'+(y[0]||"")+'</td><td class="disc">'+(y[1]||"")+'</td></tr>'; }
  return out || '<tr><td class="disc">empty</td></tr>'; }

$("#refresh").onclick=load; $("#dlgClose").onclick=()=>$("#dlg").close();
load();
</script>
</body>
</html>
"""
