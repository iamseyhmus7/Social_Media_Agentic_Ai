export type Scene = {title:string; narration:string; visual_prompt:string; action?:string;state_before?:string;state_after?:string};
export type Script = {hook:string; scenes:Scene[]; cta:string;format?:string;continuity?:string};
export type Publication = {id:string; status:string; publish_at:string|null; video_id:string|null; error:string|null};
export type Asset = {id:string; kind:string; url:string};
export type RemoteJob = {status:string;attempt:number;version:number|null;created:number;completed_clips:number;failed_clips:number};
export type Run = {id:string;project_id:string;revision:number;pipeline_version?:number;edit_style?:"classic"|"dynamic"|"editorial"|"auto";status:string;stage:string;outputs:Record<string,any>;error:string|null;approved:boolean;assets:Asset[];publication:Publication|null;created:number;started?:number;finished?:number;cancel_requested?:boolean;remote_jobs?:RemoteJob[];editor_progress?:Record<string,Record<string,{status:string;detail:string}>>;visual_progress?:{completed:number;total:number;unit:'shots'|'scenes';scene_images:Record<string,string>};recovery?:{version:number;active?:string;voice?:{status?:string;used?:number;remaining?:number;action?:string};provider?:{automatic?:boolean;retry_at?:number|null;deadline?:number}};provider_wait?:{automatic?:boolean;retry_at?:number|null;cycles?:number}};
export type Project = {id:string;title:string;topic:string;duration:number;audience:string;tone:string;revision:number;created:number;run:Run|null;music_asset?:string};
export type User = {id:string;name:string;email:string;role:'admin'|'member'};
export type Health = {ok:boolean;database_backend:string;queue_mode:string;evren_configured:boolean;youtube_configured:boolean;ffmpeg_available:boolean;tts_provider:string;tts_configured:boolean;image_provider:string;video_provider:string;editor_provider:string;kaggle_configured:boolean};


