import type {CSSProperties} from 'react';

// A real brush-shaped reveal: each stroke travels down/up the panel,
// advancing across it from left to right rather than sliding a rectangle.
function brush(x:number,y:number,width:number,height:number){
 const points:string[]=[];
 for(let i=0;i<=Math.ceil(width/12);i++){
  const px=x+Math.min(i*12,width);
  points.push(`${i===0?'M':'L'} ${px} ${i%2===0?y:y+height} L ${px} ${i%2===0?y+height:y}`);
 }
 return points.join(' ');
}
const regions=[
 {id:'storyboards',x:48,y:286,w:352,h:310,start:.04,duration:.85},
 {id:'identity',x:455,y:365,w:470,h:203,start:.55,duration:1.05},
 {id:'wave',x:889,y:480,w:97,h:103,start:1.25,duration:.45},
 {id:'photo-first',x:993,y:303,w:142,h:345,start:1.55,duration:.95},
 {id:'photo-main',x:1149,y:231,w:280,h:478,start:2,duration:1.15},
 {id:'photo-last',x:1441,y:311,w:172,h:338,start:2.65,duration:.95},
];
function ArtImages(){return <><use className="cinema-brand-night" href="#sahne-hero-night"/><use className="cinema-brand-day" href="#sahne-hero-day"/></>;}
export function HeroArtwork(){
 return <>
 <svg className="cinema-brand-background cinema-brand-drawing" viewBox="0 0 1672 941" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">
  <defs>
   <image id="sahne-hero-night" href="/images/sahne-home-background.webp" width="1672" height="941"/>
   <image id="sahne-hero-day" href="/images/sahne-home-daylight.webp" width="1672" height="941"/>
   <filter id="sahne-cutout-night" colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 3 3 3 0 -.9"/></filter>
   <filter id="sahne-cutout-day" colorInterpolationFilters="sRGB"><feColorMatrix type="matrix" values="1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 -3 -3 -3 0 8"/></filter>
   <mask id="sahne-sketch-without-frames" maskUnits="userSpaceOnUse" x="0" y="0" width="1672" height="941">
    <rect width="1672" height="941" fill="white"/>
    <path d="M 63 301 L 212 320 L 211 420 L 64 425 Z M 231 419 L 389 431 L 386 508 L 230 503 Z M 94 496 L 272 503 L 268 590 L 94 585 Z" fill="none" stroke="black" strokeWidth="12"/>
   </mask>
   <filter id="sahne-pencil" x="0" y="0" width="100%" height="100%" colorInterpolationFilters="sRGB">
    <feColorMatrix type="saturate" values="0"/>
    <feConvolveMatrix order="3" kernelMatrix="-1 -1 -1 -1 8 -1 -1 -1 -1"/>
    <feColorMatrix type="matrix" values="0 0 0 0 .53 0 0 0 0 .37 0 0 0 0 .75 8 8 8 0 -.08"/>
   </filter>
   {regions.map(region=><g key={region.id}>
    {['ink','color'].map(pass=><mask key={pass} id={`sahne-${region.id}-${pass}`} maskUnits="userSpaceOnUse" x="0" y="0" width="1672" height="941" style={{maskType:'alpha'}}>
     <path className="hero-brush-stroke" d={brush(region.x,region.y,region.w,region.h)} fill="none" stroke="white" strokeWidth="16" strokeLinejoin="round" strokeLinecap="round" pathLength="1000" style={{'--draw-delay':`${region.start+(pass==='color'?.42:0)}s`,'--draw-duration':`${region.duration}s`} as CSSProperties}/>
    </mask>)}
   </g>)}
  </defs>
  <image className="hero-drawing-paper" href="/images/sahne-page-atmosphere.webp" width="1672" height="941" preserveAspectRatio="none"/>
  {regions.map(region=><g key={region.id} mask={region.id==='storyboards'?'url(#sahne-sketch-without-frames)':undefined}>
   <g mask={`url(#sahne-${region.id}-ink)`}><g filter="url(#sahne-pencil)"><ArtImages/></g></g>
   <g className={`hero-region-color${region.id.startsWith('photo-')?'':' hero-region-cutout'}`} mask={`url(#sahne-${region.id}-color)`}><ArtImages/></g>
  </g>)}
  <path className="hero-drawing-connection" d="M 210 355 C 350 350 382 500 490 559 S 730 574 886 533 M 978 525 C 1035 516 1068 557 1125 570 C 1188 443 1325 492 1390 550 S 1518 612 1570 526 S 1640 470 1672 467" fill="none" stroke="currentColor" strokeWidth="1.8" pathLength="1000"/>
  <g className="hero-panel-linework" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
   <path className="hero-contour-draw" pathLength="1000" d="M 1306 317 C 1300 277 1398 271 1392 322 C 1389 350 1364 368 1363 383 H 1338 C 1338 365 1312 345 1306 317 M 1338 383 L 1341 395 H 1361 L 1363 383 M 1344 287 C 1326 318 1342 348 1345 380 M 1360 286 C 1378 315 1360 353 1356 380 M 1153 620 L 1190 541 L 1212 584 L 1243 502 L 1270 582 L 1290 551 L 1330 638 L 1370 536 L 1426 611 M 1155 676 L 1215 623 L 1249 657 L 1284 613 L 1338 695 L 1380 633 L 1425 663"/>
  </g>
  <g className="hero-drawing-finished"><ArtImages/></g>
 </svg>
 </>;
}
