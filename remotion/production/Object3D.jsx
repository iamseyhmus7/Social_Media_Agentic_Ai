import React from 'react';
import {ThreeCanvas} from '@remotion/three';
import {useCurrentFrame,useVideoConfig,interpolate} from './timeline.jsx';

// Bounded native geometry only: no downloaded models, textures or generated code.
export const Object3D=({object,top=470})=>{
 const frame=useCurrentFrame(),{fps}=useVideoConfig();
 const angle=frame/fps*object.speed;
 const opacity=interpolate(frame,[0,12],[0,1],{extrapolateLeft:'clamp',extrapolateRight:'clamp'});
 return <div data-object-3d={object.kind} style={{position:'absolute',left:{left:80,center:160,right:245}[object.position],top,width:640,height:640,opacity,pointerEvents:'none'}}>
  <ThreeCanvas width={640} height={640} camera={{fov:38,position:[0,0,6]}} gl={{alpha:true,antialias:true,preserveDrawingBuffer:true}} dpr={1}>
   <ambientLight intensity={.8}/>
   <directionalLight position={[3,4,5]} intensity={2.6}/>
   <pointLight position={[-3,-1,2]} intensity={18} color="#8bc8ff"/>
   <mesh rotation={[.3+angle*.4,angle,-.15]} scale={object.scale}>
    {object.kind==='cube'&&<boxGeometry args={[1.8,1.8,1.8]}/>}
    {object.kind==='sphere'&&<sphereGeometry args={[1.15,32,24]}/>}
    {object.kind==='torus'&&<torusGeometry args={[.95,.28,16,48]}/>}
    {object.kind==='icosahedron'&&<icosahedronGeometry args={[1.3,0]}/>}
    <meshStandardMaterial color={object.color} roughness={.28} metalness={.45} wireframe={object.wireframe}/>
   </mesh>
  </ThreeCanvas>
 </div>;
};
