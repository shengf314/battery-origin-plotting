// Publication Plot Rendering Pipeline asset: render an exported SVG for visual
// inspection (no dependency on the Origin window).
// Usage: node render_preview.cjs <svg> <out_png> <width_px> <height_px> <node_modules_dir>
const fs = require('fs');
const path = require('path');

async function main() {
  const [svg, out, width, height, modules] = process.argv.slice(2);
  const { chromium } = require(path.join(modules, 'playwright'));
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({
    viewport: { width: Number(width), height: Number(height) },
    deviceScaleFactor: 1,
  });
  const content = fs.readFileSync(svg, 'utf8');
  await page.setContent(
    '<html><style>body{margin:0;background:white}body>svg{width:' + width +
    'px;height:' + height + 'px}</style><body>' + content + '</body></html>');
  await page.screenshot({ path: out });
  await browser.close();
  process.stdout.write(JSON.stringify({ preview: out, width: Number(width), height: Number(height) }));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
