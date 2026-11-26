'use strict';
document.getElementById('change').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target, status = document.getElementById('status'), button = form.querySelector('button');
  const current = document.getElementById('current'), next = document.getElementById('new'), confirm = document.getElementById('confirm');
  if (next.value !== confirm.value) { status.textContent = 'كلمتا المرور الجديدتان غير متطابقتين.'; return; }
  if (next.value === current.value) { status.textContent = 'اختر كلمة مرور جديدة تختلف عن المؤقتة.'; return; }
  button.disabled = true;
  try {
    const r = await fetch('/api/password', {method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json','X-Harith':'1'}, body:JSON.stringify({current:current.value,new:next.value})});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'تعذر حفظ كلمة المرور.');
    form.reset(); status.textContent = 'حُفظت كلمة المرور الجديدة. سجّل الدخول بها الآن.';
    button.textContent = 'الانتقال لتسجيل الدخول'; button.type = 'button'; button.onclick = () => location.replace('/');
  } catch (e) { status.textContent = e.message; }
  finally { button.disabled = false; }
});
