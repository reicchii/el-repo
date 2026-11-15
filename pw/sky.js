/* PW.SkyMap: the real SPHEREx DR1 all-sky mosaic from IRSA, drawn straight from its HiPS tiles.
   Source: https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube (102 layers, PNG, orders 0 to 5, 512 px tiles).
   Projection: Hammer-Aitoff centred on the view, east to the left, so the whole sky fits when zoomed out and the
   centre is nearly undistorted when zoomed in. HEALPix maths follows healpix_base (nested scheme). */
(function(){
'use strict';
var PW=window.PW;
var HIPS='https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube';
var WAVE=[0.753,0.771,0.790,0.809,0.828,0.848,0.868,0.889,0.910,0.932,0.955,0.978,1.001,1.025,1.050,1.075,1.102,1.113,1.139,1.167,1.195,1.224,1.254,1.284,1.315,1.346,1.378,1.412,1.446,1.481,1.517,1.554,1.592,1.631,1.656,1.695,1.735,1.775,1.818,1.861,1.905,1.949,1.995,2.041,2.089,2.139,2.189,2.240,2.292,2.345,2.399,2.445,2.506,2.575,2.646,2.719,2.794,2.871,2.951,3.033,3.118,3.204,3.293,3.383,3.476,3.570,3.667,3.768,3.833,3.867,3.901,3.935,3.970,4.005,4.040,4.076,4.112,4.148,4.184,4.220,4.257,4.294,4.331,4.368,4.405,4.435,4.467,4.500,4.533,4.566,4.600,4.635,4.669,4.704,4.739,4.773,4.808,4.843,4.879,4.915,4.951,4.988];
PW.WAVE=WAVE;PW.HIPS=HIPS;
PW.BLANK=function(l){return l===50||l===51};
/* layer for a detector: the middle channel, which is never a blank dichroic layer */
PW.detLayer=function(d){return 17*d+8};
PW.layerName=function(l){return WAVE[l].toFixed(2)+' µm · D'+(Math.floor(l/17)+1)+' channel '+(l%17+1)};

/* ---------- HEALPix (nested) ---------- */
function xyf(N,z,phi,out){var za=Math.abs(z),tt=phi*0.6366197723675814,t1,t2,jp,jm,ifp,ifm,ntt,tp,tmp;tt=tt-4*Math.floor(tt/4);
  if(za<=2/3){t1=N*(0.5+tt);t2=N*z*0.75;jp=Math.floor(t1-t2);jm=Math.floor(t1+t2);ifp=Math.floor(jp/N);ifm=Math.floor(jm/N);
    out[0]=ifp===ifm?((ifp&3)|4):ifp<ifm?(ifp&3):((ifm&3)+8);out[1]=jm&(N-1);out[2]=N-(jp&(N-1))-1}
  else{ntt=Math.min(3,Math.floor(tt));tp=tt-ntt;tmp=N*Math.sqrt(3*(1-za));jp=Math.min(N-1,Math.floor(tp*tmp));jm=Math.min(N-1,Math.floor((1-tp)*tmp));
    if(z>=0){out[0]=ntt;out[1]=N-jm-1;out[2]=N-jp-1}else{out[0]=ntt+8;out[1]=jp;out[2]=jm}}}
function spread(v){v=(v|(v<<8))&0x00FF00FF;v=(v|(v<<4))&0x0F0F0F0F;v=(v|(v<<2))&0x33333333;v=(v|(v<<1))&0x55555555;return v}
function tileIndex(k,f,tx,ty){return f*(1<<(2*k))+(spread(tx)|(spread(ty)<<1))}
/* where a HEALPix pixel sits inside its 512 x 512 tile image; orientation chosen by the seam test in the build notes */
var ORIENT=1;
/* render() inlines orientation 1 for speed; texel() keeps all eight for the seam test and readBands */
function texel(px,py){switch(ORIENT){case 0:return (511-px)*512+py;case 1:return px*512+py;case 2:return py*512+px;case 3:return (511-py)*512+px;
  case 4:return px*512+(511-py);case 5:return (511-px)*512+(511-py);case 6:return py*512+(511-px);default:return (511-py)*512+(511-px)}}
PW._orient=function(o){if(o==null)return ORIENT;ORIENT=o;PW.skyMaps.forEach(function(m){m.dirty()})};
PW._hp={xyf:xyf,tileIndex:tileIndex};

/* ---------- tile cache, shared by every map on the page ---------- */
var cache=new Map(),wait=new Map(),queue=[],active=0,MAXC=8,listeners=new Set(),failed=new Set(),hits=0;
function key(k,ip,l){return (l*8+k)*20000+ip}
function url(k,ip,l){return HIPS+'/Norder'+k+'/Dir'+(Math.floor(ip/10000)*10000)+'/Npix'+ip+'/Npix'+ip+(l?'_'+l:'')+'.png'}
var cv0=document.createElement('canvas');cv0.width=cv0.height=512;var cx0=cv0.getContext('2d',{willReadFrequently:true});
function want(k,ip,l,front){var kk=key(k,ip,l);if(cache.has(kk)||wait.has(kk)||failed.has(kk))return;wait.set(kk,1);var job={k:k,ip:ip,l:l,kk:kk};if(front)queue.unshift(job);else queue.push(job);pump()}
function pump(){while(active<MAXC&&queue.length){var j=queue.shift();active++;load(j)}}
function load(j){var im=new Image();im.crossOrigin='anonymous';
  im.onload=function(){cx0.clearRect(0,0,512,512);cx0.drawImage(im,0,0);var d=cx0.getImageData(0,0,512,512).data,a=new Uint8Array(512*512),i;for(i=0;i<a.length;i++)a[i]=d[i*4];
    cache.set(j.kk,a);done(j)};
  im.onerror=function(){failed.add(j.kk);done(j)};im.src=url(j.k,j.ip,j.l)}
function done(j){wait.delete(j.kk);active--;pump();listeners.forEach(function(f){f(j)});if(cache.size>900){var it=cache.keys();for(var n=0;n<200;n++)cache.delete(it.next().value)}}
PW.skyStatus=function(){return {cached:cache.size,waiting:wait.size,failed:failed.size,active:active}};

/* read the 102-band quick-look brightness at one position from the finest tiles (0 to 255 display values, not calibrated) */
PW.readBands=function(ra,dec,onStep){var o=[0,0,0],N=512<<5,k=5,z=Math.sin(dec*Math.PI/180),phi=((ra%360)+360)%360*Math.PI/180;xyf(N,z,phi,o);
  var ip=tileIndex(k,o[0],o[1]>>9,o[2]>>9),t=texel(o[1]&511,o[2]&511),out=new Array(102),n=0,todo=[];
  for(var l=0;l<102;l++)if(!PW.BLANK(l))todo.push(l);else out[l]=null;
  return new Promise(function(res){var left=todo.length;
    function got(l){var a=cache.get(key(k,ip,l));out[l]=a?a[t]:null;n++;if(onStep)onStep(n,todo.length);if(--left===0){listeners.delete(fn);res(out)}}
    function fn(j){if(j.k===k&&j.ip===ip&&todo.indexOf(j.l)>-1&&out[j.l]===undefined)got(j.l)}
    listeners.add(fn);todo.forEach(function(l){if(cache.has(key(k,ip,l)))got(l);else want(k,ip,l,true)})})};

/* ---------- the map ---------- */
PW.skyMaps=new Set();
var R2=Math.SQRT2,D2R=Math.PI/180;
function SkyMap(canvas,opt){var m=this;opt=opt||{};this.cv=canvas;this.ctx=canvas.getContext('2d');this.ra=opt.ra||266.4;this.dec=opt.dec||-28.9;
  this.s=opt.s||200;this.layers=opt.layers||[PW.detLayer(5),PW.detLayer(2),PW.detLayer(0)];this.gain=opt.gain||2.4;this.off=opt.off||1;this.q=1;this.live=false;this.bg=opt.bg||[8,9,11];
  this.fill=!!opt.fill;this.auto=opt.auto!==false;this.gainMul=opt.gainMul||1;this.offAdd=opt.offAdd||0;this.minS=0;this.maxS=180000;this.need=new Set();this._raf=0;this.onview=opt.onview||null;this._lis=function(){m.dirty()};listeners.add(this._lis);PW.skyMaps.add(this);this.resize()}
SkyMap.prototype={
 destroy:function(){listeners.delete(this._lis);PW.skyMaps.delete(this);cancelAnimationFrame(this._raf)},
 resize:function(){var r=this.cv.getBoundingClientRect();this.W=Math.max(2,r.width);this.H=Math.max(2,r.height);this.minS=Math.min(this.W/(4*R2)*1.02,this.H/(2*R2)*1.02)/R2*R2;this.clampS();this.dirty()},
 clampS:function(){this.minS=this.fill?Math.max(this.W/4.1,this.H/2.05):Math.min(this.W/5.8,this.H/2.9);if(this.s<this.minS)this.s=this.minS;if(this.s>this.maxS)this.s=this.maxS},
 fov:function(){return this.W/this.s/D2R},
 setView:function(ra,dec,fovDeg){this.ra=((ra%360)+360)%360;this.dec=Math.max(-90,Math.min(90,dec));if(fovDeg)this.s=this.W/(fovDeg*D2R);this.clampS();this.dirty()},
 setLayers:function(ls){this.layers=ls;this._settle=0;this.dirty()},
 mat:function(){var a=this.ra*D2R,d=this.dec*D2R,ca=Math.cos(a),sa=Math.sin(a),cd=Math.cos(d),sd=Math.sin(d);
   /* world = Rz(ra) * Ry(-dec) * v */
   return [ca*cd,-sa,-ca*sd, sa*cd,ca,-sa*sd, sd,0,cd]},
 /* sky (deg) to CSS pixels, or null when on the far side */
 project:function(ra,dec){var M=this.mat(),a=ra*D2R,d=dec*D2R,w0=Math.cos(d)*Math.cos(a),w1=Math.cos(d)*Math.sin(a),w2=Math.sin(d),
   v0=M[0]*w0+M[3]*w1+M[6]*w2,v1=M[1]*w0+M[4]*w1+M[7]*w2,v2=M[2]*w0+M[5]*w1+M[8]*w2,b=Math.asin(Math.max(-1,Math.min(1,v2))),l=Math.atan2(v1,v0),cb=Math.cos(b),den=Math.sqrt(1+cb*Math.cos(l/2)),
   X=2*R2*cb*Math.sin(l/2)/den,Y=R2*v2/den;
   return [this.W/2-this.s*X/R2,this.H/2-this.s*Y/R2,Math.abs(l)<Math.PI/2]},
 unproject:function(x,y){var X=-(x-this.W/2)*R2/this.s,Y=-(y-this.H/2)*R2/this.s,t=1-X*X/16-Y*Y/4;if(t<0.5)return null;
   var z=Math.sqrt(t),A=z*X,B=2*(2*t-1),r2=A*A+B*B,cl=(B*B-A*A)/r2,sl=2*A*B/r2,sb=z*Y,cb=Math.sqrt(Math.max(0,1-sb*sb)),v0=cb*cl,v1=cb*sl,v2=sb,M=this.mat(),
   w0=M[0]*v0+M[1]*v1+M[2]*v2,w1=M[3]*v0+M[4]*v1+M[5]*v2,w2=M[6]*v0+M[7]*v1+M[8]*v2;
   return [((Math.atan2(w1,w0)/D2R)+360)%360,Math.asin(Math.max(-1,Math.min(1,w2)))/D2R]},
 order:function(){var px=1/(this.s*this.q),k=0;while(k<5&&1.0233/(512<<k)>px*1.4)k++;return k},
 dirty:function(fromUser){var m=this;if(fromUser)this._settle=0;if(this._raf)return;this._raf=requestAnimationFrame(function(){m._raf=0;m.render()})},
 render:function(){var T0=performance.now(),me=this;this._render();var dt=performance.now()-T0;
   /* adapt resolution to the device: aim for about 28 ms while moving and 110 ms when still */
   if(this.live)this.liveBudget=Math.max(30000,Math.min(160000,(this.liveBudget||90000)*Math.min(1.25,Math.max(.6,28/Math.max(1,dt)))));
   else this.idleBudget=Math.max(90000,Math.min(520000,(this.idleBudget||330000)*Math.min(1.2,Math.max(.6,110/Math.max(1,dt)))))},
 _render:function(){var A0=this.W*this.H,q=Math.sqrt((this.live?this.liveBudget||90000:this.idleBudget||330000)/A0);q=Math.min(q,this.live?.7:Math.min(window.devicePixelRatio||1,1.25));
     var w=Math.max(2,Math.round(this.W*q)),h=Math.max(2,Math.round(this.H*q));this.q=w/this.W;
   if(this.cv.width!==w||this.cv.height!==h){this.cv.width=w;this.cv.height=h;this._img=null}
   if(!this._img)this._img=this.ctx.createImageData(w,h);
   var img=this._img,p=img.data,M=this.mat(),k=this.order(),N=512<<k,s=this.s*this.q,cx=w/2,cy=h/2,L=this.layers,nl=L.length,o=[0,0,0],
     auto=this.auto!==false,LV=auto&&this.lv?this.lv:[[this.off,this.gain],[this.off,this.gain],[this.off,this.gain]],HI=[new Uint32Array(256),new Uint32Array(256),new Uint32Array(256)],smp=0,
     bg=this.bg,need=new Map(),i,j,X,Y,t,z,A,B,r2,cl,sl,sb,cb,v0,v1,v2,w0,w1,w2,phi,ip,c,ta,lk,kk,val,jj,px,py,ch,ord,ck=[-1,-1,-1],ca=[null,null,null],csh=[0,0,0],
     G=4,gw=Math.ceil(w/G)+1,gh=Math.ceil(h/G)+1,GV=this._gv&&this._gv.length===gw*gh*4?this._gv:(this._gv=new Float32Array(gw*gh*4)),gi,gj,fx,fy,n00,n10,n01,n11,in4,ln,wa,wb,wc,wd;
   /* unit vectors on a coarse grid; pixels inside a fully visible cell are interpolated, edge cells are computed exactly */
   function vecAt(x,y,out,at){var X=-(x-cx)*R2/s,Y=-(y-cy)*R2/s,t=1-X*X/16-Y*Y/4;if(t<0.5){out[at+3]=0;return}
     var z=Math.sqrt(t),A=z*X,B=2*(2*t-1),r2=A*A+B*B,cl=(B*B-A*A)/r2,sl=2*A*B/r2,sb=z*Y,cb=Math.sqrt(1-sb*sb),v0=cb*cl,v1=cb*sl,v2=sb;
     out[at]=M[0]*v0+M[1]*v1+M[2]*v2;out[at+1]=M[3]*v0+M[4]*v1+M[5]*v2;out[at+2]=M[6]*v0+M[7]*v1+M[8]*v2;out[at+3]=1}
   for(gj=0;gj<gh;gj++)for(gi=0;gi<gw;gi++)vecAt(gi*G,gj*G,GV,(gj*gw+gi)*4);
   var one=new Float32Array(4);
   for(j=0;j<h;j++){gj=(j/G)|0;fy=(j-gj*G)/G;for(i=0;i<w;i++){c=(j*w+i)*4;gi=(i/G)|0;fx=(i-gi*G)/G;
     n00=(gj*gw+gi)*4;n10=n00+4;n01=n00+gw*4;n11=n01+4;in4=GV[n00+3]&&GV[n10+3]&&GV[n01+3]&&GV[n11+3];
     if(in4){wa=(1-fx)*(1-fy);wb=fx*(1-fy);wc=(1-fx)*fy;wd=fx*fy;
       w0=GV[n00]*wa+GV[n10]*wb+GV[n01]*wc+GV[n11]*wd;w1=GV[n00+1]*wa+GV[n10+1]*wb+GV[n01+1]*wc+GV[n11+1]*wd;w2=GV[n00+2]*wa+GV[n10+2]*wb+GV[n01+2]*wc+GV[n11+2]*wd;
       ln=Math.sqrt(w0*w0+w1*w1+w2*w2);w2/=ln}
     else{vecAt(i+.5,j+.5,one,0);if(!one[3]){p[c]=bg[0];p[c+1]=bg[1];p[c+2]=bg[2];p[c+3]=255;continue}w0=one[0];w1=one[1];w2=one[2]}
     phi=Math.atan2(w1,w0);if(phi<0)phi+=6.283185307179586;if(w2>1)w2=1;else if(w2<-1)w2=-1;
     xyf(N,w2,phi,o);px=o[1];py=o[2];ip=tileIndex(k,o[0],px>>9,py>>9);
     for(ch=0;ch<nl;ch++){lk=L[ch];kk=key(k,ip,lk);
       /* one lookup per tile, not per pixel; while a tile loads, its loaded ancestor stands in so the map is never blank */
       if(kk!==ck[ch]){ck[ch]=kk;ca[ch]=cache.get(kk);csh[ch]=0;
         if(!ca[ch]){if(!need.has(kk))need.set(kk,[k,ip,lk]);for(ord=k-1;ord>=0;ord--){ta=cache.get(key(ord,tileIndex(ord,o[0],(px>>(k-ord))>>9,(py>>(k-ord))>>9),lk));if(ta){ca[ch]=ta;csh[ch]=k-ord;break}}}}
       ta=ca[ch];if(ta){jj=csh[ch];val=jj?ta[((px>>jj)&511)*512+((py>>jj)&511)]:ta[(px&511)*512+(py&511)];if((smp&7)===0)HI[ch][val]++;val=(val-LV[ch][0])*LV[ch][1]}else val=0;
       p[c+ch]=val<0?0:val>255?255:val}
     if(nl===1){p[c+1]=p[c+2]=p[c]}
     p[c+3]=255;smp++}}
   this.ctx.putImageData(img,0,0);
   /* automatic limits from what is on screen: black at the 1st percentile, white at the 99.6th, per channel */
   if(auto&&!this.live){var nlv=[],chg=false;for(ch=0;ch<nl;ch++){var hst=HI[ch],tot=0,lo=0,hi=255,acc=0,b;for(b=0;b<256;b++)tot+=hst[b];
       if(tot<50){nlv.push(LV[ch]);continue}for(b=0;b<256;b++){acc+=hst[b];if(acc>=tot*.01){lo=b;break}}acc=0;for(b=255;b>=0;b--){acc+=hst[b];if(acc>=tot*.004){hi=b;break}}
       var gn=Math.min(24,255/Math.max(6,hi-lo))*this.gainMul,of=Math.max(0,lo-this.offAdd);nlv.push([of,gn]);if(Math.abs(gn-LV[ch][1])/LV[ch][1]>.06||Math.abs(of-LV[ch][0])>1.5)chg=true}
     while(nlv.length<3)nlv.push(nlv[0]);if(nl===1){nlv[1]=nlv[2]=nlv[0]}
     if(chg||!this.lv){this.lv=nlv;if((this._settle=(this._settle||0)+1)<4)this.dirty()}else this._settle=0}
   need.forEach(function(v){want(v[0],v[1],v[2])});
   /* keep the coarse levels of the current layers ready, so zooming out is instant */
   if(!this._warm||this._warm!==L.join()){this._warm=L.join();for(var f=0;f<12;f++)L.forEach(function(l){want(0,f,l)})}
   this.lastNeed=need;if(this.onview)this.onview(this)},
 /* fetch the visible tiles of other layers ahead of time, for smooth playback */
 prefetch:function(layers){var m=this;if(!this.lastNeed)return;this.lastNeed.forEach(function(v){layers.forEach(function(l){want(v[0],v[1],l)})})},
 ready:function(layers){var ok=true;if(!this.lastNeed)return false;this.lastNeed.forEach(function(v){layers.forEach(function(l){if(!cache.has(key(v[0],v[1],l))&&!failed.has(key(v[0],v[1],l)))ok=false})});return ok},
 /* pan, zoom, pinch and keyboard */
 interact:function(el){var m=this,pts={},dn=null,pin=null,idle;
   function live(){m.live=true;m._settle=0;clearTimeout(idle);idle=setTimeout(function(){m.live=false;m.dirty()},160)}
   function zoomAt(f,x,y){var p=m.unproject(x,y),s0=m.s;m.s*=f;m.clampS();if(p&&m.s!==s0){var c=m.unproject(m.W/2+(x-m.W/2)*(1-s0/m.s),m.H/2+(y-m.H/2)*(1-s0/m.s));
       if(c&&f>1){/* keep the point under the cursor in place */var q=m.project(p[0],p[1]);var c2=m.unproject(m.W/2+(q[0]-x),m.H/2+(q[1]-y));if(c2){m.ra=c2[0];m.dec=c2[1]}}
       else if(c){m.ra=c[0];m.dec=c[1]}}live();m.dirty()}
   this.zoomAt=zoomAt;
   el.addEventListener('wheel',function(e){e.preventDefault();var r=el.getBoundingClientRect();zoomAt(Math.pow(1.0018,-e.deltaY*(e.deltaMode?33:1)),e.clientX-r.left,e.clientY-r.top)},{passive:false});
   el.addEventListener('pointerdown',function(e){pts[e.pointerId]=[e.clientX,e.clientY];try{el.setPointerCapture(e.pointerId)}catch(x){}var k=Object.keys(pts);
     if(k.length===2){pin=[Math.hypot(pts[k[0]][0]-pts[k[1]][0],pts[k[0]][1]-pts[k[1]][1])||1,m.s];dn=null}else{dn=[e.clientX,e.clientY,0];m._moved=false}});
   el.addEventListener('pointermove',function(e){var r=el.getBoundingClientRect(),k,d2,c;if(pts[e.pointerId])pts[e.pointerId]=[e.clientX,e.clientY];
     if(pin){k=Object.keys(pts);if(k.length<2)return;d2=Math.hypot(pts[k[0]][0]-pts[k[1]][0],pts[k[0]][1]-pts[k[1]][1])||1;
       zoomAt(pin[1]*d2/pin[0]/m.s,(pts[k[0]][0]+pts[k[1]][0])/2-r.left,(pts[k[0]][1]+pts[k[1]][1])/2-r.top);m._moved=true;return}
     if(!dn)return;var dx=e.clientX-dn[0],dy=e.clientY-dn[1];if(!dn[2]&&Math.abs(dx)+Math.abs(dy)<4)return;dn[2]=1;m._moved=true;
     c=m.unproject(m.W/2-dx,m.H/2-dy);if(c){m.ra=c[0];m.dec=c[1]}dn[0]=e.clientX;dn[1]=e.clientY;el.style.cursor='grabbing';live();m.dirty()});
   function up(e){delete pts[e.pointerId];if(Object.keys(pts).length<2)pin=null;dn=null;el.style.cursor=''}
   el.addEventListener('pointerup',up);el.addEventListener('pointercancel',up)},
 /* fly to a position: zoom out, move along the great circle, zoom in, under 1.2 s */
 flyTo:function(ra,dec,fov,done){var m=this,a0=[this.ra,this.dec],s0=this.s,s1=Math.max(this.minS,Math.min(this.maxS,this.W/(fov*D2R))),t0=performance.now(),T=PW.still?0:1100;
   function vec(r,d){r*=D2R;d*=D2R;return [Math.cos(d)*Math.cos(r),Math.cos(d)*Math.sin(r),Math.sin(d)]}
   var u=vec(a0[0],a0[1]),v=vec(ra,dec),om=Math.acos(Math.max(-1,Math.min(1,u[0]*v[0]+u[1]*v[1]+u[2]*v[2]))),sMid=Math.min(s0,s1,this.W/(Math.max(om/D2R*2.2,fov)*D2R));
   function step(now){var t=T?Math.min(1,(now-t0)/T):1,e=t<.5?2*t*t:1-Math.pow(-2*t+2,2)/2,w,x,y,z,ls;
     if(om>1e-9){var so=Math.sin(om);w=[Math.sin((1-e)*om)/so,Math.sin(e*om)/so];x=w[0]*u[0]+w[1]*v[0];y=w[0]*u[1]+w[1]*v[1];z=w[0]*u[2]+w[1]*v[2];m.ra=((Math.atan2(y,x)/D2R)+360)%360;m.dec=Math.asin(Math.max(-1,Math.min(1,z)))/D2R}
     ls=t<.5?Math.log(s0)+(Math.log(sMid)-Math.log(s0))*(t*2):Math.log(sMid)+(Math.log(s1)-Math.log(sMid))*((t-.5)*2);m.s=Math.exp(ls);m.clampS();m.live=t<1;m._settle=0;m.render();
     if(t<1)requestAnimationFrame(step);else if(done)done()}
   requestAnimationFrame(step)}
};
PW.SkyMap=SkyMap;

/* coordinate text */
PW.sexa=function(ra,dec){var h=ra/15,hh=Math.floor(h),mm=Math.floor((h-hh)*60),ss=((h-hh)*60-mm)*60,sg=dec<0?'−':'+',d=Math.abs(dec),dd=Math.floor(d),dm=Math.floor((d-dd)*60),ds=((d-dd)*60-dm)*60;
  if(ss>=59.95){ss=0;mm++}if(ds>=59.95){ds=0;dm++}
  return hh+'h'+String(mm).padStart(2,'0')+'m'+ss.toFixed(1).padStart(4,'0')+'s  '+sg+dd+'°'+String(dm).padStart(2,'0')+'′'+ds.toFixed(1).padStart(4,'0')+'″'};
PW.deci=function(ra,dec){return ra.toFixed(5)+'°  '+(dec<0?'−':'+')+Math.abs(dec).toFixed(5)+'°'};
PW.fovText=function(f){return f>=1?f.toFixed(f>=10?0:1)+'°':f*60>=1?(f*60).toFixed(1)+'′':Math.round(f*3600)+'″'};
})();
