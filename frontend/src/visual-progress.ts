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
  return assetUrl(run,id);
}

export function sourceForAsset(run:Run|null|undefined,id:string|undefined){
  const visual=run?.outputs.visual;
  const shot=Object.entries(visual?.shot_images||run?.visual_progress?.shot_images||{}).find(([,asset])=>asset===id)?.[0];
  return shot?(visual?.generation||run?.visual_progress?.generation)?.[shot]?.source:undefined;
}

export function assetUrl(run:Run|null|undefined,id:string|undefined){
  if(!id)return undefined;
  const source=sourceForAsset(run,id);
  // Unsplash requires API-provided hotlinks when displaying source photos.
  return source?.catalog==='unsplash'&&source.preview_url?source.preview_url:run?.assets.find(asset=>asset.id===id)?.url;
}
