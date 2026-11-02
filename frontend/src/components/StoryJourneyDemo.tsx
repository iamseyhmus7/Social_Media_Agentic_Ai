import {useEffect,useRef,useState} from 'react';
import {ArrowRight,Check,CheckCircle2,Clapperboard,FileText,Images,LoaderCircle,Mic,RotateCcw,Send,ShieldCheck,Sparkles,UserRound,Workflow} from 'lucide-react';
import examples from './story-demo-examples.json';
import {publicTeam as agents} from '../content/public-team';

type Status='idle'|'running'|'revising'|'review'|'approved';
const roles=agents.map(a=>({name:a.name,detail:a.summary,icon:a.icon}));
const durations=[850,1000,1250,1100,1350,1450,1500,900];

export function StoryJourneyDemo({signedIn,onNavigate}:{signedIn:boolean;onNavigate:(path:'/'|'/app'|'/login'|'/register')=>void}){
  const [topic,setTopic]=useState(0);
  const [status,setStatus]=useState<Status>('idle');
  const [step,setStep]=useState(0);
  const [inspected,setInspected]=useState<number|null>(null);
  const [short,setShort]=useState(false);
  const [videoReady,setVideoReady]=useState(false);
  const [videoError,setVideoError]=useState(false);
  const [mediaAttempt,setMediaAttempt]=useState(0);
  const [inView,setInView]=useState(false);
  const [pageVisible,setPageVisible]=useState(!document.hidden);
  const section=useRef<HTMLElement>(null);
  const videoRef=useRef<HTMLVideoElement>(null);
  const workflow=useRef<HTMLDivElement>(null);
  const example=examples[topic];
  const busy=status==='running'||status==='revising';
  const finished=status==='review'||status==='approved';
  const current=inspected??step;
  const seconds=short?9:12;
  const videoSrc='/demo/videos/'+example.id+'-'+(short?'short':'original')+'.mp4';
  const destination=signedIn?'/app':'/register';

  useEffect(()=>{
    const element=section.current;if(!element)return;
    const observer=new IntersectionObserver(([entry])=>setInView(entry.isIntersecting),{threshold:.03});
    observer.observe(element);
    const visibility=()=>setPageVisible(!document.hidden);
    document.addEventListener('visibilitychange',visibility);
    return()=>{observer.disconnect();document.removeEventListener('visibilitychange',visibility);};
  },[]);
  useEffect(()=>{
    if(!busy||!inView||!pageVisible)return;
    const timer=window.setTimeout(()=>{
      if(step===roles.length-1)setStatus('review');
      else setStep(value=>value+1);
    },durations[step]);
    return()=>window.clearTimeout(timer);
  },[busy,step,inView,pageVisible,status,topic]);

  useEffect(()=>{
    const video=videoRef.current;if(!video)return;
    const observer=new IntersectionObserver(([entry])=>{if(!entry.isIntersecting)video.pause();},{threshold:.1});
    const visibility=()=>{if(document.hidden)video.pause();};
    observer.observe(video);document.addEventListener('visibilitychange',visibility);
    return()=>{observer.disconnect();document.removeEventListener('visibilitychange',visibility);};
  },[finished,videoSrc,mediaAttempt]);

  function reset(nextTopic=topic){
    setTopic(nextTopic);setStatus('idle');setStep(0);setInspected(null);setShort(false);setVideoReady(false);setVideoError(false);
  }
  function start(){
    setStatus('running');setStep(0);setInspected(null);setVideoReady(false);setVideoError(false);
    if(window.matchMedia('(max-width: 700px)').matches)workflow.current?.scrollIntoView({block:'start',behavior:'auto'});
  }
  function revise(){
    setShort(true);setStatus('revising');setStep(6);setInspected(null);setVideoReady(false);setVideoError(false);
  }
  function navigate(event:React.MouseEvent<HTMLAnchorElement>){
    if(event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
    event.preventDefault();onNavigate(destination);
  }
  const messages=[
    'Üç sahnelik bir anlatım. Önce fikir, sonra senaryo; ardından ses metni, görseller ve kurgu.',
    example.strategy,
    '“'+example.hook+'”',
    example.scenes[0].narration,
    'Aynı görsel dünyaya ait üç örnek kare bir araya gelir.',
    'Bu adımda görsellere nasıl hareket katıldığını görürsün. Burada önceden hazırlanmış sahneler kullanılır; yeni video üretilmez.',
    `${seconds} saniyelik, telefonda izlemeye uygun bir video. ${short?'Her sahne üç saniyeye indirildi.':'Her sahne dört saniye boyunca gösterilir.'}`,
    example.title+' #Sahne #HikâyeniAnlat #Kapadokya'
  ];

  return <section className="landing-section landing-container journey-section" id="fikirden-videoya" ref={section}>
    <div className="landing-section-heading"><div><span className="landing-eyebrow">KÜÇÜK BİR FİKİR, BÜYÜK BİR DÜNYA.</span><h2>Bir fikir yazılır.<br/><em>Bir hikâye başlar.</em></h2></div><p>İlk cümleden son kareye, akışı kendin deneyimle. Bir konu seç, ekibini izle ve son sözü sen söyle.</p></div>
    <div className="journey-shell">
      <header className="journey-toolbar"><div><span className="journey-demo-badge"><Sparkles size={13}/>KENDİN DENE</span><span>Birlikte, adım adım.</span></div><button type="button" onClick={()=>reset()} disabled={status==='idle'}><RotateCcw size={14}/>Baştan başla</button></header>
      <div className="journey-grid">
        <div className="journey-brief"><div className="journey-panel-heading"><span>01</span><div><h3>Senin ilk cümlen.</h3><p>Bir örnek seçerek başla.</p></div></div>
          <div className="journey-topics" role="group" aria-label="Örnek konu seçimi">{examples.map((item,index)=><button type="button" key={item.id} aria-pressed={topic===index} onClick={()=>reset(index)}><span>{index===0?<Images size={17}/>:index===1?<Sparkles size={17}/>:<FileText size={17}/>}</span>{item.label}{topic===index&&<Check size={14}/>}</button>)}</div>
          <label className="journey-prompt-label" htmlFor="journey-prompt"><UserRound size={15}/>Örnek konu</label><textarea id="journey-prompt" value={example.prompt} readOnly aria-describedby="journey-prompt-note"/>
          <div className="journey-brief-tags"><span>Türkçe</span><span>3 sahne</span><span>Dikey video</span></div>
          <button type="button" className="journey-start" disabled={busy} onClick={start}>{busy?<><LoaderCircle size={16} className="journey-spin"/>Örnek adımlar gösteriliyor</>:<>{finished?'Örneği tekrar izle':'Örneği adım adım gör'}<ArrowRight size={17}/></>}</button>
          <p id="journey-prompt-note" className="journey-disclosure">Bu tanıtım hazır videolarla çalışır; yeni video üretmez. Kendi konunu hesabından videoya dönüştürebilirsin.</p>
          <a className="journey-own-idea" href={destination} onClick={navigate}>Kendi konumla üretmek istiyorum<ArrowRight size={14}/></a>
        </div>
        <div className="journey-workflow" ref={workflow}>
          <div className="journey-panel-heading"><span>02</span><div><h3>Bir ekip, tek hikâye.</h3><p>{status==='idle'?'Konunun nasıl videoya dönüştüğünü gör.':status==='revising'?'Yeni kurgu, yeni bir inceleme.':finished?'Örnek akış tamamlandı.':'Her adım hikâyene bir şey katıyor.'}</p></div></div>
          <ol className="journey-role-list" aria-label="Örnek hazırlık adımları">{roles.map(({name,detail,icon:Icon},index)=>{
            const done=finished||(status!=='idle'&&index<step);const active=busy&&index===step;
            return <li key={name} className={(done?'is-done ':'')+(active?'is-active ':'')+(current===index&&status!=='idle'?'is-inspected':'')} aria-current={active?'step':undefined}><button type="button" disabled={status==='idle'||(!done&&!active)} onClick={()=>setInspected(index)}><span className="journey-role-icon"><Icon size={16}/></span><span><strong>{name}</strong><small>{detail}</small></span><span className="journey-role-state">{done?<CheckCircle2 size={15}/>:active?<LoaderCircle size={15} className="journey-spin"/>:<span/>}</span></button></li>;
          })}</ol>
          <div className="journey-artifact" aria-label="Bu adımda hazırlanan örnek">{status==='idle'?<><span className="journey-artifact-label"><Workflow size={13}/>BURADA NE HAZIRLANIYOR?</span><p>Her adımın ne kattığını burada göreceksin.</p></>:<><span className="journey-artifact-label"><Sparkles size={13}/>{roles[current].name.toLocaleUpperCase('tr-TR')} · HAZIR ÖRNEK</span><p>{messages[current]}</p>{current===4&&<div className="journey-scene-thumbs">{example.scenes.map((scene,index)=><img key={scene.image} src={'/demo/'+scene.image+'.png'} alt={'Örnek sahne '+(index+1)}/>)}</div>}{current===3&&<small>Türkçe seslendirme metni örneği. Bu demodaki klip sessizdir.</small>}{inspected!==null&&<button type="button" onClick={()=>setInspected(null)}>Sıradaki adımı gör<ArrowRight size={12}/></button>}</>}</div>
        </div>
        <div className="journey-result"><div className="journey-panel-heading"><span>03</span><div><h3>Sahne senin.</h3><p>{finished?'İzle. İncele. Karar ver.':'Son kare, senin onayına gelir.'}</p></div></div>
          <div className="journey-phone"><div className="journey-phone-label"><span>SAHNE</span><span>{finished?`v${short?2:1} / ${seconds} SN`:'HAZIR ÖRNEK'}</span></div>{finished?<video ref={videoRef} key={videoSrc+mediaAttempt} controls muted playsInline preload="metadata" poster={'/demo/'+example.scenes[0].image+'.png'} onLoadedData={()=>setVideoReady(true)} onError={()=>setVideoError(true)} aria-label={example.title+' Sessiz örnek video'}><source src={videoSrc} type="video/mp4"/>Tarayıcın video oynatmayı desteklemiyor.</video>:<div className="journey-preview-placeholder"><img src={'/demo/'+example.scenes[0].image+'.png'} alt="Seçilen örnek konunun kapak görseli"/><div>{busy?<LoaderCircle size={29} strokeWidth={1.2} className="journey-spin"/>:<Clapperboard size={30} strokeWidth={1.2}/>}<strong>{busy?'Hikâye şekilleniyor.':'Burada bir hikâye var.'}</strong><span>{busy?roles[step].name+' · Hazır örnek':'Bir konu seç, nasıl hazırlandığını gör.'}</span></div></div>}</div>
          {videoError&&<div className="journey-video-error" role="alert">Video yüklenemedi.<button type="button" onClick={()=>{setVideoError(false);setMediaAttempt(value=>value+1);}}>Yeniden yükle</button></div>}
          <p className="journey-video-caption">{finished?`${seconds} saniyelik sessiz örnek video`:'Bu bölümde önceden hazırlanmış bir örneği izlersin.'}</p>
          <div className="journey-review-actions"><button type="button" className="journey-revise" disabled={!finished||short} onClick={revise}><RotateCcw size={14}/>{short?'Kısa kurgu seçildi':'Daha kısa kurgu iste'}</button><button type="button" className="journey-approve" disabled={!finished||!videoReady||videoError||status==='approved'} onClick={()=>setStatus('approved')}><ShieldCheck size={15}/>{status==='approved'?'Örneği onayladın':'İnceledim, onayla'}</button></div>
          <div className="journey-decision" role="status">{status==='approved'?<><CheckCircle2 size={16}/><span>Bu örneği onayladın.<br/>Şimdi sıra senin hikâyende.</span></>:status==='revising'?<span>Daha kısa bir örnek hazırlanıyor. Bittiğinde yeniden izleyip karar verebilirsin.</span>:finished?<span>{short?'Yeni sürüm hazır. ':'Video hazır. '}Buradaki onay yalnızca örnek içindir; hiçbir şey paylaşılmaz.</span>:<span>Son karar her zaman sende.</span>}</div>
        </div>
      </div>
      <footer className="journey-footer"><div><ShieldCheck size={17}/><span>Fikrin senin. Son söz de senin.</span></div><a href={destination} onClick={navigate}>{signedIn?'Kendi stüdyoma geç':'Şimdi kendi videonu oluştur'}<ArrowRight size={16}/></a></footer>
    </div>
    <p className="journey-status" role="status" aria-live="polite">{busy?'Örnek adım: '+roles[step].name:status==='review'?'Örnek video incelemene hazır.':status==='approved'?'Bu örneği beğendin. Kendi videonu hazırlamak için hesabına geçebilirsin.':'Hazır bir konu seçerek etkileşimli demoyu deneyebilirsin.'}</p>
  </section>;
}
