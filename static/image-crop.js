/* 轻量裁剪器：个人主页背景等「固定比例封面」复用同一套交互。
   原生 canvas 实现，无第三方依赖；只裁剪不美化，输出的图仍走 /api/forum/images。 */
(() => {
  "use strict";

  const MAX_WIDTH = 1600;
  let dialog = null;

  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (key === "text") node.textContent = value;
      else if (key === "className") node.className = value;
      else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
      else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
    }
    node.append(...children.filter((child) => child != null));
    return node;
  }

  function ensureDialog() {
    if (dialog) return dialog;
    const stage = el("div", { className: "crop-stage" });
    const picture = el("img", { className: "crop-picture", alt: "" });
    const slider = el("input", { type: "range", className: "crop-zoom", min: "1", max: "4", step: "0.01", value: "1", "aria-label": "缩放" });
    stage.append(picture);
    const cancel = el("button", { type: "button", className: "crop-button", text: "取消" });
    const confirm = el("button", { type: "button", className: "crop-button crop-button-primary", text: "设为背景" });
    const hint = el("p", { className: "crop-hint", text: "拖动调整位置，滑块缩放；Shift + 滚轮也可以缩放。" });
    dialog = el("dialog", { className: "crop-dialog", "aria-label": "裁剪封面" },
      el("div", { className: "crop-head" }, el("h2", { text: "裁剪封面" }), hint),
      stage,
      el("div", { className: "crop-controls" }, el("span", { className: "crop-zoom-label", text: "缩放" }), slider, cancel, confirm),
    );
    document.body.append(dialog);
    dialog.stage = stage; dialog.picture = picture; dialog.slider = slider;
    dialog.cancelButton = cancel; dialog.confirmButton = confirm; dialog.hint = hint;
    return dialog;
  }

  function open(file, options = {}) {
    const ratio = Math.max(0.6, Math.min(8, options.ratio || 3));
    const ui = ensureDialog();
    ui.hint.textContent = options.hint || "拖动调整位置，滑块缩放；Shift + 滚轮也可以缩放。";
    ui.confirmButton.textContent = options.confirmText || "设为背景";

    return new Promise((resolve, reject) => {
      const objectUrl = URL.createObjectURL(file);
      const image = new Image();
      const state = { scale: 1, minScale: 1, x: 0, y: 0, frameWidth: 0, frameHeight: 0, drag: null };

      const clamp = () => {
        const width = image.naturalWidth * state.scale, height = image.naturalHeight * state.scale;
        state.x = Math.min(0, Math.max(state.frameWidth - width, state.x));
        state.y = Math.min(0, Math.max(state.frameHeight - height, state.y));
      };
      const render = () => {
        const width = image.naturalWidth * state.scale, height = image.naturalHeight * state.scale;
        ui.picture.style.width = `${width}px`;
        ui.picture.style.height = `${height}px`;
        ui.picture.style.transform = `translate(${state.x}px, ${state.y}px)`;
      };
      const layout = () => {
        const frame = ui.stage.getBoundingClientRect();
        if (!frame.width) return;
        state.frameWidth = frame.width;
        state.frameHeight = frame.width / ratio;
        ui.stage.style.height = `${state.frameHeight}px`;
        // 最小缩放 = 刚好铺满裁剪框；换比例或转屏后重新计算并夹回可拖范围。
        state.minScale = Math.max(state.frameWidth / image.naturalWidth, state.frameHeight / image.naturalHeight);
        ui.slider.min = String(state.minScale);
        if (state.scale < state.minScale) {
          state.scale = state.minScale;
          ui.slider.value = String(state.scale);
        }
        clamp(); render();
      };

      const cleanup = () => {
        ui.stage.removeEventListener("pointerdown", down);
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        window.removeEventListener("resize", layout);
        ui.stage.removeEventListener("wheel", wheel);
        ui.slider.removeEventListener("input", zoom);
        ui.cancelButton.removeEventListener("click", cancel);
        ui.confirmButton.removeEventListener("click", confirm);
        dialog.removeEventListener("cancel", cancelEvent);
        if (dialog.open) dialog.close();
        URL.revokeObjectURL(objectUrl);
        ui.picture.removeAttribute("src");
        ui.picture.removeAttribute("style");
      };
      const finish = (result) => { cleanup(); resolve(result); };
      const cancel = () => finish(null);
      const cancelEvent = (event) => { event.preventDefault(); cancel(); };

      const down = (event) => {
        if (event.button != null && event.button !== 0) return;
        event.preventDefault();
        state.drag = { x: event.clientX, y: event.clientY, left: state.x, top: state.y };
        ui.picture.setPointerCapture?.(event.pointerId);
      };
      const move = (event) => {
        if (!state.drag) return;
        state.x = state.drag.left + event.clientX - state.drag.x;
        state.y = state.drag.top + event.clientY - state.drag.y;
        clamp(); render();
      };
      const up = () => { state.drag = null; };
      const zoom = () => {
        state.scale = Number(ui.slider.value);
        clamp(); render();
      };
      const wheel = (event) => {
        if (!event.shiftKey && Math.abs(event.deltaY) < 2) return;
        event.preventDefault();
        const next = Math.min(4, Math.max(state.minScale, state.scale * (event.deltaY < 0 ? 1.08 : 1 / 1.08)));
        state.scale = next;
        ui.slider.value = String(next);
        clamp(); render();
      };

      const confirm = () => {
        const frame = ui.stage.getBoundingClientRect();
        const sourceX = -state.x / state.scale, sourceY = -state.y / state.scale;
        const sourceWidth = frame.width / state.scale, sourceHeight = frame.height / state.scale;
        const width = Math.min(MAX_WIDTH, Math.round(sourceWidth));
        const height = Math.max(1, Math.round(width / ratio));
        const canvas = document.createElement("canvas");
        canvas.width = width; canvas.height = height;
        const context = canvas.getContext("2d");
        context.imageSmoothingQuality = "high";
        context.drawImage(image, sourceX, sourceY, sourceWidth, sourceHeight, 0, 0, width, height);
        const done = (blob) => finish(blob ? new File([blob], "cover.webp", { type: blob.type }) : null);
        if (canvas.toBlob) canvas.toBlob(done, "image/webp", 0.88);
        else finish(null);
      };

      image.onload = () => {
        ui.picture.src = objectUrl;
        ui.stage.addEventListener("pointerdown", down);
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
        window.addEventListener("resize", layout);
        ui.stage.addEventListener("wheel", wheel, { passive: false });
        ui.slider.addEventListener("input", zoom);
        ui.cancelButton.addEventListener("click", cancel);
        ui.confirmButton.addEventListener("click", confirm);
        dialog.addEventListener("cancel", cancelEvent);
        if (!dialog.open) dialog.showModal();
        // 等 dialog 完成布局，取到的宽度才不是 0。
        requestAnimationFrame(() => {
          const frame = ui.stage.getBoundingClientRect();
          state.frameWidth = frame.width || 1;
          state.frameHeight = state.frameWidth / ratio;
          ui.stage.style.height = `${state.frameHeight}px`;
          state.minScale = Math.max(state.frameWidth / image.naturalWidth, state.frameHeight / image.naturalHeight);
          state.scale = state.minScale;
          ui.slider.min = String(state.minScale);
          ui.slider.value = String(state.scale);
          state.x = (state.frameWidth - image.naturalWidth * state.scale) / 2;
          state.y = (state.frameHeight - image.naturalHeight * state.scale) / 2;
          clamp(); render();
        });
      };
      image.onerror = () => { URL.revokeObjectURL(objectUrl); cleanup(); reject(new Error("这张图片无法读取，请换一张试试")); };
      image.src = objectUrl;
    });
  }

  window.KflowCrop = { open };
})();
