import assert from 'node:assert/strict';
import {requestCandidate,validSessionCandidate} from '../scripts/connect_browser.mjs';

const fictitious='fictitious-session-not-a-real-credential';
let reads=0;
const request=url=>({url:()=>url,allHeaders:async()=>{reads++;return {authorization:fictitious};}});
assert.equal(await requestCandidate(request('https://discord.com/api/v10/users/@me')),fictitious);
assert.equal(await requestCandidate(request('https://discord.com/api/v10/channels/123/messages?limit=100')),fictitious);
const before=reads;
for(const url of ['https://elsewhere.invalid/api/v10/users/@me','https://discord.com.attacker.invalid/api/v10/users/@me','http://discord.com/api/v10/users/@me','https://discord.com/login','https://discord.com/api/v10/auth/login']){
  assert.equal(await requestCandidate(request(url)),null);
}
assert.equal(reads,before,'Unrelated origins and login forms must not be inspected');
assert.equal(validSessionCandidate('short'),null);
assert.equal(validSessionCandidate('fictitious credential contains spaces'),null);
assert.equal(validSessionCandidate(fictitious),fictitious);
console.log('Scoped browser session checks passed; no browser or real credential was accessed.');
