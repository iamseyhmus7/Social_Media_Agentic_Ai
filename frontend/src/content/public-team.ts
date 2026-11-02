import {agents} from '../agents';

// Public copy describes benefits; canonical production roles stay in agents.ts.
const descriptions:Record<string,{name:string;summary:string;input:string;output:string;benefit:string}>={
 supervisor:{name:'Planlama',summary:'Fikrini uygulanabilir adımlara ayırır',input:'Ne anlatmak istediğini ve videonun ne kadar süreceğini söylersin.',output:'Metinden son görüntüye kadar izlenecek yol hazırlanır.',benefit:'Nereden başlayacağını düşünmeden ilk adımı atarsın.'},
 strategy:{name:'Fikir geliştirme',summary:'İzleyicinin ilgisini çekecek açıyı bulur',input:'Konunu ve kimlere seslenmek istediğini anlatırsın.',output:'Videonun neye odaklanacağı ve nasıl başlayacağı belirlenir.',benefit:'Dağınık fikirlerin, anlatması kolay bir hikâyeye dönüşür.'},
 script:{name:'Metin yazımı',summary:'Anlatmak istediğini akıcı bir hikâyeye çevirir',input:'Vermek istediğin mesajı paylaşırsın.',output:'Videoda söylenecek sözler ve sahnelerin sırası yazılır.',benefit:'Boş bir sayfaya bakarak cümle aramakla uğraşmazsın.'},
 voice:{name:'Seslendirme',summary:'Hikâyeni Türkçe anlatımla buluşturur',input:'Hikâyenin samimi, merak uyandıran ya da sakin olmasını istersin.',output:'Yazılan metne uygun bir sesli anlatım hazırlanır.',benefit:'Mikrofon karşısına geçmeden sesli bir video hazırlarsın.'},
 visual:{name:'Görsel hazırlama',summary:'Hikâyene uygun görüntüler oluşturur',input:'Görmek istediğin ortamı ve tarzı tarif edersin.',output:'Sahneler için birbiriyle uyumlu görseller ve bir kapak hazırlanır.',benefit:'Fikrini anlatacak görüntüleri tek tek aramak zorunda kalmazsın.'},
 motion:{name:'Hareketli sahneler',summary:'Durağan görselleri hareketli çekimlere dönüştürür',input:'Hikâyeni ve nasıl bir görünüm istediğini anlatırsın.',output:'Görsellere uygun hareketler ve kamera geçişleri hazırlanır.',benefit:'Çekim yapmadan hikâyene hareket katarsın.'},
 editor:{name:'Video düzenleme',summary:'Görüntüyü, sesi ve altyazıyı birleştirir',input:'Nasıl bir anlatım ve tempo istediğini söylersin.',output:'Sahneler sıraya girer; ses ve altyazıyla birlikte bir video olur.',benefit:'Ayrı bir düzenleme programında saatler geçirmen gerekmez.'},
 publisher:{name:'Paylaşıma hazırlık',summary:'Videonun başlığını ve açıklamasını hazırlar',input:'Videoyu izler, son hâlini onaylarsın.',output:'Başlık ve açıklama hazırlanır. Videonu indirebilir, bağlı YouTube kanalında paylaşabilirsin.',benefit:'Paylaşım hazırlığını kolaylaştırırsın. Yayınlama kararı sende kalır.'},
};
export const publicTeam=agents.map(agent=>({...agent,...descriptions[agent.id]}));
