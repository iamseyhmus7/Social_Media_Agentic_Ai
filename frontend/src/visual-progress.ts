import type {Run} from './types';

export function visualProgress(run:Run|null,demo=false){
  const sceneCount=run?.outputs.script?.scenes?.length||0;
  const confirmed=run?.outputs.visual?.images as string[]|undefined;
  if(demo){
    const images=confirmed||run?.assets.filter(a=>a.kind==='image').map(a=>a.id)||[];
    return {completed:Math.min(images.length,sceneCount),total:sceneCount,label:'görsel',images};
  }
  const progress=run?.visual_progress;
  const shots=run?.outputs.visual?.shot_images;
  const total=progress?.total??(confirmed?(shots?Object.keys(shots).length:confirmed.length):sceneCount);
  const completed=progress?.completed??(confirmed?total:0);
  const images=confirmed||Array.from({length:sceneCount},(_,i)=>progress?.scene_images[String(i)]);
  return {completed,total,label:progress?.unit==='shots'||shots?'çekim görseli':'görsel',images};
}

export function visualCover(run:Run|null,demo=false){
  const id=run?.outputs.visual?.cover||visualProgress(run,demo).images.find(Boolean);
  return id?run?.assets.find(asset=>asset.id===id)?.url:undefined;
}
