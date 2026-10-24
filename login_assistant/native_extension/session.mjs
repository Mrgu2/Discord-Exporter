export function sessionCandidate(details, tabID, expires, now=Date.now()) {
 if(!Number.isInteger(tabID)||details.tabId!==tabID||now>=expires||details.method!=='GET'||details.initiator!=='https://discord.com')return null;
 let url;try{url=new URL(details.url);}catch{return null;}
 if(url.origin!=='https://discord.com'||!/^\/api\/v\d+\/(?:users\/@me(?:\/|$)|channels\/\d+\/messages(?:\/|$))/.test(url.pathname))return null;
 const headers=details.requestHeaders||[];
 const value=headers.find(h=>h.name.toLowerCase()==='authorization')?.value;
 return typeof value==='string'&&value.length>=16&&value.length<=4096&&!/\s/.test(value)?value:null;
}
