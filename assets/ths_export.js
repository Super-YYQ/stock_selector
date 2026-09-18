(function () {
  "use strict";

  // ===== 同花顺识股导出模块 =====
  // app.js 在每次 renderAll / switchView 后通过 window.__thsExport__.setScopes
  // 推送各视图当前可见股票的快照；本模块据此生成「专用识股图」与「识股文本」。
  // 画布一律白底黑字、仅名称 + 6 位代码、每页不超过 12 只，纯 Canvas 绘制，不取页面截图。

  var SCOPES = { reportDate: "", views: {}, currentView: "overview" };
  var PAGE_SIZE = 12;

  // 画布规格（需求 §10.3）
  var CANVAS_WIDTH = 1080;
  var CANVAS_PADDING_X = 48;
  var CANVAS_PADDING_Y = 48;
  var ROW_HEIGHT = 88;
  var ROW_GAP = 0;
  var COL_RANK_W = 96;       // 序号列宽
  var NAME_FONT = "600 40px 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Hiragino Sans GB', sans-serif";
  var CODE_FONT = "500 34px 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', 'Hiragino Sans GB', monospace";
  var RANK_FONT = "500 30px 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif";
  var PAGE_FONT = "400 22px 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif";

  // 配色（需求 §10.3）
  var COLOR_BG = "#FFFFFF";
  var COLOR_NAME = "#111111";
  var COLOR_CODE = "#444444";
  var COLOR_RANK = "#666666";
  var COLOR_LINE = "#DDDDDD";
  var COLOR_PAGE = "#9AA0A6";

  function code6(value) {
    return String(value == null ? "" : value).replace(/\D/g, "").padStart(6, "0").slice(-6);
  }

  function currentScope() {
    var view = SCOPES.currentView || "overview";
    return (SCOPES.views && SCOPES.views[view]) || { label: "", rows: [] };
  }

  function buildText(stocks) {
    return stocks.map(function (s) {
      return s.name + " " + code6(s.code);
    }).join("\n");
  }

  function pageTitle(scope, page, pages, total) {
    return "同花顺识股 · " + (scope.label || "当前名单") +
      (pages > 1 ? "（第 " + page + " / " + pages + " 页）" : "") +
      "  共 " + total + " 只";
  }

  function downloadDataURL(dataUrl, filename) {
    try {
      var a = document.createElement("a");
      a.href = dataUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      return true;
    } catch (e) {
      return false;
    }
  }

  function copyText(text, done, fail) {
    var onClipboard = function (writer) {
      var p = writer ? writer(text) : Promise.reject(new Error("no clipboard"));
      return p.then(done, fail);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallbackClip(text, done, fail); });
    } else {
      fallbackClip(text, done, fail);
    }
  }

  function fallbackClip(text, done, fail) {
    try {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      if (ok) done(); else fail(new Error("execCommand copy 失败"));
    } catch (e) {
      fail(e);
    }
  }

  // 画布按一页股票数组绘制；单页不画页码，多页画在底部（§6.4）
  function drawPageCanvas(rows, page, pages, total) {
    var rowsCount = rows.length;
    var height = CANVAS_PADDING_Y * 2 + rowsCount * (ROW_HEIGHT + ROW_GAP);
    var footerNeeded = pages > 1 || total > rowsCount;
    if (footerNeeded) height += 56;
    var canvas = document.createElement("canvas");
    var dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
    canvas.width = CANVAS_WIDTH * dpr;
    canvas.height = height * dpr;
    canvas.style.width = CANVAS_WIDTH + "px";
    canvas.style.height = height + "px";
    var ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    ctx.fillStyle = COLOR_BG;
    ctx.fillRect(0, 0, CANVAS_WIDTH, height);
    ctx.textBaseline = "middle";

    var startY = CANVAS_PADDING_Y;
    for (var i = 0; i < rowsCount; i++) {
      var row = rows[i];
      var y = startY + i * (ROW_HEIGHT + ROW_GAP) + ROW_HEIGHT / 2;
      // 序号
      var rank = row.rank || (i + 1);
      ctx.fillStyle = COLOR_RANK;
      ctx.font = RANK_FONT;
      ctx.textAlign = "left";
      ctx.fillText(String(rank) + ".", CANVAS_PADDING_X, y);
      var nameX = CANVAS_PADDING_X + COL_RANK_W;
      // 名称
      ctx.fillStyle = COLOR_NAME;
      ctx.font = NAME_FONT;
      var nameText = String(row.name || "--");
      var maxWidth = CANVAS_WIDTH - CANVAS_PADDING_X - 280; // 留出代码区宽度
      var nameWidth = ctx.measureText(nameText).width;
      if (nameWidth > maxWidth) {
        nameText = truncateText(ctx, nameText, maxWidth);
      }
      ctx.fillText(nameText, nameX, y);
      // 代码右对齐
      ctx.fillStyle = COLOR_CODE;
      ctx.font = CODE_FONT;
      ctx.textAlign = "right";
      ctx.fillText(code6(row.code), CANVAS_WIDTH - CANVAS_PADDING_X, y);
      ctx.textAlign = "left";
      // 分隔线
      if (i < rowsCount - 1) {
        var lineY = startY + (i + 1) * (ROW_HEIGHT + ROW_GAP);
        ctx.strokeStyle = COLOR_LINE;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(CANVAS_PADDING_X, lineY);
        ctx.lineTo(CANVAS_WIDTH - CANVAS_PADDING_X, lineY);
        ctx.stroke();
      }
    }
    // 页码
    if (footerNeeded) {
      var footY = height - 28;
      ctx.fillStyle = COLOR_PAGE;
      ctx.font = PAGE_FONT;
      ctx.textAlign = "right";
      ctx.fillText(pages > 1 ? "第 " + page + " / " + pages + " 页 · 共 " + total + " 只" : "共 " + total + " 只", CANVAS_WIDTH - CANVAS_PADDING_X, footY);
      ctx.textAlign = "left";
    }
    return canvas;
  }

  function truncateText(ctx, text, maxWidth) {
    var low = 0, high = text.length, mid;
    while (low < high) {
      mid = Math.floor((low + high + 1) / 2);
      if (ctx.measureText(text.slice(0, mid) + "…").width <= maxWidth) {
        low = mid;
      } else {
        high = mid - 1;
      }
    }
    return text.slice(0, low) + "…";
  }

  function chunk(arr, size) {
    if (!arr.length) return [[]];
    var pages = [];
    for (var i = 0; i < arr.length; i += size) pages.push(arr.slice(i, i + size));
    return pages;
  }

  // ============ 弹层 ============
  function createOverlay() {
    var backdrop = document.createElement("div");
    backdrop.className = "ths-overlay-backdrop";
    var dialog = document.createElement("div");
    dialog.className = "ths-dialog";
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    backdrop.appendChild(dialog);
    backdrop.addEventListener("click", function (e) {
      if (e.target === backdrop) closeOverlay(backdrop);
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeOverlay(backdrop);
    });
    document.body.appendChild(backdrop);
    document.body.classList.add("ths-overlay-open");
    return { backdrop: backdrop, dialog: dialog };
  }

  function closeOverlay(backdrop) {
    if (!backdrop || !backdrop.parentNode) return;
    backdrop.parentNode.removeChild(backdrop);
    document.body.classList.remove("ths-overlay-open");
  }

  function openTextDialog(scope) {
    var stocks = scope.rows || [];
    if (!stocks.length) { toast("当前名单无可导出股票"); return; }
    var text = buildText(stocks);
    var ui = createOverlay();
    var dialog = ui.dialog;
    dialog.innerHTML =
      '<div class="ths-dialog-head">' +
        '<h3>同花顺文本识股</h3>' +
        '<button type="button" class="ths-close" aria-label="关闭"><i data-lucide="x"></i></button>' +
      '</div>' +
      '<div class="ths-dialog-sub">仅含“名称 代码”，一行一只，可直接粘贴到同花顺「AI 文本识股」</div>' +
      '<textarea readonly class="ths-text-box"></textarea>' +
      '<div class="ths-dialog-foot">' +
        '<span class="ths-count">' + stocks.length + ' 只 · ' + (scope.label || "当前名单") + '</span>' +
        '<div><button type="button" class="secondary-button ths-copy"><i data-lucide="clipboard-copy"></i><span>复制文本</span></button>' +
        '<button type="button" class="ghost-button ths-close-btn">关闭</button></div>' +
      '</div>';
    dialog.querySelector(".ths-text-box").value = text;
    dialog.querySelector(".ths-close").addEventListener("click", function () { closeOverlay(ui.backdrop); });
    dialog.querySelector(".ths-close-btn").addEventListener("click", function () { closeOverlay(ui.backdrop); });
    dialog.querySelector(".ths-copy").addEventListener("click", function () {
      copyText(text, function () { toast("已复制 " + stocks.length + " 只股票文本"); },
        function () { toast("复制失败，请手动选择文本框内容复制"); });
    });
    if (window.lucide) window.lucide.createIcons();
  }

  function openImageDialog(scope) {
    var stocks = scope.rows || [];
    if (!stocks.length) { toast("当前名单无可导出股票"); return; }
    var total = stocks.length;
    var pages = chunk(stocks, PAGE_SIZE);
    var pageCount = pages.length;
    var current = 1;
    var ui = createOverlay();
    var dialog = ui.dialog;
    dialog.classList.add("ths-image-dialog");
    dialog.innerHTML =
      '<div class="ths-dialog-head">' +
        '<h3>同花顺识股图片</h3>' +
        '<button type="button" class="ths-close" aria-label="关闭"><i data-lucide="x"></i></button>' +
      '</div>' +
      '<div class="ths-image-wrap"><div class="ths-image-scroll"><div class="ths-canvas-host"></div></div></div>' +
      '<div class="ths-pager">' +
        '<button type="button" class="icon-button ths-prev" disabled><i data-lucide="chevron-left"></i></button>' +
        '<span class="ths-page-no">1 / 1</span>' +
        '<button type="button" class="icon-button ths-next" disabled><i data-lucide="chevron-right"></i></button>' +
      '</div>' +
      '<div class="ths-dialog-foot ths-image-foot">' +
        '<span class="ths-count ths-tip"><i data-lucide="info"></i><span>如无法下载，长按图片保存到相册</span></span>' +
        '<div><button type="button" class="secondary-button ths-download"><i data-lucide="download"></i><span>下载本页图片</span></button>' +
        '<button type="button" class="ghost-button ths-close-btn">关闭</button></div>' +
      '</div>';

    var host = dialog.querySelector(".ths-canvas-host");
    var pageNoEl = dialog.querySelector(".ths-page-no");
    var prevBtn = dialog.querySelector(".ths-prev");
    var nextBtn = dialog.querySelector(".ths-next");

    function render() {
      var pageRows = pages[current - 1] || [];
      var canvas = drawPageCanvas(pageRows, current, pageCount, total);
      host.innerHTML = "";
      host.appendChild(canvas);
      pageNoEl.textContent = pageCount > 1 ? current + " / " + pageCount : (total + " 只");
      prevBtn.disabled = current <= 1;
      nextBtn.disabled = current >= pageCount;
      if (window.lucide) window.lucide.createIcons();
    }

    function filename() {
      var date = SCOPES.reportDate || "";
      var label = (scope.label || "识股").replace(/[\\/:*?"<>|]/g, "");
      return "识股图_" + (date ? date + "_" : "") + label + "_第" + current + "页.png";
    }

    prevBtn.addEventListener("click", function () { if (current > 1) { current--; render(); } });
    nextBtn.addEventListener("click", function () { if (current < pageCount) { current++; render(); } });
    dialog.querySelector(".ths-close").addEventListener("click", function () { closeOverlay(ui.backdrop); });
    dialog.querySelector(".ths-close-btn").addEventListener("click", function () { closeOverlay(ui.backdrop); });
    dialog.querySelector(".ths-download").addEventListener("click", function () {
      var canvas = host.querySelector("canvas");
      if (!canvas) return;
      var url;
      try { url = canvas.toDataURL("image/png"); }
      catch (e) { toast("图片生成失败：" + (e.message || e)); return; }
      var ok = downloadDataURL(url, filename());
      if (!ok) toast("浏览器拦截了下载，请长按图片保存");
      else toast("已开始下载 " + filename());
    });
    render();
  }

  // ============ 按钮 UI ============
  function injectButton(parent, type, label, icon, viewName) {
    if (parent.querySelector('[data-ths="' + type + '"][data-ths-view="' + viewName + '"]')) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary-button ths-export-button";
    btn.setAttribute("data-ths", type);
    btn.setAttribute("data-ths-view", viewName);
    btn.innerHTML = '<i data-lucide="' + icon + '"></i><span>' + label + '</span>';
    btn.addEventListener("click", function () {
      var saved = SCOPES.currentView;
      SCOPES.currentView = viewName;
      var scope = currentScope();
      SCOPES.currentView = saved;
      if (type === "image") openImageDialog(scope);
      else openTextDialog(scope);
    });
    parent.appendChild(btn);
    if (window.lucide) window.lucide.createIcons();
  }

  function injectButtons() {
    var focusToolbar = document.querySelector("#view-overview .focus-toolbar .compact-filters");
    if (focusToolbar) {
      injectButton(focusToolbar, "text", "识股文本", "clipboard-list", "overview");
      injectButton(focusToolbar, "image", "识股图片", "image", "overview");
    }
    var watchToolbar = document.querySelector("#view-watchlist .page-toolbar");
    if (watchToolbar) {
      injectButton(watchToolbar, "text", "识股文本", "clipboard-list", "watchlist");
      injectButton(watchToolbar, "image", "识股图片", "image", "watchlist");
    }
    var customToolbar = document.querySelector("#view-custom .custom-toolbar");
    if (customToolbar) {
      injectButton(customToolbar, "text", "识股文本", "clipboard-list", "custom");
      injectButton(customToolbar, "image", "识股图片", "image", "custom");
    }
  }

  // ============ toast（复用 #toast 节点）============
  var toastTimer = null;
  function toast(message) {
    var node = document.getElementById("toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("show");
    if (toastTimer) window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(function () { node.classList.remove("show"); }, 2800);
  }

  // ============ 对外接口 ============
  window.__thsExport__ = {
    setScopes: function (scopes) {
      SCOPES = scopes || { reportDate: "", views: {}, currentView: "overview" };
    }
  };

  // 注入按钮（DOM 已就绪；脚本在 app.js 之后加载）
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", injectButtons);
  } else {
    injectButtons();
  }
  // app.js 的 renderAll 可能在本模块加载前已执行过一次，按钮注入后无妨——
  // 导出按需时实时读取最新 SCOPES（由每次 renderAll/switchView 重推），无需重试历史快照。
}());
