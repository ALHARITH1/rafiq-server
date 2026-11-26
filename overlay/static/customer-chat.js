
'use strict';
const key=location.pathname.split('/').pop(),store='cs-session:'+key;
let session='';try{session=sessionStorage.getItem(store)||'';}catch(e){}
const status=document.getElementById('status'),list=document.getElementById('messages');
function show(messages){list.replaceChildren();for(const m of messages){const a=document.createElement('article');a.textContent=m.body;list.append(a);if(m.reply){const b=document.createElement('article');b.className='reply';b.textContent=m.reply;list.append(b);}else{const p=document.createElement('p');p.className='muted';p.textContent='حُفظت الرسالة للمتابعة. لا توجد إجابة معتمدة مطابقة حالياً.';list.append(p);}}}
async function request(payload){document.getElementById('send').disabled=true;document.getElementById('refresh').disabled=true;try{const r=await fetch('/api/customer-chat/'+encodeURIComponent(key),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...payload,session})});const d=await r.json();if(!r.ok)throw Error(d.error||'تعذر الاتصال');session=d.session;try{sessionStorage.setItem(store,session);}catch(e){}show(d.messages);status.textContent='';status.className='muted';return true;}catch(e){status.textContent=e.message;status.className='error';return false;}finally{document.getElementById('send').disabled=false;document.getElementById('refresh').disabled=false;}}
let pending=null;
document.getElementById('form').onsubmit=async(e)=>{e.preventDefault();const body=document.getElementById('body');if(!body.value.trim())return;if(!pending||pending.body!==body.value)pending={body:body.value,request_id:crypto.randomUUID()};if(await request({action:'send',...pending})){body.value='';pending=null;}};
document.getElementById('refresh').onclick=()=>request({action:'read'});
request({action:'read'});
