// Gera as imagens do canal:  node branding/render.js  (precisa do Playwright)
const { chromium } = require('playwright');
const path = require('path');
const items = [
  ['banner.html', 'banner.png', 2560, 1440, false],
  ['avatar.html', 'avatar.png', 800, 800, false],
  ['watermark.html', 'watermark.png', 150, 150, true],
];
(async () => {
  const browser = await chromium.launch();
  for (const [src, out, w, h, transparent] of items) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.goto('file://' + path.join(__dirname, src));
    await page.evaluate(() => document.fonts.ready);
    await page.screenshot({ path: path.join(__dirname, out), omitBackground: transparent });
    await page.close();
    console.log('ok', out);
  }
  await browser.close();
})();
