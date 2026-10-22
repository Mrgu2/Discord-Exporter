import assert from 'node:assert/strict';
import {requestCandidate,validSessionCandidate,safePageState} from '../scripts/connect_browser.mjs';

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
assert.equal(safePageState('https://discord.com/login?redirect_to=private'),'discord_login');
assert.equal(safePageState('https://discord.com/channels/123/456'),'discord_channels');
assert.equal(safePageState('about:blank'),'blank');
assert.equal(safePageState('https://elsewhere.invalid/private'),'other_site');
assert.ok(!JSON.stringify(safePageState('https://discord.com/channels/123/456')).includes('123'));
console.log('Scoped browser session checks passed; no browser or real credential was accessed.');
