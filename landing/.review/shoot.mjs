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

// scrollFrac: fraction of full scrollable height to jump to before shooting
const stops = [
  { name: '01-hero', scrollFrac: 0 },
  { name: '02-hero-mid-fade', scrollFrac: 0.045 },
  { name: '03-cards-in', scrollFrac: null, selector: '#cards-trigger', offsetFrac: 0.15 },
  { name: '04-cards-mid', scrollFrac: null, selector: '#cards-trigger', offsetFrac: 0.5 },
  { name: '05-to-roi', scrollFrac: null, selector: '#to-roi' },
  { name: '06-cach-hoat-dong', scrollFrac: null, selector: '#cach-hoat-dong' },
  { name: '07-don-nhom', scrollFrac: null, selector: null, textAnchor: 'Đơn nhóm văn phòng' },
  { name: '08-analytics', scrollFrac: null, selector: null, textAnchor: 'Biết tờ nào ra tiền' },
  { name: '09-gia', scrollFrac: null, selector: '#gia' },
  { name: '10-faq', scrollFrac: null, selector: null, textAnchor: 'Câu quán hay hỏi' },
  { name: '11-final', scrollFrac: null, selector: '#final' },
  { name: '12-footer', scrollFrac: 1 },
];

const browser = await chromium.launch();
for (const [vpName, vp] of Object.entries(viewports)) {
  const page = await browser.newPage({ viewport: vp, deviceScaleFactor: 2 });
  await page.goto(pageFile, { waitUntil: 'load' });
  // Harness-only: site ships scroll-behavior:smooth for real users, which animates our
  // programmatic jumps and makes fixed-wait screenshots land mid-flight. Force instant here.
  await page.evaluate(() => { document.documentElement.style.scrollBehavior = 'auto'; });
  await page.waitForTimeout(600);

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
    } else if (stop.textAnchor) {
      await page.evaluate((txt) => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
          if (node.textContent.includes(txt)) {
            const el = node.parentElement.closest('section') || node.parentElement;
            const rect = el.getBoundingClientRect();
            window.scrollTo(0, window.scrollY + rect.top - 80);
            return;
          }
        }
      }, stop.textAnchor);
    } else if (stop.scrollFrac != null) {
      await page.evaluate((frac) => {
        const max = document.documentElement.scrollHeight - window.innerHeight;
        window.scrollTo(0, max * frac);
      }, stop.scrollFrac);
    }
    // let rAF-driven scroll effects settle AND the 1s .reveal blur/opacity transition finish
    await page.waitForTimeout(1300);
    const file = path.join(outDir, `${vpName}-${stop.name}.png`);
    await page.screenshot({ path: file });
    console.log('shot', file);
  }
  await page.close();
}
await browser.close();
console.log('done');
