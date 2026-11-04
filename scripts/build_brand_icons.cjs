const fs = require('node:fs');
const {chromium} = require('playwright');
// Canonical artwork is favicon.svg; keep PNG and ICO consumers in sync.
(async () => {
  const browser = await chromium.launch({channel:'msedge',headless:true});
  try {
    const page = await browser.newPage();
    const svg = fs.readFileSync('static/favicon.svg','utf8');
    fs.writeFileSync('static/kflow-mark.svg',svg.replace(/<rect\b[^>]*\/>/, '').replace('fill="#fff"','fill="currentColor"'));
    async function raster(size) {
      const data = await page.evaluate(async ({svg,size}) => {
        const img = new Image();
        img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        await img.decode();
        const canvas = document.createElement('canvas');
        canvas.width = canvas.height = size;
        canvas.getContext('2d').drawImage(img,0,0,size,size);
        return canvas.toDataURL('image/png').split(',')[1];
      }, {svg,size});
      return Buffer.from(data,'base64');
    }
    for (const [file,size] of [['brand-k.png',256],['apple-touch-icon.png',180],['icon-192.png',192],['icon-512.png',512]]) {
      fs.writeFileSync('static/'+file, await raster(size));
    }
    const sizes = [16,24,32,48,64,128,256], frames=[];
    for (const size of sizes) frames.push(await raster(size));
    const header = Buffer.alloc(6 + sizes.length * 16);
    header.writeUInt16LE(1,2); header.writeUInt16LE(sizes.length,4);
    let offset = header.length;
    frames.forEach((data,i) => {
      const entry = 6 + i * 16;
      header[entry] = header[entry+1] = sizes[i] === 256 ? 0 : sizes[i];
      header.writeUInt16LE(1,entry+4); header.writeUInt16LE(32,entry+6);
      header.writeUInt32LE(data.length,entry+8); header.writeUInt32LE(offset,entry+12);
      offset += data.length;
    });
    fs.writeFileSync('static/favicon.ico',Buffer.concat([header,...frames]));
  } finally { await browser.close(); }
})().catch(error => {console.error(error);process.exitCode=1;});
