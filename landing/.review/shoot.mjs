// Screenshot harness for design-review loop. Not shipped — dev tool only.
import { chromium } from 'playwright';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pageFile = 'file://' + path.resolve(__dirname, '..', 'index.html');
const outDir = path.resolve(__dirname, 'shots');

const viewports = {
  se: { width: 375, height: 667 },
  mobile: { width: 390, height: 844 },
  tablet: { width: 820, height: 1180 },
  desktop: { width: 1440, height: 900 },
};

const stops = [
  { name: '01-hero', scrollFrac: 0 },
  { name: '02-about', scrollFrac: null, selector: '#about' },
  { name: '03-features', scrollFrac: null, selector: '#features' },
  { name: '04-features-cards', scrollFrac: null, selector: '.fcard.showcase', offsetFrac: 0.3 },
  { name: '05-footer', scrollFrac: 1 },
];

const browser = await chromium.launch();
for (const [vpName, vp] of Object.entries(viewports)) {
  const page = await browser.newPage({ viewport: vp, deviceScaleFactor: 2 });
  await page.goto(pageFile, { waitUntil: 'load' });
  await page.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; });
  await page.waitForTimeout(500);

  for (const stop of stops) {
    if (stop.selector) {
      await page.evaluate(({ sel, offsetFrac }) => {
        const el = document.querySelector(sel);
        if (el) {
          const rect = el.getBoundingClientRect();
          const target = window.scrollY + rect.top - (offsetFrac != null ? window.innerHeight * (1 - offsetFrac) : 80);
          window.scrollTo(0, Math.max(0, target));
        }
      }, { sel: stop.selector, offsetFrac: stop.offsetFrac });
    } else if (stop.scrollFrac != null) {
      await page.evaluate((frac) => {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        window.scrollTo(0, max * frac);
      }, stop.scrollFrac);
    }
    await page.waitForTimeout(1300);
    const file = path.join(outDir, `${vpName}-${stop.name}.png`);
    await page.screenshot({ path: file });
    console.log('shot', file);
  }
  await page.close();
}
await browser.close();
console.log('done');
