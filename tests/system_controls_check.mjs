// All mutations, startup changes and host power requests are intercepted.
import assert from 'node:assert/strict';
import {loadPlaywright,browserOptions} from '../scripts/browser_runtime.mjs';
const p=await loadPlaywright({localOnly:true});
const browser=await p.chromium.launch({headless:true,...browserOptions(p)});
const base=process.argv[2]||'http://127.0.0.1:8765';
assert.equal(new URL(base).hostname,'127.0.0.1');
try{
  for(const system of ['darwin','linux'])for(const width of [390,1360]){
    const page=await browser.newPage({viewport:{width,height:1000}});
    const data={platform:{system},config:{channels:[],schedule:{enabled:false},model:{}},credentials:{discord:false},archive:{message_count:0},state:{},drafts:[],runs:[],remote:{},service:{available:true,instance:'fictional'},
      system:{startup:{available:true,enabled:false,scope:system==='linux'?'boot':'login',note:'关闭开关不会停止当前服务。'},power:{supported:system==='linux',reboot:false,poweroff:false,note:'需要系统授权'}}};
    let powerCalls=0,startupCalls=0;
    await page.route('**/api/**',async route=>{
      const request=route.request(),path=new URL(request.url()).pathname;
      if(request.method()!=='GET'){
        if(path==='/api/autostart'){
          startupCalls++;data.system.startup.enabled=request.postDataJSON().enabled;
          return route.fulfill({json:data.system.startup});
        }
        if(path==='/api/host-power'){
          powerCalls++;const value=request.postDataJSON();assert.equal(value.confirmation,'重启服务器');
          data.service.action='host-'+value.action;
          return route.fulfill({status:202,json:{action:data.service.action}});
        }
        throw new Error('Unexpected mutation: '+path);
      }
      await route.fulfill({json:data});
    });
    await page.goto(base+'/web/index.html');
    await page.waitForFunction(()=>!document.querySelector('#startup-controls').hidden);
    await page.locator('#advanced-settings').evaluate(el=>el.open=true);
    assert.equal(await page.locator('#startup-label').textContent(),system==='linux'?'开机后自动运行':'登录后自动运行');
    await page.locator('label:has(#startup-enabled)').click();
    await page.waitForFunction(()=>!document.querySelector('#startup-enabled').disabled);
    assert.equal(data.system.startup.enabled,true);
    await page.locator('label:has(#startup-enabled)').click();
    await page.waitForFunction(()=>!document.querySelector('#startup-enabled').disabled);
    assert.equal(data.system.startup.enabled,false);assert.equal(startupCalls,2);
    assert.equal(powerCalls,0);
    if(system==='linux'){
      assert.ok(await page.locator('#host-reboot').isDisabled());
      data.system.power.reboot=true;await page.locator('#refresh-button').click();
      await page.waitForFunction(()=>!document.querySelector('#host-reboot').disabled);
      page.once('dialog',dialog=>{assert.ok(dialog.message().includes('当前未开启自动启动'));return dialog.dismiss();});await page.locator('#host-reboot').click();assert.equal(powerCalls,0);
      page.once('dialog',dialog=>dialog.accept('yes'));await page.locator('#host-reboot').click();assert.equal(powerCalls,0);
      page.once('dialog',dialog=>dialog.accept('重启服务器'));await page.locator('#host-reboot').click();
      await page.waitForFunction(()=>document.querySelector('#service-control-status').textContent.includes('重启服务器'));
      assert.equal(powerCalls,1);
    }else assert.ok(await page.locator('#host-power-controls').isHidden());
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.close();
  }
  console.log('Mac/Linux 桌面与手机宽度：自启动开关、权限禁用、电源取消/错误确认/正确确认均通过；所有变更使用模拟接口。');
}finally{await browser.close();}
