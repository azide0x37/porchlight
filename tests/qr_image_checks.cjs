"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const helperPath = path.join(__dirname, "../src/porchlight/webroot/guest/qr-image.js");
const { fromPixels } = require(helperPath);

function pixels(width, height, dark) {
  const data = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = (y * width + x) * 4;
      data.fill(dark(x, y) ? 0 : 255, offset, offset + 3);
      data[offset + 3] = 255;
    }
  }
  return { width, height, data };
}

function rasterize(result) {
  const image = pixels(result.width, result.height, () => false);
  const rectangles = result.path.match(/M\d+ \d+h\d+v1h-\d+z/g) || [];
  assert.equal(rectangles.join(""), result.path, "SVG contains only numeric rectangles");
  for (const rectangle of rectangles) {
    const [x, y, width, height, back] = rectangle.match(/\d+/g).map(Number);
    assert.equal(width, back);
    assert.equal(height, 1);
    assert.ok(x >= 0 && y >= 0 && x + width <= image.width && y < image.height);
    for (let column = x; column < x + width; column += 1) {
      const offset = (y * image.width + column) * 4;
      image.data.fill(0, offset, offset + 3);
    }
  }
  return image;
}

function exactPixels() {
  const qrcode = require("../src/porchlight/webroot/guest/vendor/qrcode-generator.js");
  const code = qrcode(0, "M");
  code.addData("WIFI:T:WPA;S:Test;P:synthetic-only;;", "Byte");
  code.make();
  const modules = code.getModuleCount();
  const quiet = 4;
  const scale = 4;
  const size = (modules + quiet * 2) * scale;
  const source = pixels(size, size, (x, y) => {
    const column = Math.floor(x / scale) - quiet;
    const row = Math.floor(y / scale) - quiet;
    return column >= 0 && row >= 0 && column < modules && row < modules && code.isDark(row, column);
  });
  const result = fromPixels(source);
  assert.equal(result.width, size);
  assert.equal(result.height, size);
  assert.deepEqual(rasterize(result).data, source.data, "every module and quiet-zone pixel survives");
  const edgeCase = pixels(9, 5, (x, y) => x === 0 || y === 4 || (x === 8 && y === 0));
  assert.deepEqual(rasterize(fromPixels(edgeCase)).data, edgeCase.data, "edge runs are not cropped");
}

function limits() {
  for (const value of [1, 127, 254]) {
    const image = pixels(3, 3, (x, y) => x === y);
    image.data[4] = image.data[5] = image.data[6] = value;
    assert.throws(() => fromPixels(image), /monochrome/);
  }
  const translucent = pixels(3, 3, (x, y) => x === y);
  translucent.data[3] = 254;
  assert.throws(() => fromPixels(translucent), /monochrome/);
  const colored = pixels(3, 3, (x, y) => x === y);
  colored.data[0] = 255;
  assert.throws(() => fromPixels(colored), /monochrome/);
  for (const [width, height] of [[513, 1], [1, 513], [0, 1], [-1, 1], [1.5, 1], [Infinity, 1]]) {
    assert.throws(() => fromPixels({ width, height, data: [] }), /dimensions/);
  }
  assert.throws(() => fromPixels({ width: 2, height: 2, data: new Uint8Array(15) }), /pixels/);
  assert.throws(() => fromPixels(pixels(3, 3, () => false)), /empty/);
  assert.throws(() => fromPixels(pixels(3, 3, () => true)), /empty/);
  assert.throws(() => fromPixels(pixels(512, 512, (x, y) => (x + y) % 2 === 0)), /complexity/);
}

function pngHeader(width, height) {
  const header = new Uint8Array(24);
  header.set([137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82]);
  const fields = new DataView(header.buffer);
  fields.setUint32(16, width);
  fields.setUint32(20, height);
  return new Blob([header], { type: "image/png" });
}

function browser(mode, source) {
  const seen = { created: [], revoked: [], removed: [], draws: [], canvas: null };
  class FakeImage {
    constructor() {
      this.naturalWidth = source.width + (mode === "mismatch" ? 1 : 0);
      this.naturalHeight = source.height;
    }
    set src(value) {
      if (mode === "timeout") return;
      queueMicrotask(() => {
        if (mode === "decode-error") this.onerror();
        else this.onload();
      });
    }
    removeAttribute(name) { seen.removed.push(name); }
  }
  const context = {
    imageSmoothingEnabled: true,
    drawImage(...args) { seen.draws.push(args); },
    getImageData(x, y, width, height) {
      assert.deepEqual([x, y, width, height], [0, 0, source.width, source.height]);
      assert.equal(this.imageSmoothingEnabled, false);
      if (mode === "read-error") throw new Error("canvas read failed");
      return source;
    },
  };
  const window = {
    Image: FakeImage,
    FileReader: class {
      readAsArrayBuffer(blob) {
        assert.equal(blob.size, 24, "legacy reader only reads the bounded header");
        Blob.prototype.arrayBuffer.call(blob).then((result) => {
          this.result = result;
          this.onload();
        });
      }
    },
    URL: {
      createObjectURL(blob) { seen.created.push(blob); return "blob:test-only"; },
      revokeObjectURL(url) { seen.revoked.push(url); },
    },
    setTimeout: (callback, delay) => setTimeout(callback, mode === "timeout" ? 0 : delay),
    clearTimeout,
    document: {
      createElement(tag) {
        assert.equal(tag, "canvas");
        seen.canvas = { width: 0, height: 0, getContext: () => mode === "no-context" ? null : context };
        return seen.canvas;
      },
    },
  };
  const sandbox = { window };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(helperPath, "utf8"), sandbox);
  return { convert: window.PorchlightQrImage.fromBlob, seen };
}

async function resources() {
  const source = pixels(12, 12, (x, y) => x >= 4 && x < 8 && y >= 4 && y < 8);
  for (const mode of ["success", "legacy-blob", "decode-error", "read-error", "timeout", "mismatch", "no-context"]) {
    const { convert, seen } = browser(mode, source);
    const blob = pngHeader(12, 12);
    if (mode === "legacy-blob") {
      blob.slice = (...args) => {
        const prefix = Blob.prototype.slice.apply(blob, args);
        Object.defineProperty(prefix, "arrayBuffer", { value: undefined });
        return prefix;
      };
    }
    if (mode === "success" || mode === "legacy-blob") assert.deepEqual(rasterize(await convert(blob)).data, source.data);
    else await assert.rejects(convert(blob));
    assert.equal(seen.created.length, 1, mode);
    assert.deepEqual(seen.revoked, ["blob:test-only"], mode + " revokes temporary source URL");
    assert.deepEqual(seen.removed, ["src"], mode + " retires decoder source");
    if (seen.canvas) assert.deepEqual([seen.canvas.width, seen.canvas.height], [0, 0], "pixel buffer retired");
    if (seen.draws.length) assert.equal(seen.draws[0].length, 3, "draw uses native pixels without scaling");
  }
  for (const blob of [pngHeader(513, 1), pngHeader(1, 513), new Blob([new Uint8Array(131073)], { type: "image/png" }),
    new Blob([new Uint8Array(24)], { type: "image/png" }), new Blob(["not png"], { type: "text/plain" })]) {
    const { convert, seen } = browser("success", source);
    await assert.rejects(convert(blob));
    assert.equal(seen.created.length, 0, "invalid PNG refused before browser decoding");
  }
}

const checks = { exactPixels, limits, resources };
Promise.resolve().then(() => checks[process.argv[2]]()).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
