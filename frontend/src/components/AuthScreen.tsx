import {useEffect,useRef,useState,type FormEvent} from 'react';
import {ArrowLeft,ArrowRight,Check,Eye,EyeOff,Film,LoaderCircle,LockKeyhole,Mail,Sparkles,UserRound} from 'lucide-react';
import {Button} from './ui';
import {post,setCSRF} from '../api';
import {ThemeToggle} from './ThemeToggle';

export type AuthMode='login'|'register';
export function AuthScreen({mode,onMode,onClose,onSuccess}:{mode:AuthMode;onMode:(mode:AuthMode)=>void;onClose:()=>void;onSuccess:()=>Promise<void>}){
  const register=mode==='register';
  const [name,setName]=useState('');const [email,setEmail]=useState('');const [password,setPassword]=useState('');
  const [confirm,setConfirm]=useState('');const [show,setShow]=useState(false);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const heading=useRef<HTMLHeadingElement>(null);
  useEffect(()=>{setError('');setPassword('');setConfirm('');heading.current?.focus();document.title=register?'Hesap oluştur · Sahne':'Giriş yap · Sahne';return()=>{document.title='Sahne · Yapay Zekâ Video Stüdyosu';};},[mode,register]);
  async function submit(event:FormEvent){
    event.preventDefault();setError('');
    if(register&&password!==confirm){setError('Parolalar eşleşmiyor. Lütfen tekrar kontrol et.');return;}
    setBusy(true);
    try{const result=await post('/auth/'+(register?'register':'login'),register?{name:name.trim(),email:email.trim(),password}:{email:email.trim(),password});setCSRF(result.csrf);await onSuccess();}
    catch(err){setError((err as Error).message);}finally{setBusy(false);}
  }
  return <main className="auth-page">
    <section className="auth-story" aria-label="Sahne video stüdyosu">
      <img className="auth-story-background" src="/images/sahne-auth-studio.webp" alt="" aria-hidden="true" width={1024} height={1536} fetchPriority="high" decoding="async"/>
      <button className="wordmark" onClick={onClose} aria-label="Sahne ana sayfası">Sahne<Sparkles size={22}/></button>
      <div className="auth-story-copy"><span className="auth-kicker"><span/> FİKİRLERİN İÇİN YENİ BİR SAHNE</span><h2>Bir fikirle başla.<br/><em>Hikâyeni büyüt.</em></h2><p>Aklındaki konuyu yaz. Metin, Türkçe seslendirme ve görüntüler bir araya gelsin. Sen izle, içine sinen hâlini paylaş.</p></div>
      <footer className="auth-story-footer"><Film size={15}/> Fikrinden videona. Her adımda yanında.</footer>
    </section>
    <section className="auth-form-side">
      <header className="auth-top"><button onClick={onClose}><ArrowLeft size={16}/>Ana sayfaya dön</button><ThemeToggle/></header>
      <div className="auth-form-wrap">
        <div className="auth-form-icon"><Sparkles size={24} strokeWidth={1.5}/></div>
        <div className="auth-switch" aria-label="Hesap işlemi"><button onClick={()=>onMode('login')} aria-pressed={!register} disabled={busy}>Giriş yap</button><button onClick={()=>onMode('register')} aria-pressed={register} disabled={busy}>Hesap oluştur</button></div>
        <h1 ref={heading} tabIndex={-1}>{register?'Hikâyen burada başlıyor.':'Yeniden hoş geldin.'}</h1><p className="auth-subtitle">{register?'Kendi çalışma alanını oluştur. İlk fikrini birlikte sahneye taşıyalım.':'Fikirlerin, projelerin ve üretim ekibin seni bekliyor.'}</p>
        <form className="auth-form" onSubmit={submit} aria-busy={busy}>
          {register&&<label>Ad soyad<div className="auth-input"><UserRound size={18}/><input name="name" autoComplete="name" placeholder="Adın ve soyadın" required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></div></label>}
          <label>E-posta adresi<div className="auth-input"><Mail size={18}/><input name="email" type="email" autoComplete="email" placeholder="sen@ornek.com" required maxLength={254} value={email} onChange={e=>setEmail(e.target.value)}/></div></label>
          <label>Parola<div className="auth-input"><LockKeyhole size={18}/><input name="password" type={show?'text':'password'} autoComplete={register?'new-password':'current-password'} placeholder={register?'En az 12 karakter':'Parolanı gir'} required minLength={register?12:1} maxLength={200} value={password} onChange={e=>setPassword(e.target.value)} aria-describedby={register?'password-hint':undefined}/><button type="button" onClick={()=>setShow(!show)} aria-label={show?'Parolayı gizle':'Parolayı göster'} aria-pressed={show}>{show?<EyeOff size={18}/>:<Eye size={18}/>}</button></div></label>
          {register&&<><small className={'password-hint '+(password.length>=12?'valid':'')} id="password-hint"><Check size={13}/> En az 12 karakter kullan.</small><label>Parola tekrarı<div className="auth-input"><LockKeyhole size={18}/><input name="confirm" type={show?'text':'password'} autoComplete="new-password" placeholder="Parolanı tekrar gir" required maxLength={200} value={confirm} onChange={e=>setConfirm(e.target.value)}/></div></label></>}
          {error&&<p className="error-box" role="alert">{error}</p>}
          <Button type="submit" disabled={busy}>{busy?<LoaderCircle className="spin" size={18}/>:null}{busy?'Biraz bekle…':register?'Çalışma alanımı oluştur':'Çalışma alanına gir'}{!busy&&<ArrowRight size={18}/>}</Button>
        </form>
        <p className="auth-alternate">{register?'Zaten bir hesabın var mı?':'Sahne’de yeni misin?'} <button disabled={busy} onClick={()=>onMode(register?'login':'register')}>{register?'Giriş yap':'Hesap oluştur'}</button></p>
        <div className="auth-trust"><LockKeyhole size={15}/><p>Projelerin sana ait bir çalışma alanında tutulur.<br/>Videoların, onayın olmadan yayınlanmaz.</p></div>
        {register&&<p className="auth-pilot-note">Bir fikirle başla. Hazırlanan videoyu önce sen incele; paylaşım kararı sende.</p>}
      </div>
      <footer className="auth-form-footer"><span>Sahne · Fikirden son kareye.</span><span>Türkçe üretim için tasarlandı.</span></footer>
    </section>
  </main>;
}
