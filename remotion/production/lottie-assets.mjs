// Original vector animations. No network assets, expressions, scripts or fonts.
const key=(t,s,e)=>({t,s,e,i:{x:[.667],y:[1]},o:{x:[.333],y:[0]}});
const base={v:'5.7.4',fr:30,ip:0,op:60,w:320,h:320,nm:'Sahne symbolic graphics',ddd:0,assets:[]};
const transform={o:{a:0,k:100},r:{a:0,k:0},p:{a:0,k:[160,160,0]},a:{a:0,k:[0,0,0]},s:{a:0,k:[100,100,100]}};
const stroke={ty:'st',c:{a:0,k:[.835,.678,.447,1]},o:{a:0,k:100},w:{a:0,k:8},lc:2,lj:2};
const layer=(shapes,ks=transform)=>({ddd:0,ind:1,ty:4,nm:'symbol',sr:1,ks,ao:0,shapes,ip:0,op:60,st:0,bm:0});
export const lottieAssets={
 pulse_ring:{...base,layers:[layer([{ty:'el',p:{a:0,k:[0,0]},s:{a:0,k:[210,210]},d:1},stroke],{
  ...transform,s:{a:1,k:[key(0,[60,60,100],[110,110,100]),{t:45,s:[110,110,100]}]},
  o:{a:1,k:[key(0,[0],[100]),key(10,[100],[0]),{t:60,s:[0]}]}})]},
 flow_arrow:{...base,layers:[layer([
  {ty:'sh',ks:{a:0,k:{i:[[0,0],[0,0],[0,0],[0,0]],o:[[0,0],[0,0],[0,0],[0,0]],v:[[-95,0],[95,0],[45,-50],[95,0]],c:false}}},
  {ty:'sh',ks:{a:0,k:{i:[[0,0],[0,0]],o:[[0,0],[0,0]],v:[[95,0],[45,50]],c:false}}},stroke,
  {ty:'tm',s:{a:0,k:0},e:{a:1,k:[key(0,[0],[100]),{t:30,s:[100]}]},o:{a:0,k:0},m:1},
 ])]},
};
