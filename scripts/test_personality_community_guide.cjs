const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const { chromium } = require('playwright');
const id = '00000000-0000-0000-0000-000000000001';
const badge = { code:'mbti-infp', name:'INFP · 心间拾光', icon:'feather', tier:'identity' };
const report = { type:'INFP', title:'温柔而坚定', theme:'forest', analysis_mode:'ai', summary:'从日常选择，认识自己的内在偏好。', character:null,
  keywords:['真诚','想象力'], axes:[['I','E'],['N','S'],['F','T'],['P','J']].map(([left,right])=>({left,right,left_name:left,right_name:right,value:65})),
  dimensions:['empathy','values','boundaries','action','energy','curiosity'].map((key,i)=>({key,name:'维度 '+i,value:60})),
  candidates:['INFP'], sections:Array.from({length:4},(_,i)=>({title:'生活中的你 '+i,text:'这是一段用于验证阅读和领取入口的示例报告。'.repeat(4),evidence:[]})),
  growth:[{title:'给自己一点空间',text:'慢慢找到舒服的节奏。'}] };
fs.mkdirSync('data/logs',{recursive:true});

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    for(const scenario of ['desktop','mobile','draft','skip','forged','retry','returning']) {
      const width=scenario==='desktop'?1440:390;
      const context=await browser.newContext({viewport:{width,height:900},reducedMotion:scenario==='mobile'?'reduce':'no-preference'});
      const page=await context.newPage();
      const claims=[],posts=[],errors=[]; let equipped=scenario!=='desktop'&&scenario!=='mobile'&&scenario!=='retry',failed=false;
      page.on('pageerror',error=>errors.push(error.message));
      await page.addInitScript(scenario=>{
        localStorage.setItem('kflow-theme',scenario==='desktop'?'light':'dark');
        if(scenario==='draft')localStorage.setItem('kflow-murmurs-draft:explorer',JSON.stringify({content:'我原来写的草稿',images:[],key:'draft-key-123',channel:'growth'}));
      },scenario);
      await page.route('**/*',async route=>{
        const request=route.request(),p=new URL(request.url()).pathname;let data,status=200;
        if(p===`/api/personality/assessments/${id}/report`) data={status:'completed',report};
        else if(p==='/api/achievements/personality/claim') {
          const body=request.postDataJSON();claims.push(body);
          assert.equal(body.equip,true);assert.equal(body.assessment_id,id);
          if(scenario==='retry'&&!failed){failed=true;status=503;data={error:'领取服务暂时不可用，请重试'};}
          else {equipped=true;data={badge,equipped:true,redirect:'/murmurs?welcome=personality'};}
        } else if(p==='/api/murmurs/session') data={profile:{username:'explorer',display_name:'测试探索者',avatar_url:'',showcase:equipped&&scenario!=='forged'?badge:null},first_post_reward:{eligible:scenario!=='returning',points:10,imaging_cost:10}};
        else if(p==='/api/murmurs'&&request.method()==='POST') {
          const body=request.postDataJSON();posts.push(body);
          data={item:{id:123},first_post_reward:scenario==='returning'?null:{points:10,balance:10,imaging_cost:10,imaging_url:'/imaging'}};
        } else if(p.startsWith('/api/'))data={items:[],total:0,page:1,pages:1,page_count:1,counts:{alerts:0,feedback:0},profile:null};
        if(data)return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
        const file=path.join(process.cwd(),p.startsWith('/personality/report/')?'static/personality/report.html':p==='/murmurs'?'static/murmurs.html':p.startsWith('/static/')?p.slice(1):'static'+p);
        return fs.existsSync(file)&&fs.statSync(file).isFile()?route.fulfill({path:file}):route.fulfill({status:404,body:''});
      });
      if(['desktop','mobile','retry'].includes(scenario)) {
        await page.goto(`https://kflow.test/personality/report/${id}`);
        const claim=page.locator('#claim-personality-badge');
        await page.waitForFunction(()=>!document.querySelector('#claim-personality-badge').disabled);
        assert.equal(await claim.evaluate(el=>el.classList.contains('claim-attention')),false);
        await claim.scrollIntoViewIfNeeded();
        await page.waitForFunction(()=>document.querySelector('#claim-personality-badge').classList.contains('claim-attention'));
        const count=await claim.evaluate(el=>getComputedStyle(el).animationIterationCount);
        if(scenario==='mobile')assert.equal(await claim.evaluate(el=>getComputedStyle(el).animationName),'none');
        else assert.equal(count,'3');
        await claim.evaluate(el=>{el.click();el.click();});
        if(scenario==='retry') {
          await page.locator('#badge-claim-dialog[open]').waitFor();
          assert((await page.locator('#reward-status').innerText()).includes('重试'));
          await page.locator('.claim-dialog-later').click();
          await claim.click();
        }
        await page.waitForURL('**/murmurs*');
        assert.equal(claims.length,scenario==='retry'?2:1);
      } else await page.goto('https://kflow.test/murmurs?welcome=personality');
      if(scenario==='forged') {
        await page.waitForFunction(()=>document.querySelector('#mm-feed').getAttribute('aria-busy')==='false');
        assert.equal(await page.locator('#mm-dialog').evaluate(el=>el.open),false);
        assert.equal(await page.locator('#mm-content').inputValue(),'');
      } else {
        await page.locator('#mm-dialog[open]').waitFor();
        assert((await page.locator('#mm-dialog-title').innerText()).includes('INFP'));
        assert((await page.locator('.mm-personality-preview-name').innerText()).includes('测试探索者'));
        assert.equal(await page.locator('.mm-personality-preview .mbti-capsule').count(),1);
        assert.equal(new URL(page.url()).searchParams.get('welcome'),null);
        assert.equal(posts.length,0);
        assert.equal((await page.locator('#mm-dialog-body').innerText()).includes('10 K 积分'),scenario!=='returning');
        await page.screenshot({path:`data/logs/personality-community-${scenario}.png`,fullPage:false});
        if(scenario==='skip') {
          await page.getByRole('button',{name:'先看看大家',exact:true}).click();
          assert.equal(await page.locator('#mm-content').inputValue(),'');
        } else {
          await page.getByRole('button',{name:scenario==='draft'?'继续编辑我的草稿':'用这句话打个招呼',exact:true}).click();
          assert.equal(await page.locator('#mm-content').inputValue(),scenario==='draft'?'我原来写的草稿':'新鲜出炉的 INFP，来社区报个到。');
          assert(await page.locator('#mm-personality-post-hint').isVisible());
          assert.equal(posts.length,0);
          if(['desktop','mobile','returning'].includes(scenario)) {
            await page.locator('#mm-content').fill('我修改后的开场白');
            await page.locator('#mm-publish').click();
            await page.waitForFunction(()=>!document.querySelector('#mm-personality-post-hint'));
            assert.equal(posts.length,1);assert.equal(posts[0].content,'我修改后的开场白');
            if(scenario==='returning') {
              assert.equal(await page.locator('#mm-dialog').evaluate(el=>el.open),false);
              assert.equal(await page.locator('#mm-first-post-offer').count(),0);
            } else {
            await page.waitForFunction(()=>document.querySelector('#mm-dialog-title').textContent==='第一条碎碎念，发布成功！');
            assert((await page.locator('.mm-first-post-earned').innerText()).includes('10 K'));
            assert.equal(await page.getByRole('link',{name:'去显影试试 →',exact:true}).getAttribute('href'),'/imaging');
            assert.equal(await page.locator('.mm-imaging-examples img').count(),3);
            await page.screenshot({path:`data/logs/first-post-reward-${scenario}.png`,fullPage:false});
            }
          }
        }
      }
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      assert.deepEqual(errors,[]);
      console.log(`PASS ${scenario}: claim/equip, real preview, opt-in draft, manual publish`);
      await context.close();
    }
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
