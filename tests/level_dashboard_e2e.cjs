// Local visual checks. All API requests are intercepted; no database writes.
const assert=require('node:assert/strict');
const path=require('path');
const {chromium}=require(path.join(process.cwd(),'.test-runtime/ui/node_modules/playwright'));
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  let fail=false;
  let reading={ts:Math.floor(Date.now()/1000),edad_s:0,en_linea:true,sin_datos:false,temperatura:23,nivel_agua:95,turbidez:12,distancia_cm:2.29,nivel_calibracion:'provisional-7.8-2.0',nivel_estado:'valida'};
  await page.route('**/api/**',async route=>{
   const p=new URL(route.request().url()).pathname;
   if(p==='/api/me')return route.fulfill({json:{usuario:'Prueba visual local',csrf_token:'test-only'}});
   if(p==='/api/dispositivos')return route.fulfill({json:{dispositivos:[{id:1,asignacion_id:1,nombre:'Pecera de prueba',en_linea:true,envios_activos:true,anterior:false,ultima:reading.ts}]}});
   if(p==='/api/lecturas/ultima')return route.fulfill(fail?{status:503,json:{detail:'Simulated connection failure'}}:{json:reading});
   return route.fulfill({json:{registros:[]}});
  });
  await page.goto(process.env.AQUAMONITOR_TEST_ORIGIN || 'http://127.0.0.1:5000/',{waitUntil:'networkidle'});
  await page.locator('#app').waitFor({state:'visible'});
  for(const value of [0,25,50,71.2,75,95,100]) {
   reading={...reading,nivel_agua:value,distancia_cm:value===0?7.8:value===25?6.35:value===50?4.9:value===71.2?3.67:value===75?3.45:value===95?2.29:2.0,edad_s:0,ts:Math.floor(Date.now()/1000)};
   await page.evaluate(()=>actualizarLecturas());
   await page.waitForFunction(expected=>{
    const water=document.getElementById('agua-nivelAgua'),glass=water.parentElement;
    return Math.abs(water.getBoundingClientRect().height/glass.getBoundingClientRect().height*100-expected)<0.2;
   },value);
   assert.ok((await page.locator('#val-nivelAgua').innerText()).startsWith(value.toFixed(1)));
   assert.equal(await page.locator('#agua-nivelAgua').evaluate(el=>getComputedStyle(el,'::before').animationName),'ola');
   assert.equal(await page.locator('#nivel-sin-lectura').isVisible(),false);
   if(value===71.2){
    const original=require('node:child_process').execFileSync('git',['show','563ca98:public/styles.css'],{encoding:'utf8'});
    const reference=await page.addStyleTag({content:original});
    await page.locator('link[href*="styles.css"]').evaluate(el=>el.disabled=true);
    await page.locator('.tanque').screenshot({path:'.test-runtime/water-git-reference-71_2.png'});
    await page.locator('link[href*="styles.css"]').evaluate(el=>el.disabled=false);
    await reference.evaluate(el=>el.remove());
    await page.locator('.tanque').screenshot({path:'.test-runtime/water-restored-71_2.png'});
   }
  }
  assert.match(await page.locator('#distancia-nivelAgua').innerText(),/2.00 cm/);
  reading={...reading,nivel_agua:87.6,distancia_cm:null,nivel_calibracion:null,nivel_estado:undefined};
  await page.evaluate(()=>actualizarLecturas());
  assert.equal((await page.locator('#val-nivelAgua').innerText()).trim(),'--');
  assert.match(await page.locator('#desc-nivelAgua').innerText(),/Sin lectura/);
  assert.equal(await page.locator('#nivel-sin-lectura').isVisible(),true);
  await page.locator('.tanque').screenshot({path:'.test-runtime/water-no-valid-reading.png'});
  for(const bad of [
   {nivel_agua:0,distancia_cm:null,nivel_calibracion:null,nivel_estado:undefined},
   {nivel_agua:87.6,distancia_cm:8.11,nivel_calibracion:'legacy-30-5',nivel_estado:'valida'},
   {nivel_agua:87.6,distancia_cm:8.11,nivel_calibracion:'provisional-7.8-2.0',nivel_estado:'calibracion_incompatible'}
  ]){
   reading={...reading,...bad};await page.evaluate(()=>actualizarLecturas());
   assert.equal((await page.locator('#val-nivelAgua').innerText()).trim(),'--');
   assert.equal(await page.locator('#nivel-sin-lectura').isVisible(),true);
  }
  reading={...reading,distancia_cm:2.29,nivel_calibracion:'provisional-7.8-2.0',nivel_estado:'valida'};
  reading={...reading,nivel_agua:150};await page.evaluate(()=>actualizarLecturas());
  assert.equal((await page.locator('#val-nivelAgua').innerText()).trim(),'--');
  reading={...reading,nivel_agua:95,edad_s:60,ts:Math.floor(Date.now()/1000)-60};await page.evaluate(()=>actualizarLecturas());
  assert.equal((await page.locator('#val-nivelAgua').innerText()).trim(),'--');
  reading={...reading,edad_s:0,ts:Math.floor(Date.now()/1000)};await page.evaluate(()=>actualizarLecturas());
  await page.evaluate(()=>{lecturaVigenteHasta=performance.now()-1;verificarVigenciaLectura();});
  assert.equal((await page.locator('#val-nivelAgua').innerText()).trim(),'--');
  await page.evaluate(()=>actualizarLecturas());fail=true;await page.evaluate(()=>actualizarLecturas());
  assert.equal((await page.locator('#val-nivelAgua').innerText()).trim(),'--');
  assert.match(await page.locator('#ultima-actualizacion').innerText(),/Última recepción:/);
  assert.match(await page.locator('#ultima-actualizacion').innerText(),/sin lectura actual/);
  fail=false;reading={...reading,temperatura:99.7,temperatura_estado:undefined,temperatura_observada:undefined};
  await page.evaluate(()=>actualizarLecturas());
  assert.equal((await page.locator('#val-temperatura').innerText()).trim(),'--');
  assert.match(await page.locator('#tag-temperatura').innerText(),/Sospechosa/);
  assert.match(await page.locator('#desc-temperatura').innerText(),/99.7/);
  reading={...reading,temperatura:null,temperatura_estado:'sospechosa',temperatura_observada:99.7};
  await page.evaluate(()=>actualizarLecturas());
  assert.equal((await page.locator('#val-temperatura').innerText()).trim(),'--');
  assert.match(await page.locator('#tag-temperatura').innerText(),/Sospechosa/);
  await page.evaluate(()=>{
    bleActivo=true;const buffer=new ArrayBuffer(8);const view=new DataView(buffer);
    view.setInt16(0,997,true);view.setInt16(2,500,true);view.setInt16(4,120,true);view.setInt16(6,0x7fff,true);
    recibirPaqueteBle(view);
  });
  assert.match(await page.locator('#tag-temperatura').innerText(),/Sospechosa/);
  await page.evaluate(()=>{lecturaVigenteHasta=performance.now()-1;verificarVigenciaLectura();bleActivo=false;});
  assert.equal((await page.locator('#val-nivelAgua').innerText()).trim(),'--');
  console.log('PASS temperature quality and visible receipt time; stale WiFi/BLE values cleared');
  console.log('PASS restored historical wave and exact wrapper 0/50/71.2/95/100; unknown legacy 87.6 hidden, no fake zero; stale/failed data cleared');
 } finally {await browser.close();}
})().catch(err=>{console.log('LEVEL_BROWSER_FAILED',err.name,err.message);process.exitCode=1;});
