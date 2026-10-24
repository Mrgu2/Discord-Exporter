// Reads only the helper's short-lived public routing intent. Never reads login or chat.
try {
 const raw=new URLSearchParams(location.hash.slice(1)).get('archive-bind');
 if(raw){
  const meta=JSON.parse(atob(raw.replaceAll('-','+').replaceAll('_','/')));
  chrome.runtime.sendMessage({action:'intent',meta}).catch(()=>{});
  history.replaceState(null,'',location.pathname+location.search);
 }
}catch{}
