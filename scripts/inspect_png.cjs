// Publication Plot Rendering Pipeline asset: PNG export inspection.
// Usage: node inspect_png.cjs <png> <node_modules_dir>
const path = require('path');

async function main() {
  const [target, modules] = process.argv.slice(2);
  const sharp = require(path.join(modules, 'sharp'));
  const image = sharp(target);
  const meta = await image.metadata();
  const { data, info } = await image.raw().toBuffer({ resolveWithObject: true });
  const channels = info.channels;
  const at = (x, y) => {
    const offset = (y * info.width + x) * channels;
    return [data[offset], data[offset + 1], data[offset + 2]];
  };
  const corners = [
    at(0, 0),
    at(info.width - 1, 0),
    at(0, info.height - 1),
    at(info.width - 1, info.height - 1),
  ];
  let nonWhite = 0;
  const step = Math.max(1, Math.floor(Math.sqrt((info.width * info.height) / 400000)));
  let sampled = 0;
  for (let y = 0; y < info.height; y += step) {
    for (let x = 0; x < info.width; x += step) {
      const offset = (y * info.width + x) * channels;
      sampled += 1;
      if (data[offset] !== 255 || data[offset + 1] !== 255 || data[offset + 2] !== 255) {
        nonWhite += 1;
      }
    }
  }
  const report = {
    width: meta.width,
    height: meta.height,
    density: meta.density || null,
    space: meta.space,
    channels,
    hasAlpha: Boolean(meta.hasAlpha),
    hasProfile: Boolean(meta.icc),
    corners,
    sampled_pixels: sampled,
    non_white_sampled: nonWhite,
    format: meta.format,
  };
  process.stdout.write(JSON.stringify(report));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
