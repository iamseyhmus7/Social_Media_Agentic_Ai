import {useSyncExternalStore} from 'react';
import {Moon,Sun} from 'lucide-react';
const key='sahne-color-theme';
const eventName='sahne-theme-change';
function apply(theme:string){document.documentElement.dataset.theme=theme;}
export function initializeTheme(){let theme='dark';try{const saved=localStorage.getItem(key);if(saved==='light'||saved==='dark')theme=saved;}catch{}apply(theme);}
function subscribe(callback:()=>void){
 const sync=(event:StorageEvent)=>{if(event.key===key){apply(event.newValue==='light'?'light':'dark');callback();}};
 window.addEventListener(eventName,callback);window.addEventListener('storage',sync);
 return()=>{window.removeEventListener(eventName,callback);window.removeEventListener('storage',sync);};
}
export function ThemeToggle(){
 const theme=useSyncExternalStore(subscribe,()=>document.documentElement.dataset.theme||'dark',()=> 'dark');
 const light=theme==='light';
 function toggle(){const next=light?'dark':'light';apply(next);try{localStorage.setItem(key,next);}catch{}window.dispatchEvent(new Event(eventName));}
 return <button type="button" className="theme-toggle" role="switch" aria-checked={!light} data-mode={theme} onClick={toggle} aria-label="Gece modu" title={light?'Gece modunu aç':'Gündüz modunu aç'}>
  <span className="theme-toggle-thumb" aria-hidden="true"/>
  <Sun className="theme-toggle-sun" size={17} aria-hidden="true"/>
  <Moon className="theme-toggle-moon" size={17} aria-hidden="true"/>
 </button>;
}
