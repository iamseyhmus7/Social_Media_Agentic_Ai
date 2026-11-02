export type AppPath='/'|'/app'|'/login'|'/register';
export function resolveRoute(path:string,signedIn:boolean,pending:boolean):{screen:'home'|'workspace'|'login'|'register'|'loading';redirect?:AppPath}{
  if(path==='/')return {screen:'home'};
  if(path==='/app'||path.startsWith('/app/')){
    if(pending)return {screen:'loading'};
    return signedIn?{screen:'workspace'}:{screen:'loading',redirect:'/login'};
  }
  if(path==='/login'||path==='/register'){
    if(signedIn)return {screen:'loading',redirect:'/app'};
    return {screen:path==='/login'?'login':'register'};
  }
  return {screen:'home',redirect:'/'};
}
