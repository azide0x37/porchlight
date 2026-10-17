/* Turn the authenticated UniFi PNG into CSS-colored geometry without decoding its
   Wi-Fi payload. Only opaque, exactly black/white source pixels are accepted. */
((root, factory) => {
  "use strict";
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PorchlightQrImage = api;
})(typeof window === "object" ? window : globalThis, (root) => {
  "use strict";

  const MAX_DIMENSION = 512;
  const MAX_BYTES = 131072;
  const MAX_RUNS = 16384;
  const MAX_PATH_LENGTH = 262144;
  const DECODE_TIMEOUT_MS = 4000;

  function dimensions(width, height) {
    if (!Number.isInteger(width) || !Number.isInteger(height) || width < 1 || height < 1
        || width > MAX_DIMENSION || height > MAX_DIMENSION) throw new Error("wifi qr dimensions");
  }

  function fromPixels(image) {
    const { width, height, data } = image;
    dimensions(width, height);
    if (!data || data.length !== width * height * 4) throw new Error("wifi qr pixels");
    let path = "";
    let runs = 0;
    let light = false;
    for (let y = 0; y < height; y += 1) {
      let start = -1;
      for (let x = 0; x <= width; x += 1) {
        let dark = false;
        if (x < width) {
          const offset = (y * width + x) * 4;
          const value = data[offset];
          if ((value !== 0 && value !== 255) || data[offset + 1] !== value
              || data[offset + 2] !== value || data[offset + 3] !== 255) {
            // Never threshold gray or transparent edges into different QR modules.
            throw new Error("wifi qr not monochrome");
          }
          dark = value === 0;
          light = light || !dark;
        }
        if (dark && start < 0) start = x;
        if (!dark && start >= 0) {
          const length = x - start;
          path += `M${start} ${y}h${length}v1h-${length}z`;
          runs += 1;
          if (runs > MAX_RUNS || path.length > MAX_PATH_LENGTH) throw new Error("wifi qr complexity");
          start = -1;
        }
      }
    }
    if (!runs || !light) throw new Error("wifi qr empty");
    return { width, height, path };
  }

  function pngHeader(blob) {
    const prefix = blob.slice(0, 24);
    if (typeof prefix.arrayBuffer === "function") return prefix.arrayBuffer();
    // Cast receivers can lag desktop Chrome's Blob API support.
    return new Promise((resolve, reject) => {
      const reader = new root.FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(new Error("wifi qr header"));
      reader.readAsArrayBuffer(prefix);
    });
  }

  async function fromBlob(blob) {
    if (!blob || blob.type !== "image/png" || blob.size < 24 || blob.size > MAX_BYTES) {
      throw new Error("wifi qr image");
    }
    // Bound the decoded allocation before handing the PNG to the browser decoder.
    const header = new Uint8Array(await pngHeader(blob));
    const signature = [137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82];
    if (signature.some((byte, index) => header[index] !== byte)) throw new Error("wifi qr png");
    const fields = new DataView(header.buffer);
    const width = fields.getUint32(16);
    const height = fields.getUint32(20);
    dimensions(width, height);

    const image = new root.Image();
    const url = root.URL.createObjectURL(blob);
    let timer;
    let canvas;
    try {
      await new Promise((resolve, reject) => {
        timer = root.setTimeout(() => reject(new Error("wifi qr timeout")), DECODE_TIMEOUT_MS);
        image.onload = resolve;
        image.onerror = () => reject(new Error("wifi qr decode"));
        image.src = url;
      });
      if (image.naturalWidth !== width || image.naturalHeight !== height) throw new Error("wifi qr dimensions");
      canvas = root.document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("wifi qr canvas");
      context.imageSmoothingEnabled = false;
      context.drawImage(image, 0, 0);
      return fromPixels(context.getImageData(0, 0, width, height));
    } finally {
      root.clearTimeout(timer);
      image.onload = null;
      image.onerror = null;
      image.removeAttribute("src");
      root.URL.revokeObjectURL(url);
      if (canvas) canvas.width = canvas.height = 0;
    }
  }

  return Object.freeze({ fromPixels, fromBlob });
});
