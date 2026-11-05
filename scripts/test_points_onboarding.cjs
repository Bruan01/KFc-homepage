const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  for(const width of [390,1440]){
   for(const scenario of ['register','billing','insufficient']){
    const page=await browser.newPage({viewport:{width,height:960}});const starts=[],errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(theme=>localStorage.setItem('kflow-theme',theme),width===390?'dark':'light');
    await page.route('**/*',async route=>{
     const req=route.request(),p=new URL(req.url()).pathname;
     if(p.startsWith('/api/')){
      let data={};let status=200;
      if(p==='/api/account/me')data={loggedIn:false};
      if(p==='/api/user/me')data={loggedIn:true,username:'billing-user'};
      if(p==='/api/user/register')data={is_admin:false,registration_reward:{points:20,personality_cost:10,imaging_cost:10,first_post:{eligible:true,points:10}}};
      if(p==='/api/personality/config')data={enabled:true,ai_available:true,cost:10,balance:scenario==='insufficient'?5:20};
      if(p==='/api/personality/assessments'){
       starts.push(req.postDataJSON());status=503;data={error:'测试连接中断，请重试'};
      }
      return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
     }
     if(p==='/murmurs')return route.fulfill({contentType:'text/html',body:'<h1>碎碎念</h1>'});
     const file=path.join(process.cwd(),p==='/login'?'static/user-login.html':p==='/personality/test'?'static/personality/test.html':p.startsWith('/static/')?p.slice(1):'static'+p);
     if(fs.existsSync(file)&&fs.statSync(file).isFile())return route.fulfill({path:file});
     return route.fulfill({status:404,body:''});
    });
    if(scenario==='register'){
     await page.goto('https://kflow.test/login?next=%2Fmurmurs');
     await page.locator('[data-auth-view="register"]').click();
     for(const [id,value] of Object.entries({registerUsername:'new-user',registerEmail:'new@example.com',registerCode:'123456',registerPassword:'testing-password',registerPasswordConfirm:'testing-password'}))await page.locator('#'+id).fill(value);
     await page.locator('#registerSubmit').click();
     await page.locator('.registration-reward[open]').waitFor();
     assert.match(await page.locator('.registration-reward').innerText(),/20 K 积分已到账/);
     assert.equal(await page.locator('.registration-reward-use').count(),2);
     assert.equal(await page.locator('.registration-reward-continue').getAttribute('href'),'/murmurs');
     assert.match(page.url(),/login/);
     await page.screenshot({path:`data/logs/registration-reward-${width}.png`});
     const bounds=await page.locator('.registration-reward').boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=width+1);
     await page.locator('.registration-reward-continue').click();await page.waitForURL('**/murmurs');
    }else{
     await page.goto('https://kflow.test/personality/test');
     await page.locator('.assessment-price').waitFor();
     assert.match(await page.locator('.assessment-price').innerText(),/10 K/);
     assert.match(await page.locator('.personality-balance').innerText(),scenario==='insufficient'?/5 K/:/20 K/);
     if(scenario==='billing')assert.match(await page.locator('.assessment-price').innerText(),/开始后剩余 10 K/);
     if(scenario==='insufficient'){
      assert(await page.locator('#begin').isDisabled());assert(await page.locator('#ai-consent').isDisabled());assert.equal(starts.length,0);
     }else{
      await page.locator('#ai-consent').check();await page.screenshot({path:`data/logs/personality-price-${width}.png`});await page.locator('#begin').click();await page.locator('#test-status').filter({hasText:'测试连接中断'}).waitFor();
      await page.reload();await page.locator('#ai-consent').check();await page.locator('#begin').click();await page.waitForFunction(()=>document.querySelector('#test-status').textContent.includes('测试连接中断'));
      assert.equal(starts.length,2);assert.equal(starts[0].client_key,starts[1].client_key);assert.equal(starts[0].expected_cost,10);assert.equal(starts[0].points_consent,true);
      
     }
    }
    assert.deepEqual(errors,[]);await page.close();process.stdout.write(`${scenario} ${width} passed\n`);
   }
  }
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
