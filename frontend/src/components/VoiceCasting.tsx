type Candidate = {key:string;name:string;library_users?:number|null;status?:string;asset_id?:string;error?:string;review?:{suitability:number;reason:string;issues:string[]}};
type Casting = {phase:string;sample_text:string;decision_model:string;candidates:Candidate[];decision?:{profile_key:string;reason:string}};

export function VoiceCasting({casting,audioUrl}:{casting:Casting;audioUrl:(id:string)=>string|undefined}){
 const labels:Record<string,string>={shortlisting:'Türkçe anlatıcılar araştırılıyor',generating:'Aynı senaryodan ses örnekleri üretiliyor',reviewing:'Agent sesleri karşılaştırıyor',selected:'Anlatıcı seçildi',blocked:'Ses erişimi bekleniyor'};
 return <section aria-label="Türkçe ses adayları" className="voice-casting">
  <h3>Türkçe ses adayları</h3><p>{labels[casting.phase]||'Ses karşılaştırması'} · {casting.decision_model}</p>
  <blockquote>{casting.sample_text}</blockquote>
  <div style={{display:'grid',gap:16}}>{casting.candidates.map(candidate=><article key={candidate.key} style={{padding:18,border:'1px solid #ddd7e7',borderRadius:12}}>
   <strong>{candidate.name}{casting.decision?.profile_key===candidate.key?' · Seçildi':''}</strong>
   <p>{candidate.status==='unavailable'?'Bu hesapta API erişimi yok':candidate.status==='ready'?'API erişimi doğrulandı':'API erişimi doğrulanıyor'}{candidate.library_users!=null&&<> · Kütüphaneye ekleyenler: {candidate.library_users.toLocaleString('tr-TR')}</>}</p>
   {candidate.asset_id&&<audio style={{display:'block',width:'100%',marginTop:12}} controls preload="none" src={audioUrl(candidate.asset_id)} aria-label={candidate.name+' senaryo örneği'}/>}
   {candidate.error&&<p>{candidate.error}</p>}
   {candidate.review&&<><p>Uygunluk: {Math.round(candidate.review.suitability*100)}/100</p><p>{candidate.review.reason}</p></>}
  </article>)}</div>
  {casting.decision&&<p><strong>Agent’ın karar gerekçesi:</strong> {casting.decision.reason}</p>}
 </section>;
}
