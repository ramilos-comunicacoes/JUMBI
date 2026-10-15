/* Original artwork stays stored unchanged after background removal.
   Duotone is an on-device presentation, recalculated for the actual surface. */
(() => {
  const states = new WeakMap();
  const luminance = rgb => rgb.map(v => v / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4).reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
  const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05);
  const colorCanvas = document.createElement('canvas');
  colorCanvas.width = colorCanvas.height = 1;
  const colorContext = colorCanvas.getContext('2d', {willReadFrequently: true});
  const colors = new Map();
  function parse(color) {
    if (colors.has(color)) return colors.get(color);
    // Canvas resolves both rgb() and CSS Color 4/color-mix() into sRGB bytes.
    colorContext.clearRect(0, 0, 1, 1);
    colorContext.fillStyle = color;
    colorContext.fillRect(0, 0, 1, 1);
    const bytes = colorContext.getImageData(0, 0, 1, 1).data;
    const value = [bytes[0], bytes[1], bytes[2], bytes[3] / 255];
    if (colors.size > 100) colors.clear();
    colors.set(color, value);
    return value;
  }
  function surface(image) {
    let result = [0, 0, 0], remaining = 1;
    for (let node = image.parentElement; node && remaining > .001; node = node.parentElement) {
      const color = parse(getComputedStyle(node).backgroundColor);
      const alpha = color.length > 3 ? color[3] : 1;
      if (color.length >= 3) {
        result = result.map((v, i) => v + color[i] * alpha * remaining);
        remaining *= 1 - alpha;
      }
    }
    return result.map(v => v + 255 * remaining);
  }
  const mix = (a, b, amount) => a.map((v, i) => Math.round(v * (1 - amount) + b[i] * amount));
  function render(image) {
    const state = states.get(image);
    if (!state?.pixels) return;
    const background = surface(image);
    const style = getComputedStyle(image);
    const brand = style.getPropertyValue('--office-primary').trim();
    const key = background.join(',') + brand;
    if (key === state.key) return;
    state.key = key;
    let visible = 0, lowContrast = 0;
    const data = state.pixels.data;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 128) continue;
      visible++;
      if (contrast([data[i], data[i + 1], data[i + 2]], background) < 3) lowContrast++;
    }
    if (!visible || lowContrast / visible < .08) {
      state.rendered = state.original;
      if (image.src !== state.original) image.src = state.original;
      image.dataset.brandTreatment = 'original';
      return;
    }
    const ink = contrast([255, 255, 255], background) >= contrast([16, 19, 26], background) ? [255, 255, 255] : [16, 19, 26];
    let accent = /^#[a-f\d]{6}$/i.test(brand) ? [1, 3, 5].map(i => parseInt(brand.slice(i, i + 2), 16)) : [245, 160, 0];
    for (let step = 0; contrast(accent, background) < 3.2 && step < 12; step++) accent = mix(accent, ink, .2);
    const canvas = document.createElement('canvas');
    canvas.width = state.width; canvas.height = state.height;
    const context = canvas.getContext('2d');
    const output = new ImageData(new Uint8ClampedArray(data), state.width, state.height);
    for (let i = 0; i < data.length; i += 4) {
      const tone = luminance([data[i], data[i + 1], data[i + 2]]) > .45 ? ink : accent;
      output.data[i] = tone[0]; output.data[i + 1] = tone[1]; output.data[i + 2] = tone[2];
    }
    context.putImageData(output, 0, 0);
    state.rendered = canvas.toDataURL('image/png');
    image.src = state.rendered;
    image.dataset.brandTreatment = 'duotone';
  }
  function capture(image) {
    let state = states.get(image);
    if (state?.rendered === image.src && state.pixels) return;
    if (!image.complete || !image.naturalWidth) return;
    try {
      const canvas = document.createElement('canvas');
      const scale = Math.min(1, 768 / Math.max(image.naturalWidth, image.naturalHeight));
      canvas.width = Math.max(1, Math.round(image.naturalWidth * scale));
      canvas.height = Math.max(1, Math.round(image.naturalHeight * scale));
      const context = canvas.getContext('2d', {willReadFrequently: true});
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      state = {original: image.src, pixels: context.getImageData(0, 0, canvas.width, canvas.height), width: canvas.width, height: canvas.height};
      states.set(image, state);
      render(image);
    } catch (_) {
      // External images without CORS remain usable in their original colors.
      image.dataset.brandTreatment = 'original';
    }
  }
  let frame;
  function refresh() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => document.querySelectorAll('[data-adaptive-logo]').forEach(image => {capture(image); render(image);}));
  }
  document.querySelectorAll('[data-adaptive-logo]').forEach(image => image.addEventListener('load', () => capture(image)));
  new MutationObserver(refresh).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'style']});
  document.querySelectorAll('[data-brand-preview]').forEach(node => new MutationObserver(refresh).observe(node, {attributes: true, attributeFilter: ['style']}));
  window.addEventListener('resize', refresh);
  window.JumbiBranding = {refresh};
  refresh();
})();
