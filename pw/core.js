/* Phantom Worlds core: data, local store, simulated sky. Global: PW
   PW.DET, PW.VISITS, PW.FIELDS, PW.JUMP, PW.src(fieldId, srcId), PW.frame(), PW.paint(), PW.spectrum(), PW.store, PW.h(), PW.icon() */
(function(){
'use strict';
var PW=window.PW={};

/* ---------- small DOM helpers ---------- */
PW.h=function(tag,attrs,kids){var e=document.createElement(tag),k;attrs=attrs||{};
  for(k in attrs){if(attrs[k]==null||attrs[k]===false)continue;if(k==='text')e.textContent=attrs[k];else if(k.slice(0,2)==='on')e.addEventListener(k.slice(2),attrs[k]);else e.setAttribute(k,attrs[k]===true?'':attrs[k])}
  (kids||[]).forEach(function(c){if(c==null||c===false)return;e.appendChild(typeof c==='string'?document.createTextNode(c):c)});return e};
PW.s=function(tag,attrs,text){var e=document.createElementNS('http://www.w3.org/2000/svg',tag),k;for(k in attrs)e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;return e};
PW.icon=function(name,cls){var s=PW.s('svg',{class:'ic'+(cls?' '+cls:''),viewBox:'0 0 24 24','aria-hidden':'true'});s.appendChild(PW.s('use',{href:'#i-'+name}));return s};
PW.$=function(q,r){return (r||document).querySelector(q)};
PW.$$=function(q,r){return [].slice.call((r||document).querySelectorAll(q))};
PW.still=matchMedia('(prefers-reduced-motion:reduce)').matches;

/* ---------- instrument ---------- */
PW.DET=[
 {id:'D1',lo:0.75,hi:1.11,c:'#A98BFF'},{id:'D2',lo:1.11,hi:1.64,c:'#63A9FF'},{id:'D3',lo:1.64,hi:2.42,c:'#4FD4C4'},
 {id:'D4',lo:2.42,hi:3.82,c:'#BEDF5A'},{id:'D5',lo:3.82,hi:4.42,c:'#FFB04D'},{id:'D6',lo:4.42,hi:5.00,c:'#FF6A5C'}];
PW.VISITS=[{date:'9 May 2025',season:'A',t:0},{date:'6 Nov 2025',season:'B',t:1},{date:'8 May 2026',season:'A',t:2},{date:'6 Nov 2026',season:'B',t:3}];
PW.PIX=6.15;
PW.TODAY='15 Nov 2026';
PW.STATUS={
 'Draft':['pencil','st-draft'],'Needs votes':['chat','st-votes'],'Queued':['hourglass','st-queued'],'In review':['lock','st-review'],
 'Accepted':['check','st-accepted'],'Closed':['cross','st-closed'],'Withdrawn':['out','st-withdrawn']};
PW.word=function(p){return p<50?'Unclassified':p<70?'Possibly':p<90?'Probably':'Very likely'};

/* ---------- sources and fields ----------
   Positions are pixel offsets from the field centre (east is left, north is up, so +x is west and +y is south).
   sed: relative brightness in D1..D6. kind drives the simulated spectrum. */
var WARM=[1,.92,.75,.5,.22,.12];
function star(id,x,y,f,g){return {id:id,name:'Gaia DR3 '+id,x:x,y:y,f:f,sed:WARM,kind:'star',status:'Known',simbad:'Star',
  best:['a main-sequence star',96],sn:Math.round(f*4),blend:3,pm:null,pmCat:g||'under 0.05',hist:[1,1,1]}}
PW.FIELDS={
 wise0855:{name:'WISE 0855−0714',blurb:'The coldest known brown dwarf',ra:133.78700,dec:-7.24400,seed:11,frames:261,det:[1,1,1,1,1,1],
  src:[{id:'W0855',name:'WISE 0855−0714',x:-1.7,y:.3,vx:.66,vy:-.06,f:9,sed:[0,0,0,.06,.6,1],kind:'cold',status:'Known',simbad:'Brown dwarf',
    best:['a Y-type brown dwarf',83],sn:11,blend:18,pm:['8.1','0.6',276],pmCat:'8.15',hist:[0,1,1],
    mol:[['Carbon dioxide dip at 4.27 µm','0.36','0.06'],['Carbon monoxide dip at 4.67 µm','0.26','0.07'],['Methane dip at 3.3 µm',null,'too faint below 3.8 µm']],
    facts:[['Temperature','285 K','Catalog','Luhman and Esplin 2016'],['Distance','2.28 pc','Catalog','Kirkpatrick et al. 2021']],
    why:['No light below 3.8 µm','Steep rise toward 5 µm','Dips where carbon dioxide and carbon monoxide absorb'],runner:'T-type brown dwarf, 12%'},
   star('5761985432616501376',1.1,.1,8)]},
 barnard:{name:"Barnard's Star",blurb:'The fastest-moving star in the sky',ra:269.45208,dec:4.69339,seed:23,frames:363,det:[1,1,1,1,1,1],
  src:[{id:'BARN',name:"Barnard's Star",x:.2,y:1.4,vx:-.07,vy:-.85,f:26,sed:[.5,.8,1,.8,.45,.3],kind:'mdwarf',status:'Known',simbad:'Red dwarf',
    best:['an M-type red dwarf',97],sn:140,blend:1,pm:['10.3','0.4',356],pmCat:'10.39',hist:[1,1,1],
    mol:[['Water band at 1.9 µm','0.21','0.02'],['Water band at 2.7 µm','0.18','0.03'],['Carbon monoxide at 2.3 µm','0.08','0.02']],
    facts:[['Distance','1.83 pc','Catalog','Gaia DR3'],['Type','M4','Catalog','SIMBAD']],
    why:['Smooth curve peaking near 1.6 µm','Shallow water bands of a cool star'],runner:'K-type star, 2%'}]},
 epsindi:{name:'Epsilon Indi B',blurb:'A pair of brown dwarfs next door',ra:331.04360,dec:-56.78270,seed:37,frames:465,det:[1,1,1,1,1,1],
  src:[{id:'EPSB',name:'Epsilon Indi B',x:-.9,y:.5,vx:.38,vy:.2,f:11,sed:[.03,.12,.35,.3,.7,.8],kind:'tdwarf',status:'Known',simbad:'Brown dwarf pair',
    best:['a T-type brown dwarf',78],sn:24,blend:4,pm:['4.6','0.5',124],pmCat:'4.70',hist:[1,1,1],
    mol:[['Methane dip at 3.3 µm','0.42','0.05'],['Water band at 2.7 µm','0.31','0.06'],['Carbon monoxide dip at 4.67 µm','0.12','0.05']],
    facts:[['Distance','3.64 pc','Catalog','Gaia DR3'],['Types','T1 and T6','Catalog','King et al. 2010']],
    why:['Deep methane dip at 3.3 µm','Peaks at 1.25 and 4.1 µm with a trough between'],runner:'L-type brown dwarf, 15%'}]},
 rwaur:{name:'RW Aurigae',blurb:'A young star that fades behind its own dust',ra:76.95630,dec:30.40140,seed:41,frames:335,det:[1,1,1,1,1,1],
  src:[{id:'RWAUR',name:'RW Aurigae',x:0,y:0,f:22,sed:[.6,.8,1,1,.9,.8],vary:[1,.45,.8,.3],kind:'yso',status:'Known',simbad:'T Tauri star',
    best:['a young star with a disc',88],sn:95,blend:2,pm:null,pmCat:'under 0.05',pmWhy:'the source varies between visits',hist:[1,1,1],
    mol:[['Water ice at 3.05 µm','0.14','0.03'],['Hydrogen line at 1.87 µm','0.22','0.04'],['Carbon monoxide at 2.3 µm','0.09','0.03']],
    facts:[['Change between visits','up to 3.3 times','Measured','4 visits']],
    why:['Flat, red curve of warm dust','Hydrogen emission lines'],runner:'Reddened giant, 7%'}]},
 rdra:{name:'R Draconis',blurb:'A pulsing giant near the ecliptic pole',ra:248.16700,dec:66.75500,seed:53,frames:2493,det:[1,1,1,1,1,1],
  src:[{id:'RDRA',name:'R Draconis',x:0,y:0,f:40,sed:[.3,.7,1,.9,.6,.5],vary:[.35,1,.6,.9],kind:'mira',status:'Known',simbad:'Mira variable',
    best:['a Mira variable',94],sn:310,blend:1,pm:null,pmCat:'under 0.05',pmWhy:'the source varies between visits',hist:[1,1,1],
    mol:[['Water band at 1.9 µm','0.38','0.02'],['Water band at 2.7 µm','0.44','0.02'],['Carbon monoxide at 2.3 µm','0.19','0.02']],
    facts:[['Period','245.6 d','Catalog','AAVSO VSX']],
    why:['Deep water bands of a cool giant','Brightness swings between visits'],runner:'Semi-regular variable, 5%'}]},
 atlas:{name:'Comet 3I/ATLAS',blurb:'An interstellar comet, seen in August 2025',ra:265.40000,dec:-19.60000,seed:67,frames:84,det:[1,1,1,1,1,1],moving:true,
  src:[{id:'3I',name:'3I/ATLAS',x:-5,y:2,vx:3.4,vy:-1.3,f:7,sed:[.25,.3,.3,.35,1,.5],kind:'comet',status:'Known',simbad:'Interstellar comet',
    best:['a comet with a carbon dioxide coma',91],sn:19,blend:6,pm:['moving target',null,null],pmCat:'ephemeris from JPL Horizons',hist:[0,0,1],
    mol:[['Carbon dioxide glow at 4.26 µm','0.81','0.07'],['Water at 2.7 µm','0.09','0.05'],['Carbon monoxide at 4.67 µm','0.11','0.06']],
    facts:[['Found','1 Jul 2025','Catalog','ATLAS survey, MPEC 2025-N12']],
    why:['Bright carbon dioxide emission at 4.26 µm','Fast motion across the field'],runner:'Asteroid, 6%'}]},
 aquila:{name:'Milky Way field in Aquila',blurb:'A crowded field, fully processed',ra:291.36412,dec:10.47633,seed:79,frames:612,det:[1,1,1,1,1,1],processed:true,nstars:70,
  src:[{id:'PW-0007',name:'PW-0007',x:-1.2,y:.9,vx:.62,vy:.14,f:5.5,sed:[0,0,0,.05,.55,1],kind:'cold',status:'Uncatalogued',auto:true,find:'F-0007',
    best:['a Y-type brown dwarf',41],capped:true,sn:7,blend:22,pm:['7.8','1.9',257],pmCat:null,hist:[0,0,1],tags:['beyond4','moved','nocat'],prio:.86,
    mol:[['Carbon dioxide dip at 4.27 µm','0.29','0.11'],['Carbon monoxide dip at 4.67 µm',null,'signal too low'],['Methane dip at 3.3 µm',null,'too faint below 3.8 µm']],
    why:['No light below 3.8 µm','Moves 3.9″ between visits'],runner:'Image artifact, 33%'},
   {id:'PW-0004',name:'PW-0004',x:9,y:-6,f:10,sed:[.08,.2,.5,.8,1,.95],kind:'yso',status:'Uncatalogued',auto:true,find:'F-0004',
    best:['a young star with a disc',62],sn:16,blend:9,pm:null,pmCat:null,hist:[0,1,1],tags:['ice','co2','red','nocat'],prio:.64,
    mol:[['Water ice at 3.05 µm','0.33','0.06'],['Carbon dioxide ice at 4.27 µm','0.27','0.07'],['Carbon monoxide at 4.67 µm','0.10','0.06']],
    why:['Ice bands at 3.05 and 4.27 µm','Very red curve'],runner:'Dusty giant, 24%'},
   {id:'PW-0003',name:'PW-0003',x:-11,y:-8,f:12,sed:[.5,.8,1,.9,.6,.5],vary:[1,.5,.9,.4],kind:'mira',status:'Unclassified',auto:true,find:'F-0003',
    best:['a variable star',58],sn:31,blend:12,pm:null,pmCat:'under 0.05',pmWhy:'the source varies between visits',hist:[1,1,1],tags:['changed'],prio:.52,
    mol:[['Water band at 1.9 µm','0.19','0.05'],['Water band at 2.7 µm','0.22','0.05'],['Carbon monoxide at 2.3 µm','0.07','0.04']],
    why:['Brightness changes by half between visits'],runner:'Eclipsing pair, 21%'},
   {id:'PW-0001',name:'PW-0001',x:12,y:9,vx:.2,vy:-.1,f:8,sed:[.03,.12,.4,.3,.7,.8],kind:'tdwarf',status:'Uncatalogued',auto:true,find:'F-0001',
    best:['a T-type brown dwarf',74],sn:14,blend:8,pm:['2.4','0.9',117],pmCat:null,hist:[0,1,1],tags:['ch4','moved','nocat'],prio:.71,
    mol:[['Methane dip at 3.3 µm','0.39','0.08'],['Water band at 2.7 µm','0.28','0.08'],['Carbon monoxide dip at 4.67 µm',null,'signal too low']],
    why:['Deep methane dip at 3.3 µm'],runner:'L-type brown dwarf, 18%'}]}
};
/* ---------- values from the pipeline's sample export of 15 Nov 2026 (replace the placeholders above) ---------- */
function up(f,o){var s=PW.FIELDS[f].src[0],k;for(k in o)s[k]=o[k]}
up('barnard',{sn:2201.53,rms:'0.284',pm:['12.873',null,356],pmCat:'10.39',noest:true,pred:['failed','8.882','1.24']});
up('epsindi',{sn:130.39,rms:'0.578',pm:['4.208',null,124],pmCat:'4.696',best:['',50],capped:true,novel:true,pred:['held','2.179','3.25'],runner:null,why:null,
  mol:[['Methane dip at 3.3 µm','1060','42'],['Water ice at 3.05 µm','955','76'],['Carbon dioxide at 4.26 µm','−12.5','2.2'],['Carbon monoxide at 4.67 µm','−8.1','3.2']],
  chg:[null,[.3235,111.65],[1.5017,80.29],[.4962,260.4],[.9159,464.99],[.7825,130.39]]});
up('rwaur',{sn:2984.86,rms:'0.856',pm:['2.083',null,null],noest:true,sat:'some'});
up('rdra',{sn:288.87,rms:'4.488',pm:null,pmWhy:'Gaia alignment RMS 4.488″ exceeds the 2.0″ limit',pmCat:'0.036',best:['a star',70],novel:true,sat:'all',runner:null,why:null,mol:[['Molecule readings',null,'source flagged variable between visits']]});
up('wise0855',{noest:true});
PW.FIELDS.epsindi.ra=331.04383;PW.FIELDS.epsindi.dec=-56.78269;PW.FIELDS.epsindi.frames=487;PW.FIELDS.rdra.ra=248.16762;PW.FIELDS.rdra.dec=66.75497;PW.FIELDS.rdra.frames=2588;
function sig(id,x,y,f,kind,o){var s={id:id,name:id,x:x,y:y,f:f,kind:kind,sed:kind==='cold'?[0,0,0,.05,.55,1]:kind==='star'?WARM:[.4,.8,1,.9,.6,.5],status:'Uncatalogued',auto:true,blend:10,pm:null,pmCat:null,hist:[0,1,1],tags:['nocat'],best:['',null]},k;for(k in o)s[k]=o[k];return s}
var VARI={status:'Known',simbad:'Star, Gaia DR3',tags:['changed'],pmWhy:'the source varies between visits',pmCat:'under 0.05',hist:[1,1,1],sigkind:'Variable source'};
function vr(o){var k,r={};for(k in VARI)r[k]=VARI[k];for(k in o)r[k]=o[k];return r}
PW.FIELDS.aquila.name='W1925 Galactic Plane';
PW.FIELDS.aquila.src=[
 sig('W1925-RES-3',-1.2,.9,9,'cold',{sn:81.92,preal:.9156,prio:.92,sigkind:'Leftover residual',find:'F-0007',type:'Unclassified'}),
 sig('W1925-RES-5',9,-6,10,'mira',{best:['an evolved giant star',null],sn:45.82,preal:.9344,prio:.78,sigkind:'Leftover residual',find:'F-0004',type:'Evolved giant'}),
 sig('W1925-RES-6',12,9,8,'mira',{best:['an evolved giant star',null],sn:44.3,preal:.9273,prio:.74,sigkind:'Leftover residual',find:'F-0001',type:'Evolved giant'}),
 sig('GaiaDR3-4295536881729300608',-11,-8,12,'mira',vr({sn:33,preal:.9991,prio:.6,find:'F-0003',type:'Unclassified',vary:[1,.5,.9,.4]})),
 sig('GaiaDR3-4295430121684377600',-14,10,11,'mira',vr({best:['an evolved giant star',null],sn:32.52,preal:1,prio:.55,type:'Evolved giant',vary:[1,.7,1.1,.6]}))];
PW.FIELDS.rwaur.name='RW Aurigae field';PW.FIELDS.rwaur.processed=true;
[['GaiaDR3-156431234433162368',48.33,.8873,8,-7],['GaiaDR3-156337294907839232',43.53,.9062,-9,6],['GaiaDR3-156430886538071552',41.55,.9238,11,8]].forEach(function(g){
  PW.FIELDS.rwaur.src.push(sig(g[0],g[3],g[4],9,'star',vr({best:['a star',null],sn:g[1],preal:g[2],prio:g[2]-.35,type:'Star',vary:[1,.75,1.05,.7]})))});
PW.SIGNALS=function(){var a=[];['aquila','rwaur'].forEach(function(f){PW.FIELDS[f].src.forEach(function(s){if(s.auto)a.push({f:f,s:s})})});return a.sort(function(x,y){return y.s.prio-x.s.prio})};
/* one sentence for a model estimate, following the spec's confidence words */
PW.estText=function(S){var b=S.best;if(S.noest)return 'Model estimate: not in the sample data';
  if(!b[0])return 'Unclassified · '+(b[1]==null?'probability not provided':b[1]+'%')+' · Estimated';
  if(b[1]==null)return b[0].replace(/^an? /,'').replace(/^./,function(c){return c.toUpperCase()})+' · probability not provided · Estimated';
  return (b[1]<50?'Unclassified':PW.word(b[1])+' '+b[0])+' · '+b[1]+'% · Estimated'};
PW.JUMP=['aquila','rwaur','barnard','epsindi','wise0855','rdra','atlas'];
PW.LIGHT=[['ch4','Methane dip'],['ice','Water ice'],['co2','CO2'],['co','CO'],['pah','3.3 µm glow'],['hyd','Hydrogen lines'],['red','Very red'],['beyond4','Seen only beyond 4 µm'],['moved','Moved between visits'],['changed','Changed brightness'],['nocat','Not in any catalog']];
PW.src=function(f,id){var F=PW.FIELDS[f];return F&&F.src.filter(function(s){return s.id===id})[0]};

/* ---------- simulated sky ---------- */
PW.rng=function(s){return function(){s=s+0x6D2B79F5|0;var t=Math.imul(s^s>>>15,1|s);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}};
Object.keys(PW.FIELDS).forEach(function(k){var F=PW.FIELDS[k],r=PW.rng(F.seed*977),i,x,y,n=F.nstars||34;F.id=k;F.bg=[];
  for(i=0;i<n;i++){x=(r()-.5)*56;y=(r()-.5)*56;if(F.src.some(function(s){return Math.abs(s.x-x)<3.5&&Math.abs(s.y-y)<3.5}))continue;F.bg.push({x:x,y:y,f:.8+Math.pow(r(),3)*(F.processed?14:9),gid:String(4e18+Math.floor(r()*9e17))})}});
/* frame(field, detector, visit, o): o = {n, cx, cy, follow:[vx,vy], test:{x,y,vx,vy,f}, model:'image'|'model'|'residual'} */
PW.frame=function(F,d,v,o){o=o||{};var n=o.n||24,cx=o.cx||0,cy=o.cy||0,a=new Float32Array(n*n),r=PW.rng(F.seed*131+d*17+v*7+1),i,
    fx=o.follow?o.follow[0]*v:0,fy=o.follow?o.follow[1]*v:0,mode=o.model||'image';
  if(mode!=='model')for(i=0;i<a.length;i++)a[i]=(r()+r()+r()-1.5)*1.1;
  function put(x,y,f){var px,py,dx,dy,X=x-cx-fx+n/2,Y=y-cy-fy+n/2;if(X<-4||Y<-4||X>n+4||Y>n+4)return;
    for(py=Math.max(0,Math.floor(Y-3));py<=Math.min(n-1,Math.ceil(Y+3));py++)for(px=Math.max(0,Math.floor(X-3));px<=Math.min(n-1,Math.ceil(X+3));px++){dx=px+.5-X;dy=py+.5-Y;a[py*n+px]+=f*Math.exp(-(dx*dx+dy*dy)/1.3)}}
  if(mode!=='residual')F.bg.forEach(function(s){put(s.x,s.y,s.f*WARM[d])});
  F.src.forEach(function(s){if(mode==='residual'&&s.status==='Known')return;if(mode==='model'&&s.status!=='Known')return;
    put(s.x+(s.vx||0)*v,s.y+(s.vy||0)*v,s.f*s.sed[d]*(s.vary?s.vary[v]:1))});
  if(o.test)put(o.test.x+o.test.vx*v,o.test.y+o.test.vy*v,o.test.f);
  return a};
PW.mix=function(list,w){var a=new Float32Array(list[0].length),i,j;for(j=0;j<list.length;j++)for(i=0;i<a.length;i++)a[i]+=list[j][i]*w[j];return a};
/* cividis-like colour-blind-safe ramp, 5 stops */
var CIV=[[0,32,76],[65,77,107],[124,123,120],[188,175,111],[255,233,69]];
/* paint(canvas, [grey] | [r,g,b], o): o = {signed, lo, hi, invert, cmap} */
PW.paint=function(cv,ch,o){o=o||{};var n=Math.round(Math.sqrt(ch[0].length)),c,im,p,i,j,v,t,k,lo=o.lo==null?-1.3:o.lo,hi=o.hi==null?26:o.hi;
  if(cv.width!==n)cv.width=cv.height=n;c=cv.getContext('2d');im=c.createImageData(n,n);p=im.data;
  for(i=0;i<n*n;i++){if(o.mask!=null&&ch[0][i]>o.mask){p[i*4]=52;p[i*4+1]=38;p[i*4+2]=40;p[i*4+3]=255;continue}for(j=0;j<3;j++){v=ch[ch.length===3?j:0][i];
      t=o.signed?.5+v/26:Math.asinh(Math.max(0,v-lo)/1.6)/Math.asinh(Math.max(1,hi-lo)/1.6);t=t<0?0:t>1?1:t;if(o.invert)t=1-t;
      if(o.cmap&&ch.length===1){k=Math.min(3,Math.floor(t*4));v=CIV[k][j]+(CIV[k+1][j]-CIV[k][j])*(t*4-k)}else v=t*255;p[i*4+j]=v}p[i*4+3]=255}
  c.putImageData(im,0,0)};
/* spectrum(source) -> 102 points {w, f, e, ul, d} */
PW.spectrum=function(s){var r=PW.rng((s.f*1000|0)+s.id.length*31),E=[.75,1.11,1.64,2.42,3.82,4.42,5],out=[],d,i,w,f,e,g=function(c,wd){return Math.exp(-Math.pow((w-c)/wd,2))};
  for(d=0;d<6;d++)for(i=0;i<17;i++){w=E[d]+(E[d+1]-E[d])*(i+.5)/17;
    if(s.kind==='cold')f=w<3.72?0:18+430*Math.pow((w-3.6)/1.4,2.1)*(1-.36*g(4.27,.06)-.26*g(4.67,.07));
    else if(s.kind==='tdwarf')f=(260*g(1.25,.18)+190*g(1.6,.14)+150*g(2.1,.2)+330*g(4.1,.42)+40)*(1-.42*g(3.3,.16)-.3*g(2.7,.14));
    else if(s.kind==='yso')f=(120+95*(w-.75))*(1-.33*g(3.05,.14)-.27*g(4.27,.06))+60*g(1.87,.03);
    else if(s.kind==='comet')f=70+40*g(1.2,.6)+520*g(4.26,.09)+50*g(2.7,.1);
    else if(s.kind==='mira')f=(900*Math.exp(-Math.pow((w-1.9)/1.5,2))+160)*(1-.38*g(1.9,.1)-.44*g(2.7,.13)-.19*g(2.3,.05));
    else f=(s.kind==='mdwarf'?1100:420)*Math.pow(w/1.6,-1.6)*Math.exp(-Math.pow(.9/w,3))*(1-.2*g(1.9,.09)-.18*g(2.7,.11));
    f*=s.f/9;e=6+f*.05;if(f<12){out.push({w:w,ul:8+r()*8,d:d})}else out.push({w:w,f:f*(1+(r()-.5)*.08),e:e,d:d})}
  return out};

/* ---------- local store (this browser only) ---------- */
var KEY='pw-new1',mem=null,subs=[];
var SEED={user:null,role:'guest',labs:null,xp:0,saved:[],markers:[],following:[],voted:{},toured:false,note:[],
 finds:[
  {id:'F-0007',title:'Bright residual left after known sources are removed',type:'Unclassified',source:'Auto-detected',finder:null,status:'Needs votes',up:6,down:1,need:10,field:'aquila',src:'W1925-RES-3',made:'14 Nov 2026',
   notes:'Flagged as a leftover residual in the W1925 field after known sources were removed. The estimate that it is real and not an artifact is 92%. S/N 81.92. The type model returns Unclassified.',comments:[]},
  {id:'F-0004',title:'Residual with the spectrum of an evolved giant',type:'Evolved giant',source:'Auto-detected',finder:null,status:'Queued',up:12,down:2,need:10,field:'aquila',src:'W1925-RES-5',made:'9 Nov 2026',
   notes:'Leftover residual in the W1925 field. The estimate that it is real is 93%. S/N 45.82. The type model returns Evolved giant star.',comments:[]},
  {id:'F-0003',title:'Brightness halves and recovers across four visits',type:'Variable star',source:'Auto-detected',finder:null,status:'In review',up:15,down:1,need:10,field:'aquila',src:'GaiaDR3-4295536881729300608',made:'2 Nov 2026',
   notes:'Catalogued Gaia DR3 star flagged as a variable source. The estimate that the change is real is 99.9%. S/N 33.',comments:[]},
  {id:'F-0001',title:'Second residual matching an evolved giant',type:'Evolved giant',source:'Auto-detected',finder:null,status:'Accepted',up:21,down:0,need:10,field:'aquila',src:'W1925-RES-6',made:'20 Oct 2026',tags:['Ready to report'],
   notes:'Leftover residual in the W1925 field. The estimate that it is real is 93%. S/N 44.3. The type model returns Evolved giant star.',comments:[]},
  {id:'F-0006',title:'Carbon dioxide glow around a fast mover',type:'Comet',source:'Auto-detected',finder:null,status:'Closed',reason:'Known object',up:11,down:0,need:10,field:'atlas',src:'3I',made:'18 Aug 2025',
   notes:'Matches Comet 3I/ATLAS in the JPL Horizons ephemeris.',comments:[]},
  {id:'F-0005',title:'Cold source stepping west past a background star',type:'Y-type brown dwarf',source:'Auto-detected',finder:null,status:'Closed',reason:'Known object',up:14,down:0,need:10,field:'wise0855',src:'W0855',made:'12 Nov 2025',
   notes:'Matches WISE 0855−0714 in SIMBAD once its catalog motion is applied.',comments:[]}]};
function load(){if(mem)return mem;try{mem=JSON.parse(localStorage.getItem(KEY))}catch(e){}if(!mem||!mem.finds)mem=JSON.parse(JSON.stringify(SEED));return mem}
PW.store={get:load,
 set:function(fn){fn(load());try{localStorage.setItem(KEY,JSON.stringify(mem))}catch(e){}subs.forEach(function(f){f(mem)})},
 on:function(f){subs.push(f)},
 reset:function(){mem=JSON.parse(JSON.stringify(SEED));try{localStorage.removeItem(KEY)}catch(e){}subs.forEach(function(f){f(mem)})},
 find:function(id){return load().finds.filter(function(f){return f.id===id})[0]},
 findFor:function(field,src){return load().finds.filter(function(f){return f.field===field&&f.src===src&&f.status!=='Draft'&&f.status!=='Withdrawn'})[0]}};
PW.LEVELS=[['Alnitak','#9BB0FF',0],['Rigel','#AABFFF',50],['Vega','#F8F7FF',150],['Procyon','#F8F7FF',300],['The Sun','#FFF4EA',500],['Arcturus','#FFD2A1',750],["Barnard's Star",'#FFB04D',1050],['Luhman 16','#B4402E',1400],['Epsilon Indi B','#8A2A1F',1800],['WISE 0855','#0B0B0D',2300]];
PW.level=function(xp){var i=0;while(i<9&&xp>=PW.LEVELS[i+1][2])i++;return i};
PW.xp=function(n,why){PW.store.set(function(s){s.xp+=n});PW.toast('+'+n+' XP · '+why)};
PW.toast=function(msg){var t=PW.$('#toast');t.textContent=msg;t.hidden=false;clearTimeout(PW._tt);PW._tt=setTimeout(function(){t.hidden=true},3600)};
})();
