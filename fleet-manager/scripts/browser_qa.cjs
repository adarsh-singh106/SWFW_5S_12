const fs=require('node:fs'), path=require('node:path'), assert=require('node:assert/strict');
let input=''; process.stdin.on('data',x=>input+=x); process.stdin.on('end',()=>run(JSON.parse(input)));
async function run(c){
 const report={assertions:[],screenshots:[],consoleErrors:[],failedRequests:[],navigationFailures:[],loginRequestFields:[]};
 let ws,id=0,expected=false;const pending=new Map();
 function send(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error('CDP timeout '+method))},10000);pending.set(n,{resolve:x=>{clearTimeout(timer);resolve(x)},reject:x=>{clearTimeout(timer);reject(x)}});ws.send(JSON.stringify({id:n,method,params}))})}
 async function ev(expression){const x=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(x.exceptionDetails)throw Error(x.exceptionDetails.exception?.description||x.exceptionDetails.text);return x.result?.value}
 const sleep=ms=>new Promise(r=>setTimeout(r,ms));
 async function until(expression,label){for(let n=0;n<100;n++){if(await ev(expression)){report.assertions.push(label);return}await sleep(50)}throw Error('Assertion failed: '+label)}
 const vis=id=>`getComputedStyle(document.getElementById(${JSON.stringify(id)})).display!=='none'`;
 const click=s=>ev(`document.querySelector(${JSON.stringify(s)}).focus();document.querySelector(${JSON.stringify(s)}).click()`);
 async function type(id,text){await ev(`document.getElementById(${JSON.stringify(id)}).focus();document.getElementById(${JSON.stringify(id)}).value=''`);await send('Input.insertText',{text});await ev(`document.getElementById(${JSON.stringify(id)}).dispatchEvent(new Event('input',{bubbles:true}))`)}
 const adminPassword='AdminPassword2026!';
 async function login(){await type('token-input',adminPassword);await click('#auth-submit-btn');await until(`!(${vis('auth-modal')}) && document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===3`,'form authentication loads inventory')}
 async function control(data){assert.equal((await fetch(c.base+'/__qa/control',{method:'POST',headers:{Authorization:'Bearer '+c.token,'Content-Type':'application/json'},body:JSON.stringify(data)})).status,200)}
 async function shot(name){const data=await send('Page.captureScreenshot',{format:'png'});const file=path.join(c.output,name+'.png');fs.writeFileSync(file,Buffer.from(data.data,'base64'),{flag:'wx'});report.screenshots.push(file)}
 try{
  const tabs=await(await fetch(`http://127.0.0.1:${c.debugPort}/json/list`)).json();ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
  ws.onmessage=e=>{const x=JSON.parse(e.data);if(x.id){const p=pending.get(x.id);pending.delete(x.id);if(p)x.error?p.reject(Error(x.error.message)):p.resolve(x.result);return}
   if(x.method==='Runtime.exceptionThrown')report.consoleErrors.push({type:'exception',data:x.params,expected:false});
   if(x.method==='Runtime.consoleAPICalled'&&['error','assert'].includes(x.params.type))report.consoleErrors.push({type:'console',data:x.params,expected:false});
   if(x.method==='Log.entryAdded'&&x.params.entry.level==='error')report.consoleErrors.push({type:'log',data:x.params.entry,expected:(expected && x.params.entry.source==='network')||x.params.entry.url?.endsWith('/favicon.ico')});
   if(x.method==='Network.loadingFailed')report.failedRequests.push({type:'transport',data:x.params,expected:false});
   if(x.method==='Network.requestWillBeSent'&&x.params.request.url.endsWith('/api/auth/login')&&x.params.request.postData){try{report.loginRequestFields.push(Object.keys(JSON.parse(x.params.request.postData)))}catch{report.loginRequestFields.push(['unparseable'])}}
   if(x.method==='Network.responseReceived'&&x.params.response.status>=400)report.failedRequests.push({type:'http',url:x.params.response.url,status:x.params.response.status,expected:expected||x.params.response.url.endsWith('/favicon.ico')});
  };
  for(const d of ['Page','Runtime','Log','Network'])await send(d+'.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  const nav=await send('Page.navigate',{url:c.base+'/dashboard'});if(nav.errorText){report.navigationFailures.push(nav.errorText);throw Error(nav.errorText)}
  await until(`document.readyState==='complete' && document.getElementById('auth-modal') && ${vis('auth-modal')}`,'auth modal rendered');await send('Page.bringToFront');await sleep(250);
  if(c.injectFailure)throw Error('Injected failure for cleanup verification');
  expected=true;
  report.validation422=await ev(`(async()=>{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});const body=await r.json();return {status:r.status,error:body.error||null,detail:(body.detail||[]).map(x=>({loc:x.loc,type:x.type}))}})()`);
  assert.equal(report.validation422.status,422);assert.ok(report.validation422.error||report.validation422.detail.length);
  report.assertions.push('actual browser 422 validation response inspected');expected=false;
  if(c.firstRun){
   await until(`${vis('auth-setup-view')} && document.activeElement===document.getElementById('setup-password')`,'first-run setup view and focus');
   await shot('01-first-run-setup');
   await type('setup-password',adminPassword);await type('setup-confirm-password',adminPassword);
   await click('#setup-submit-btn');
   await until(`!(${vis('auth-modal')}) && document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===3`,'first-run setup issues browser session and loads inventory');
  }else{
   await until(vis('auth-login-view'),'login view displayed');
   expected=true;await type('token-input','invalid-fixture');await click('#auth-submit-btn');await until(`document.getElementById('auth-error').textContent.includes('Invalid')`,'invalid authentication feedback');await sleep(100);expected=false;
   await type('token-input','CHANGEME');await shot('02-changeme-initial-login');
   await click('#auth-submit-btn');await until(vis('auth-change-password-view'),'mandatory password change view displayed');await shot('03-mandatory-password-change');
   await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
   await until(`${vis('auth-modal')} && ${vis('auth-change-password-view')} && document.querySelector('.app-header').inert`,'mandatory change ignores Escape and locks dashboard');
   await ev(`(async()=>{const fleet=await import('/static/js/fleet.js');await fleet.fetchFleetStatus()})()`);
   await until(`${vis('auth-change-password-view')} && document.getElementById('last-updated').textContent.includes('Browser refresh pending')`,'dashboard refresh stays blocked during mandatory change');
   await click('#auth-modal');await until(`${vis('auth-change-password-view')} && document.querySelector('.app-header').inert`,'mandatory change ignores outside click');
   await until(`document.getElementById('auth-storage-notice').textContent.includes('HttpOnly cookie') && !document.getElementById('auth-storage-notice').textContent.includes('JavaScript memory')`,'browser session copy accurately describes HttpOnly cookie');
   await click('#change-password-signout-btn');await until(`${vis('auth-login-view')} && ${vis('auth-modal')} && document.activeElement===document.getElementById('token-input')`,'mandatory change Sign out returns to login with focus');
   assert.equal((await ev(`(async()=>{const s=await(await fetch('/api/auth/session')).json();return s.authenticated})()`)),false);report.assertions.push('mandatory Sign out revokes session');
   await type('token-input','CHANGEME');await click('#auth-submit-btn');await until(vis('auth-change-password-view'),'mandatory change remains required after signing in again');
   await type('change-new-password',adminPassword);await type('change-confirm-password',adminPassword);await click('#change-password-submit-btn');
   await until(`!(${vis('auth-modal')}) && document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===3`,'password change establishes admin password and loads inventory');
  }
  await until(`document.querySelectorAll('.health-card').length===3 && document.querySelector('.health-card').textContent.includes('Target up')`,'Prometheus fixture populates Fleet Health cards');
  await ev(`document.getElementById('health-overview').textContent += ' · QA fixture metrics (not live host measurements)'`);
  await shot('05-authenticated-dashboard');
  await until(`document.querySelector('#health-detail .health-trend svg') && document.documentElement.scrollWidth<=innerWidth`,'health detail trends render without page overflow');
  await ev(`(async()=>{const api=await import('/static/js/api.js');api.showAlert('<script>unsafe</script>','danger',40)})()`);
  await until(`document.getElementById('global-alert').getAttribute('role')==='alert' && document.querySelector('.toast-message').textContent==='<script>unsafe</script>' && !document.querySelector('.toast script') && document.getElementById('global-alert').getBoundingClientRect().width<=380`,'compact error toast is live, safe text and bounded width');
  await sleep(80);await until(vis('global-alert'),'error toast waits for accessible dismissal');
  await click('.toast-dismiss');await until(`!(${vis('global-alert')})`,'error toast dismiss control works');
  await ev(`(async()=>{const api=await import('/static/js/api.js');api.showAlert('Saved','success',40)})()`);await until(`!(${vis('global-alert')})`,'success toast auto dismisses');
  await ev(`window.scrollTo({top:document.getElementById('fleet-health').offsetTop-190,behavior:'instant'})`);await shot('fleet-health');
  await ev(`window.scrollTo({top:document.getElementById('health-detail').offsetTop-190,behavior:'instant'})`);await shot('fleet-health-detail');
  await send('Page.reload');
  await until(`document.readyState==='complete' && !(${vis('auth-modal')}) && document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===3`,'dashboard refresh preserves active browser session and inventory');
  expected=true;
  const csrfRejection=await ev(`(async()=>{const r=await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin'});return {status:r.status,active:(await(await fetch('/api/auth/session')).json()).authenticated}})()`);
  assert.deepEqual(csrfRejection,{status:401,active:true});report.assertions.push('invalid CSRF cannot revoke browser session');expected=false;
  await click('#logout-btn');
  await until(vis('auth-modal'),'session locking on logout');
  await until(vis('auth-login-view'),'normal login view displayed after logout');
  await ev(`document.getElementById('auth-error').style.display='none'`);
  await shot('04-normal-login');
  await login();
  const fleetContract=await(await fetch(c.base+'/api/nodes/status',{headers:{Authorization:'Bearer '+c.token}})).json();
  await until(`document.getElementById('observation-ttl').textContent.includes('${fleetContract.observation_ttl_seconds}s') && document.getElementById('last-updated').textContent.includes('Last successful browser refresh')`,'API TTL and browser refresh time remain separate');
  await until(`document.querySelector('label[for="node-address"]').textContent==='Node address (IPv4, IPv6 or hostname)' && ['192.168.1.10','2001:db8::1','node-a.example.com'].every(x=>document.getElementById('node-address-help').textContent.includes(x))`,'registration explains IP and hostname syntax without implying DNS reachability');
  await ev(`(async()=>{const fleet=await import('/static/js/fleet.js');fleet.renderFleet({...${JSON.stringify({observation_ttl_seconds:180,nodes:[]})},configuration_issues:['FLEET_MANAGER_SSH_PRIVATE_KEY']})})()`);
  await until(`!document.getElementById('ssh-config-guidance').hidden && document.getElementById('ssh-config-guidance').textContent.includes('FLEET_MANAGER_SSH_PRIVATE_KEY') && !(${vis('global-alert')})`,'SSH configuration warning stays inline without global banner');
  await click('#refresh-btn');await until(`document.getElementById('ssh-config-guidance').hidden`,'inline SSH guidance clears after valid refresh');
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
  await ev(`window.scrollTo({top:document.getElementById('inventory-card').offsetTop-190,behavior:'instant'})`);await shot('inventory');
  await click('[data-node-id="1"] td:last-child button:nth-child(2)');await until(`document.getElementById('ops-node-title').textContent.includes('alpha') && document.querySelectorAll('.history-item').length===20`,'node selection and 20-record history');
  await click('.history-nav button:last-child');await until(`document.querySelectorAll('.history-item').length===5`,'history next page');await click('.history-nav button:first-child');await until(`document.querySelectorAll('.history-item').length===20`,'history previous page');
  await until(`document.getElementById('command-preview-text').textContent==='uptime'`,'initial command preview uptime');
  await click('#action-memory');await until(`document.getElementById('command-preview-text').textContent==='free -m'`,'preview updates to free -m');
  await click('#action-disk');await until(`document.getElementById('command-preview-text').textContent==='df -h -P -- /'`,'preview updates to df -h -P');
  await type('arg-disk-path','bad path');await until(`document.getElementById('arg-disk-error').textContent.includes('absolute POSIX') && document.getElementById('command-preview-text').textContent.includes('[invalid path]')`,'client inline validation error and preview indication');
  await type('arg-disk-path','/var/log');await until(`!document.getElementById('arg-disk-error').textContent && document.getElementById('command-preview-text').textContent==='df -h -P -- /var/log'`,'valid path clears error and updates preview');
  await click('#action-service');await until(`document.getElementById('command-preview-text').textContent==='systemctl --no-pager status -- ssh'`,'preview updates to systemctl status ssh');
  await click('#action-uptime');await until(`document.getElementById('command-preview-text').textContent==='uptime'`,'return to uptime');
  await click('#exec-btn');await until(`document.getElementById('op-result-box') && ${vis('op-result-box')} && document.getElementById('result-outcome-badge').textContent==='SUCCESS' && document.getElementById('result-stdout').textContent.includes('isolated uptime')`,'operation execution updates inspector with SUCCESS outcome and stdout');await ev(`window.scrollTo({top:document.getElementById('operations-workbench').offsetTop-190,behavior:'instant'})`);await shot('operations-workbench');
  await click('#copy-output-btn');await until(`document.getElementById('copy-btn-text').textContent==='Copied!'`,'copy button explicit feedback');
  await click('#audit-history-table tbody tr:first-child .inspect-btn');await until(`document.getElementById('inspector-mode-tag').textContent.includes('Historical') && document.querySelector('#audit-history-table tr.selected-history-row')`,'historical audit record inspection and row highlight');await ev(`window.scrollTo({top:document.querySelector('.workbench-history').offsetTop-190,behavior:'instant'})`);await shot('audit-history');
  await click('#return-to-inventory-btn');await until(`document.activeElement === document.querySelector('[data-node-id="1"] td:last-child button:nth-child(2)')`,'return to inventory restores focus');
  await click('[data-node-id="2"] td:last-child button:last-child');await until(`${vis('onboarding-modal')} && document.getElementById('bootstrap-cmd-snippet').textContent.includes('authorized_keys') && typeof document.getElementById('scan-host-key-btn').onclick==='function'`,'resume existing node and bootstrap display');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});await until(`document.getElementById('onboarding-modal').contains(document.activeElement)`,'keyboard focus inside modal');
  await click('#scan-host-key-btn');await until(`${vis('step-fp-box')} && document.getElementById('step-trust-btn').disabled`,'fresh scan requires independent acknowledgement');
  await until(`document.getElementById('scanned-fingerprint-content').textContent.startsWith('SHA256:') && document.getElementById('trusted-fingerprint-content').textContent.includes('None')`,'scanned and trusted fingerprints labelled separately');
  await ev(`document.getElementById('fingerprint-acknowledgement').focus()`);
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32});await send('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32});
  await until(`document.getElementById('fingerprint-acknowledgement').checked && !document.getElementById('step-trust-btn').disabled`,'keyboard acknowledgement enables explicit trust');
  await click('#step-trust-btn');await until(`document.getElementById('trusted-fingerprint-content').textContent.startsWith('SHA256:') && !(${vis('step-fp-box')})`,'explicit trust enrollment');
  await click('#onboarding-check-ssh-btn');await until(`document.getElementById('validation-result').textContent.includes('SSH connected') && document.getElementById('onboarding-setup-state').textContent.includes('previously passed')`,'actual SSH outcome and setup shown separately');await shot('onboarding-ready');
  expected=true;
  await ev(`(async()=>{const state=await import('/static/js/state.js');state.setOperatorToken('invalid-fixture')})()`);
  await click('#onboarding-primary-btn');
  await until(`${vis('auth-modal')} && !document.getElementById('auth-modal').inert && document.getElementById('onboarding-modal').inert && document.activeElement===document.getElementById('token-input')`,'authentication retry takes dialog ownership and keyboard focus');
  await login();expected=false;
  await until(`${vis('onboarding-modal')} && !document.getElementById('onboarding-modal').inert`,'onboarding resumes after authentication');
  await until(`document.getElementById('auth-modal').inert`,'hidden authentication dialog remains locked by onboarding');
  await until(`document.getElementById('onboarding-modal').contains(document.activeElement)`,'focus returns inside onboarding');
  await control({ssh_fail:true});await click('#onboarding-check-ssh-btn');
  await until(`document.getElementById('validation-result').textContent.includes('AUTH_FAILED') && document.getElementById('onboarding-setup-state').textContent.includes('needs attention')`,'HTTP success with failed SSH outcome is shown as failure');
  await control({ssh_fail:false});await click('#onboarding-check-ssh-btn');
  await until(`document.getElementById('validation-result').textContent.includes('SSH connected') && document.getElementById('onboarding-setup-state').textContent.includes('previously passed')`,'successful SSH retry restores verified setup');
  await ev(`(async()=>{const onboarding=await import('/static/js/node-onboarding.js');await onboarding.openOnboardingModal({id:1,name:'alpha-ready',address:'127.0.0.1',ssh_port:2201})})()`);
  await until(`document.getElementById('onboarding-node-title').textContent.includes('alpha-ready') && document.getElementById('auth-modal').inert && document.querySelector('.app-header').inert`,'direct node switch retains modal ownership');
  await control({scan_mismatch:true});await click('#scan-host-key-btn');
  await until(`document.getElementById('onboarding-feedback').textContent.includes('differs') && document.getElementById('scanned-fingerprint-content').textContent.startsWith('SHA256:') && document.getElementById('step-trust-btn').disabled && !document.getElementById('scan-host-key-btn').disabled`,'mismatched key blocks trust and permits rescan');await shot('onboarding-mismatch');
  await control({scan_mismatch:false});await click('#scan-host-key-btn');
  await until(`!document.getElementById('fingerprint-acknowledgement').checked && document.getElementById('step-trust-btn').disabled && !(${vis('step-fp-box')})`,'deliberate rescan clears acknowledgement');
  await ev(`document.getElementById('close-onboarding-btn').focus()`);
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});await until(`!(${vis('onboarding-modal')})`,'Escape dismisses onboarding');
  await until(`!document.querySelector('.app-header').inert && !document.getElementById('auth-modal').inert`,'closing onboarding restores background interaction');
  await control({delay:0.5});await click('[data-node-id="2"] td:last-child button:last-child');await sleep(100);await click('#close-onboarding-btn');await click('[data-node-id="3"] td:last-child button:last-child');await sleep(700);await until(`document.getElementById('onboarding-node-title').textContent.includes('gamma') && ${vis('step-complete-box')} && document.getElementById('onboarding-setup-state').textContent!=='Loading' && typeof document.getElementById('scan-host-key-btn').onclick==='function'`,'delayed response keeps current node and visible status panel');await click('#scan-host-key-btn');await until(vis('step-trust-btn'),'current modal handlers remain valid');await click('#close-onboarding-btn');await control({delay:0});
  expected=true;await control({outage:true});await click('#refresh-btn');await until(`document.getElementById('inventory-card').getAttribute('data-refresh-state')==='unverified' && document.getElementById('last-updated').textContent.includes('stale/unverified') && document.getElementById('last-updated').textContent.includes('Last successful browser refresh')`,'API outage marks stale data and preserves last success time');await control({outage:false});await click('#refresh-btn');await until(`document.getElementById('last-updated').textContent.startsWith('Browser refreshed successfully.') && !document.getElementById('inventory-card').hasAttribute('data-refresh-state')`,'API outage recovery');await sleep(100);expected=false;
  for(const [width,height] of [[1440,900],[1024,800],[768,1024],[390,844]]){
   await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   await ev('window.scrollTo(0,0);document.querySelector(".table-responsive").scrollLeft=0');
   await until(`innerWidth===${width} && document.documentElement.scrollWidth<=innerWidth && scrollY===0`,'responsive viewport '+width+'x'+height);
   if(width===1440)await until(`document.querySelector('.table-responsive').scrollWidth<=document.querySelector('.table-responsive').clientWidth && [...document.querySelectorAll('.inventory-actions')].every(x=>x.getBoundingClientRect().right<=document.querySelector('.table-responsive').getBoundingClientRect().right)`,'1440 inventory actions fit without horizontal scrolling');
   if(width===1024)await until(`getComputedStyle(document.querySelector('.inventory-table td:nth-child(2)')).display==='none' && getComputedStyle(document.querySelector('.inventory-actions')).display!=='none'`,'1024 priority columns and actions');
   if(width===768)await until(`document.querySelector('.table-responsive').scrollWidth>document.querySelector('.table-responsive').clientWidth && getComputedStyle(document.querySelector('.inventory-table td:nth-child(3)')).display!=='none'`,'768 semantic table has internal scroll with connectivity visible');
   if(width===390)await until(`getComputedStyle(document.querySelector('#nodes-table-body tr[data-node-id]')).display==='grid' && document.querySelector('#nodes-table-body tr[data-node-id]').textContent.includes('Operations')`,'390 node record layout and primary action');
   await until(`document.querySelectorAll('.health-card').length===3 && [...document.querySelectorAll('.health-card')].every(x=>x.getBoundingClientRect().right<=innerWidth) && document.getElementById('global-alert').getBoundingClientRect().width<=380`,'health cards and toast fit viewport '+width);
   await shot('dashboard-'+width+'x'+height);
   await ev(`document.getElementById('operations-workbench').scrollIntoView({behavior:'instant',block:'start'})`);
   await sleep(100);
   await until(`document.documentElement.scrollWidth<=innerWidth`,'workbench fits without page-level horizontal overflow at '+width);
   await shot('workbench-'+width+'x'+height);
   await ev('window.scrollTo(0,0)');await sleep(100);
   await click('[data-node-id="2"] td:last-child button:last-child');
   await until(`${vis('onboarding-modal')} && document.getElementById('onboarding-setup-state').textContent!=='Loading' && document.getElementById('trusted-fingerprint-content').textContent!=='Loading'`,'onboarding dialog loads at '+width);
   await until(`document.querySelector('.onboarding-dialog').getBoundingClientRect().bottom<=innerHeight && document.querySelector('.onboarding-dialog-footer').getBoundingClientRect().bottom<=innerHeight && document.querySelector('.onboarding-dialog-header').getBoundingClientRect().top>=0`,'modal header and footer reachable at '+width);
   await until(`document.querySelector('.onboarding-dialog-header').getBoundingClientRect().left>=0 && document.getElementById('close-onboarding-btn').getBoundingClientRect().right<=innerWidth && document.getElementById('onboarding-scroll').scrollWidth<=document.getElementById('onboarding-scroll').clientWidth && document.getElementById('bootstrap-cmd-snippet').getBoundingClientRect().right<=innerWidth`,'onboarding text and close control avoid horizontal clipping at '+width);
   await shot('onboarding-'+width+'x'+height);
   await click('#close-onboarding-btn');
   if(width===390){
    await ev(`window.scrollTo({top:document.querySelector('#nodes-table-body tr[data-node-id]').getBoundingClientRect().top+scrollY-320,behavior:'instant'})`);
    await sleep(150);await shot('inventory-390x844');
   }
  }
  for(const [width,height] of [[768,420],[390,500]]){
   await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
   await click('[data-node-id="2"] td:last-child button:last-child');await until(vis('onboarding-modal'),'short modal opens');
   await until(`document.querySelector('.onboarding-dialog').getBoundingClientRect().bottom<=innerHeight && document.getElementById('onboarding-scroll').scrollHeight>document.getElementById('onboarding-scroll').clientHeight && document.querySelector('.onboarding-dialog-footer').getBoundingClientRect().bottom<=innerHeight && document.documentElement.scrollWidth<=innerWidth`,'short modal scroll and controls fit '+width);
   await shot('onboarding-'+width+'x'+height);
   await click('#close-onboarding-btn');
  }
  await control({expire_sessions:true});
  expected=true;await click('#refresh-btn');await until(vis('auth-modal'),'expired session prompts re-authentication');
  const unauthorizedCount=()=>report.failedRequests.filter(x=>x.status===401&&x.url.endsWith('/api/nodes/status')).length;
  const firstUnauthorized=unauthorizedCount();assert.equal(firstUnauthorized,1,'one status request detects expiry');
  await sleep(11000);assert.equal(unauthorizedCount(),firstUnauthorized,'no repeated unauthorized polling');report.assertions.push('no repeated unauthorized polling after expiry');
  await login();expected=false;
  await until(`document.querySelectorAll('#nodes-table-body tr[data-node-id]').length===3`,'re-authentication restores inventory');
  assert.equal(report.consoleErrors.filter(x=>!x.expected).length,0,'unexpected console/module errors');assert.equal(report.failedRequests.filter(x=>!x.expected).length,0,'unexpected failed requests');report.assertions.push('console/network/module/navigation inspection');report.passed=true;
 }catch(e){report.passed=false;report.failure=e.stack;process.exitCode=1;try{if(ws?.readyState===1)await shot('failure')}catch{}}
 finally{fs.writeFileSync(path.join(c.output,'browser.json'),JSON.stringify(report,null,2),{flag:'wx'});try{if(ws?.readyState===1)await send('Browser.close')}catch{}ws?.close();console.log(JSON.stringify({passed:report.passed,assertions:report.assertions,failure:report.failure},null,2))}
}
