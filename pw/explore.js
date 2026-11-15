/* Shared interface helpers, then Sky Explorer on the real SPHEREx DR1 all-sky mosaic. */
(function(){
'use strict';
var PW=window.PW,h=PW.h,s=PW.s,$=PW.$,$$=PW.$$,D=PW.DET,VS=PW.VISITS;
function esc(t){return String(t==null?'':t).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
PW.esc=esc;
var D2R=Math.PI/180;

/* ---------- shared helpers ---------- */
PW.hammer=function(ra,dec){var l=(ra-180)*D2R,p=dec*D2R,z=Math.sqrt(1+Math.cos(p)*Math.cos(l/2));
  return [.5-(2*Math.SQRT2*Math.cos(p)*Math.sin(l/2)/z)/(4*Math.SQRT2),.5-(Math.SQRT2*Math.sin(p)/z)/(2*Math.SQRT2)]};
PW.modal=function(title,body,foot,wide){var m=h('div',{class:'modal'+(wide?' wide':''),role:'dialog','aria-modal':'true','aria-label':title},[
    h('header',{},[h('h2',{class:'h20',text:title}),h('button',{class:'ibtn','aria-label':'Close',onclick:close},[PW.icon('cross')])]),body,foot&&h('footer',{},foot)]),
   sc=h('div',{class:'scrim',onclick:function(e){if(e.target===sc)close()}},[m]),prev=document.activeElement;
  function key(e){if(e.key==='Escape')close()}
  function close(){sc.remove();document.removeEventListener('keydown',key);if(prev&&prev.focus&&prev.isConnected)prev.focus()}
  document.addEventListener('keydown',key);document.body.appendChild(sc);var f=m.querySelector('input,textarea,select,.btn.pri')||m.querySelector('button');if(f)f.focus();close.el=m;return close};
document.addEventListener('click',function(e){var o=$('.pop.origin');if(o)o.remove();var n=e.target.closest&&e.target.closest('.num');if(!n||!n.dataset.o)return;
  var r=n.getBoundingClientRect(),p=h('div',{class:'pop origin',role:'tooltip'},[h('b',{text:n.dataset.ot||'Origin'}),n.dataset.o]);document.body.appendChild(p);
  p.style.top=(r.bottom+scrollY+8)+'px';p.style.left=Math.max(8,Math.min(r.left,innerWidth-p.offsetWidth-8))+'px'});
function num(v,unit,unc,origin,detail){return '<button type="button" class="num" data-ot="'+esc(origin)+'" data-o="'+esc(detail)+'">'+esc(v)+(unc?' ± '+esc(unc):'')+esc(unit||'')+' <i>· '+esc(origin)+'</i></button>'}
PW.num=num;
PW.dl=function(name,type,text){var a=h('a',{href:URL.createObjectURL(new Blob([text],{type:type})),download:name});document.body.appendChild(a);a.click();a.remove()};
function chartFrame(W,H,L,R,T,B,label){var g=s('svg',{class:'chart',viewBox:'0 0 '+W+' '+H,role:'img','aria-label':label}),X=function(w){return L+(w-.75)/4.25*(R-L)};
  [.75,1.11,1.64,2.42,3.82,4.42,5].forEach(function(w,k){g.appendChild(s('path',{d:'M'+X(w)+' '+T+'V'+B,stroke:'#262A31'}));if(k<6){var t=s('text',{x:(X(w)+X(D[k].hi))/2,y:12,'text-anchor':'middle'},D[k].id);t.style.fill=D[k].c;g.appendChild(t)}});
  g.appendChild(s('path',{d:'M'+L+' '+B+'H'+R,stroke:'#3A404A'}));[1,2,3,4,5].forEach(function(w){g.appendChild(s('text',{x:w===5?R:X(w),y:H-8,'text-anchor':w===5?'end':'middle'},w+(w===5?' µm':'')))});return [g,X]}
/* quick-look brightness across the 102 layers of the real mosaic (display values 0 to 255) */
PW.bandChart=function(vals,big){var W=big?720:368,H=big?240:168,L=36,R=W-8,T=20,B=H-28,f=chartFrame(W,H,L,R,T,B,'Brightness in 102 SPHEREx bands at this position, from the DR1 mosaic'),g=f[0],X=f[1],
    mx=Math.max(8,Math.max.apply(null,vals.map(function(v){return v||0}))*1.1),Y=function(v){return B-v/mx*(B-T)},d='';
  g.appendChild(s('text',{x:L-6,y:T+4,'text-anchor':'end'},Math.round(mx)));g.appendChild(s('text',{x:L-6,y:B,'text-anchor':'end'},'0'));
  vals.forEach(function(v,i){if(v==null)return;var x=X(PW.WAVE[i]);d+=(d?'L':'M')+x+' '+Y(v);var c=s('circle',{cx:x,cy:Y(v),r:big?2.4:1.9,fill:'hsl('+(270-i*270/101).toFixed(0)+' 85% 66%)'});g.appendChild(c)});
  if(d)g.insertBefore(s('path',{d:d,fill:'none',stroke:'#3A404A'}),g.firstChild.nextSibling);return g};
PW.bandStrip=function(vals){var mx=Math.max(1,Math.max.apply(null,vals.map(function(v){return v||0}))),d=h('div',{class:'strip',role:'img','aria-label':'102-band strip, violet for short wavelengths to red for long, brighter where the mosaic is brighter'});
  vals.forEach(function(v,i){d.appendChild(h('i',{style:'background:'+(v==null?'#111317':'hsl('+(270-i*270/101).toFixed(0)+' 85% '+(5+Math.pow((v||0)/mx,.6)*58).toFixed(0)+'%)')}))});return d};
/* kept for pages that show a source's model spectrum shape */
PW.specChart=function(src,big){var P=PW.spectrum(src),W=big?720:368,H=big?260:176,L=36,R=W-8,T=20,B=H-28,f=chartFrame(W,H,L,R,T,B,'Spectrum of '+src.name),g=f[0],X=f[1],
    mx=Math.max.apply(null,P.map(function(p){return p.f?p.f+p.e:p.ul}))*1.08,Y=function(v){return B-v/mx*(B-T)};
  P.forEach(function(p){var x=X(p.w);if(p.ul){g.appendChild(s('path',{d:'M'+(x-2.5)+' '+(Y(p.ul)-4)+'h5l-2.5 4z',fill:'#5A616C'}));return}
    g.appendChild(s('path',{d:'M'+x+' '+Y(p.f+p.e)+'V'+Y(Math.max(0,p.f-p.e)),stroke:'#9AA1AC'}));g.appendChild(s('circle',{cx:x,cy:Y(p.f),r:big?2.4:1.8,fill:'#E8EAED'}))});return g};
PW.strip=function(src){var P=PW.spectrum(src);return PW.bandStrip(P.map(function(p){return p.f||0}))};
/* a field for any position, so the visit player works anywhere */
PW.spotField=function(ra,dec){return {id:'spot',name:'Position',ra:ra,dec:dec,seed:Math.abs(Math.round(ra*1000+dec*7919))%100000+3,frames:0,src:[],bg:(function(){var r=PW.rng(Math.abs(Math.round(ra*997+dec*131))+1),a=[],i;for(i=0;i<30;i++)a.push({x:(r()-.5)*56,y:(r()-.5)*56,f:.8+Math.pow(r(),3)*9});return a})()}};
PW.player=function(cv,fieldId,srcId){var F=typeof fieldId==='object'?fieldId:PW.FIELDS[fieldId],S=(srcId&&PW.src(F.id,srcId))||F.src[0]||{x:0,y:0,sed:[1,1,1,1,1,1]},v=0,d=S.sed[5]>=S.sed[2]?5:2,t;
  function draw(){PW.paint(cv,[PW.frame(F,d,v,{n:20,cx:S.x+(S.vx||0)*1.5,cy:S.y+(S.vy||0)*1.5})]);cv.dataset.v=v}
  draw();if(!PW.still)t=setInterval(function(){if(!cv.isConnected){clearInterval(t);return}if(cv.dataset.hold)return;v=(v+1)%4;draw()},800);
  return function(to){v=to;cv.dataset.hold=1;draw()}};
PW.sigPos=function(F,S,v){v=v||0;return [F.ra-((S.x+(S.vx||0)*v)*PW.PIX/3600)/Math.cos(F.dec*D2R),F.dec-(S.y+(S.vy||0)*v)*PW.PIX/3600]};
/* every source gets the same four molecule rows, plus any extra readings it has; a missing value always says why */
var STD=[['Water ice','3.05 µm',/water ice|ice at 3\.05/i],['Methane','3.3 µm',/methane/i],['Carbon dioxide','4.27 µm',/carbon dioxide|co₂/i],['Carbon monoxide','4.67 µm',/monoxide/i]];
PW.molRows=function(S){var mol=(S&&S.mol)||[],used=[],why=mol.length===1&&!mol[0][1]&&!STD.some(function(t){return t[2].test(mol[0][0])})?mol[0][2]:null,rows;
  rows=STD.map(function(t){var m=mol.filter(function(x,i){if(used.indexOf(i)<0&&t[2].test(x[0])){used.push(i);return true}return false})[0];
    return [t[0]+' at '+t[1],m?m[1]:null,m?m[2]:(why||(S&&S.status==='Uncatalogued'||S&&S.sigkind?'not in the pipeline sample export':'no reading for this source yet')),t[1]]});
  mol.forEach(function(x,i){if(used.indexOf(i)<0&&!(why&&i===0))rows.push([x[0],x[1],x[2],(/(\d\.\d+) µm/.exec(x[0])||[])[1]+' µm'])});
  return rows.sort(function(a,b){return (b[1]!=null)-(a[1]!=null)})};
PW.findPos=function(f){if(f.ra!=null)return [f.ra,f.dec];var F=PW.FIELDS[f.field],S=F&&PW.src(f.field,f.src);return F?(S?PW.sigPos(F,S,3):[F.ra,F.dec]):null};
PW.parseCoord=function(q){q=q.trim().replace(/−/g,'-');var m=/^(-?\d+(?:\.\d+)?)[\s,]+([+-]?\d+(?:\.\d+)?)$/.exec(q),a,b;
  if(m){a=+m[1];b=+m[2];return a>=0&&a<360&&Math.abs(b)<=90?[a,b]:null}
  m=/^(\d{1,2})[h:\s]+(\d{1,2})[m:\s]+(\d{1,2}(?:\.\d+)?)s?[\s,]+([+-]?)(\d{1,2})[d°:\s]+(\d{1,2})['′m:\s]+(\d{1,2}(?:\.\d+)?)["″s]?$/i.exec(q);
  if(m){a=(+m[1]+m[2]/60+m[3]/3600)*15;b=(+m[5]+m[6]/60+m[7]/3600)*(m[4]==='-'?-1:1);return a>=0&&a<360&&Math.abs(b)<=90?[a,b]:null}return null};
function sep(a,b){var x=Math.sin((b[1]-a[1])*D2R/2),y=Math.sin((b[0]-a[0])*D2R/2);return 2*Math.asin(Math.sqrt(x*x+Math.cos(a[1]*D2R)*Math.cos(b[1]*D2R)*y*y))/D2R}
PW.sep=sep;

/* ---------- share a find: one form used by Sky Explorer, Discussions and the data panel ---------- */
var TYPES=['Brown dwarf','Moving object','Variable star','Young star with a disc','Evolved giant','Comet','Galaxy','Artifact to check','Not sure'];
PW.shareFind=function(o){o=o||{};var st=PW.store.get(),body=h('div',{}),close;
  var posTxt=o.ra!=null?PW.deci(o.ra,o.dec)+' J2000':'No position chosen yet';
  if(!st.user){body.appendChild(h('p',{class:'t16',text:'Sign in to share a find. Exploring and reading stay open without an account.'}));
    body.appendChild(h('p',{class:'muted',text:'Position you were looking at: '+posTxt}));
    close=PW.modal('Share your find',body,[h('a',{class:'btn',href:'#/join',onclick:function(){close()}},['Create account']),h('a',{class:'btn pri',href:'#/signin',onclick:function(){close()}},['Sign in'])]);return}
  var ra=h('input',{class:'input',inputmode:'decimal',value:o.ra!=null?o.ra.toFixed(5):'',placeholder:'291.36412','aria-describedby':'shPos'}),
    de=h('input',{class:'input',inputmode:'decimal',value:o.dec!=null?o.dec.toFixed(5):'',placeholder:'+10.47633','aria-describedby':'shPos'}),
    type=h('select',{class:'select'},TYPES.map(function(t){return h('option',{text:t})})),notes=h('textarea',{class:'area',placeholder:'What did you see, and in which detectors and visits'}),
    perr=h('small',{id:'shPos',class:'err'}),nerr=h('small',{class:'err'}),att=h('ul',{class:'t12 muted',style:'display:grid;gap:4px'});
  if(o.type)type.value=o.type;
  function attach(){att.textContent='';var a=+ra.value,b=+de.value;[o.src?'Frame video with '+o.src.name+' marked':'Frame video of this position',
    'Coordinates: '+(ra.value&&de.value&&!isNaN(a)&&!isNaN(b)?PW.deci(a,b)+' J2000':'enter a position'),'Brightness in 102 bands from the SPHEREx mosaic',
    o.src&&o.src.mol&&o.src.mol[0]&&o.src.mol[0][1]?'Molecules: '+o.src.mol[0][0]+' '+o.src.mol[0][1]:null,o.src?'Model: '+PW.estText(o.src):'Model estimate: runs after you share'].forEach(function(t){if(t)att.appendChild(h('li',{text:t}))})}
  ra.addEventListener('input',attach);de.addEventListener('input',attach);attach();
  body.appendChild(h('div',{class:'field'},[h('span',{text:'Position, J2000'}),h('div',{style:'display:grid;grid-template-columns:1fr 1fr;gap:8px'},[h('label',{class:'field'},[h('small',{text:'RA, degrees'}),ra]),h('label',{class:'field'},[h('small',{text:'Dec, degrees'}),de])]),perr,
    location.hash.indexOf('#/explore')===0?null:h('a',{class:'link t12',href:'#/explore'+(o.ra!=null?'?ra='+o.ra.toFixed(5)+'&dec='+o.dec.toFixed(5)+'&fov=0.5':''),onclick:function(){close()}},['Pick the position in Sky Explorer'])]));
  body.appendChild(h('label',{class:'field'},[h('span',{text:'What do you think it is'}),type]));
  body.appendChild(h('label',{class:'field'},[h('span',{text:'Your notes'}),notes,nerr]));
  body.appendChild(h('div',{class:'field'},[h('span',{text:'We’ll attach'}),att]));
  function make(status,btn){var a=+ra.value,b=+de.value;perr.textContent=nerr.textContent='';
    if(ra.value===''||de.value===''||isNaN(a)||isNaN(b)||a<0||a>=360||Math.abs(b)>90){perr.textContent='Enter RA from 0 to 360 and Dec from −90 to +90, in degrees.';ra.focus();return}
    if(status!=='Draft'&&notes.value.trim().length<12){nerr.textContent='Add a sentence about what you saw. It helps voters check the same frames.';notes.focus();return}
    var dup=PW.store.get().finds.filter(function(f){var p=PW.findPos(f);return p&&f.status!=='Withdrawn'&&sep(p,[a,b])<10/3600})[0];
    if(dup&&status!=='Draft'){perr.textContent='';var go=h('a',{class:'link',href:'#/discussions/'+dup.id,onclick:function(){close()}},['open its discussion']);perr.append('Already shared within 10″ as '+dup.id+'. Vote or comment there instead, or ');perr.appendChild(go);perr.append('.');return}
    var id='F-'+String(1000+PW.store.get().finds.length).slice(1)+'C';
    btn.classList.add('busy');setTimeout(function(){btn.classList.remove('busy');
      PW.store.set(function(t){t.finds.unshift({id:id,title:(type.value==='Not sure'?'Unidentified source':type.value)+' at '+a.toFixed(3)+' '+(b<0?'−':'+')+Math.abs(b).toFixed(3),type:type.value,source:'Community',finder:t.user,mine:true,status:status,up:0,down:0,need:10,
        ra:a,dec:b,field:o.field||null,src:o.src?o.src.id:null,made:PW.TODAY,notes:notes.value.trim(),comments:[]})});
      close();if(status==='Draft'){PW.toast('Saved as draft. Find it on your profile under Finds.');return}
      var wait=h('div',{},[h('p',{class:'t16',text:'Checking…'})]),c2=PW.modal('Share your find',wait);
      setTimeout(function(){wait.textContent='';wait.appendChild(h('p',{class:'t16',text:'Your find is live.'}));wait.appendChild(h('p',{class:'muted',text:'It needs 10 up votes to reach a Labs reviewer.'}));
        wait.appendChild(h('a',{class:'btn pri',href:'#/discussions/'+id,onclick:function(){c2()}},['Open discussion']));PW.xp(15,'Shot in the Dark, find shared');if(PW.explore.refresh)PW.explore.refresh()},800)},500)}
  var bd=h('button',{class:'btn',type:'button'},['Save as draft']),bs=h('button',{class:'btn pri',type:'button'},['Share your find']);bd.onclick=function(){make('Draft',bd)};bs.onclick=function(){make('Needs votes',bs)};
  close=PW.modal('Share your find',body,[bd,bs])};

/* ---------- Proof, from the pipeline's sample export ---------- */
function tb(head,rows){return '<div style="overflow-x:auto"><table class="t12" style="width:100%;border-collapse:collapse;color:var(--muted)"><thead><tr style="text-align:left">'+head.map(function(x){return '<th style="padding:8px 16px 8px 0;font-weight:500">'+x+'</th>'}).join('')+'</tr></thead><tbody>'+
  rows.map(function(r){return '<tr style="border-top:1px solid var(--line)">'+r.map(function(c,i){return '<td style="padding:8px 16px 8px 0;vertical-align:top'+(i?'':';color:var(--text)')+'">'+c+'</td>'}).join('')+'</tr>'}).join('')+'</tbody></table></div>'}
PW.proof=function(){var b=h('div',{});b.innerHTML='<p class="muted">Results from the pipeline’s sample export of 15 Nov 2026. Thresholds are shown as set, unedited. The test targets are known objects used only to check the system.</p>'+
  '<div><h3 class="h16">Tier B report card, version 0.3.0</h3><p class="muted" style="margin:4px 0 8px">8 pass · 5 fail · 0 not measured</p>'+tb(['Test','Pass mark','Measured'],[
   ['B1 · RW Aurigae field photometry','median ≤ 5%, scatter ≤ 10%','median 3.5%'],['B2 · W1925 field photometry','scatter ≤ 20%','scatter 19.24%'],['B3 · RW Aurigae field recovery','80% or more','80.0%'],
   ['B4 · Benchmark list and field neighbours','≥ 80% found, ≤ 1% false matches','recall 100%'],['B5 · Type model, gold sample above S/N 10','recall ≥ 0.80, calibration error ≤ 0.05','minimum recall 0.5833'],
   ['B6 · Real-or-artifact model','recall 0.90 or more','recall 0.9048'],['B7 · Movers among the test targets','predicted within 2σ, staying put excluded beyond 3σ','held 1 of 3'],
   ['B8 · Searched depth in both fields','published as measured','90% recovery at 13.50 AB mag off the plane, 15.50 AB mag in the plane (D6)'],['B9 · SMDET-1 crowding benchmark','published as measured','not detected, as expected'],
   ['B10 · Edge check','1% or less','0.0% (0 of 19)'],['B11 · Ultracool dwarf subtype','≥ 80% within 2 subtypes','87.5%']])+'</div>'+
  '<div><h3 class="h16" style="margin-bottom:8px">Test targets</h3>'+tb(['Target','Gaia alignment','D6 S/N','Motion','Residual','Note'],[
   ["Barnard's Star",'0.284″','2201.53','12.873″/yr','2.484″/yr','prediction check failed'],['WISE 0855','0.198″','−1.48','not measured','not measured','not detected in D6'],
   ['Epsilon Indi B','0.578″','130.39','4.208″/yr','0.563″/yr','prediction check held'],['RW Aurigae','0.856″','2984.86','2.083″/yr','2.082″/yr','saturated detectors excluded'],['R Draconis','4.488″','288.87','not measured','not measured','core saturated']])+'</div>'+
  '<div class="grid2"><div><h3 class="h16">Model release</h3><ul class="rows muted"><li>Type model spherex-dr1-e1e2-v2, unpublished</li><li>763 spectra · gold recall 0.8571</li><li>Calibration error 0.0645 · E2 accuracy 0.9355</li><li>Conformal coverage 0.9785</li></ul></div>'+
  '<div><h3 class="h16">Stated limits</h3><ul class="rows muted"><li>Single-visit 50% recovery reaches 15.91 AB mag off the plane and 15.94 AB mag in it. The four-survey goal is 17.8 to 18.8 AB mag (Bock et al. 2025).</li><li>Crowding costs 2.2 mag in D3 in the Galactic plane.</li><li>One cutout covers 6.56′. A planet at 500 au shifts about 800″ in six months, so cross-tile links are needed.</li><li>The all-sky map is the DR1 mosaic at 12.9″ per pixel. Single visits are 6.15″ per pixel.</li></ul></div></div>'+
  '<div class="grid2"><div><h3 class="h16">Next</h3><ul class="rows muted"><li>Move extraction from 14″ cubes to 6.2″ Level-2 PSF fitting.</li><li>Reach per-class recall ≥ 0.80 and calibration error ≤ 0.05 to pass the model release gate.</li><li>Remove known catalogued stars in both fields and add an injection suite.</li></ul></div>'+
  '<div><h3 class="h16">Data credits</h3><ul class="rows muted"><li>SPHEREx DR1 all-sky HiPS cube and Quick Releases via IRSA (DOI 10.26131/IRSA652, IRSA662).</li><li>Gaia DR3, 2MASS, CatWISE2020, unWISE, SIMBAD, VizieR, AAVSO VSX, IMCCE SkyBoT.</li><li>Not a NASA product. Built for the NASA Space Apps Challenge 2026.</li></ul></div></div>';
  PW.modal('Proof',b,null,true)};

/* ========== Sky Explorer ========== */
var E,root,map,playT=null,visT=null,keyH,resH;
var VMODES=[['play','Play'],['diff','Difference'],['stack','Stack'],['rgb','Visits as colour']];
function S0(){return PW.store.get()}
/* everything that can be selected on the map */
function items(){var a=[];
  PW.SIGNALS().forEach(function(o){var F=PW.FIELDS[o.f],p=PW.sigPos(F,o.s,3);a.push({kind:'signal',f:o.f,s:o.s,id:o.s.id,name:o.s.id.replace('GaiaDR3-','Gaia '),ra:p[0],dec:p[1],warm:o.s.status==='Uncatalogued'})});
  if(E.ov.tests)PW.JUMP.forEach(function(k){var F=PW.FIELDS[k];if(F.processed)return;var S=F.src[0],p=PW.sigPos(F,S,3);a.push({kind:'signal',f:k,s:S,id:S.id,name:S.name,ra:p[0],dec:p[1],test:true})});
  if(E.ov.finds)S0().finds.forEach(function(f){if(f.status==='Draft'&&!f.mine)return;if(f.field&&f.src&&!f.ra)return;var p=PW.findPos(f);if(p)a.push({kind:'find',find:f,id:f.id,name:f.id,ra:p[0],dec:p[1],warm:true})});
  if(E.ov.mine)S0().markers.forEach(function(m,i){if(m.ra!=null)a.push({kind:'marker',i:i,id:'m'+i,name:'Your marker',ra:m.ra,dec:m.dec})});
  return a}
function selItem(){var s=E.sel;if(!s)return null;if(s.kind==='signal'){var F=PW.FIELDS[s.f];return {F:F,S:PW.src(s.f,s.id)}}return null}

function sync(){clearTimeout(sync.t);sync.t=setTimeout(function(){if(!root||!root.isConnected)return;var q=['ra='+map.ra.toFixed(5),'dec='+map.dec.toFixed(5),'fov='+(+map.fov().toPrecision(3)),'b='+(E.rgb?'rgb':E.layer)];
  if(E.sel&&E.sel.kind==='signal')q.push('f='+E.sel.f,'s='+E.sel.id);if(E.sel&&E.sel.kind==='spot')q.push('pick=1');history.replaceState(null,'','#/explore?'+q.join('&'))},300)}

/* ---------- overlay: marks, grid, readouts ---------- */
function overlay(){if(!root||!root.isConnected)return;var g=$('#ov',root),W=map.W,H=map.H,fov=map.fov(),list=items(),lbl=fov<3,i,p;g.setAttribute('viewBox','0 0 '+W+' '+H);g.textContent='';
  if(E.ov.grid){var st=[30,15,10,5,2,1,.5,.25,1/6,1/12,1/30,1/60].filter(function(x){return x<=fov/3})[0]||1/120,ra0=Math.floor((map.ra-fov*2)/st)*st,de0=Math.max(-90,Math.floor((map.dec-fov)/st)*st),d='',a,b,q,first;
    for(a=0;a<=Math.min(360,fov*4+st);a+=st){first=true;for(b=-90;b<=90;b+=Math.min(2,st/4)){q=map.project(ra0+a,b);if(!q[2]){first=true;continue}d+=(first?'M':'L')+q[0].toFixed(1)+' '+q[1].toFixed(1);first=false}}
    for(b=de0;b<=Math.min(90,map.dec+fov);b+=st){first=true;for(a=0;a<=360;a+=Math.min(2,st/4)){q=map.project(a,b);if(!q[2]){first=true;continue}d+=(first?'M':'L')+q[0].toFixed(1)+' '+q[1].toFixed(1);first=false}}
    g.appendChild(s('path',{d:d,fill:'none',stroke:'#9DB8FF','stroke-opacity':.22,'stroke-width':1}))}
  var boxes=[],labels=[];
  list.forEach(function(it){p=map.project(it.ra,it.dec);if(!p[2]||p[0]<-40||p[1]<-40||p[0]>W+40||p[1]>H+40)return;it.x=p[0];it.y=p[1];
    var sel=E.sel&&E.sel.id===it.id,c=sel?'#9DB8FF':it.kind==='marker'?'#9DB8FF':it.warm?'#FF9A52':'#E8EAED',r=it.test?7:9;
    boxes.push([p[0]-r,p[1]-r,p[0]+r,p[1]+r]);if(lbl||sel)labels.push({it:it,p:[p[0],p[1]],c:c,sel:sel,pr:sel?0:it.kind==='find'?1:it.warm?2:it.test?4:3});
    if(it.kind==='marker')g.appendChild(s('path',{d:'M'+p[0]+' '+(p[1]-7)+'l7 7-7 7-7-7z',fill:'#9DB8FF'}));
    else if(it.kind==='find'){var stc={'Needs votes':'#E8EAED','Queued':'#E8C860','In review':'#6EA8FF','Accepted':'#7BD88F','Closed':'#FF7B72','Withdrawn':'#7C8491','Draft':'#9AA1AC'}[it.find.status]||'#E8EAED';
      g.appendChild(s('rect',{x:p[0]-7,y:p[1]-7,width:14,height:14,fill:'none',stroke:sel?'#9DB8FF':stc,'stroke-width':sel?2:1.5,transform:'rotate(45 '+p[0]+' '+p[1]+')'}))}
    else g.appendChild(s('circle',{cx:p[0],cy:p[1],r:r,fill:'none',stroke:c,'stroke-width':sel?2:1.25,'stroke-dasharray':it.test?'3 3':'',class:it.warm&&!sel?'pulse':''}))});
  /* labels: most important first, each tries four positions and is dropped if all of them collide */
  labels.sort(function(a,b){return a.pr-b.pr}).forEach(function(L){var t=L.it.name+(L.it.kind==='find'?' · '+L.it.find.status:''),w=t.length*6.6+4,x=L.p[0],y=L.p[1],
      opts=[[1,-1],[1,1],[-1,-1],[-1,1]],k,dx,dy,bx,ok;
    for(k=0;k<4;k++){dx=opts[k][0];dy=opts[k][1];bx=dx>0?[x+22,y+(dy<0?-24:4),x+24+w,y+(dy<0?-6:22)]:[x-24-w,y+(dy<0?-24:4),x-22,y+(dy<0?-6:22)];
      ok=bx[0]>0&&bx[2]<W&&bx[1]>0&&bx[3]<H&&boxes.every(function(b){return bx[2]<b[0]||bx[0]>b[2]||bx[3]<b[1]||bx[1]>b[3]});if(ok||L.sel&&k===3)break}
    if(!ok&&!L.sel)return;boxes.push(bx);
    g.appendChild(s('path',{d:'M'+(x+7*dx)+' '+(y+7*dy)+'l'+8*dx+' '+8*dy+'h'+6*dx,stroke:L.c,'stroke-width':1,fill:'none'}));
    g.appendChild(s('text',{x:dx>0?x+24:x-24,y:y+(dy<0?-11:17),fill:L.c,class:'olab','text-anchor':dx>0?'start':'end'},t))});
  if(E.sel&&E.sel.kind==='spot'){p=map.project(E.sel.ra,E.sel.dec);if(p[2]){g.appendChild(s('path',{d:'M'+(p[0]-14)+' '+p[1]+'h9M'+(p[0]+5)+' '+p[1]+'h9M'+p[0]+' '+(p[1]-14)+'v9M'+p[0]+' '+(p[1]+5)+'v9',stroke:'#9DB8FF','stroke-width':1.5}));
    if(lbl)g.appendChild(s('text',{x:p[0]+18,y:p[1]-10,fill:'#9DB8FF',class:'olab'},'Selected position'))}}
  if(E.rule&&E.rule.length){var p1=map.project(E.rule[0][0],E.rule[0][1]);g.appendChild(s('circle',{cx:p1[0],cy:p1[1],r:3,fill:'#9DB8FF'}));
    if(E.rule[1]){var p2=map.project(E.rule[1][0],E.rule[1][1]),dd=sep(E.rule[0],E.rule[1]);g.appendChild(s('path',{d:'M'+p1[0]+' '+p1[1]+'L'+p2[0]+' '+p2[1],stroke:'#9DB8FF','stroke-width':1.5}));
      g.appendChild(s('text',{x:(p1[0]+p2[0])/2,y:(p1[1]+p2[1])/2-8,fill:'#9DB8FF','text-anchor':'middle',class:'olab'},dd>=1?dd.toFixed(3)+'°':dd*60>=1?(dd*60).toFixed(2)+'′':(dd*3600).toFixed(1)+'″'))}}
  /* scale bar */
  var arc=[[1,'1″'],[5,'5″'],[10,'10″'],[30,'30″'],[60,'1′'],[300,'5′'],[600,'10′'],[1800,'30′'],[3600,'1°'],[18000,'5°'],[36000,'10°'],[108000,'30°']],px=map.s*D2R/3600,best=arc[0];
  for(i=0;i<arc.length;i++)if(arc[i][0]*px<=W*.18)best=arc[i];
  $('#voBL',root).innerHTML=fov<120?'<i class="sbar" style="width:'+Math.max(8,best[0]*px).toFixed(1)+'px"></i>'+best[1]:'';
  var L=E.rgb?'Colour: <span style="color:#6EA8FF">'+PW.WAVE[E.cl[2]].toFixed(2)+'</span> · <span style="color:#7BD88F">'+PW.WAVE[E.cl[1]].toFixed(2)+'</span> · <span style="color:#FF7B72">'+PW.WAVE[E.cl[0]].toFixed(2)+' µm</span> · false colour':PW.layerName(E.layer);
  $('#voTL',root).innerHTML=L+'<br>SPHEREx DR1 all-sky mosaic · IRSA';
  $('#cC',root).textContent=E.sexa?PW.sexa(map.ra,map.dec):PW.deci(map.ra,map.dec);$('#cF',root).textContent=PW.fovText(fov)+' across';
  var st=PW.skyStatus();$('#cL',root).textContent=st.waiting?'Loading '+st.waiting+(st.waiting===1?' tile':' tiles'):'';
  sync()}

/* ---------- right panel: what it is, evidence, status, actions ---------- */
function panel(){var box=$('#exR',root),sel=E.sel;box.hidden=!sel;if(!sel)return;var it=selItem(),html='',S=it&&it.S,F=it&&it.F,pos,fd,saved;
  if(sel.kind==='signal'&&!S){E.sel=null;box.hidden=true;return}
  pos=sel.kind==='signal'?PW.sigPos(F,S,3):[sel.ra,sel.dec];
  fd=sel.kind==='signal'?PW.store.findFor(sel.f,S.id):S0().finds.filter(function(f){var p=PW.findPos(f);return p&&f.status!=='Withdrawn'&&f.status!=='Draft'&&sep(p,pos)<10/3600})[0];
  saved=S0().saved.some(function(x){return x.ra!=null?sep([x.ra,x.dec],pos)<1/3600:x.f===sel.f&&x.s===sel.id});
  var stat=sel.kind==='signal'?S.status:'Position',chip=stat==='Known'?'k':stat==='Uncatalogued'?'u':'',line=fd?'Already shared · <a class="link" href="#/discussions/'+fd.id+'">View discussion</a>':sel.kind==='signal'&&S.status==='Known'?'Known object · SIMBAD: '+esc(S.simbad):'Nothing on record here';
  html='<header><span class="lab">Data panel</span><span><button class="ibtn sheet-h" id="pSize" aria-label="Resize panel"></button><button class="ibtn" id="pClose" aria-label="Close panel"></button></span></header>'+
   '<div class="sec what"><span class="schip '+chip+'">'+esc(stat)+'</span><h2 class="h20">'+esc(sel.kind==='signal'?S.name:'Selected position')+'</h2>'+
   (sel.kind==='signal'?'<p class="best">'+esc(PW.estText(S))+'</p>'+(S.capped?'<p class="t12 muted">The two models disagree, so the shown value is capped at 50%.</p>':''):'<p class="best">No model estimate yet. Share it to run the checks.</p>')+
   '<p class="t12">'+num(PW.deci(pos[0],pos[1]),'',null,sel.kind==='signal'?'Measured':'Chosen on the map',sel.kind==='signal'?'Position in the latest visit, 6 Nov 2026. J2000.':'The position you clicked. J2000.')+'</p><p class="t12 muted">'+PW.sexa(pos[0],pos[1])+'</p>'+
   '<p class="t12 muted">'+line+'</p></div>';
  if(sel.kind==='signal'){var rows=[];if(S.sigkind)rows.push(['Signal',esc(S.sigkind)]);if(S.preal!=null)rows.push(['Real, not an artifact',num((S.preal*100).toFixed(1).replace(/\.0$/,'')+'%','',null,'Estimated','Output of the real-or-artifact model.')]);
    if(S.sn!=null)rows.push(['Signal to noise',num('S/N '+S.sn,'',null,'Measured','In the brightest detector.')]);if(S.novel)rows.push(['Novelty check','unlike the training set']);
    if(S.rms)rows.push(['Gaia alignment',num(S.rms,'″ RMS',null,'Measured','Motion is not measured above 2.0″.')]);if(S.sat)rows.push(['Saturation',S.sat==='all'?'core saturated in D1 to D6':'saturated detectors excluded']);
    if(S.pm)rows.push(['Motion, measured',/^[0-9]/.test(S.pm[0])?num(S.pm[0],'″/yr',S.pm[1],'Measured','From SPHEREx cutouts across the visits.'):esc(S.pm[0])]);else rows.push(['Motion, measured','<span class="muted">not measured: '+esc(S.pmWhy||'no shift larger than the error')+'</span>']);
    if(S.pmCat)rows.push(['Motion, catalog',num(S.pmCat,/^[0-9]/.test(S.pmCat)?'″/yr':'',null,'Catalog','Published value.')]);if(S.pred)rows.push(['Prediction check',esc(S.pred[0])+' · '+S.pred[1]+'″, 2σ is '+S.pred[2]+'″']);
    html+='<div class="sec"><span class="lab">From the pipeline</span><dl class="kv">'+rows.map(function(r){return '<dt>'+r[0]+'</dt><dd>'+r[1]+'</dd>'}).join('')+'</dl>'+
     (S.chg?'<span class="lab">Change between visits</span><ul class="rows t12">'+S.chg.map(function(c,i){return '<li><span style="color:'+D[i].c+'">'+D[i].id+'</span><span>'+(c?'ratio '+c[0].toFixed(2)+' · S/N '+c[1]:'<span class="muted">not measured: low S/N</span>')+'</span></li>'}).join('')+'</ul>':'')+'</div>';
    html+='<div class="sec"><span class="lab">Molecules</span><ul class="rows">'+PW.molRows(S).slice(0,3).map(function(m){return '<li><span>'+esc(m[0])+'</span><span>'+(m[1]?num(m[1],'',m[2],'Measured','Signature strength with its uncertainty, from the pipeline.'):'<span class="muted">not measured: '+esc(m[2])+'</span>')+'</span></li>'}).join('')+'</ul></div>'}
  html+='<div class="sec"><span class="lab">Brightness in 102 bands <span class="muted" style="text-transform:none;letter-spacing:0">real mosaic</span></span><div id="pBands"></div></div>';
  if(fd)html+='<div class="sec"><span class="lab">Status</span><span class="st '+PW.STATUS[fd.status][1]+'" id="pSt"></span></div>';
  html+='<div class="sec acts" id="pActs"></div>';
  box.innerHTML=html;$('#pClose',box).appendChild(PW.icon('cross'));$('#pSize',box).appendChild(PW.icon('updown'));
  if(fd){var e=$('#pSt',box);e.appendChild(PW.icon(PW.STATUS[fd.status][0]));e.appendChild(document.createTextNode(fd.status+(fd.reason?' · '+fd.reason:'')))}
  bands(pos);
  var A=$('#pActs',box),src=sel.kind==='signal'?S:null;
  if(fd)A.appendChild(h('a',{class:'btn pri',href:'#/discussions/'+fd.id},['Open discussion']));
  else if(!src||src.status!=='Known')A.appendChild(h('button',{class:'btn pri',onclick:function(){PW.shareFind({ra:pos[0],dec:pos[1],field:sel.f,src:src})}},['Share your find']));
  else A.appendChild(h('button',{class:'btn pri',onclick:function(){visits(true)}},['Play visits here']));
  A.appendChild(h('div',{class:'two'},[
    h('button',{class:'btn',onclick:function(){PW.store.set(function(t){if(saved)t.saved=t.saved.filter(function(x){return !(x.ra!=null?sep([x.ra,x.dec],pos)<1/3600:x.f===sel.f&&x.s===sel.id)});else t.saved.push({ra:pos[0],dec:pos[1],f:sel.f||null,s:sel.kind==='signal'?sel.id:null,name:sel.kind==='signal'?S.name:'Position '+pos[0].toFixed(3)+' '+pos[1].toFixed(3)})});PW.toast(saved?'Removed from Saved':'Saved to your profile');panel()}},[PW.icon('bookmark'),saved?'Saved':'Save']),
    h('button',{class:'btn',onclick:function(){visits(true)}},[PW.icon('play'),'Play visits'])]));
  $('#pClose',box).onclick=function(){E.sel=null;panel();overlay();visits(false)};
  $('#pSize',box).onclick=function(){var o=['28dvh','50dvh','88dvh'],i=(o.indexOf(box.style.getPropertyValue('--sheet')||'50dvh')+1)%3;box.style.setProperty('--sheet',o[i])}}
/* read the real 102-band values at a position, live, band by band */
function bands(pos){var B=$('#pBands',root),key=pos[0].toFixed(5)+pos[1].toFixed(5);if(!B)return;
  if(E.bcache[key]){draw(E.bcache[key]);return}
  var bt=h('button',{class:'btn sm',onclick:go},['Read all 102 bands here']);B.appendChild(h('p',{class:'t12 muted',text:'Reads this position in every layer of the DR1 mosaic, about 100 small images.'}));B.appendChild(bt);
  function go(){B.textContent='';var msg=h('p',{class:'t12 muted',role:'status',text:'Reading band 0 of 100.'}),bar=h('div',{class:'bar'},[h('i',{style:'width:0;animation:none'})]);B.appendChild(msg);B.appendChild(bar);
    PW.readBands(pos[0],pos[1],function(n,t){msg.textContent='Reading band '+n+' of '+t+'.';bar.firstChild.style.width=(n/t*100)+'%'}).then(function(v){E.bcache[key]=v;if($('#pBands',root)===B)draw(v)})}
  function draw(v){B.textContent='';B.appendChild(PW.bandChart(v));B.appendChild(PW.bandStrip(v));
    B.appendChild(h('p',{class:'t12 muted',text:'Display values from the DR1 mosaic, 0 to 255 on an asinh stretch of 0 to 40 MJy/sr. A quick look, not calibrated photometry. Bands 51 and 52 are blank in DR1.'}))}}

/* ---------- visits at a position: per-visit frames come from the frame service ---------- */
function visits(open){var P=$('#vis',root);if(open===false||!E.sel){P.hidden=true;stopV();return}if(open)P.hidden=false;if(P.hidden)return;
  var it=selItem(),F=it?it.F:PW.spotField(E.sel.ra,E.sel.dec),S=it?it.S:{x:0,y:0,sed:[1,1,1,1,1,1]},d=E.rgb?5:Math.floor(E.layer/17),V=E.vis,fr=function(v){return PW.frame(F,d,v,{n:24,cx:S.x+(S.vx||0)*1.5,cy:S.y+(S.vy||0)*1.5})},cv=$('#vCv',P);
  if(V.m==='diff')PW.paint(cv,[PW.mix([fr(Math.max(1,V.v)),fr(Math.max(1,V.v)-1)],[1,-1])],{signed:true});
  else if(V.m==='stack')PW.paint(cv,[PW.mix([fr(0),fr(1),fr(2),fr(3)],[.25,.25,.25,.25])]);
  else if(V.m==='rgb')PW.paint(cv,[fr(0),fr(1),fr(3)]);
  else PW.paint(cv,[fr(V.v)]);
  $$('[data-vm]',P).forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.vm===V.m))});
  $('#vT',P).textContent=(V.m==='diff'?VS[Math.max(1,V.v)].date+' minus '+VS[Math.max(1,V.v)-1].date:V.m==='stack'?'Stack of 4 visits':V.m==='rgb'?'Visits 1, 2 and 4 as red, green, blue':'Visit '+(V.v+1)+' of 4 · '+VS[V.v].date)+' · '+D[d].id;
  var pb=$('#vPlay',P);pb.textContent='';pb.appendChild(PW.icon(visT?'pause':'play'));pb.setAttribute('aria-label',visT?'Pause visits':'Play visits');
  $$('.vm-dot',P).forEach(function(c){c.setAttribute('opacity',+c.dataset.v===V.v&&+c.dataset.d===d?1:.32)})}
function stopV(){if(visT){clearInterval(visT);visT=null}}
function playV(){if(visT){stopV();visits();return}E.vis.m='play';visT=setInterval(function(){E.vis.v=(E.vis.v+1)%4;visits()},700);visits()}

/* ---------- bands ---------- */
function setLayer(l){E.rgb=false;E.layer=Math.max(0,Math.min(101,l));if(PW.BLANK(E.layer))E.layer+=E.layer===50?-1:1;map.setLayers([E.layer]);ui();overlay();if(!$('#vis',root).hidden)visits()}
function setRGB(){E.rgb=true;map.setLayers(E.cl);ui();overlay()}
function stopP(){if(playT){clearInterval(playT);playT=null}ui()}
function playBands(){if(playT){stopP();return}var d=E.rgb?5:Math.floor(E.layer/17),ls=[],i;for(i=0;i<17;i++)if(!PW.BLANK(17*d+i))ls.push(17*d+i);if(E.rgb)setLayer(ls[0]);
  map.prefetch(ls);playT=setInterval(function(){var i=ls.indexOf(E.layer),n=ls[(i+1)%ls.length];if(!map.ready([n])){map.prefetch([n]);return}setLayer(n)},PW.still?1200:260);ui()}
function ui(){if(!root)return;$$('[data-b]',root).forEach(function(b){b.setAttribute('aria-pressed',String(b.dataset.b==='rgb'?E.rgb:!E.rgb&&+b.dataset.b===Math.floor(E.layer/17)))});
  var w=$('#wl',root);w.value=E.layer;w.disabled=E.rgb;$('#wlT',root).textContent=E.rgb?'Colour':PW.WAVE[E.layer].toFixed(2)+' µm';
  var pb=$('#bPlay',root);pb.textContent='';pb.appendChild(PW.icon(playT?'pause':'play'));pb.appendChild(h('span',{text:playT?'Pause':'Play bands'}));pb.setAttribute('aria-pressed',String(!!playT));pb.setAttribute('aria-label',playT?'Pause bands':'Play bands');pb.title=playT?'Pause bands':'Play the bands of this detector'}

/* ---------- menus ---------- */
function menu(btn,kids){var o=$('.pop.menu');if(o){o.remove();if(o._for===btn)return}var p=h('div',{class:'pop menu',style:'display:grid;gap:8px;min-width:260px'},kids);p._for=btn;document.body.appendChild(p);
  var r=btn.getBoundingClientRect();p.style.top=(r.bottom+scrollY+8)+'px';p.style.left=Math.max(8,Math.min(r.left,innerWidth-p.offsetWidth-8))+'px';
  setTimeout(function(){document.addEventListener('click',function c(e){if(p.contains(e.target))return;p.remove();document.removeEventListener('click',c)})},0)}
function chk(label,get,set){var i=h('input',{type:'checkbox'});i.checked=get();i.addEventListener('change',function(){set(i.checked);overlay()});return h('label',{class:'check'},[i,label])}
function range(label,min,max,step,get,set){var r=h('input',{type:'range',min:min,max:max,step:step,value:get()}),o=h('b',{text:String(get())});r.addEventListener('input',function(){set(+r.value);o.textContent=r.value;map.dirty()});return h('label',{class:'field'},[h('span',{class:'t12'},[label+' ',o]),r])}

/* ---------- left panel: Search by light and Auto-detected ---------- */
function left(){var box=$('#exL',root);box.hidden=!E.left;if(!E.left)return;
  box.innerHTML='<header><span class="lab">Search by light</span><button class="ibtn" id="lClose" aria-label="Close panel"></button></header><div class="sec" id="lSearch"></div><div class="sec" id="lAuto"><span class="lab">Auto-detected</span></div>';
  $('#lClose',box).appendChild(PW.icon('cross'));$('#lClose',box).onclick=function(){E.left=false;left()};
  var L=$('#lSearch',box),A=$('#lAuto',box),all=PW.SIGNALS(),tg=h('div',{style:'display:grid;grid-template-columns:1fr 1fr;gap:0 8px'}),
   ty=h('select',{class:'select','aria-label':'Object type'},[h('option',{value:'',text:'Any type'})].concat(['Ultracool dwarf','Young star','Star','Evolved giant','Galaxy','Active galaxy or quasar','Unclassified'].map(function(t){return h('option',{text:t})})));
  ty.value=E.ltype||'';ty.onchange=function(){E.ltype=ty.value;left()};
  L.appendChild(h('p',{class:'t12 muted',text:'Covers the W1925 Galactic Plane field and the RW Aurigae field, 3.3′ radius each. Full-sky search is not active yet.'}));
  L.appendChild(h('label',{class:'field'},[h('span',{class:'t12',text:'Type, from the model'}),ty]));
  [['ch4','Methane dip'],['ice','Water ice'],['co2','CO2 ice'],['co','CO ice'],['moved','Moved between visits'],['changed','Changed brightness'],['nocat','Not in any catalog']].forEach(function(t){
    var i=h('input',{type:'checkbox'});i.checked=E.light.indexOf(t[0])>-1;i.onchange=function(){if(i.checked)E.light.push(t[0]);else E.light=E.light.filter(function(x){return x!==t[0]});left()};tg.appendChild(h('label',{class:'check'},[i,t[1]]))});L.appendChild(tg);
  [['sn','Minimum S/N',5,80],['bl','Maximum light from neighbours, %',5,100]].forEach(function(c){var r=h('input',{type:'range',min:c[2],max:c[3],value:E[c[0]]}),o=h('b',{text:String(E[c[0]])});r.oninput=function(){E[c[0]]=+r.value;o.textContent=r.value};r.onchange=left;L.appendChild(h('label',{class:'field'},[h('span',{class:'t12'},[c[1]+' ',o]),r]))});
  var hit=all.filter(function(o){var x=o.s;return x.sn>=E.sn&&x.blend<=E.bl&&(!E.ltype||x.type===E.ltype)&&E.light.every(function(t){return x.tags.indexOf(t)>-1})});
  L.appendChild(h('span',{class:'lab',text:hit.length+' of '+all.length+' match, by priority'}));
  if(!hit.length)L.appendChild(h('p',{class:'muted',text:'No source matches these filters. Clear a toggle or lower the minimum S/N.'}));
  hit.forEach(function(o){L.appendChild(res(o))});all.forEach(function(o){A.appendChild(res(o,true))});
  function res(o,auto){var x=o.s,fd=x.find&&PW.store.find(x.find);return h('button',{class:'res','aria-current':String(!!(E.sel&&E.sel.id===x.id)),onclick:function(){pickSignal(o.f,x.id,true)}},[
     h('span',{},[h('b',{text:x.id.replace('GaiaDR3-','Gaia ')}),' · '+x.type]),h('span',{class:'prio',title:'Priority'},[h('i',{style:'width:'+x.prio*100+'%'})]),
     h('small',{text:auto?x.sigkind+' · '+(fd?fd.status:'not shared'):PW.FIELDS[o.f].name.split(' ')[0]+' · S/N '+x.sn+' · real '+(x.preal*100).toFixed(1)+'%'})])}}
function pickSignal(f,id,fly){var F=PW.FIELDS[f],S=PW.src(f,id);if(!S)return;E.sel={kind:'signal',f:f,id:id};panel();left();var p=PW.sigPos(F,S,3);
  if(fly)map.flyTo(p[0],p[1],Math.min(map.fov(),.35),overlay);else overlay();if(!$('#vis',root).hidden)visits()}
PW.goField=function(k){var F=PW.FIELDS[k];if(F&&F.src[0])pickSignal(k,F.src[0].id,true)};

/* ---------- mount ---------- */
PW.explore={mount:function(el,q){root=el;var st=S0();
  E={layer:PW.detLayer(2),rgb:true,cl:[PW.detLayer(5),PW.detLayer(2),PW.detLayer(0)],sel:null,left:innerWidth>900&&!!st.user,light:[],sn:5,bl:100,ltype:'',sexa:false,
     ov:{signals:true,tests:true,finds:true,mine:true,grid:false},tool:null,rule:null,bcache:{},vis:{v:0,m:'play'}};
  if(q.b&&q.b!=='rgb'&&!isNaN(+q.b)){E.rgb=false;E.layer=+q.b}
  el.innerHTML='<div class="ex"><aside class="side" id="exL" hidden></aside><div class="mid"><div class="tools" id="tools"></div>'+
   '<div class="stage" id="stage"><canvas id="map" role="img" aria-label="SPHEREx DR1 all-sky mosaic. Drag to move, scroll or pinch to zoom."></canvas><svg id="ov" aria-hidden="true"></svg>'+
   '<div class="vo tl" id="voTL"></div><div class="vo tr">N ↑<br>E ←</div><div class="vo bl" id="voBL"></div><div class="vo br" id="voBR"></div>'+
   '<div class="vpanel panel" id="vis" hidden><header><span class="lab">Visits at this position</span><button class="ibtn" id="vClose" aria-label="Close visits"></button></header>'+
    '<canvas id="vCv" role="img" aria-label="Frames of the selected position, visit by visit"></canvas><p class="t12" id="vT"></p><div class="seg" id="vModes"></div>'+
    '<div class="btns" style="align-items:center"><button class="ibtn" id="vPrev" aria-label="Previous visit"></button><button class="ibtn" id="vPlay"></button><button class="ibtn" id="vNext" aria-label="Next visit"></button></div>'+
    '<svg id="vMx" viewBox="0 0 268 74" role="img" aria-label="Observation matrix: four visits across, wavelength up, one dot per frame"></svg>'+
    '<p class="t12 muted">The frame service is not connected in this build, so these frames are simulated. The map behind is real.</p></div>'+
   '<div class="tour" id="tour" hidden></div></div>'+
   '<div class="statusline" id="sline"><span class="lab" style="letter-spacing:.04em">Centre</span><button class="coord" id="cC" title="Switch between degrees and hours"></button><span class="muted" id="cF"></span><span class="muted" id="cL" role="status"></span><span class="grow"></span><span class="muted t12" id="cCur"></span>'+
   '<div class="seg" id="zoom"><button aria-label="Zoom out" id="zOut">−</button><button aria-label="Zoom in" id="zIn">+</button></div></div></div>'+
   '<aside class="side r" id="exR" hidden></aside></div>';
  var T=$('#tools',el);
  T.appendChild(h('button',{class:'btn sm',onclick:function(){E.left=!E.left;left()}},[PW.icon('filter','sm'),h('span',{text:'Search by light'})]));
  var jump=h('select',{class:'select',style:'width:132px;height:32px','aria-label':'Jump to'},[h('option',{value:'',text:'Jump to…'}),h('option',{value:'sky',text:'Whole sky'}),h('optgroup',{label:'Processed fields'},['aquila','rwaur'].map(function(k){return h('option',{value:k,text:PW.FIELDS[k].name})})),
    h('optgroup',{label:'Test fields'},PW.JUMP.filter(function(k){return !PW.FIELDS[k].processed}).map(function(k){return h('option',{value:k,text:PW.FIELDS[k].name})}))]);
  jump.onchange=function(){var v=jump.value;jump.value='';if(v==='sky'){E.sel=null;panel();visits(false);map.flyTo(266.4,-28.9,360,overlay)}else if(PW.FIELDS[v]){var F=PW.FIELDS[v];if(F.processed){E.sel=null;panel();map.flyTo(F.ra,F.dec,.2,overlay)}else PW.goField(v)}};T.appendChild(jump);
  T.appendChild(h('span',{class:'sep'}));
  var bs=h('div',{class:'seg',role:'group','aria-label':'Band'});bs.appendChild(h('button',{'data-b':'rgb',text:'Colour',onclick:function(){stopP();setRGB()}}));
  D.forEach(function(d,i){bs.appendChild(h('button',{'data-b':i,text:d.id,title:d.lo.toFixed(2)+' to '+d.hi.toFixed(2)+' µm',style:'box-shadow:inset 0 -2px '+d.c,onclick:function(){stopP();setLayer(E.rgb?PW.detLayer(i):Math.floor(E.layer/17)===i?E.layer:PW.detLayer(i))}}))});T.appendChild(bs);
  var wl=h('input',{type:'range',id:'wl',min:0,max:101,step:1,value:E.layer,'aria-label':'Wavelength layer',style:'width:96px'});wl.oninput=function(){stopP();setLayer(+wl.value)};T.appendChild(wl);T.appendChild(h('span',{class:'t12',id:'wlT',style:'min-width:64px'}));
  T.appendChild(h('button',{class:'btn sm',id:'bPlay',onclick:playBands}));
  T.appendChild(h('span',{class:'grow'}));
  T.appendChild(h('button',{class:'btn sm',onclick:function(e){menu(e.currentTarget,[h('span',{class:'lab',text:'Image'}),
     chk('Automatic limits',function(){return map.auto},function(v){map.auto=v;map._settle=0;map.dirty()}),
     range('Brightness',.4,3,.05,function(){return map.gainMul},function(v){map.gainMul=v;map._settle=0}),range('Black level',-20,20,1,function(){return map.offAdd},function(v){map.offAdd=v;map._settle=0}),
     h('span',{class:'lab',text:'On the map'}),chk('Coordinate grid',function(){return E.ov.grid},function(v){E.ov.grid=v}),chk('Shared finds',function(){return E.ov.finds},function(v){E.ov.finds=v}),
     chk('Test fields',function(){return E.ov.tests},function(v){E.ov.tests=v}),chk('Your markers',function(){return E.ov.mine},function(v){E.ov.mine=v})])}},[PW.icon('layers','sm'),h('span',{text:'Display'})]));
  T.appendChild(h('button',{class:'btn sm',onclick:function(e){menu(e.currentTarget,[
     h('button',{class:'btn sm',onclick:function(){E.tool='marker';PW.toast('Click the map to place a marker')}},[PW.icon('pin','sm'),'Place a marker']),
     h('button',{class:'btn sm',onclick:function(){E.tool='ruler';E.rule=null;PW.toast('Click two points to measure their separation')}},[PW.icon('ruler','sm'),'Measure separation']),
     h('button',{class:'btn sm',onclick:function(){var c=$('#hq');if(c)c.focus()}},[PW.icon('search','sm'),'Go to coordinates'])])}},[PW.icon('tool','sm'),h('span',{text:'Tools'})]));
  T.appendChild(h('button',{class:'btn sm',onclick:function(e){var c=PW.deci(map.ra,map.dec).replace(/[°]/g,'').replace('−','-').replace(/\s+/,' ');menu(e.currentTarget,[
     h('button',{class:'btn sm',onclick:function(){try{var a=h('a',{href:$('#map',root).toDataURL('image/png'),download:'spherex-'+map.ra.toFixed(3)+'_'+map.dec.toFixed(3)+'.png'});document.body.appendChild(a);a.click();a.remove();PW.toast('PNG of the view downloaded')}catch(x){PW.toast('The browser blocked the image export')}}},['PNG of the view']),
     h('button',{class:'btn sm',onclick:function(){if(navigator.clipboard)navigator.clipboard.writeText(location.href);PW.toast('Link to this view copied')}},['Copy link to this view']),
     h('span',{class:'lab',text:'Other telescopes'}),
     h('a',{class:'link',target:'_blank',rel:'noopener',href:'https://irsa.ipac.caltech.edu/applications/finderchart/?objstr='+encodeURIComponent(c),text:'IRSA Finder Chart'}),
     h('a',{class:'link',target:'_blank',rel:'noopener',href:'https://aladin.cds.unistra.fr/AladinLite/?target='+encodeURIComponent(c)+'&fov='+Math.min(5,map.fov()).toFixed(2)+'&survey=P%2FallWISE%2Fcolor',text:'AllWISE in Aladin Lite'}),
     h('a',{class:'link',target:'_blank',rel:'noopener',href:'https://simbad.cds.unistra.fr/simbad/sim-coo?Coord='+encodeURIComponent(c)+'&Radius=2&Radius.unit=arcmin',text:'SIMBAD around the centre'})])}},[PW.icon('download','sm'),h('span',{text:'Export'})]));
  T.appendChild(h('button',{class:'btn sm quiet',onclick:PW.proof},['Proof']));
  T.appendChild(h('button',{class:'btn sm pri',id:'bShare',onclick:function(){var it=selItem(),p=E.sel?(E.sel.kind==='signal'?PW.sigPos(it.F,it.S,3):[E.sel.ra,E.sel.dec]):[map.ra,map.dec];
     PW.shareFind({ra:p[0],dec:p[1],field:E.sel&&E.sel.f,src:it&&it.S})}},['Share your find']));
  $('#vClose',el).appendChild(PW.icon('cross'));$('#vClose',el).onclick=function(){visits(false)};
  VMODES.forEach(function(m){$('#vModes',el).appendChild(h('button',{'data-vm':m[0],text:m[1],onclick:function(){stopV();E.vis.m=m[0];visits()}}))});
  $('#vPrev',el).appendChild(PW.icon('prev'));$('#vNext',el).appendChild(PW.icon('next'));
  $('#vPrev',el).onclick=function(){stopV();E.vis.m=E.vis.m==='stack'||E.vis.m==='rgb'?'play':E.vis.m;E.vis.v=(E.vis.v+3)%4;visits()};$('#vNext',el).onclick=function(){stopV();E.vis.m=E.vis.m==='stack'||E.vis.m==='rgb'?'play':E.vis.m;E.vis.v=(E.vis.v+1)%4;visits()};$('#vPlay',el).onclick=playV;
  (function(){var g=$('#vMx',el),v,b,d,x,y;for(v=0;v<4;v++){g.appendChild(s('text',{x:28+v*60+26,y:72,'text-anchor':'middle',class:'mxt'},VS[v].date.replace(/^\d+ /,'')));
    for(b=0;b<102;b++){d=Math.floor(b/17);x=28+v*60+4+(b/101)*44;y=60-Math.log(PW.WAVE[b]/.75)/Math.log(5/.75)*54;var c=s('circle',{cx:x,cy:y,r:1.6,fill:D[d].c,class:'vm-dot','data-v':v,'data-d':d});
      c.addEventListener('click',(function(vv,dd){return function(){stopV();E.vis.v=vv;E.vis.m='play';if(!E.rgb)setLayer(PW.detLayer(dd));else visits()}})(v,d));g.appendChild(c)}}
    g.appendChild(s('text',{x:22,y:10,'text-anchor':'end',class:'mxt'},'5 µm'));g.appendChild(s('text',{x:22,y:62,'text-anchor':'end',class:'mxt'},'0.75'))})();
  $('#cC',el).onclick=function(){E.sexa=!E.sexa;overlay()};
  $('#zIn',el).onclick=function(){map.zoomAt(1.6,map.W/2,map.H/2)};$('#zOut',el).onclick=function(){map.zoomAt(1/1.6,map.W/2,map.H/2)};
  /* the map */
  var cv=$('#map',el),stg=$('#stage',el);map=new PW.SkyMap(cv,{ra:266.4,dec:-28.9,layers:E.rgb?E.cl:[E.layer],onview:function(){overlay()}});map.interact(cv);
  var f0=q.f&&PW.FIELDS[q.f],p0;
  if(q.ra!=null&&!isNaN(+q.ra))map.setView(+q.ra,+q.dec,+q.fov||1);else if(f0){p0=q.s&&PW.src(q.f,q.s)?PW.sigPos(f0,PW.src(q.f,q.s),3):[f0.ra,f0.dec];map.setView(p0[0],p0[1],.3)}else map.setView(266.4,-28.9,360);
  if(f0&&q.s&&PW.src(q.f,q.s))E.sel={kind:'signal',f:q.f,id:q.s};
  cv.addEventListener('click',function(e){if(map._moved){map._moved=false;return}var r=cv.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,c=map.unproject(x,y),best=null,bd=14;if(!c)return;
    if(E.tool==='marker'){PW.store.set(function(t){t.markers.push({ra:c[0],dec:c[1]})});E.tool=null;PW.toast('Marker placed at '+PW.deci(c[0],c[1]));overlay();return}
    if(E.tool==='ruler'){E.rule=!E.rule||E.rule.length>1?[c]:[E.rule[0],c];if(E.rule.length>1)E.tool=null;overlay();return}
    items().forEach(function(it){var p=map.project(it.ra,it.dec);if(!p[2])return;var d=Math.hypot(p[0]-x,p[1]-y);if(d<bd){bd=d;best=it}});
    if(best&&best.kind==='signal')E.sel={kind:'signal',f:best.f,id:best.id};
    else if(best&&best.kind==='find'){var fp=PW.findPos(best.find);E.sel=best.find.field&&best.find.src&&PW.src(best.find.field,best.find.src)?{kind:'signal',f:best.find.field,id:best.find.src}:{kind:'spot',ra:fp[0],dec:fp[1],id:best.id}}
    else E.sel={kind:'spot',ra:c[0],dec:c[1],id:'spot'};
    panel();overlay();if(!$('#vis',root).hidden)visits()});
  cv.addEventListener('pointermove',function(e){var r=cv.getBoundingClientRect(),c=map.unproject(e.clientX-r.left,e.clientY-r.top);$('#cCur',el).textContent=c?'Cursor '+(E.sexa?PW.sexa(c[0],c[1]):PW.deci(c[0],c[1])):''});
  cv.addEventListener('pointerleave',function(){$('#cCur',el).textContent=''});
  resH=function(){map.resize()};addEventListener('resize',resH);
  if(window.ResizeObserver){this._ro=new ResizeObserver(function(){map.resize()});this._ro.observe(stg)}
  keyH=function(e){if(!root||/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)||e.metaKey||e.ctrlKey||e.altKey)return;var k=e.key,c;
    if(k==='/'){e.preventDefault();c=$('#hq');if(c)c.focus();return}
    if(k==='?'){var b=h('div',{});b.innerHTML='<dl class="kv"><dt>Drag, arrows</dt><dd>Move</dd><dt>Scroll, pinch, + and −</dt><dd>Zoom</dd><dt>Space</dt><dd>Play or pause the bands</dd><dt>1 to 6</dt><dd>Detector</dd><dt>[ and ]</dt><dd>Previous and next band</dd><dt>c</dt><dd>Colour</dd><dt>v</dt><dd>Visits at the selection</dd><dt>/</dt><dd>Search</dd></dl>';PW.modal('Keyboard shortcuts',b);return}
    var P=map.W/map.s/D2R*.12;
    if(k==='ArrowLeft'){map.setView(map.ra+P/Math.max(.2,Math.cos(map.dec*D2R)),map.dec)}else if(k==='ArrowRight'){map.setView(map.ra-P/Math.max(.2,Math.cos(map.dec*D2R)),map.dec)}
    else if(k==='ArrowUp')map.setView(map.ra,map.dec+P);else if(k==='ArrowDown')map.setView(map.ra,map.dec-P);
    else if(k==='+'||k==='=')map.zoomAt(1.6,map.W/2,map.H/2);else if(k==='-')map.zoomAt(1/1.6,map.W/2,map.H/2);
    else if(k===' '){playBands()}else if(/^[1-6]$/.test(k)){stopP();setLayer(PW.detLayer(+k-1))}else if(k==='c'){stopP();setRGB()}
    else if(k==='['){stopP();setLayer(E.layer-1)}else if(k===']'){stopP();setLayer(E.layer+1)}else if(k==='v'&&E.sel){visits(true)}else return;e.preventDefault()};
  document.addEventListener('keydown',keyH);
  ui();left();panel();overlay();if(q.tour)tour(0)},
 unmount:function(){stopP();stopV();if(map)map.destroy();removeEventListener('resize',resH);document.removeEventListener('keydown',keyH);if(this._ro)this._ro.disconnect();var o=$('.pop.menu');if(o)o.remove();clearTimeout(sync.t);root=null},
 refresh:function(){if(root){panel();overlay()}},
 search:function(q){var c=PW.parseCoord(q),n=q.toLowerCase().replace(/[^a-z0-9]/g,''),hit;
   if(c){E.sel={kind:'spot',ra:c[0],dec:c[1],id:'spot'};panel();map.flyTo(c[0],c[1],.5,overlay);return true}
   if(n.length<3){PW.toast('Type a name, or coordinates such as 291.364 10.476 or 19h25m27s +10d28m35s.');return false}
   hit=PW.JUMP.filter(function(k){return PW.FIELDS[k].name.toLowerCase().replace(/[^a-z0-9]/g,'').indexOf(n)>-1})[0];if(hit){var F=PW.FIELDS[hit];if(F.processed){map.flyTo(F.ra,F.dec,.2,overlay)}else PW.goField(hit);return true}
   hit=PW.SIGNALS().filter(function(o){return o.s.id.toLowerCase().replace(/[^a-z0-9]/g,'').indexOf(n)>-1})[0];if(hit){pickSignal(hit.f,hit.s.id,true);return true}
   /* any other name: ask the CDS name resolver */
   PW.toast('Looking up “'+q+'”…');
   fetch('https://cds.unistra.fr/cgi-bin/nph-sesame/-oI/A?'+encodeURIComponent(q)).then(function(r){return r.text()}).then(function(t){var m=/%J\s+([\d.]+)\s+([+-][\d.]+)/.exec(t);
     if(!m){PW.toast('No object called “'+q+'” in SIMBAD, NED or VizieR. Try coordinates.');return}var a=+m[1],b=+m[2];E.sel={kind:'spot',ra:a,dec:b,id:'spot'};panel();map.flyTo(a,b,.5,overlay);PW.toast(q+' · '+PW.deci(a,b))})
   .catch(function(){PW.toast('The name resolver did not answer. Try coordinates instead.')});return true}};

/* ---------- quick tour: four steps on Epsilon Indi B ---------- */
var TOUR=[['This is the real SPHEREx sky, the whole of it. Drag to move and scroll to zoom, like a map.',function(){E.sel=null;panel();map.flyTo(266.4,-28.9,360,overlay)}],
 ['We fly to Epsilon Indi B, a pair of brown dwarfs 12 light-years away, used here as a test object.',function(){PW.goField('epsindi')}],
 ['Each detector sees a different slice of infrared. Play bands steps through its 17 wavelengths.',function(){setLayer(PW.detLayer(4));if(!PW.still&&!playT)playBands()}],
 ['Visits at this position shows the time series. The data panel holds the pipeline’s readings.',function(){stopP();visits(true)}]];
function tour(i){var t=$('#tour',root);if(i<0||i>=TOUR.length){t.hidden=true;if(i>=TOUR.length){PW.store.set(function(s2){s2.toured=true});PW.xp(20,'First Light, quick tour finished')}return}
  TOUR[i][1]();t.hidden=false;t.innerHTML='';t.appendChild(h('span',{class:'lab',text:'Quick tour · step '+(i+1)+' of '+TOUR.length}));t.appendChild(h('p',{text:TOUR[i][0]}));
  t.appendChild(h('div',{class:'btns'},[h('button',{class:'btn quiet',onclick:function(){stopP();tour(-1)}},['Skip']),h('button',{class:'btn pri',onclick:function(){tour(i+1)}},[i===TOUR.length-1?'Finish':'Next'])]))}
})();
