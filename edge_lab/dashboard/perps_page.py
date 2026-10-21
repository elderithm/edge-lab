"""The dashboard's Perps view (one self-contained page, same styles as the Event Contracts view)."""

from __future__ import annotations

from .page import PAGE_HTML

_STYLE = PAGE_HTML[PAGE_HTML.index("<style>") : PAGE_HTML.index("</style>") + len("</style>")]

PERPS_PAGE_HTML = (
    r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>DreamDEX Perps Edge Lab</title>
"""
    + _STYLE
    + r"""
<style>
  .tbl { width:100%; overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:12px; }
  .tbl table td, .tbl table th { padding:7px 10px; border-bottom:1px solid var(--line); white-space:nowrap; }
  .tbl table td.num { text-align:right; }
  .b-WATCH{background:var(--gray);} .b-REVIEW{background:var(--blu);}
  .b-HIGH_EXECUTION_COST,.b-INSUFFICIENT_LIQUIDITY,.b-HIGH_LIQUIDATION_RISK{background:var(--amb);}
  .b-STALE_DATA,.b-INSUFFICIENT_DATA{background:var(--red);}
  .b-APPROVED{background:var(--grn);} .b-BLOCKED{background:var(--red);}
  .src.live { color:var(--grn); border-color:var(--grn); } .src.paper { color:var(--blu); border-color:var(--blu); }
  h2.sect { font-size:13px; text-transform:uppercase; letter-spacing:.04em; color:var(--mut); margin:22px 0 8px; }
  .form { display:flex; gap:8px; flex-wrap:wrap; align-items:center; margin:6px 0 10px; }
  input, select { font:inherit; padding:5px 8px; border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--ink); }
  a { color:var(--blu); }
  .missing { color:var(--red); font-size:12px; }
</style>
</head>
<body>
<header>
  <h1>DreamDEX Perps Edge Lab</h1>
  <span class="src" id="srcBadge">…</span>
  <a href="/" class="disc">Event Contracts view →</a>
  <div class="spacer"></div>
  <span id="meta"></span>
  <button id="refresh">Refresh</button>
</header>
<main>
  <h2 class="sect">Market overview</h2>
  <div id="empty">Loading perp markets…</div>
  <div class="tbl" id="tblWrap" style="display:none"><table id="tbl">
    <thead><tr><th>Market</th><th>Mark</th><th>Index</th><th>Basis</th><th>Funding /8h</th><th>Funding /yr</th>
      <th>Spread</th><th>Depth ±50bps (bid / ask)</th><th>Round-trip cost</th><th>Vol 24h</th><th>Assessment</th><th></th></tr></thead>
    <tbody></tbody></table></div>
  <p class="note">Observations and estimated costs — not executable edge and not a profit forecast. Ranked by the published
    category order, then by round-trip cost at a 100 USDso probe. Effective leverage is capped at 1x.
    Execution is CLI-only, on Hideki testnet, behind every risk check and an explicit --yes.</p>

  <h2 class="sect">Positions / history <span class="src paper">PAPER</span></h2>
  <div id="paper" class="disc">Loading…</div>
</main>
<dialog id="dlg"><div class="dlg-h"><strong id="dlgTitle"></strong><button id="dlgClose">Close</button></div>
  <div class="dlg-b" id="dlgBody"></div></dialog>
<script>
const $ = (s,r=document)=>r.querySelector(s);
const esc = (v)=> String(v).replace(/[&<>"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmt = (v)=> v===null||v===undefined||v==="" ? '<span class="missing">missing</span>' : esc(v);
const num = (v,d=2)=> v===null||v===undefined ? '<span class="missing">missing</span>' : Number(v).toLocaleString(undefined,{maximumFractionDigits:d});
const bps = (v)=> v===null||v===undefined ? '<span class="missing">n/a</span>' : Number(v).toFixed(2)+" bps";
const pct = (v,d=2)=> v===null||v===undefined ? '<span class="missing">n/a</span>' : (Number(v)*100).toFixed(d)+"%";
const row = (k,v)=> '<div class="k">'+esc(k)+'</div><div class="v">'+v+'</div>';
let SOURCE = "";

function badgeFor(src){
  const sb=$("#srcBadge");
  if(src==="SIMULATED_FIXTURE"){ sb.textContent="SIMULATED FIXTURE"; sb.className="src sim"; }
  else { sb.textContent="LIVE TESTNET · Hideki 50383"; sb.className="src live"; }
}

async function load(){
  $("#empty").style.display="block"; $("#empty").textContent="Loading perp markets…"; $("#tblWrap").style.display="none";
  let d; try { d = await (await fetch("/api/perps/scan")).json(); } catch(e){ $("#empty").textContent="Failed to reach the dashboard server."; return; }
  if(d.error){ $("#empty").textContent="Error: "+d.error; return; }
  SOURCE=d.source; badgeFor(d.source);
  $("#meta").textContent="updated "+new Date(d.generated_at*1000).toLocaleTimeString()+" · "+d.count+" markets"+(d.read_errors.length? " · "+d.read_errors.length+" read errors":"");
  const tb=$("#tbl tbody"); tb.innerHTML="";
  for(const a of d.assessments){
    const o=a.observed, l=o.liquidity, f=o.funding;
    const tr=document.createElement("tr");
    tr.innerHTML='<td><b>'+esc(a.market.symbol)+'</b></td><td class="num">'+num(o.basis.mark,4)+'</td><td class="num">'+num(o.basis.index,4)+
      '</td><td class="num">'+bps(o.basis.bps)+'</td><td class="num">'+pct(f.rate_per_window,4)+'</td><td class="num">'+pct(f.annualized)+
      '</td><td class="num">'+bps(l.spread_bps)+'</td><td class="num">'+num(l.bid_depth_quote,0)+' / '+num(l.ask_depth_quote,0)+
      '</td><td class="num">'+bps(a.execution_cost.round_trip_cost_bps)+'</td><td class="num">'+(o.volatility.status==="OK"?pct(o.volatility.sigma_24h):'<span class="missing">INSUFFICIENT_DATA</span>')+
      '</td><td><span class="badge b-'+esc(a.category)+'">'+esc(a.category)+'</span></td><td><button>Inspect</button></td>';
    tr.querySelector("button").onclick=()=>inspect(a.market.market_id, a.market.symbol);
    tb.appendChild(tr);
  }
  $("#empty").style.display=d.count?"none":"block"; if(!d.count) $("#empty").textContent="No perp markets returned.";
  $("#tblWrap").style.display=d.count?"block":"none";
}

function obj(o){ return '<div class="rows">'+Object.entries(o||{}).map(([k,v])=>row(k, v!==null&&typeof v==="object"? esc(JSON.stringify(v)) : fmt(v))).join("")+'</div>'; }
function checks(list){ return (list||[]).map(c=>'<div class="chk"><span class="'+(c.passed?"ok":"no")+'">'+(c.passed?"✓":"✗")+'</span> <b>'+esc(c.name)+'</b> <span class="disc">'+esc(c.detail)+'</span></div>').join(""); }

async function inspect(id, title){
  $("#dlgTitle").textContent=title; $("#dlgBody").innerHTML="Loading…"; $("#dlg").showModal();
  const d = await (await fetch("/api/perps/inspect?market="+encodeURIComponent(id))).json();
  if(d.error){ $("#dlgBody").textContent="Error: "+d.error; return; }
  const ob=d.order_book, o=d.observed, n=Math.max(ob.bids.length, ob.asks.length);
  let book=""; for(let i=0;i<n;i++){ const b=ob.bids[i]||["",""], a=ob.asks[i]||["",""];
    book+='<tr><td class="disc">'+esc(b[1])+'</td><td class="ok">'+esc(b[0])+'</td><td class="no">'+esc(a[0])+'</td><td class="disc">'+esc(a[1])+'</td></tr>'; }
  const m=d.market;
  $("#dlgBody").innerHTML =
    '<div class="sec"><h3>Assessment</h3><span class="badge b-'+esc(d.category)+'">'+esc(d.category)+'</span> <span class="disc">'+esc(d.source)+' · captured '+new Date(d.captured_at*1000).toLocaleTimeString()+'</span>'+
      '<ul>'+d.reasons.map(r=>'<li class="expl">'+esc(r)+'</li>').join("")+'</ul></div>'+
    '<div class="sec"><h3>Market (identity = chain + pool)</h3>'+obj({pool:m.market_id, chain_id:m.chain_id, base_decimals:m.base_decimals, tick_size:m.tick_size, lot_size:m.lot_size, min_quantity:m.min_quantity, protocol_max_leverage:m.protocol_max_leverage+"x (Edge Lab cap: 1x)"})+'</div>'+
    '<div class="sec"><h3>Order book (block '+fmt(ob.block_number)+')</h3><table><tr><th>Bid size</th><th>Bid</th><th>Ask</th><th>Ask size</th></tr>'+book+'</table></div>'+
    '<div class="sec"><h3>Funding</h3>'+obj(o.funding)+'</div>'+
    '<div class="sec"><h3>Basis (mark vs index)</h3>'+obj(o.basis)+'</div>'+
    '<div class="sec"><h3>Liquidity</h3>'+obj(o.liquidity)+'</div>'+
    '<div class="sec"><h3>Volatility</h3>'+obj(o.volatility)+'</div>'+
    '<div class="sec"><h3>Execution cost probe ('+esc(d.execution_cost.reference_notional)+' USDso)</h3>'+
      '<div class="rows">'+row("round trip", bps(d.execution_cost.round_trip_cost_bps))+'</div>'+
      '<details><summary class="disc">entry long / short</summary>'+obj(d.execution_cost.entry_long)+'<hr/>'+obj(d.execution_cost.entry_short)+'</details></div>'+
    '<div class="sec"><h3>Risk</h3>'+obj(d.risk.risk_params)+'<details><summary class="disc">liquidation probe (ESTIMATE, 1x)</summary>'+obj(d.risk.liquidation_probe)+'</details></div>'+
    '<div class="sec"><h3>Expected edge</h3><div class="expl">'+esc(d.expected_edge.status)+' — '+esc(d.expected_edge.note)+'</div></div>'+
    (d.warnings.length? '<div class="sec"><h3>Warnings</h3>'+d.warnings.map(w=>'<div class="missing">'+esc(w)+'</div>').join("")+'</div>':'')+
    '<div class="sec"><h3>Order preview (unsigned)</h3><div class="form">'+
      '<select id="pvSide"><option value="long">Long</option><option value="short">Short</option></select>'+
      '<input id="pvSize" size="10" value="'+esc(m.min_quantity)+'" title="base quantity" />'+
      '<input id="pvAcct" size="20" placeholder="account (optional, public)" />'+
      '<button id="pvGo">Preview</button></div><div id="pvOut" class="disc">Nothing is signed or submitted from the dashboard.</div></div>';
  $("#pvGo").onclick=()=>preview(m.market_id);
}

async function preview(id){
  $("#pvOut").innerHTML="Checking…";
  const qs="market="+encodeURIComponent(id)+"&side="+$("#pvSide").value+"&size="+encodeURIComponent($("#pvSize").value)+"&account="+encodeURIComponent($("#pvAcct").value);
  const d = await (await fetch("/api/perps/preview?"+qs)).json();
  if(d.error){ $("#pvOut").textContent="Error: "+d.error; return; }
  const p=d.paper, e=p.execution_estimate||{}, mg=p.margin_estimate||{}, it=p.intent||{};
  let html='<div class="rows">'+row("Estimated notional", num(e.notional,4))+row("Expected avg price", num(e.avg_price,6)+' <span class="disc">(book walk)</span>')+
    row("IOC limit price", fmt(it.limit_price))+row("Slippage vs mid", bps(e.slippage_bps))+row("Required initial margin", num(mg.initial_margin,4))+
    row("Est. liquidation", num(mg.est_liquidation_price,4)+' <span class="disc">ESTIMATE vs paper equity</span>')+'</div>'+
    '<p><span class="src paper">PAPER</span> <span class="badge b-'+(p.approved?"APPROVED":"BLOCKED")+'">'+(p.approved?"APPROVED":"BLOCKED")+'</span></p>'+checks(p.checks);
  if(d.testnet){ const t=d.testnet;
    html+='<p><span class="src live">TESTNET eligibility</span> <span class="badge b-'+(t.approved?"APPROVED":"BLOCKED")+'">'+(t.approved?"ELIGIBLE":"BLOCKED")+'</span> <span class="disc">account '+fmt(d.account)+'</span></p>'+checks(t.checks); }
  html+='<p class="disc">'+esc(d.execution_note)+'</p>';
  $("#pvOut").innerHTML=html;
}

async function loadPaper(){
  const d = await (await fetch("/api/perps/paper")).json();
  if(d.error){ $("#paper").textContent="Error: "+d.error; return; }
  const s=d.summary;
  let html='<div class="rows" style="max-width:520px">'+row("Label", esc(s.label))+row("Starting equity (simulated)", fmt(s.starting_equity))+row("Equity (simulated)", fmt(s.equity))+
    row("Realized P&L", fmt(s.realized_pnl))+row("Unrealized P&L", fmt(s.unrealized_pnl))+row("Funding paid (open, est.)", fmt(s.open_funding_paid))+'</div>';
  html+='<div class="tbl" style="margin-top:10px"><table><tr><th>#</th><th>Market</th><th>Side</th><th>Qty</th><th>Entry (simulated fill)</th><th>Mark</th><th>Unrealized</th><th>Realized</th><th>Status</th><th>Fill source</th></tr>'+
    (d.positions.length? d.positions.map(p=>'<tr><td>'+p.id+'</td><td>'+esc(p.symbol)+'</td><td>'+esc(p.side)+'</td><td>'+esc(p.quantity)+'</td><td>'+esc(p.entry_price)+'</td><td>'+fmt(p.mark)+'</td><td>'+fmt(p.unrealized_pnl)+'</td><td>'+fmt(p.realized_pnl)+'</td><td>'+esc(p.status)+'</td><td class="disc">'+esc(p.price_source)+'</td></tr>').join("") : '<tr><td colspan="10" class="disc">No paper positions yet — use `edge-lab perps paper-trade`.</td></tr>')+'</table></div>';
  html+='<h2 class="sect">Testnet orders <span class="src live">LIVE TESTNET</span></h2><div class="tbl"><table><tr><th>#</th><th>Market</th><th>Side</th><th>Qty</th><th>Tx hash</th><th>Receipt</th><th>Reconciled state</th><th>Position after</th></tr>'+
    (d.testnet_orders.length? d.testnet_orders.map(o=>'<tr><td>'+o.id+'</td><td>'+esc(o.symbol)+'</td><td>'+esc(o.side)+'</td><td>'+esc(o.quantity)+'</td><td class="disc">'+fmt(o.tx_hash)+'</td><td>'+fmt(o.receipt_status)+'</td><td>'+esc(o.reconciled_status)+'</td><td>'+fmt(o.position_after)+'</td></tr>').join("") : '<tr><td colspan="8" class="disc">No testnet orders recorded. A submission is only shown as filled when the receipt and decoded fills say so.</td></tr>')+'</table></div>';
  $("#paper").innerHTML=html;
}

$("#refresh").onclick=()=>{load(); loadPaper();}; $("#dlgClose").onclick=()=>$("#dlg").close();
load(); loadPaper();
</script>
</body>
</html>
"""
)
