// Requires Playwright installed in .test-runtime/ui; uses existing Chrome only.
// All device credentials live in Node memory, never in browser page code.
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const path = require('node:path');
const { chromium } = require(path.join(process.cwd(), '.test-runtime/ui/node_modules/playwright'));
const origin = 'http://127.0.0.1:5059';
const password = 'local-ui-test-password-123';
const config = 'ac_' + crypto.randomBytes(32).toString('hex');
let measure = 'am_' + crypto.randomBytes(32).toString('hex');
async function device(route, body, token=config, method='POST') {
  const r = await fetch(origin+'/api'+route, { method, headers: { 'Content-Type':'application/json', Authorization:'Bearer '+token }, ...(method==='GET'?{}:{body:JSON.stringify(body)}) });
  assert.ok(r.ok, `Device endpoint ${route}: ${r.status}`);
  return r.json();
}
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  const errors=[];
  try {
    const context=await browser.newContext({viewport:{width:1280,height:900}});
    const page=await context.newPage();
    page.on('pageerror',err=>errors.push(err.message));
    async function openDevices() {
      // Navigation reloads the list asynchronously. Wait for its actual DOM replacement.
      const previous = await page.locator('#lista-mis-dispositivos > *').first().elementHandle();
      await Promise.all([
        page.waitForResponse(r=>new URL(r.url()).pathname==='/api/dispositivos' && r.request().method()==='GET' && r.status()===200),
        page.locator('[data-view=dispositivos]').click()
      ]);
      if (previous) await page.waitForFunction(element=>!element.isConnected,previous);
      await page.locator('#lista-mis-dispositivos > *').first().waitFor({state:'visible'});
    }

    await page.goto(new URL("/admin.html", origin).href,{waitUntil:"networkidle"});
    await page.locator('#ir-a-registro').click();
    await page.locator('#registro-usuario').fill('ui_'+crypto.randomBytes(5).toString('hex'));
    await page.locator('#registro-password').fill(password);
    await page.locator('#registro-password2').fill(password);
    await page.locator('#form-registro button[type=submit]').click();
    await page.locator('#app').waitFor({state:'visible'});
    const cookies=await context.cookies();
    assert.ok(cookies.find(c=>c.name==='aquamonitor_session' && c.httpOnly && c.sameSite==='Strict'));
    assert.equal(await page.evaluate(()=>localStorage.getItem('aquamonitor_token')),null);
    await device('/equipos/registro',{registration_id:crypto.randomUUID(),generation:crypto.randomUUID(),measurement_token:measure,mac:'AA:BB:CC:DD:EE:FF'});
    const {code}=await device('/equipos/vinculacion',{request_id:crypto.randomUUID()});
    await openDevices();
    await page.locator('#btn-anadir-dispositivo').click();
    await page.locator('#vincular-codigo').fill(code);
    await page.locator('#vincular-nombre').fill('Estanque de prueba');
    await page.locator('#btn-vincular-codigo').click();
    await page.locator('#modal-scanner').waitFor({state:'hidden'});
    await device('/lecturas',{temperatura:23,nivel_agua:70,turbidez:12,rssi:-60},measure);
    await page.locator('[data-view=dashboard]').click();
    await page.waitForFunction(()=>document.querySelector('#val-temperatura').textContent.includes('23.0'));
    await page.locator('[data-view=historicos]').click();
    await page.locator('#tabla-historicos-body tr').first().waitFor();
    assert.ok((await page.locator('#tabla-historicos-body').innerText()).includes('23.0'));
    await openDevices();
    await page.locator('.device-actions summary').click();
    await page.locator('.device-actions input').fill(password);
    await page.getByRole('button',{name:'Revocar envíos',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#lista-mis-dispositivos').textContent.includes('Envíos deshabilitados'));
    await page.locator('.device-actions summary').click();
    await page.locator('.device-actions input').fill(password);
    await Promise.all([
      page.waitForResponse(r=>r.url().endsWith('/recuperar') && r.request().method()==='POST' && r.status()===200),
      page.getByRole('button',{name:'Autorizar recuperación',exact:true}).click()
    ]);
    const status=await device('/equipos/estado',undefined,config,'GET');
    assert.ok(status.recovery_authorized);
    measure='am_'+crypto.randomBytes(32).toString('hex');
    await device('/equipos/credenciales/medicion',{generation:crypto.randomUUID(),measurement_token:measure});
    await device('/lecturas',{temperatura:24},measure);
    await page.locator('#btn-refrescar-dispositivos').click();
    await page.waitForFunction(()=>document.querySelector('#lista-mis-dispositivos').textContent.includes('En línea'));
    page.once('dialog',dialog=>dialog.accept());
    await page.locator('.device-actions summary').click();
    await page.locator('.device-actions input').fill(password);
    await page.getByRole('button',{name:'Liberar para transferencia',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#lista-mis-dispositivos').textContent.includes('Anterior'));
    await page.getByRole('button',{name:'Consultar historial',exact:true}).click();
    await page.waitForFunction(()=>document.querySelector('#tabla-historicos-body').textContent.includes('24.0'));
    await page.setViewportSize({width:390,height:844});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
    await page.screenshot({path:'.test-runtime/dashboard-mobile.png',fullPage:true});
    await page.locator('#btn-logout').click();
    await page.locator('#auth-screen').waitFor({state:'visible'});
    assert.equal((await context.cookies()).some(c=>c.name==='aquamonitor_session'),false);
    assert.deepEqual(errors,[]);
    console.log('PASS: browser registration, HttpOnly session, pairing, telemetry, history, revocation, recovery, release, mobile layout and logout.');
  } finally { await browser.close(); }
})().catch(err=>{ console.error(err.message); process.exitCode=1; });
