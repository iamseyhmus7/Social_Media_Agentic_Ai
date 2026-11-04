export type Feedback = {id:string;status:string;prompt:string;answer:string;source_run_id:string;decision:{summary?:string;clarification?:string;stages?:string[]};error?:string;run_id?:string};

export function clarificationTarget(projectId:string,run:{id:string;status:string;outputs:Record<string,any>},current?:Feedback){
 if(current?.status==='needs_clarification'&&current.decision.clarification?.trim())return {question:current.decision.clarification,path:'/projects/'+projectId+'/feedback/'+current.id+'/answers'};
 // Production questions belong to the pre-video flow. Existing-video commands
 // must not be routed by the source run's technical waiting_input status.
 if(!run.outputs.editor?.video&&run.status==='waiting_input'&&run.outputs.clarification?.question?.trim())return {question:run.outputs.clarification.question as string,path:'/runs/'+run.id+'/answers'};
 return null;
}

export function feedbackStatusText(item:Feedback){
 switch(item.status){
  case 'applied':return item.decision.summary||'Yeni sürüm oluşturuldu.';
  case 'queued':return 'İsteğin değerlendiriliyor…';
  case 'waiting_provider':return 'İsteğin kaydedildi. Model hizmeti bekleniyor; değerlendirme otomatik devam edecek.';
  case 'needs_clarification':return item.decision.clarification||'İsteğin için açıklama gerekiyor.';
  case 'waiting_quota':return 'Kota bekleniyor. İsteğin henüz uygulanmadı.';
  case 'superseded':return 'Yerine yeni değişiklik isteği gönderildi.';
  default:return item.error||'Değişiklik isteği uygulanamadı. Mevcut video korundu.';
 }
}
