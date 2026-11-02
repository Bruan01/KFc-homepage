/* DOM export stays local to this browser; no answers are sent to an image service. */
(() => {
  'use strict';
  let renderer;
  function loadRenderer(){
    if(window.html2canvas)return Promise.resolve(window.html2canvas);
    if(!renderer)renderer=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/personality/vendor/html2canvas.min.js';script.onload=()=>resolve(window.html2canvas);script.onerror=()=>{renderer=null;script.remove();reject(Error('图片组件加载失败，请重试'));};document.head.append(script);});
    return renderer;
  }
  const blobURL=blob=>new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(Error('图片读取失败'));reader.readAsDataURL(blob);});
  async function saveBlob(blob,type,mode){
    const filename=`心映-${type}-${mode==='long'?'完整长图':'共鸣短图'}.png`,mobile=/Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)||navigator.maxTouchPoints>1;
    const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=filename;
    if(mobile&&!('download' in anchor)){anchor.target='_blank';anchor.rel='noopener';}
    document.body.append(anchor);anchor.click();anchor.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
    return mobile?'图片已开始下载，请在浏览器下载列表查看；需要存入相册时，可在下载列表中选择保存到相册。':'图片已开始下载，请在浏览器下载列表查看。';
  }
  window.XinyingExportPNG=async({includeQuote,type,mode='short'})=>{
    const render=await loadRenderer(),frame=document.createElement('iframe'),long=mode==='long';
    frame.title='档案图片导出';frame.setAttribute('aria-hidden','true');frame.tabIndex=-1;
    frame.style.cssText='position:fixed;left:-20000px;top:0;width:1160px;height:1600px;border:0;pointer-events:none';
    document.body.append(frame);
    try{
      const doc=frame.contentDocument;
      doc.open();doc.write('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body></body></html>');doc.close();
      const styles=await Promise.all([...document.querySelectorAll('link[rel=stylesheet]')].map(async link=>{const response=await fetch(link.href);if(!response.ok)throw Error('样式加载失败，请重试');return response.text();}));
      doc.documentElement.dataset.personalityTheme=document.documentElement.dataset.personalityTheme;
      doc.body.className=document.body.className;
      const style=doc.createElement('style');style.textContent=styles.join('\n')+'\nbody{margin:0;padding:28px;width:1160px}#share-sheet{width:1104px;box-shadow:none}.share-sheet:before{display:none}.cover-art img{filter:none}#main{width:1104px;max-width:1104px;padding:0;margin:0}.report-layout{display:block}.contents{display:none}';doc.head.append(style);
      const source=document.querySelector(long?'#main':'#share-sheet'),sheet=doc.importNode(source,true);
      if(long)sheet.querySelectorAll('[data-export-exclude],.save-trigger,.save-section,#character-upgrade,#report-state,.contents').forEach(node=>node.remove());
      doc.body.append(sheet);
      if(!includeQuote)sheet.querySelectorAll('[data-private-quote]').forEach(node=>node.remove());
      for(const img of sheet.querySelectorAll('img')){
        if(img.hidden||!img.getAttribute('src'))continue;
        const response=await fetch(img.src,{credentials:'same-origin'});if(!response.ok)throw Error('角色图片未准备好，请稍后重试');
        img.src=await blobURL(await response.blob());await img.decode();
      }
      await doc.fonts.ready;
      for(const svg of [...sheet.querySelectorAll('svg#radar')]){
        for(const element of [svg,...svg.querySelectorAll('*')]){
          const computed=frame.contentWindow.getComputedStyle(element);
          for(const property of ['fill','stroke','font-family','font-size','font-weight'])element.style.setProperty(property,computed.getPropertyValue(property));
        }
        const width=svg.getBoundingClientRect().width,height=svg.getBoundingClientRect().height;
        svg.setAttribute('xmlns','http://www.w3.org/2000/svg');svg.setAttribute('width',width);svg.setAttribute('height',height);
        const img=doc.createElement('img');img.src=await blobURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml;charset=utf-8'}));
        img.style.cssText=svg.style.cssText;img.style.width=width+'px';img.style.height=height+'px';img.className=svg.getAttribute('class')||'';img.id=svg.id;svg.replaceWith(img);await img.decode();
      }
      const height=Math.ceil(sheet.getBoundingClientRect().height+56);frame.style.height=height+'px';
      const scale=long?Math.min(1,12000/height):2;
      const canvas=await render(doc.body,{scale,width:1160,height,windowWidth:1160,windowHeight:height,scrollX:0,scrollY:0,logging:false,backgroundColor:frame.contentWindow.getComputedStyle(doc.body).backgroundColor});
      const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/png'));if(!blob)throw Error('图片生成失败，请重试');
      return await saveBlob(blob,type,mode);
    }finally{frame.remove();}
  };
})();
