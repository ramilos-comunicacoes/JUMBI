(() => {
  const form = document.getElementById('customization-form');
  if (!form) return;
  document.querySelectorAll('.customization-index a').forEach(link=>link.addEventListener('click',()=>{const section=document.querySelector(link.getAttribute('href')); if(section)section.open=true;}));
  form.querySelectorAll('.has-error').forEach(field=>{const section=field.closest('details');if(section)section.open=true;});
  form.addEventListener('invalid',event=>{const section=event.target.closest('details');if(section)section.open=true;},true);
  const preview = document.querySelector('[data-brand-preview]');
  const ink = color => {
    const rgb = [1,3,5].map(i => parseInt(color.slice(i,i+2),16)/255).map(v => v <= .04045 ? v/12.92 : ((v+.055)/1.055)**2.4);
    return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722 > .179 ? '#10131a' : '#ffffff';
  };
  for (const [name,variable] of [['brand_primary_color','primary'],['brand_sidebar_color','sidebar'],['brand_accent_color','accent']]) {
    const control=form.elements[name];
    control?.addEventListener('input',()=> {preview.style.setProperty('--office-'+variable,control.value); if(variable!=='accent') preview.style.setProperty('--office-'+variable+'-ink',ink(control.value));});
  }
  form.elements.system_title?.addEventListener('input',e=>{document.querySelector('[data-preview-title]').textContent=e.target.value||'JUMBI';});
  for (const [name,selector] of [['brand_logo','[data-preview-logo]'],['brand_collapsed_logo','[data-preview-icon]'],['brand_favicon','[data-preview-icon]']]) {
    let previous;
    form.elements[name]?.addEventListener('change',e=>{const file=e.target.files?.[0]; if(!file || file.size>2*1024*1024 || !/^image\/(png|jpeg|webp|x-icon|vnd.microsoft.icon)$/.test(file.type)) return; if(previous) URL.revokeObjectURL(previous);previous=URL.createObjectURL(file);document.querySelector(selector).src=previous;});
  }
  document.querySelectorAll('[data-order]').forEach(button=>button.addEventListener('click',()=>{
    const row=button.closest('li'), neighbor=button.dataset.order==='up'?row.previousElementSibling:row.nextElementSibling;
    if(!neighbor)return;
    if(button.dataset.order==='up')neighbor.before(row);else neighbor.after(row);
    button.focus();document.querySelector('[data-order-feedback]').textContent=row.querySelector('span').textContent+' reposicionado. Salve para aplicar.';
  }));
  document.querySelector('[data-reset-personal-theme]')?.addEventListener('click',()=>{try{localStorage.removeItem(document.documentElement.dataset.preferenceKey+':theme');}catch(_){}const theme=form.elements.theme.value;document.documentElement.dataset.theme=theme==='system'?(matchMedia('(prefers-color-scheme:light)').matches?'light':'dark'):theme;});
})();
