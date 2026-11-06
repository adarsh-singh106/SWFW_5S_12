const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
let input=''; process.stdin.on('data',x=>input+=x); process.stdin.on('end',()=>run(JSON.parse(input)));
async function run(c){
 const report={assertions:[],screenshots:[],consoleErrors:[],failedRequests:[],navigationFailures:[]};
 let ws,id=0,expected=false;const pending=new Map();
 function send(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error('CDP timeout '+method))},10000);pending.set(n,{resolve:x=>{clearTimeout(timer);resolve(x)},reject:x=>{clearTimeout(timer);reject(x)}});ws.send(JSON.stringify({id:n,method,params}))})}
 async function ev(expression){const x=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(x.exceptionDetails)throw Error(x.exceptionDetails.exception?.description||x.exceptionDetails.text);return x.result?.value}
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 async function until(expression,label){for(let n=0;n<100;n++){if(await ev(expression)){report.assertions.push(label);return}await sleep(50)}throw Error('Assertion failed: '+label)}
 const vis=id=>`getComputedStyle(document.getElementById(${JSON.stringify(id)})).display!=='none'`;
 const click=s=>ev(`document.querySelector(${JSON.stringify(s)}).focus();document.querySelector(${JSON.stringify(s)}).click()`);
 async function type(id,text){await ev(`document.getElementById(${JSON.stringify(id)}).focus();document.getElementById(${JSON.stringify(id)}).value=''`);await send('Input.insertText',{text});await ev(`document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('input',{bubbles:true}))`)}
 async function login(){await type('token-input',c.token);await click('#auth-submit-btn');await until(`!(${vis('auth-modal')}) && document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===3`,'form authentication loads inventory')}
 async function control(data){assert.equal((await fetch(c.base+'/__qa/control',{method:'POST',headers:{Authorization:'Bearer '+c.token,'Content-Type':'application/json'},body:JSON.stringify(data)})).status,200)}
 async function shot(name){const data=await send('Page.captureScreenshot',{format:'png'});const file=path.join(c.output,name+'.png');fs.writeFileSync(file,Buffer.from(data.data,'base64'),{flag:'wx'});report.screenshots.push(file)}
 try{
  const tabs=await(await fetch(`http://127.0.0.1:${c.debugPort}/json/list`)).json();ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  ws.onmessage=e=>{const x=JSON.parse(e.data);if(x.id){const p=pending.get(x.id);pending.delete(x.id);if(p)x.error?p.reject(Error(x.error.message)):p.resolve(x.result);return}
   if(x.method==='Runtime.exceptionThrown')report.consoleErrors.push({type:'exception',data:x.params,expected:false});
   if(x.method==='Runtime.consoleAPICalled'&&['error','assert'].includes(x.params.type))report.consoleErrors.push({type:'console',data:x.params,expected:false});
   if(x.method==='Log.entryAdded'&&x.params.entry.level==='error')report.consoleErrors.push({type:'log',data:x.params.entry,expected:(expected && x.params.entry.source==='network')||x.params.entry.url?.endsWith('/favicon.ico')});
   if(x.method==='Network.loadingFailed')report.failedRequests.push({type:'transport',data:x.params,expected:false});
   if(x.method==='Network.responseReceived'&&x.params.response.status>=400)report.failedRequests.push({type:'http',url:x.params.response.url,status:x.params.response.status,expected:expected||x.params.response.url.endsWith('/favicon.ico')});
  };
  for(const d of ['Page','Runtime','Log','Network'])await send(d+'.enable');
  const nav=await send('Page.navigate',{url:c.base+'/dashboard'});if(nav.errorText){report.navigationFailures.push(nav.errorText);throw Error(nav.errorText)}
  await until(`document.readyState==='complete' && document.getElementById('auth-modal') && ${vis('auth-modal')}`,'auth modal rendered');await send('Page.bringToFront');await sleep(250);
  if(c.injectFailure)throw Error('Injected failure for cleanup verification');
  expected=true;await type('token-input','invalid-fixture');await click('#auth-submit-btn');await until(`document.getElementById('auth-error').textContent.includes('Invalid')`,'invalid authentication feedback');await sleep(100);expected=false;
  await login();
  const fleetContract=await(await fetch(c.base+'/api/nodes/status',{headers:{Authorization:'Bearer '+c.token}})).json();
  await until(`document.getElementById('observation-ttl').textContent.includes('${fleetContract.observation_ttl_seconds}s') && document.getElementById('last-updated').textContent.includes('Last successful browser refresh')`,'API TTL and browser refresh time remain separate');
  await until(`[...document.querySelectorAll('.app-header .icon')].every(icon=>icon.getBBox().width>0 && icon.getBBox().height>0 && icon.querySelector('use')?.getAttribute('href')?.startsWith('/static/icons.svg#'))`,'local SVG sprite symbols render in shell');
  await until(`![...document.querySelectorAll('.app-header')].some(el=>/[\u{1F300}-\u{1FAFF}]/u.test(el.textContent))`,'no emoji interface icons in shell');
  await ev(`document.getElementById('refresh-btn').focus()`);await until(`getComputedStyle(document.getElementById('refresh-btn')).outlineStyle==='solid' && parseFloat(getComputedStyle(document.getElementById('refresh-btn')).outlineWidth)>=3`,'keyboard focus visible on shell action');
  await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await until(`parseFloat(getComputedStyle(document.querySelector('.status-dot')).animationDuration)<=0.00001 && parseFloat(getComputedStyle(document.querySelector('.btn')).transitionDuration)<=0.00001`,'reduced motion suppresses animation and transition');
  await send('Emulation.setEmulatedMedia',{features:[]});
  await until(`performance.getEntriesByType('resource').every(x=>new URL(x.name).origin===location.origin)`,'no remote assets requested');
  await click('#logout-btn');await until(vis('auth-modal'),'session locking');
  await send('Page.reload');await until(`document.readyState==='complete' && ${vis('auth-modal')}`,'reload requires fresh authentication');await sleep(250);await login();
  await type('search-input','beta');await until(`document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===1 && document.querySelector('#nodes-table-body tr').dataset.nodeId==='2' && document.getElementById('inventory-results').textContent.includes('1 of 3')`,'search exact matching row and visible count');await type('search-input','');
  await click('[data-filter="REACHABLE"]');await until(`document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===1 && document.querySelector('[data-filter="REACHABLE"]').getAttribute('aria-pressed')==='true'`,'reachable filter');
  await click('[data-filter="STALE"]');await until(`document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===0`,'zero-result filter');await click('[data-filter="ALL"]');
  await until(`![...document.querySelectorAll('.inventory-panel')].some(el=>/[\u{1F300}-\u{1FAFF}]/u.test(el.textContent))`,'no emoji interface glyphs in inventory');
  await click('[data-node-id="1"] td:last-child button:nth-child(2)');await until(`document.getElementById('ops-node-title').textContent.includes('alpha') && document.querySelectorAll('.history-item').length===20`,'node selection and 20-record history');
  await click('.history-nav button:last-child');await until(`document.querySelectorAll('.history-item').length===5`,'history next page');await click('.history-nav button:first-child');await until(`document.querySelectorAll('.history-item').length===20`,'history previous page');
  await click('[data-node-id="2"] td:last-child button:last-child');await until(`${vis('onboarding-modal')} && document.getElementById('bootstrap-cmd-snippet').textContent.includes('authorized_keys')`,'resume existing node and bootstrap display');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await until(`document.getElementById('onboarding-modal').contains(document.activeElement)`,'keyboard focus inside modal');
  await click('#scan-host-key-btn');await until(vis('step-trust-btn'),'host-key scan offers explicit enrollment');await click('#step-trust-btn');await until(`document.getElementById('scanned-fingerprint-content').textContent.includes('Trust: TRUSTED') && !(${vis('step-trust-btn')})`,'explicit trust enrollment');
  await click('#onboarding-check-ssh-btn');await until(vis('step-complete-box'),'current configuration SSH authentication');await shot('onboarding-ready');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await until(`!(${vis('onboarding-modal')})`,'Escape dismisses onboarding');
  await control({delay:0.5});await click('[data-node-id="2"] td:last-child button:last-child');await sleep(100);await click('#close-onboarding-btn');await click('[data-node-id="3"] td:last-child button:last-child');await sleep(700);await until(`document.getElementById('onboarding-node-title').textContent.includes('gamma') && !(${vis('step-complete-box')})`,'delayed response cannot cross node ownership');await click('#scan-host-key-btn');await until(vis('step-trust-btn'),'current modal handlers remain valid');await click('#close-onboarding-btn');await control({delay:0});
  expected=true;await control({outage:true});await click('#refresh-btn');await until(`document.getElementById('inventory-card').getAttribute('data-refresh-state')==='unverified' && document.getElementById('last-updated').textContent.includes('stale/unverified') && document.getElementById('last-updated').textContent.includes('Last successful browser refresh')`,'API outage marks stale data and preserves last success time');await control({outage:false});await click('#refresh-btn');await until(`document.getElementById('last-updated').textContent.startsWith('Browser refreshed successfully.') && !document.getElementById('inventory-card').hasAttribute('data-refresh-state')`,'API outage recovery');await sleep(100);expected=false;
  for(const [width,height] of [[1440,900],[1024,800],[768,1024],[390,844]]){
   await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   await ev('window.scrollTo(0,0);document.querySelector(".table-responsive").scrollLeft=0');
   await until(`innerWidth===${width} && document.documentElement.scrollWidth<=innerWidth && scrollY===0`,'responsive viewport '+width+'x'+height);
   if(width===1440)await until(`document.querySelector('.table-responsive').scrollWidth<=document.querySelector('.table-responsive').clientWidth && [...document.querySelectorAll('.inventory-actions')].every(x=>x.getBoundingClientRect().right<=document.querySelector('.table-responsive').getBoundingClientRect().right)`,'1440 inventory actions fit without horizontal scrolling');
   if(width===1024)await until(`getComputedStyle(document.querySelector('.inventory-table td:nth-child(2)')).display==='none' && getComputedStyle(document.querySelector('.inventory-actions')).display!=='none'`,'1024 priority columns and actions');
   if(width===768)await until(`document.querySelector('.table-responsive').scrollWidth>document.querySelector('.table-responsive').clientWidth && getComputedStyle(document.querySelector('.inventory-table td:nth-child(3)')).display!=='none'`,'768 semantic table has internal scroll with connectivity visible');
   if(width===390)await until(`getComputedStyle(document.querySelector('#nodes-table-body tr[data-node-id]')).display==='grid' && document.querySelector('#nodes-table-body tr[data-node-id]').textContent.includes('Operations')`,'390 node record layout and primary action');
   await shot('dashboard-'+width+'x'+height);
   if(width===390){
    await ev(`window.scrollTo({top:document.querySelector('#nodes-table-body tr[data-node-id]').getBoundingClientRect().top+scrollY-320,behavior:'instant'})`);
    await sleep(150);await shot('inventory-390x844');
   }
  }
  assert.equal(report.consoleErrors.filter(x=>!x.expected).length,0,'unexpected console/module errors');assert.equal(report.failedRequests.filter(x=>!x.expected).length,0,'unexpected failed requests');report.assertions.push('console/network/module/navigation inspection');report.passed=true;
 }catch(e){report.passed=false;report.failure=e.stack;process.exitCode=1;try{if(ws?.readyState===1)await shot('failure')}catch{}}
 finally{fs.writeFileSync(path.join(c.output,'browser.json'),JSON.stringify(report,null,2),{flag:'wx'});try{if(ws?.readyState===1)await send('Browser.close')}catch{}ws?.close();console.log(JSON.stringify({passed:report.passed,assertions:report.assertions,failure:report.failure},null,2))}
}
