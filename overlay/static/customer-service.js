/* Customer service, additive to existing views. No external library or paid service. */
async function customerServiceView() {
  const data = await api('GET', '/api/customer-service');
  const wrap = el('div', {}, el('div', {class:'page-head'}, el('div', {},
    el('h1', {}, 'خدمة العملاء'), el('p', {class:'muted'}, 'صندوق واحد للرسائل والمتابعة وتقرير الساعة 08:00 بتوقيت الرياض.'))));
  const note = (text) => el('p', {class:'muted',style:'line-height:1.9'}, text);
  const box = (title, ...children) => el('section', {class:'card',style:'padding:24px;margin-bottom:20px'}, el('h2', {}, title), ...children);
  const reload = () => render();
  const run = (fn) => async (event) => { const b=event.currentTarget; b.disabled=true; try { await fn(); } catch(e) {toast(e.message);} finally {b.disabled=false;} };
  const button = (name, fn) => el('button', {class:'btn',type:'button',onclick:run(fn)}, name);
  for(const shared of (data.shared_reports||[])) {
    wrap.append(box('تقرير الحساب المرتبط: '+shared.owner_name,
      note('قراءة التقرير فقط. صندوق الرسائل والإعدادات أدناه يخصان الحساب المفتوح حالياً.'),
      ...shared.reports.map(r=>el('details',{open:true},el('summary',{},r.report_day),el('pre',{style:'white-space:pre-wrap;font:inherit;line-height:1.9'},r.content)))));
  }
  const opts = el('div', {style:'display:flex;flex-wrap:wrap;gap:16px;margin:18px 0'});
  const toggle = (key, label) => {
    const input=el('input',{type:'checkbox'}); input.checked=!!data.config[key];
    input.addEventListener('change', async () => {input.disabled=true; try {await api('PUT','/api/customer-service/settings',{[key]:input.checked}); await reload();} catch(e) {toast(e.message);input.checked=!input.checked;} finally {input.disabled=false;}});
    return el('label',{style:'display:flex;gap:8px;align-items:center'},input,label);
  };
  opts.append(toggle('report_enabled','تقرير صباحي داخل رفيق'),toggle('website_enabled','تفعيل رابط محادثة الموقع'),toggle('auto_reply','الرد تلقائياً بالإجابات المعتمدة فقط'));
  wrap.append(box('الإعدادات', note('مجاني دون استدعاء ذكاء اصطناعي مدفوع. الرد التلقائي يطابق سؤالاً معتمداً فقط؛ السؤال الجديد يبقى للمتابعة. لا تُختلق أسعار أو وعود.'),opts,
    note('حفظ إجابة أدناه يعني اعتماد نصها للرد التلقائي عند تفعيل الخيار. القنوات الاجتماعية غير المربوطة لا تستقبل رسائل ولا ترسلها.')));
  const channels=el('div',{style:'display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:12px'});
  for(const ch of data.channels) channels.append(el('div',{class:'card',style:'padding:16px'},el('h3',{},ch.name),el('span',{class:ch.connected?'chip ok':'chip warn'},ch.connected?'مفعّل':'غير مربوط'),note(ch.detail)));
  const channelbox=box('القنوات',channels);
  if(data.config.website_enabled && data.config.website_key) {
    const url=location.origin+'/customer-chat/'+data.config.website_key;
    channelbox.append(note('أضف هذا الرابط إلى زر «تواصل معنا» في موقعك. لن يُضاف تلقائياً إلى موقع آخر.'),el('a',{href:url,target:'_blank',rel:'noopener',style:'overflow-wrap:anywhere'},url));
  }
  wrap.append(channelbox);
  const stats=el('div',{style:'display:flex;flex-wrap:wrap;gap:14px;margin:16px 0'});
  for(const [label,v] of [['رسالة مسجلة',data.totals.received],['رد تلقائي',data.totals.automatic],['تحتاج متابعة',data.totals.open]]) stats.append(el('div',{class:'card',style:'padding:16px;min-width:150px'},el('strong',{style:'font-size:30px'},String(v)),note(label)));
  const report=el('pre',{style:'white-space:pre-wrap;font:inherit;line-height:1.9;background:var(--bg);padding:16px;border-radius:12px'},data.content);
  wrap.append(box('ملخص آخر 24 ساعة',stats,note('هذا ملخص الصندوق، وليس إحصاءات القنوات غير المربوطة. التقرير اليومي يظهر هنا وفي إشعارات رفيق.'),report));
  const question=el('input',{placeholder:'السؤال كما يكتبه العميل',required:true,maxlength:500,style:'width:100%;margin:8px 0'});
  const answer=el('textarea',{placeholder:'الإجابة المعتمدة، دون معلومات غير مؤكدة',required:true,maxlength:2000,rows:3,style:'width:100%;margin:8px 0'});
  const form=el('form',{onsubmit:async(e)=>{e.preventDefault();const submit=form.querySelector('button');submit.disabled=true;try {await api('POST','/api/customer-service/answers',{question:question.value,answer:answer.value});await reload();}catch(err){toast(err.message);}finally{submit.disabled=false;}}},question,answer,el('button',{class:'btn primary',type:'submit'},'اعتماد الإجابة وحفظها'));
  const knowledge=box('الإجابات المعتمدة',note('تطابق محدد بعد تجاهل التشكيل وعلامات الترقيم. لا يوجد إرسال إلى منصة ذكاء اصطناعي، ولا رد حر بلا مراجعة.'),form);
  const active=data.answers.filter(a=>a.enabled);
  if(!active.length) knowledge.append(note('لا توجد إجابات معتمدة بعد. الرد التلقائي لن يجيب عن الأسئلة الجديدة.'));
  for(const a of active) knowledge.append(el('div',{style:'padding:16px 0;border-bottom:1px solid var(--border)'},el('strong',{},a.question),note(a.answer),button('إيقاف الإجابة',async()=>{await api('POST',`/api/customer-service/answers/${a.id}/disable`,{});await reload();})));
  wrap.append(knowledge);
  const source=el('select',{}); for(const ch of data.channels)source.append(el('option',{value:ch.id},ch.name));
  const name=el('input',{placeholder:'اسم العميل، اختياري',maxlength:120});
  const body=el('textarea',{placeholder:'انسخ رسالة العميل هنا. ستُحفظ كإدخال يدوي، وليست رسالة مستوردة تلقائياً.',required:true,maxlength:4000,rows:3,style:'width:100%;margin:10px 0'});
  const manual=el('form',{onsubmit:async(e)=>{e.preventDefault();const submit=manual.querySelector('button');submit.disabled=true;try{await api('POST','/api/customer-service/messages',{channel:source.value,customer:name.value,body:body.value});await reload();}catch(err){toast(err.message);}finally{submit.disabled=false;}}},el('div',{style:'display:flex;flex-wrap:wrap;gap:10px'},source,name),body,el('button',{class:'btn',type:'submit'},'حفظ رسالة يدوية وإعداد مسودة'));
  wrap.append(box('إدخال رسالة من قناة غير مربوطة',manual));
  const inbox=box('صندوق الرسائل',note('أحدث 100 رسالة. المسودة لا تعني أنها أُرسلت.'));
  if(!data.messages.length)inbox.append(note('الصندوق فارغ. لا توجد قنوات اجتماعية مربوطة؛ لم يُفحص أي حساب خارجي.'));
  for(const m of data.messages) {
    const text=el('textarea',{rows:3,maxlength:2000,style:'width:100%;margin:12px 0','aria-label':'مسودة الرد'}); text.value=m.reply||'';
    const actions=el('div',{style:'display:flex;flex-wrap:wrap;gap:8px'},
      button('حفظ مسودة فقط',async()=>{await api('PATCH',`/api/customer-service/messages/${m.id}`,{reply:text.value});await reload();}),
      button(m.task_id?'مهمة المتابعة #'+m.task_id:'تحويل إلى مهمة',async()=>{const r=await api('POST',`/api/customer-service/messages/${m.id}/task`,{});toast('مهمة المتابعة #'+r.task_id);await reload();}),
      button(m.status==='open'?'إنهاء المتابعة':'إعادة فتح',async()=>{await api('PATCH',`/api/customer-service/messages/${m.id}`,{status:m.status==='open'?'done':'open'});await reload();}));
    if(m.source==='website')actions.append(button('إرسال النص إلى محادثة الموقع',async()=>{if(!confirm('هل تعتمد هذا النص وترسله إلى الزائر؟\n\n'+text.value))return;await api('PATCH',`/api/customer-service/messages/${m.id}`,{reply:text.value,deliver:true,status:'done'});await reload();}));
    inbox.append(el('article',{style:'padding:18px 0;border-top:1px solid var(--border)'},
      el('h3',{},'#'+m.id+' | '+data.channels.find(c=>c.id===m.channel).name+' | '+(m.customer||'عميل')),
      el('span',{class:'chip'},m.source==='manual'?'إدخال يدوي':'رسالة من رابط الموقع'),
      el('span',{class:m.status==='open'?'chip warn':'chip ok'},m.status==='open'?'للمتابعة':'مكتملة'),
      note(m.created_at),el('p',{style:'white-space:pre-wrap;overflow-wrap:anywhere'},m.body),
      note(m.reply_kind==='automatic'?'أُجيب تلقائياً بنص معتمد':m.reply_kind==='owner'?'أُرسل الرد إلى محادثة الموقع':'الرد أدناه مسودة فقط'),text,actions));
  }
  wrap.append(inbox);
  if(data.reports.length)wrap.append(box('التقارير اليومية المحفوظة',...data.reports.map(r=>el('details',{},el('summary',{},r.report_day),el('pre',{style:'white-space:pre-wrap;font:inherit;line-height:1.9'},r.content)))));
  return wrap;
}
