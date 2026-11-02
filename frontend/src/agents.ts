import catalog from '../../shared/agents.json';
import {Workflow,Sparkles,FileText,Mic,Images,Video,Clapperboard,Send} from 'lucide-react';
const icons=[Workflow,Sparkles,FileText,Mic,Images,Video,Clapperboard,Send];
export const agents=catalog.map((agent,index)=>({...agent,icon:icons[index]}));
export const agentLabels=Object.fromEntries(agents.map(a=>[a.id,a.name]));
