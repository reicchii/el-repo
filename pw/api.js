/* Phantom Worlds API adapter.
   Connects the interface to the FastAPI backend. Nothing here changes layout, copy
   or styling: every hook is additive, and every call falls back to the interface's
   own demo data when the server is unreachable.
   Endpoints used:
     GET  /api/v1/finds                    community finds
     POST /api/v1/finds                    share a find
     POST /api/v1/finds/{id}/vote          votes
     POST /api/v1/finds/{id}/comment       comments
     POST /api/v1/finds/{id}/assign        Labs claim
     POST /api/v1/finds/{id}/decide        Labs decision
     GET  /api/ml/predict/{field}/{src}    M1 preal, M2 type, M3 novelty
     GET  /api/v1/targets/{target}         molecule readings + 102-band spectrum
     GET  /api/v1/cutout/{field}/{src}     raw and 4x oversampled frames
*/
(function(){
'use strict';
var PW=window.PW;
if(!PW)return;

/* ---------- base ---------- */
var BASE=(function(){
  if(location.protocol==='file:')return 'http://127.0.0.1:8000';
  return location.origin&&location.origin!=='null'?location.origin:'http://127.0.0.1:8000';
})();
PW.API_BASE=BASE;
PW.API_LIVE=null;           /* null = not probed yet, true/false after */

function url(p){return BASE+p}

function getJSON(p,ms){
  var ctl=typeof AbortController!=='undefined'?new AbortController():null;
  var t=setTimeout(function(){if(ctl)ctl.abort()},ms||12000);
  return fetch(url(p),{credentials:'same-origin',signal:ctl?ctl.signal:undefined})
    .then(function(r){
      if(!r.ok)throw new Error('HTTP '+r.status);
      return r.text().then(function(t){return t?JSON.parse(t):null});
    })
    .then(function(d){clearTimeout(t);PW.API_LIVE=true;return d})
    .catch(function(e){clearTimeout(t);if(PW.API_LIVE===null)PW.API_LIVE=false;throw e});
}

function postJSON(p,body){
  return fetch(url(p),{method:'POST',credentials:'same-origin',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
    .then(function(r){return r.text().then(function(t){
      var d=null;try{d=t?JSON.parse(t):null}catch(e){d=t}
      if(!r.ok){var m=(d&&d.detail)||String(t||'').slice(0,160)||('HTTP '+r.status);var e2=new Error(m);e2.status=r.status;e2.body=d;throw e2}
      return d})});
}

/* ---------- field / target resolution ---------- */
var FIELD_TARGET={wise0855:'WISE_0855',barnard:'Barnards_Star',epsindi:'Epsilon_Indi_B',rwaur:'RW_Aurigae',rdra:'R_Draconis'};
var SOURCE_ALIAS={W0855:'WISE_0855',BARN:'Barnards_Star',EPSB:'Epsilon_Indi_B',RWAUR:'RW_Aurigae',RDRA:'R_Draconis'};

PW.API={
  targetFor:function(field,src){return SOURCE_ALIAS[src]||FIELD_TARGET[field]||null},
  get:getJSON,post:postJSON,

  health:function(){return getJSON('/health',6000)},
  finds:function(){return getJSON('/api/v1/finds')},

  createFind:function(f){
    return postJSON('/api/v1/finds',{id:String(f.id),title:String(f.title||'Untitled'),type:String(f.type||'Not sure'),
      source:String(f.source||'Community'),finder:f.finder||null,status:String(f.status||'Needs votes'),
      field:String(f.field||'spot'),src:String(f.src||'spot'),notes:String(f.notes||'')});
  },

  vote:function(id,dir,user){return postJSON('/api/v1/finds/'+encodeURIComponent(id)+'/vote',{direction:dir,user:user||'Citizen Explorer'})},
  comment:function(id,by,text){return postJSON('/api/v1/finds/'+encodeURIComponent(id)+'/comment',{by:by||'Citizen Explorer',text:String(text)})},
  assign:function(id,reviewer){return postJSON('/api/v1/finds/'+encodeURIComponent(id)+'/assign',{reviewer:reviewer||'Labs reviewer'})},
  decide:function(id,decision,reviewer,reason,comment){
    return postJSON('/api/v1/finds/'+encodeURIComponent(id)+'/decide',
      {decision:decision,reason:reason||null,comment:comment||null,reviewer:reviewer||'Labs reviewer'});
  },

  /* The ML and target endpoints load models on first use, which can take most of a
     minute on a cold server.  A short timeout there would abort the very requests the
     panel needs, so these two get a long budget and the map/finds calls stay short. */
  ml:function(field,src){return getJSON('/api/ml/predict/'+encodeURIComponent(field)+'/'+encodeURIComponent(src),120000)},
  target:function(name){return getJSON('/api/v1/targets/'+encodeURIComponent(name),120000)},

  /* zoom: sky | field | source | pixel.  source and pixel return the 4x oversampled grid. */
  cutout:function(field,src,zoom,os,size){
    var q='/api/v1/cutout/'+encodeURIComponent(field)+'/'+encodeURIComponent(src)+'?zoom='+encodeURIComponent(zoom||'field');
    if(os)q+='&os='+os;
    if(size)q+='&size='+size;
    return getJSON(q,20000);
  }
};

/* ---------- caches ---------- */
var MCACHE={};      /* field|src -> {ml, mol, spectrum} */
var CCACHE={};      /* field|src|zoom -> cutout payload */
var PENDING={};

/* ---------- molecule rows: backend readings -> interface [label, value, error] ---- */
var MOL_LABEL={
  H2O:'Water ice at 3.05 µm',
  CH4:'Methane dip at 3.3 µm',
  CO2:'Carbon dioxide at 4.27 µm',
  CO:'Carbon monoxide at 4.67 µm'
};

function rowsFromReadings(readings){
  if(!readings||!readings.length)return null;
  var out=[];
  readings.forEach(function(r){
    var lab=MOL_LABEL[r.molecule]||((r.feature_label||r.molecule||'Reading')+' at '+(r.wavelength_um!=null?r.wavelength_um+' µm':''));
    if(r.value==null){
      out.push([lab,null,(r.refusal_reason||'no signal above the noise in this band')]);
      return;
    }
    var unc=null;
    if(r.error_16_84&&r.error_16_84.length===2){
      unc=(Math.abs(r.error_16_84[1]-r.error_16_84[0])/2).toFixed(2);
    }
    out.push([lab,String(Math.round(r.value*100)/100),unc]);
  });
  return out.length?out:null;
}

/* the interface expects {w,f,e,d}; the backend sends real flux per band */
function spectrumFromBands(bands){
  if(!bands||!bands.length)return null;
  var out=[];
  for(var i=0;i<bands.length;i++){
    var b=bands[i];
    if(!b||b.wavelength_um==null)continue;
    var d=Math.max(0,Math.min(5,Math.floor(i/17)));
    if(b.flux_mjy==null||!b.covered){out.push({w:b.wavelength_um,ul:Math.max(1,(b.flux_error_mjy||6))*4,d:d});continue}
    out.push({w:b.wavelength_um,f:b.flux_mjy,e:b.flux_error_mjy||Math.max(0.5,b.flux_mjy*0.05),d:d});
  }
  return out.length?out:null;
}

/* ---------- hydration ---------- */
var HYDRATING=false;

function applyML(field,src,ml){
  var S=PW.src&&PW.src(field,src);
  if(!S||!ml)return false;
  var changed=false;
  if(ml.noest){
    if(S.noest!==true){S.noest=true;changed=true}
    return changed;
  }
  if(ml.preal!=null&&S.preal!==ml.preal){S.preal=ml.preal;changed=true}
  if(ml.best&&ml.best.length===2&&!S.noest){
    var b=[ml.best[0]||'',ml.best[1]];
    if(!S.best||S.best[0]!==b[0]||S.best[1]!==b[1]){S.best=b;changed=true}
  }
  if(ml.runner!=null&&S.runner!==ml.runner){S.runner=ml.runner;changed=true}
  if(ml.novel!=null&&S.novel!==ml.novel){S.novel=ml.novel;changed=true}
  if(ml.prio!=null&&S.prio!==ml.prio){S.prio=ml.prio;changed=true}
  if(ml.tags&&ml.tags.length){S.tags=ml.tags.slice();changed=true}
  if(ml.deciding_bands&&ml.deciding_bands.length){S.why=ml.deciding_bands.slice();changed=true}
  return changed;
}

var hydrated=null;

function hydrate(){
  /* one run only, but every caller gets the same promise: a second call must wait
     for the first to finish rather than resolve early with nothing loaded */
  if(hydrated)return hydrated;
  HYDRATING=true;
  var jobs=[];

  /* 1. community finds already on the server */
  jobs.push(PW.API.finds().then(function(list){
    if(!list||!list.length)return false;
    PW.store.set(function(t){
      var byId={};t.finds.forEach(function(f){byId[f.id]=1});
      list.forEach(function(f){
        if(byId[f.id])return;
        t.finds.push({id:f.id,title:f.title,type:f.type,source:f.source||'Community',finder:f.finder||'Community',
          status:f.status||'Needs votes',up:f.up||0,down:f.down||0,need:f.need||10,field:f.field,src:f.src,
          made:f.made||PW.TODAY,notes:f.notes||'',comments:f.comments||[]});
      });
    });
    return true;
  }).catch(function(){return false}));

  /* 2. every modelled source: M1/M2/M3, molecule readings, 102-band spectrum.
     The model endpoints are heavy and load on first use, so these run a few at a
     time instead of all at once; a single failure only costs that one source. */
  var pairs=[];
  Object.keys(PW.FIELDS).forEach(function(f){
    (PW.FIELDS[f].src||[]).forEach(function(s){pairs.push([f,s.id])});
  });
  pairs=pairs.filter(function(p){return PW.API.targetFor(p[0],p[1])});

  function one(p){
    var f=p[0],s=p[1],tgt=PW.API.targetFor(f,s),k=f+'|'+s;
    return Promise.all([
      PW.API.ml(f,s).then(function(ml){
        (MCACHE[k]||(MCACHE[k]={})).ml=ml;
        return applyML(f,s,ml);
      }).catch(function(){return false}),
      PW.API.target(tgt).then(function(t){
        var c=MCACHE[k]||(MCACHE[k]={});
        var rows=rowsFromReadings(t.molecules&&t.molecules.readings);
        var spec=spectrumFromBands(t.readings&&t.readings.spectral_bands);
        if(rows)c.mol=rows;
        if(spec)c.spectrum=spec;
        var S=PW.src&&PW.src(f,s),changed=false;
        if(S&&rows&&rows.length){S.mol=rows;changed=true}
        if(S&&t.astrometry){
          var a=t.astrometry;
          if(a.matched&&a.pm_total_mas_yr!=null){
            S.pm=[(a.pm_total_mas_yr/1000).toFixed(3),null,S.pm&&S.pm[2]!=null?S.pm[2]:null];
            changed=true;
          }
        }
        return changed;
      }).catch(function(){return false})
    ]).then(function(r){return r[0]===true||r[1]===true});
  }

  /* a small worker pool: three at a time keeps a cold server responsive */
  var results=[];
  function worker(){
    if(!pairs.length)return Promise.resolve();
    var p=pairs.shift();
    return one(p).then(function(r){results.push(r);return worker()});
  }
  for(var w=0;w<Math.min(3,pairs.length);w++)jobs.push(worker());

  hydrated=Promise.all(jobs).then(function(res){
    HYDRATING=false;
    return res.some(function(x){return x===true});
  }).catch(function(){HYDRATING=false;return false});
  return hydrated;
}

/* ---------- real frames from the backend cutout ---------- */
var FRAMES={};

PW.prefetchCutout=function(field,src,zoom){
  if(!PW.API.targetFor(field,src))return Promise.resolve(null);
  var k=field+'|'+src+'|'+(zoom||'source');
  if(CCACHE[k])return Promise.resolve(CCACHE[k]);
  if(PENDING[k])return Promise.resolve(null);
  PENDING[k]=true;
  return PW.API.cutout(field,src,zoom||'source',4,32).then(function(d){
    CCACHE[k]=d;delete PENDING[k];repaint();return d;
  }).catch(function(){delete PENDING[k];return null});
};

/* the backend grid for a field, only when that field has a single modelled source */
function gridFor(F){
  if(!F||!F.id||F.id==='spot')return null;
  var srcs=F.src||[];
  if(srcs.length!==1)return null;
  var d=CCACHE[F.id+'|'+srcs[0].id+'|source'];
  if(!d||!d.grid||!d.grid.values)return null;
  return d;
}

function resample(vals,n,size){
  var out=new Float32Array(n*n),i,j,sx=size/n,sy=size/n,sum,ct,y,x,yy,xx,v;
  for(j=0;j<n;j++)for(i=0;i<n;i++){
    sum=0;ct=0;
    for(yy=Math.floor(j*sy);yy<Math.min(size,Math.ceil((j+1)*sy));yy++)
      for(xx=Math.floor(i*sx);xx<Math.min(size,Math.ceil((i+1)*sx));xx++){
        y=yy;x=xx;v=vals[y*size+x];
        if(v!=null&&isFinite(v)){sum+=v;ct++}
      }
    out[j*n+i]=ct?sum/ct:0;
  }
  return out;
}

var _frame=PW.frame;
PW.frame=function(F,d,v,o){
  o=o||{};
  var g=gridFor(F);
  if(g){
    var size=g.size_render||Math.round(Math.sqrt(g.grid.values.length));
    return resample(g.grid.values,o.n||24,size);
  }
  return _frame.apply(PW,arguments);
};

/* remember the last paint so a cutout that lands late can repaint the same view */
var _paint=PW.paint,lastPaint=null;
PW.paint=function(cv,ch,o){
  lastPaint={cv:cv,ch:ch,o:o};
  return _paint.apply(PW,arguments);
};
function repaint(){
  if(!lastPaint||!lastPaint.cv||!lastPaint.cv.isConnected)return;
  try{_paint(lastPaint.cv,lastPaint.ch,lastPaint.o)}catch(e){}
}

/* ---------- 102-band spectrum: real flux where the backend has it ---------- */
var _spectrum=PW.spectrum;
PW.spectrum=function(s){
  if(s&&s.id){
    var hit=null;
    Object.keys(MCACHE).some(function(k){
      var c=MCACHE[k];
      if(c&&c.spectrum&&k.split('|')[1]===s.id){hit=c.spectrum;return true}
      return false;
    });
    if(hit)return hit;
  }
  return _spectrum.apply(PW,arguments);
};

/* ---------- molecule rows: prefer the backend readings ---------- */
var _molRows=PW.molRows;
PW.molRows=function(S){
  var rows=_molRows.apply(PW,arguments);
  if(!S||!S.id)return rows;

  /* the data panel calls this with the selected source, so it is the reliable
     place to learn what is on screen and refresh the close-up readout */
  var found=null;
  Object.keys(PW.FIELDS).some(function(f){
    var hit=(PW.FIELDS[f].src||[]).filter(function(x){return x.id===S.id})[0];
    if(hit){found={field:f,id:S.id};return true}
    return false;
  });
  if(found){
    lastSel=found;
    if(!CCACHE[found.field+'|'+found.id+'|source']&&PW.API.targetFor(found.field,found.id)){
      PW.prefetchCutout(found.field,found.id,'source');
    }
    setTimeout(cuReadout,0);
  }

  var hit=null;
  Object.keys(MCACHE).some(function(k){
    var c=MCACHE[k];
    if(c&&c.mol&&k.split('|')[1]===S.id){hit=c.mol;return true}
    return false;
  });
  if(!hit)return rows;
  var byLab={},seen={};
  hit.forEach(function(h){byLab[h[0]]=h});
  var out=rows.map(function(r){
    var h=byLab[r[0]];
    if(h){seen[r[0]]=1;return h}
    return r;
  });
  hit.forEach(function(h){if(!seen[h[0]])out.push(h)});
  return out;
};

/* ---------- shares: a guest keeps their place ---------- */
var _shareFind=PW.shareFind;
PW.shareFind=function(o){
  o=o||{};
  if(!PW.store.get().user){
    PW.store.set(function(t){t.user='Citizen Explorer';t.role='member'});
  }
  if(o.ra==null&&o.dec==null){
    var F=o.field&&PW.FIELDS[o.field];
    if(F){o.ra=F.ra;o.dec=F.dec}
  }
  return _shareFind.call(PW,o);
};

/* ---------- target selector inside the share modal ---------- */
var _modal=PW.modal;
PW.modal=function(title,body,foot,wide){
  var close=_modal.call(PW,title,body,foot,wide);
  if(title!=='Share your find'||!close||!close.el)return close;
  try{
    var m=close.el;

    /* after a successful share the interface offers a link; go straight there instead,
       so submitting never leaves the person on a blank map */
    var live=m.querySelector('a[href^="#/discussions/"]');
    if(live&&/Your find is live/i.test(m.textContent||'')){
      var target=live.getAttribute('href');
      setTimeout(function(){try{close()}catch(e){};location.hash=target},60);
      return close;
    }

    var raIn=m.querySelector('input[placeholder="291.36412"]');
    var deIn=m.querySelector('input[placeholder="+10.47633"]');
    if(!raIn||!deIn)return close;
    var bodyEl=m.children[1];
    if(!bodyEl)return close;
    var sel=PW.h('select',{class:'select','aria-label':'Target'});
    sel.appendChild(PW.h('option',{value:'',text:'Choose a target…'}));
    Object.keys(PW.FIELDS).forEach(function(f){
      var F=PW.FIELDS[f],grp=PW.h('optgroup',{label:F.name});
      (F.src||[]).forEach(function(s){
        grp.appendChild(PW.h('option',{value:f+'|'+s.id,text:s.name+' · '+F.name}));
      });
      sel.appendChild(grp);
    });
    sel.onchange=function(){
      var v=sel.value;
      if(!v)return;
      var f=v.split('|')[0],sid=v.split('|')[1];
      var F=PW.FIELDS[f],S=PW.src&&PW.src(f,sid);
      if(!F||!S)return;
      var p=PW.sigPos?PW.sigPos(F,S,3):[F.ra,F.dec];
      raIn.value=p[0].toFixed(5);
      deIn.value=(p[1]>=0?'+':'')+p[1].toFixed(5);
      raIn.dispatchEvent(new Event('input',{bubbles:true}));
      deIn.dispatchEvent(new Event('input',{bubbles:true}));
    };
    bodyEl.insertBefore(PW.h('label',{class:'field'},[PW.h('span',{text:'Target'}),sel]),bodyEl.firstChild);
  }catch(e){}
  return close;
};

/* ---------- writes made in the interface go to the backend ---------- */
var _set=PW.store.set,SYNCED={};
PW.store.set=function(fn){
  var before=PW.store.get();
  var snap=JSON.stringify(before.finds||[]);
  var res=_set.apply(PW.store,arguments);
  var after=PW.store.get();
  if(HYDRATING||!PW.API_LIVE)return res;
  if(snap===JSON.stringify(after.finds||[]))return res;
  try{syncFinds(before.finds||[],after.finds||[])}catch(e){}
  return res;
};

function syncFinds(before,after){
  var was={};before.forEach(function(f){was[f.id]=f});
  after.forEach(function(f){
    var old=was[f.id];
    var st=SYNCED[f.id]||(SYNCED[f.id]={});
    if(!old){
      if(st.created)return;
      st.created=true;
      PW.API.createFind(f).catch(function(){st.created=false});
      return;
    }
    if((f.up||0)!==(old.up||0)||(f.down||0)!==(old.down||0)){
      if(st.voting)return;
      st.voting=true;
      var dir=(f.up||0)>(old.up||0)?1:-1;
      PW.API.vote(f.id,dir,PW.store.get().user).catch(function(){}).then(function(){st.voting=false});
    }
    var oc=(old.comments||[]).length,nc=(f.comments||[]).length;
    if(nc>oc){
      var c=(f.comments||[])[nc-1];
      if(c&&!st['c'+nc]){
        st['c'+nc]=true;
        PW.API.comment(f.id,c.by,c.text).catch(function(){delete st['c'+nc]});
      }
    }
    if(f.status!==old.status&&f.status==='In review'&&!st.assigned){
      st.assigned=true;
      PW.API.assign(f.id,PW.store.get().user).catch(function(){});
    }
    if(f.status!==old.status&&(f.status==='Accepted'||f.status==='Closed')&&!st['d'+f.status]){
      st['d'+f.status]=true;
      PW.API.decide(f.id,f.status,PW.store.get().user,f.reason,'').catch(function(){});
    }
  });
}

/* ---------- close-up readout ---------- */
PW.closeupFor=function(){
  var c={};
  Object.keys(CCACHE).forEach(function(k){if(CCACHE[k]&&CCACHE[k].mode)c[k]=CCACHE[k]});
  return c;
};

/* the close-up currently backing a source, or null when the backend has no frame */
PW.closeupOf=function(field,src){
  return CCACHE[field+'|'+src+'|source']||null;
};

/* the source the data panel is showing; set by the molRows hook below */
var lastSel=null;
PW.selectedSource=function(){return lastSel};

/* say which rendering is on screen: the raw frame, or the 4x oversampled model */
function cuReadout(){
  var box=document.getElementById('voCU');
  if(!box)return;
  if(!lastSel){box.hidden=true;box.textContent='';return}
  var d=PW.closeupOf(lastSel.field,lastSel.id);
  if(!d){box.hidden=true;box.textContent='';return}
  box.hidden=false;
  box.textContent=d.label+' · '+d.pixel_arcsec_render+'″ per pixel · '+
    (d.origin==='Estimated'?'model image, not measured pixels':d.origin);
}

function installReadout(){
  var stage=document.getElementById('stage');
  if(!stage||document.getElementById('voCU'))return;
  var box=document.createElement('div');
  box.className='vo cu';
  box.id='voCU';
  box.hidden=true;
  box.setAttribute('role','status');
  stage.appendChild(box);
}

var _mount2=PW.explore&&PW.explore.mount;
if(_mount2){
  PW.explore.mount=function(){
    var r=_mount2.apply(PW.explore,arguments);
    setTimeout(function(){installReadout();cuReadout()},80);
    return r;
  };
}

var _refresh2=PW.explore&&PW.explore.refresh;
if(_refresh2){
  PW.explore.refresh=function(){
    var r=_refresh2.apply(PW.explore,arguments);
    installReadout();cuReadout();
    return r;
  };
}

/* prefetch the close-up for every modelled source once the explorer mounts */
var _mountExplore=PW.explore&&PW.explore.mount;
if(_mountExplore){
  PW.explore.mount=function(){
    var r=_mountExplore.apply(PW.explore,arguments);
    setTimeout(function(){
      Object.keys(PW.FIELDS).forEach(function(f){
        (PW.FIELDS[f].src||[]).forEach(function(x){
          if(PW.API.targetFor(f,x.id))PW.prefetchCutout(f,x.id,'source');
        });
      });
    },600);
    return r;
  };
}

/* ---------- start ---------- */
function redraw(){
  if(PW.explore&&PW.explore.refresh)PW.explore.refresh();
  var h=location.hash||'#/';
  if(h.indexOf('#/explore')===0)return;   /* the explorer redraws itself */
  try{dispatchEvent(new HashChangeEvent('hashchange'))}catch(e){}
}

hydrate().then(function(changed){if(changed)redraw()});

PW.API.hydrated=hydrate;

})();