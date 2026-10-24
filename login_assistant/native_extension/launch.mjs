// A toolbar click opens a persistent confirmation page. No page is observed here.
chrome.action.onClicked.addListener(tab=>{
 const query=new URLSearchParams();if(Number.isInteger(tab.id))query.set('tab',String(tab.id));
 chrome.tabs.create({url:chrome.runtime.getURL('popup.html')+'?'+query});
});
