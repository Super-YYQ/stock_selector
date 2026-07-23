(function () {
  "use strict";

  var state = {
    payload: null,
    status: null,
    scheduler: null,
    strategies: null,
    customStrategies: null,
    pool: null,
    mode: "local",
    ready: false,
    schedulerDirty: false,
    listName: "top50",
    search: "",
    board: "",
    focusSearch: "",
    focusBoard: "",
    focusStockCode: "",
    activeCustomKey: "",
    customSearch: ""
  };

  var viewMeta = {
    overview: ["盘后复盘", "市场概览"],
    watchlist: ["综合排序", "观察名单"],
    custom: ["公式筛选", "自定义策略"],
    strategies: ["规则配置", "策略配置"],
    system: ["数据与任务", "运行状态"]
  };

  function byId(id) { return document.getElementById(id); }
  function all(selector) { return Array.prototype.slice.call(document.querySelectorAll(selector)); }
  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#039;");
  }
  function number(value, digits) {
    var n = Number(value);
    return Number.isFinite(n) ? n.toFixed(digits == null ? 2 : digits) : "--";
  }
  function pct(value) {
    var n = Number(value);
    if (!Number.isFinite(n)) return "--";
    return (n > 0 ? "+" : "") + n.toFixed(2) + "%";
  }
  function valueClass(value) {
    var n = Number(value);
    return n > 0 ? "positive" : (n < 0 ? "negative" : "");
  }
  function splitTags(value, limit) {
    var items = String(value || "").split(/[、,，·；;]/).map(function (item) {
      return item.trim();
    }).filter(Boolean);
    return Array.from(new Set(items)).slice(0, limit || 4);
  }
  function tagHtml(items, kind) {
    return '<div class="tag-list">' + items.map(function (item) {
      return '<span class="tag ' + (kind || "") + '">' + escapeHtml(item) + "</span>";
    }).join("") + "</div>";
  }
  function toast(message) {
    var node = byId("toast");
    node.textContent = message;
    node.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(function () { node.classList.remove("show"); }, 2800);
  }
  function icons() {
    if (window.lucide) window.lucide.createIcons();
  }
  async function request(path, options) {
    var controller = new AbortController();
    var timer = window.setTimeout(function () { controller.abort(); }, 15000);
    try {
      var response = await fetch(path, Object.assign({ cache: "no-store", signal: controller.signal }, options || {}));
      if (!response.ok) {
        var detail = "";
        try {
          var errorBody = await response.json();
          detail = typeof errorBody.detail === "string" ? errorBody.detail : JSON.stringify(errorBody.detail || "");
        } catch (ignore) {
          detail = "";
        }
        throw new Error(detail || ("HTTP " + response.status));
      }
      return await response.json();
    } finally {
      window.clearTimeout(timer);
    }
  }

  async function load() {
    setConnection("loading", "正在读取数据");
    state.ready = false;
    renderRunner((state.status && state.status.runner) || {});
    try {
      state.payload = await request("/api/latest");
      state.mode = "local";
      document.body.classList.remove("static-mode");
      await loadLocalState();
      state.ready = true;
    } catch (apiError) {
      try {
        state.payload = await request("data/latest.json");
        state.mode = "static";
        state.ready = false;
        state.status = null;
        state.strategies = null;
        state.customStrategies = null;
        state.pool = null;
        document.body.classList.add("static-mode");
      } catch (staticError) {
        setConnection("error", "暂无报告数据");
        renderEmpty();
        return;
      }
    }
    renderAll();
    setConnection("ok", state.mode === "local" ? "本地服务已连接" : "云端报告");
  }

  async function loadLocalState() {
    var results = await Promise.allSettled([
      request("/api/status"),
      request("/api/strategies"),
      request("/api/pool-config"),
      request("/api/custom-strategies"),
      request("/api/scheduler")
    ]);
    if (results[0].status === "fulfilled") state.status = results[0].value;
    if (results[1].status === "fulfilled") state.strategies = results[1].value;
    if (results[2].status === "fulfilled") state.pool = results[2].value;
    if (results[3].status === "fulfilled") state.customStrategies = results[3].value;
    if (results[4].status === "fulfilled") state.scheduler = results[4].value;
  }

  function setConnection(kind, label) {
    var dot = byId("sidebar-status-dot");
    dot.className = "status-dot" + (kind === "ok" ? " ok" : kind === "error" ? " error" : "");
    byId("sidebar-status").textContent = label;
  }

  function renderEmpty() {
    byId("report-date").textContent = "暂无报告";
    byId("focus-table").innerHTML = '<tbody><tr><td class="empty-state">请先执行初始化或每日任务</td></tr></tbody>';
    byId("watchlist-table").innerHTML = '<tbody><tr><td class="empty-state">暂无观察名单</td></tr></tbody>';
    byId("custom-results-table").innerHTML = '<tbody><tr><td class="empty-state">暂无自定义策略结果</td></tr></tbody>';
  }

  function renderAll() {
    var payload = state.payload || {};
    var market = payload.market || {};
    var health = payload.health || {};
    var upRatio = Number(market.up_ratio);
    byId("report-date").textContent = payload.report_date || "--";
    byId("brief-date").textContent = payload.report_date || "--";
    byId("sidebar-date").textContent = "数据截止 " + (payload.report_date || "--");
    byId("generated-at").textContent = payload.generated_at ? "生成于 " + payload.generated_at.replace("T", " ") : "--";
    byId("kpi-market").textContent = market.market_label || "--";
    byId("kpi-risk").textContent = "风险 " + (market.risk_level || "--");
    byId("kpi-score").textContent = number(market.market_score, 1);
    byId("kpi-up-ratio").textContent = Number.isFinite(upRatio) ? number(upRatio, 1) + "%" : "--";
    byId("kpi-limit").textContent = "涨停 " + (market.limit_up_count || 0) + " / 跌停 " + (market.limit_down_count || 0);
    byId("kpi-coverage").textContent = "数据覆盖 " + number(Number(health.stock_coverage || 0) * 100, 1) + "%";
    byId("kpi-symbols").textContent = (health.covered_symbols || health.latest_symbol_count || 0) + " 只";
    byId("market-score-large").textContent = number(market.market_score, 1);
    byId("market-score-bar").style.width = Math.max(0, Math.min(100, Number(market.market_score || 0) * 10)) + "%";
    byId("evidence-score").textContent = number(market.market_score, 1);
    byId("evidence-up").textContent = Number.isFinite(upRatio) ? number(upRatio, 1) + "%" : "--";
    byId("evidence-limit").textContent = "上涨 " + (market.limit_up_count || 0) + " / 下跌 " + (market.limit_down_count || 0);
    byId("evidence-symbols").textContent = (health.covered_symbols || health.latest_symbol_count || 0) + " 只";
    byId("evidence-coverage").textContent = "数据覆盖 " + number(Number(health.stock_coverage || 0) * 100, 1) + "%";
    byId("evidence-temperature").textContent = number(market.market_score, 1);
    byId("evidence-bar").style.width = Math.max(0, Math.min(100, Number(market.market_score || 0) * 10)) + "%";
    var risk = byId("market-risk-badge");
    risk.textContent = "风险 " + (market.risk_level || "--");
    risk.className = "risk-inline " + (market.risk_level === "高" ? "high" : market.risk_level === "低" ? "low" : "");
    renderMarketGuidance(market, payload.strong_sectors || []);
    renderIndexes(market.index_changes || {});
    renderEvidenceIndexes(market.index_changes || {});
    renderSectors(payload.strong_sectors || []);
    renderFocus(payload.top10 || []);
    renderWatchlist();
    renderCustomStrategies();
    renderStrategies();
    renderPool();
    renderPerformance(payload.strategy_performance || []);
    renderSystem();
    icons();
  }

  function renderMarketGuidance(market, sectors) {
    var label = market.market_label || "震荡";
    var guidance = label === "偏强"
      ? "市场环境偏强，聚焦主线板块的量价确认，避免连续加速后的追高。"
      : label === "偏弱"
        ? "市场偏弱、量能收缩。高估值与资金博弈加剧，控制仓位，聚焦强势结构与业绩线索。"
        : "市场维持震荡，优先等待板块和个股形成共振，减少方向不明时的试错。";
    byId("market-guidance").textContent = guidance;
    var sectorName = sectors.length ? (sectors[0].sector_name || sectors[0].industry || "强势板块") : "强势板块";
    var guardrails = [
      "关注" + sectorName + "延续性与量能配合",
      label === "偏弱" ? "回避跌幅靠前及量能放大的弱势方向" : "观察领涨股回踩后的承接强度",
      "设好止损，保留现金与盘中调整空间"
    ];
    byId("guardrail-list").innerHTML = guardrails.map(function (item) {
      return "<li>" + escapeHtml(item) + "</li>";
    }).join("");
  }

  function renderEvidenceIndexes(changes) {
    var labels = { sh000001: "上证指数", sz399001: "深证成指", sz399006: "创业板指" };
    byId("evidence-index-grid").innerHTML = Object.keys(labels).map(function (code) {
      var change = Number(changes[code] || 0);
      return '<div><span>' + labels[code] + '</span><strong class="' + valueClass(change) + '">' + pct(change) + "</strong></div>";
    }).join("");
  }

  function renderIndexes(changes) {
    var labels = { sh000001: "上证指数", sz399001: "深证成指", sz399006: "创业板指" };
    byId("index-grid").innerHTML = Object.keys(labels).map(function (code) {
      var change = Number(changes[code] || 0);
      return '<div class="index-item"><span>' + labels[code] + '</span><strong class="' +
        valueClass(change) + '">' + pct(change) + "</strong></div>";
    }).join("");
  }

  function renderSectors(items) {
    byId("sector-count").textContent = items.length + " 个板块";
    byId("sector-list").innerHTML = items.slice(0, 8).map(function (item, index) {
      var score = Number(item.sector_score_raw || 0);
      return '<div class="sector-item" title="' + escapeHtml(item.sector_reason || "") + '">' +
        '<b>' + (index + 1) + '</b><strong>' + escapeHtml(item.sector_name || item.industry || "--") + '</strong>' +
        '<span class="sector-bar"><span style="width:' + Math.max(3, Math.min(100, score)) + '%"></span></span>' +
        '<em class="' + valueClass(item.pct_chg) + '">' + pct(item.pct_chg) + "</em></div>";
    }).join("") || '<div class="empty-state">暂无板块数据</div>';
  }
  function tableHtml(columns, rows) {
    var head = "<thead><tr>" + columns.map(function (column) {
      return "<th>" + column.label + "</th>";
    }).join("") + "</tr></thead>";
    if (!rows.length) {
      return head + '<tbody><tr><td class="empty-state" colspan="' + columns.length + '">暂无数据</td></tr></tbody>';
    }
    var body = rows.map(function (row) {
      return "<tr>" + columns.map(function (column) {
        var raw = row[column.key];
        var display = column.format ? column.format(raw, row) : escapeHtml(raw);
        var classes = column.className ? column.className(raw, row) : "";
        return '<td class="' + classes + '">' + display + "</td>";
      }).join("") + "</tr>";
    }).join("");
    return head + "<tbody>" + body + "</tbody>";
  }

  function stockIdentity(value, row) {
    return '<div class="stock-cell"><strong>' + escapeHtml(row.name || "--") + '</strong><small>' +
      escapeHtml(String(row.code || "").padStart(6, "0")) + "</small></div>";
  }

  function contextCell(value, row) {
    var industry = row.industry && !/^(沪市主板|深市主板|创业板|科创板|北交所|其他)$/.test(row.industry)
      ? row.industry : (row.sector || row.market_board || row.industry || "--");
    var details = splitTags(row.concepts, 2).join(" · ") || row.market_board || row.sector || "--";
    return '<div class="context-cell"><strong>' + escapeHtml(industry) + '</strong><small title="' +
      escapeHtml(row.concepts || details) + '">' + escapeHtml(details) + "</small></div>";
  }

  function signalCell(value, row) {
    var source = row.reason_tags || row.selection_reason_short || row.matched_strategies || "";
    var tags = splitTags(source, 2);
    if (!tags.length) tags = ["规则入选"];
    return tagHtml(tags, "");
  }

  function riskCell(value, row) {
    var tags = splitTags(row.risk_tags, 2);
    if (!tags.length && Number(row.risk_penalty || 0) > 0) tags = ["扣 " + number(row.risk_penalty, 1) + " 分"];
    if (!tags.length) return '<span class="risk-quiet">--</span>';
    return tagHtml(tags, "risk");
  }

  function detailButton(value, row) {
    return '<button class="icon-button detail-button" data-detail="' +
      escapeHtml(String(row.code || "")) + '" title="查看完整说明" aria-label="查看完整说明"><i data-lucide="panel-right-open"></i></button>';
  }

  var focusColumns = [
    { key: "rank", label: "#", className: function (v) { return "rank-cell " + (Number(v) <= 3 ? "top" : ""); } },
    { key: "name", label: "股票", format: stockIdentity },
    { key: "industry", label: "行业 / 题材", format: contextCell },
    { key: "total_score", label: "综合分", className: function () { return "score-cell"; }, format: function (v) { return number(v, 2); } },
    { key: "pct_chg", label: "今日涨跌", className: valueClass, format: pct },
    { key: "amount_ratio", label: "量比", format: function (v) { return number(v, 2) + "x"; } },
    { key: "market_board", label: "所属板块" }
  ];

  var watchColumns = [
    { key: "rank", label: "#", className: function (v) { return "rank-cell " + (Number(v) <= 3 ? "top" : ""); } },
    { key: "name", label: "股票", format: stockIdentity },
    { key: "total_score", label: "总分", className: function () { return "score-cell"; }, format: function (v) { return number(v, 2); } },
    { key: "industry", label: "行业 / 题材", format: contextCell },
    { key: "pct_chg", label: "今日", className: valueClass, format: pct },
    { key: "return_5d", label: "近5日", className: valueClass, format: pct },
    { key: "amount_ratio", label: "量比", format: function (v) { return number(v, 2) + "x"; } },
    { key: "rps20", label: "RPS20", format: function (v) { return number(v, 0); } },
    { key: "reason_tags", label: "入选信号", className: function () { return "signal-cell"; }, format: signalCell },
    { key: "risk_tags", label: "风险", format: riskCell },
    { key: "code", label: "", format: detailButton }
  ];

  function renderFocus(rows) {
    var query = state.focusSearch.trim().toLowerCase();
    var filtered = rows.filter(function (row) {
      if (state.focusBoard && String(row.market_board || row.industry || "") !== state.focusBoard) return false;
      if (!query) return true;
      return [row.code, row.name, row.industry, row.sector, row.market_board, row.concepts].some(function (value) {
        return String(value || "").toLowerCase().indexOf(query) >= 0;
      });
    });
    byId("focus-table").innerHTML = tableHtml(focusColumns, filtered);
    bindDetailButtons(byId("focus-table"));
    if (!filtered.length) {
      renderFocusInspector(null);
      return;
    }
    if (!filtered.some(function (row) { return String(row.code) === String(state.focusStockCode); })) {
      state.focusStockCode = String(filtered[0].code || "");
    }
    Array.prototype.slice.call(byId("focus-table").querySelectorAll("tbody tr")).forEach(function (rowNode, index) {
      var row = filtered[index];
      if (!row) return;
      rowNode.dataset.code = row.code;
      rowNode.classList.toggle("selected", String(row.code) === String(state.focusStockCode));
      rowNode.addEventListener("click", function (event) {
        if (event.target.closest("button")) return;
        state.focusStockCode = String(row.code || "");
        renderFocus(filtered);
      });
    });
    renderFocusInspector(filtered.find(function (row) {
      return String(row.code) === String(state.focusStockCode);
    }) || filtered[0]);
  }

  function renderFocusInspector(row) {
    if (!row) {
      byId("focus-stock-name").textContent = "暂无匹配股票";
      byId("focus-stock-subtitle").textContent = "--";
      byId("focus-stock-board").textContent = "--";
      byId("focus-stock-score").textContent = "--";
      byId("focus-stock-change").textContent = "--";
      byId("focus-stock-metrics").innerHTML = "";
      byId("focus-stock-signals").textContent = "--";
      byId("focus-stock-reason").textContent = "--";
      byId("focus-stock-concepts").innerHTML = "";
      byId("focus-stock-condition").textContent = "--";
      byId("focus-stock-detail").dataset.code = "";
      return;
    }
    byId("focus-stock-name").textContent = row.name || "--";
    byId("focus-stock-subtitle").textContent = String(row.code || "").padStart(6, "0") + " · " + (row.industry || row.sector || "--");
    byId("focus-stock-board").textContent = row.market_board || "--";
    byId("focus-stock-score").textContent = number(row.total_score, 2);
    byId("focus-stock-change").textContent = pct(row.pct_chg);
    byId("focus-stock-change").className = valueClass(row.pct_chg);
    var metrics = [
      ["量比", number(row.amount_ratio, 2) + "x"],
      ["RPS20", number(row.rps20, 0)],
      ["风险扣分", number(row.risk_penalty, 1)]
    ];
    byId("focus-stock-metrics").innerHTML = metrics.map(function (item) {
      return "<div><dt>" + item[0] + "</dt><dd>" + escapeHtml(item[1]) + "</dd></div>";
    }).join("");
    var signals = splitTags(row.reason_tags || row.matched_strategies, 4);
    byId("focus-stock-signals").textContent = signals.join(" · ") || "规则入选";
    byId("focus-stock-reason").textContent = row.selection_reason_short || row.selection_reason || "--";
    byId("focus-stock-concepts").innerHTML = splitTags(row.concepts, 6).map(function (item) {
      return '<span class="tag">' + escapeHtml(item) + "</span>";
    }).join("");
    byId("focus-stock-condition").textContent = row.next_day_condition || "--";
    byId("focus-stock-detail").dataset.code = String(row.code || "");
    icons();
  }

  function renderWatchlist() {
    if (!state.payload) return;
    var source = state.payload[state.listName] || [];
    var query = state.search.trim().toLowerCase();
    var rows = source.filter(function (row) {
      var boardMatches = !state.board || String(row.market_board || row.industry || "") === state.board;
      if (!boardMatches) return false;
      if (!query) return true;
      return [
        row.code, row.name, row.industry, row.sector, row.market_board, row.concepts,
        row.reason_tags, row.matched_strategies
      ].some(function (value) {
        return String(value || "").toLowerCase().indexOf(query) >= 0;
      });
    });
    byId("watchlist-heading").textContent = state.listName === "top10" ? "Top 10 重点关注" : "Top 50 观察名单";
    byId("watchlist-count").textContent = rows.length + " 只股票";
    byId("watchlist-table").innerHTML = tableHtml(watchColumns, rows);
    bindDetailButtons(byId("watchlist-table"));
    icons();
  }

  function findStock(code) {
    var payload = state.payload || {};
    var customResults = state.customStrategies && state.customStrategies.results
      ? state.customStrategies.results : (payload.custom_strategy_results || []);
    return (payload.top50 || []).concat(payload.top10 || [], customResults).find(function (row) {
      return String(row.code || "") === String(code || "");
    });
  }

  function breakdownRow(label, value, maximum, risk) {
    var numeric = Math.max(0, Number(value || 0));
    var width = Math.max(0, Math.min(100, numeric / maximum * 100));
    var color = risk ? "var(--coral)" : "var(--green)";
    return '<div class="breakdown-row"><span>' + label + '</span><span class="breakdown-track"><i style="width:' +
      width + "%;background:" + color + '"></i></span><span>' + number(numeric, 1) + "</span></div>";
  }

  function openDrawer(code) {
    var row = findStock(code);
    if (!row) return;
    var stockCode = String(row.code || "").padStart(6, "0");
    byId("drawer-title").textContent = row.name || "--";
    byId("drawer-subtitle").textContent = stockCode + " · " +
      [row.market_board, row.industry].filter(Boolean).join(" · ");
    byId("drawer-score").textContent = number(row.total_score, 2);
    byId("drawer-change").textContent = pct(row.pct_chg);
    byId("drawer-change").className = valueClass(row.pct_chg);
    byId("drawer-tags").innerHTML = splitTags(row.reason_tags || row.matched_strategies, 6).map(function (item) {
      return '<span class="tag accent">' + escapeHtml(item) + "</span>";
    }).join("");
    byId("drawer-breakdown").innerHTML =
      breakdownRow("板块", row.sector_score, 25) +
      breakdownRow("股性", row.stock_character_score, 20) +
      breakdownRow("量价", row.volume_price_score, 25) +
      breakdownRow("相对强弱", row.relative_strength_score, 15) +
      breakdownRow("策略", row.strategy_score, 15) +
      breakdownRow("大盘修正", row.market_adjust_score, 10) +
      breakdownRow("风险扣分", row.risk_penalty, 20, true);
    byId("drawer-context").textContent = row.stock_context_summary ||
      [row.industry ? "所属行业：" + row.industry : "", row.industry_activity || "", row.limit_up_reason || ""].filter(Boolean).join("；") ||
      "暂无稳定行业与题材说明";
    byId("drawer-concepts").innerHTML = splitTags(row.concepts, 12).map(function (item) {
      return '<span class="tag">' + escapeHtml(item) + "</span>";
    }).join("");
    byId("drawer-reason").textContent = row.selection_reason || row.selection_reason_short || "--";
    byId("drawer-condition").textContent = row.next_day_condition || "--";
    byId("drawer-risk").textContent = row.risk_warning || "暂无明显量化风险";
    byId("drawer-backdrop").classList.add("open");
    byId("stock-drawer").classList.add("open");
    byId("stock-drawer").setAttribute("aria-hidden", "false");
    document.body.classList.add("drawer-open");
    icons();
  }

  function closeDrawer() {
    byId("drawer-backdrop").classList.remove("open");
    byId("stock-drawer").classList.remove("open");
    byId("stock-drawer").setAttribute("aria-hidden", "true");
    document.body.classList.remove("drawer-open");
  }

  function bindDetailButtons(root) {
    Array.prototype.slice.call(root.querySelectorAll("[data-detail]")).forEach(function (button) {
      button.addEventListener("click", function () { openDrawer(button.dataset.detail); });
    });
  }

  var customColumns = [
    { key: "formula_rank", label: "#", className: function (v) { return "rank-cell " + (Number(v) <= 3 ? "top" : ""); } },
    { key: "name", label: "股票", format: stockIdentity },
    { key: "total_score", label: "综合分", className: function () { return "score-cell"; }, format: function (v) { return number(v, 2); } },
    { key: "industry", label: "行业 / 题材", format: contextCell },
    { key: "pct_chg", label: "今日", className: valueClass, format: pct },
    { key: "amount_ratio", label: "量比", format: function (v) { return number(v, 2) + "x"; } },
    { key: "rps20", label: "RPS20", format: function (v) { return number(v, 0); } },
    { key: "custom_reason", label: "命中摘要", className: function () { return "signal-cell"; }, format: function (v, row) {
      return '<span class="formula-hit-summary">量比 ' + number(row.amount_ratio, 2) + 'x · RPS20 ' +
        number(row.rps20, 0) + ' · 距20日线 ' + number(row.distance_ma20, 1) + '%</span>';
    } },
    { key: "code", label: "", format: detailButton }
  ];

  function customSource() {
    var payload = state.payload || {};
    return state.customStrategies || {
      catalog: payload.custom_strategies || [],
      results: payload.custom_strategy_results || []
    };
  }

  function renderCustomStrategies() {
    var source = customSource();
    var catalog = source.catalog || [];
    var results = source.results || [];
    byId("custom-formula-count").textContent = catalog.length + " 个";
    if (!catalog.length) {
      byId("custom-formula-list").innerHTML = '<div class="empty-state">暂无自定义公式</div>';
      byId("custom-result-title").textContent = "自定义策略结果";
      byId("custom-result-description").textContent = "--";
      byId("custom-formula-summary").textContent = "暂无公式定义";
      byId("custom-match-count").textContent = "0";
      byId("custom-results-table").innerHTML = tableHtml(customColumns, []);
      return;
    }
    if (!catalog.some(function (item) { return item.key === state.activeCustomKey; })) {
      state.activeCustomKey = catalog[0].key;
    }
    byId("custom-formula-list").innerHTML = catalog.map(function (item) {
      var active = item.key === state.activeCustomKey;
      var disabled = !item.enabled;
      var count = Number(item.matched_count || 0);
      return '<article class="formula-item ' + (active ? "active " : "") + (disabled ? "disabled" : "") + '">' +
        '<button type="button" data-custom-formula="' + escapeHtml(item.key) + '"><h3>' + escapeHtml(item.name) +
        '</h3><p>' + escapeHtml(item.description || item.formula_summary || "--") + '</p><small>' +
        (item.status === "error" ? "配置异常" : count + " 只命中") + '</small></button>' +
        '<label class="switch local-only" title="启用或停用"><input type="checkbox" data-custom-enabled="' +
        escapeHtml(item.key) + '" ' + (item.enabled ? "checked" : "") + '><span></span></label></article>';
    }).join("");
    all("[data-custom-formula]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.activeCustomKey = button.dataset.customFormula;
        renderCustomStrategies();
      });
    });
    all("[data-custom-enabled]").forEach(function (input) {
      input.addEventListener("change", function () {
        input.closest(".formula-item").classList.toggle("disabled", !input.checked);
      });
    });

    var activeFormula = catalog.find(function (item) { return item.key === state.activeCustomKey; }) || catalog[0];
    var query = state.customSearch.trim().toLowerCase();
    var rows = results.filter(function (row) {
      if (String(row.custom_strategy_key || "") !== String(activeFormula.key || "")) return false;
      if (!query) return true;
      return [row.code, row.name, row.industry, row.sector, row.market_board, row.concepts, row.custom_reason].some(function (value) {
        return String(value || "").toLowerCase().indexOf(query) >= 0;
      });
    });
    byId("custom-result-title").textContent = activeFormula.name || "自定义策略结果";
    byId("custom-result-description").textContent = activeFormula.description || "--";
    byId("custom-formula-summary").textContent = activeFormula.error || activeFormula.formula_summary || "--";
    byId("custom-match-count").textContent = rows.length;
    byId("custom-results-table").innerHTML = tableHtml(customColumns, rows);
    bindDetailButtons(byId("custom-results-table"));
    icons();
  }

  async function saveCustomStrategies() {
    var enabled = all("[data-custom-enabled]:checked").map(function (input) { return input.dataset.customEnabled; });
    var button = byId("save-custom-strategies-button");
    button.disabled = true;
    try {
      state.customStrategies = await request("/api/custom-strategies", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: enabled })
      });
      renderCustomStrategies();
      toast("自定义公式启用状态已保存，下次任务生效");
    } catch (error) {
      toast("保存失败：" + error.message);
    } finally {
      button.disabled = false;
    }
  }

  function renderStrategies() {
    var grid = byId("strategy-grid");
    if (state.strategies && state.strategies.catalog) {
      var enabled = new Set(state.strategies.enabled || []);
      byId("strategy-profile").value = state.strategies.profile || "custom";
      grid.innerHTML = state.strategies.catalog.map(function (item) {
        var checked = enabled.has(item.key);
        return '<article class="strategy-card ' + (checked ? "" : "disabled") +
          '" data-strategy-card="' + escapeHtml(item.key) + '">' +
          '<span class="family-mark ' + escapeHtml(item.family) + '"></span><div><h3>' +
          escapeHtml(item.name) + '</h3><p>' + escapeHtml(item.description) + " · 基础分 " +
          number(item.score, 0) + '</p></div><label class="switch" title="启用或停用"><input type="checkbox" data-strategy="' +
          escapeHtml(item.key) + '" ' + (checked ? "checked" : "") + "><span></span></label></article>";
      }).join("");
      all("[data-strategy]").forEach(function (input) {
        input.addEventListener("change", function () {
          input.closest(".strategy-card").classList.toggle("disabled", !input.checked);
          byId("strategy-profile").value = "custom";
        });
      });
    } else {
      var distribution = (state.payload && state.payload.strategy_distribution) || [];
      grid.innerHTML = distribution.map(function (item) {
        return '<article class="strategy-card"><span class="family-mark"></span><div><h3>' +
          escapeHtml(item.strategy) + "</h3><p>本期 Top 50 命中 " + item.count +
          " 只</p></div></article>";
      }).join("") || '<div class="empty-state">暂无策略命中记录</div>';
    }
  }

  function renderPool() {
    if (!state.pool) return;
    byId("pool-min-price").value = state.pool.min_price;
    byId("pool-min-days").value = state.pool.min_list_days;
    byId("pool-min-amount").value = state.pool.min_avg_amount_20d;
    byId("pool-exclude-st").checked = Boolean(state.pool.exclude_st);
    byId("pool-exclude-suspended").checked = Boolean(state.pool.exclude_suspended);
    var excluded = new Set(state.pool.exclude_boards || []);
    byId("board-options").innerHTML = (state.pool.available_boards || []).map(function (board) {
      return '<label><input type="checkbox" data-board-option="' + escapeHtml(board) + '" ' +
        (excluded.has(board) ? "checked" : "") + '><span>' + escapeHtml(board) + "</span></label>";
    }).join("");
  }

  async function saveStrategies() {
    var enabled = all("[data-strategy]:checked").map(function (input) { return input.dataset.strategy; });
    if (!enabled.length) {
      toast("至少保留一个启用策略");
      return;
    }
    var button = byId("save-strategies-button");
    button.disabled = true;
    try {
      state.strategies = await request("/api/strategies", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: enabled, profile: byId("strategy-profile").value })
      });
      renderStrategies();
      toast("策略配置已保存，下次任务生效");
    } catch (error) {
      toast("保存失败：" + error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function savePool() {
    var minDays = Number(byId("pool-min-days").value);
    var minPrice = Number(byId("pool-min-price").value);
    var minAmount = Number(byId("pool-min-amount").value);
    if (!Number.isFinite(minDays) || minDays < 1 || !Number.isFinite(minPrice) || minPrice <= 0 ||
        !Number.isFinite(minAmount) || minAmount < 0) {
      toast("请检查股票池数值");
      return;
    }
    var button = byId("save-pool-button");
    button.disabled = true;
    try {
      state.pool = await request("/api/pool-config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          min_list_days: Math.round(minDays),
          min_price: minPrice,
          min_avg_amount_20d: minAmount,
          exclude_st: byId("pool-exclude-st").checked,
          exclude_suspended: byId("pool-exclude-suspended").checked,
          exclude_boards: all("[data-board-option]:checked").map(function (input) {
            return input.dataset.boardOption;
          })
        })
      });
      renderPool();
      toast("股票池配置已保存，下次任务生效");
    } catch (error) {
      toast("保存失败：" + error.message);
    } finally {
      button.disabled = false;
    }
  }

  function renderPerformance(rows) {
    var columns = [
      { key: "strategy", label: "策略" },
      { key: "sample_count", label: "样本" },
      { key: "return_1d", label: "1日收益", className: valueClass, format: pct },
      { key: "win_rate_1d", label: "1日胜率", format: function (v) { return v == null ? "--" : number(v, 1) + "%"; } },
      { key: "return_5d", label: "5日收益", className: valueClass, format: pct },
      { key: "win_rate_5d", label: "5日胜率", format: function (v) { return v == null ? "--" : number(v, 1) + "%"; } },
      { key: "return_10d", label: "10日收益", className: valueClass, format: pct },
      { key: "win_rate_10d", label: "10日胜率", format: function (v) { return v == null ? "--" : number(v, 1) + "%"; } }
    ];
    byId("performance-table").innerHTML = tableHtml(columns, rows);
  }

  function renderSystem() {
    var health = (state.status && state.status.health) || (state.payload && state.payload.health) || {};
    var coverage = Number(health.stock_coverage || 0);
    var good = coverage >= 0.9 && Number(health.index_symbols || 0) >= 3;
    var healthState = byId("health-state");
    healthState.textContent = good ? "正常" : "需检查";
    healthState.className = "health-state " + (good ? "good" : "bad");
    var items = [
      ["最新交易日", health.latest_trade_date || "--"],
      ["股票覆盖", number(coverage * 100, 1) + "%"],
      ["覆盖股票", health.covered_symbols || 0],
      ["日线记录", Number(health.daily_rows || 0).toLocaleString("zh-CN")],
      ["最新日股票", health.latest_symbol_count || 0],
      ["指数数量", health.index_symbols || 0]
    ];
    byId("health-list").innerHTML = items.map(function (item) {
      return "<div><dt>" + item[0] + "</dt><dd>" + escapeHtml(item[1]) + "</dd></div>";
    }).join("");
    if (state.status) {
      renderRunner(state.status.runner || {});
      renderRuns(state.status.runs || []);
      var reports = state.status.reports || [];
      var button = byId("download-report-button");
      button.disabled = !reports.length;
      button.dataset.href = reports.length ? reports[0].download_url : "";
    }
    renderScheduler();
    byId("mode-note").textContent = state.mode === "static"
      ? "公开页面只展示筛选结果，不包含本地数据库、日志和任务执行权限。"
      : "服务仅监听本机地址；远程部署时请配置访问控制和 HTTPS。";
  }

  function displayDateTime(value) {
    if (!value) return "--";
    return String(value).replace("T", " ").slice(0, 16);
  }

  function schedulerResultLabel(value) {
    if (value == null) return "--";
    var code = Number(value);
    var labels = {
      0: "成功",
      267008: "等待运行",
      267009: "运行中",
      267010: "已停用",
      267011: "尚未运行"
    };
    return labels[code] || ("代码 " + value);
  }

  function renderScheduler() {
    var scheduler = state.scheduler || {};
    var loaded = Boolean(state.scheduler);
    var supported = loaded && scheduler.supported !== false;
    var enabled = Boolean(scheduler.enabled);
    var dirty = supported && state.schedulerDirty;
    var draftTime = dirty ? (byId("scheduler-time").value || scheduler.time || "17:30") : (scheduler.time || "17:30");
    var statusNode = byId("scheduler-state");
    statusNode.textContent = !loaded ? "读取中" : (!supported ? "不支持" : (dirty ? "待保存" : (enabled ? "已启用" : "未启用")));
    statusNode.className = "scheduler-state" + (dirty ? " pending" : (enabled ? " active" : ""));
    if (!dirty) {
      byId("scheduler-time").value = scheduler.time || "17:30";
      byId("scheduler-publish").checked = Boolean(scheduler.publish);
    }
    byId("scheduler-time").disabled = !supported;
    byId("scheduler-publish").disabled = !supported;
    byId("save-scheduler-button").disabled = !supported;
    byId("disable-scheduler-button").disabled = !supported || !enabled;
    byId("scheduler-summary-title").textContent = dirty
      ? "保存后工作日 " + draftTime + " 自动复盘"
      : enabled
        ? "工作日 " + draftTime + " 自动复盘"
      : "工作日盘后自动复盘";
    byId("scheduler-summary-text").textContent = !supported
      ? (scheduler.message || "当前系统不支持本地计划任务管理")
      : (dirty
        ? "修改尚未保存；当前计划仍为工作日 " + (scheduler.time || "17:30") + "。"
        : enabled
        ? "计划任务已生效" + (scheduler.publish ? "，完成后会推送网页报告。" : "，报告只保存在本机。")
        : "设置时间后启用，电脑关机期间不会运行，恢复可用后会补跑一次。");
    byId("scheduler-next-run").textContent = displayDateTime(scheduler.next_run_time);
    byId("scheduler-last-run").textContent = displayDateTime(scheduler.last_run_time);
    byId("scheduler-last-result").textContent = schedulerResultLabel(scheduler.last_result);
  }

  function markSchedulerDirty() {
    if (!state.scheduler || state.scheduler.supported === false) return;
    state.schedulerDirty = true;
    renderScheduler();
  }

  async function saveScheduler(enabled) {
    var body = {
      enabled: enabled,
      time: byId("scheduler-time").value || "17:30",
      publish: byId("scheduler-publish").checked
    };
    byId("save-scheduler-button").disabled = true;
    byId("disable-scheduler-button").disabled = true;
    try {
      state.scheduler = await request("/api/scheduler", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      state.schedulerDirty = false;
      renderScheduler();
      icons();
      toast(enabled ? "定时执行已启用" : "定时执行已停用");
    } catch (error) {
      toast((enabled ? "保存失败：" : "停用失败：") + error.message);
      renderScheduler();
    }
  }

  function renderRunner(runner) {
    var running = Boolean(runner.running);
    byId("run-state").textContent = !state.ready ? "准备中" : (running ? "运行中" : (runner.last_status || "空闲"));
    byId("run-state").className = "run-state" + (running ? " active" : "");
    byId("run-output").textContent = runner.output || (!state.ready ? "正在连接本地服务..." : (running ? "任务正在执行" : "等待任务"));
    byId("run-button").disabled = running || !state.ready;
    byId("quick-run-button").disabled = running || !state.ready;
  }

  function renderRuns(rows) {
    var displayRows = (rows || []).slice();
    var active = state.status && state.status.runner;
    var hasRunningRow = displayRows.some(function (row) { return row.status === "running"; });
    if (active && active.running && !hasRunningRow) {
      displayRows.unshift({
        started_at: active.started_at,
        mode: active.mode,
        report_date: active.report_date,
        status: "running",
        message: "任务已启动，正在更新数据"
      });
    }
    var columns = [
      { key: "started_at", label: "开始时间", format: function (v) { return escapeHtml(String(v || "").replace("T", " ")); } },
      { key: "mode", label: "模式", format: function (v) { return v === "init" ? "初始化" : "每日增量"; } },
      { key: "report_date", label: "报告日期" },
      { key: "status", label: "状态", format: function (v) {
        return ({ running: "运行中", success: "成功", failed: "失败" })[v] || escapeHtml(v);
      } },
      { key: "message", label: "说明", className: function () { return "signal-cell"; } }
    ];
    byId("runs-table").innerHTML = tableHtml(columns, displayRows);
  }
  function switchView(name) {
    all(".view").forEach(function (view) {
      view.classList.toggle("active", view.id === "view-" + name);
    });
    all("[data-view]").forEach(function (button) {
      button.classList.toggle("active", button.dataset.view === name);
    });
    byId("view-context").textContent = viewMeta[name][0];
    byId("view-title").textContent = viewMeta[name][1];
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function startRun(mode) {
    if (!state.ready) {
      toast("本地服务仍在准备，请稍候");
      return;
    }
    var body = { mode: mode || byId("run-mode").value };
    var runDate = byId("run-date").value;
    if (runDate) body.date = runDate;
    byId("run-button").disabled = true;
    byId("quick-run-button").disabled = true;
    try {
      var started = await request("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      state.status = state.status || { runs: [], reports: [] };
      state.status.runner = started;
      renderRunner(started);
      renderRuns(state.status.runs || []);
      switchView("system");
      toast("任务已启动");
    } catch (error) {
      toast("启动失败：" + error.message);
      renderRunner((state.status && state.status.runner) || {});
    }
  }

  async function refreshRunner() {
    if (state.mode !== "local") return;
    var wasRunning = Boolean(state.status && state.status.runner && state.status.runner.running);
    try {
      var current = await request("/api/run");
      state.status = state.status || { runs: [], reports: [] };
      state.status.runner = current;
      renderRunner(current);
      renderRuns(state.status.runs || []);
      icons();
      if (wasRunning && !current.running) {
        await load();
      }
    } catch (error) {
      setConnection("error", "本地服务连接中断");
    }
  }

  function bind() {
    all("[data-view]").forEach(function (button) {
      button.addEventListener("click", function () { switchView(button.dataset.view); });
    });
    all("[data-goto]").forEach(function (button) {
      button.addEventListener("click", function () { switchView(button.dataset.goto); });
    });
    all("[data-list]").forEach(function (button) {
      button.addEventListener("click", function () {
        state.listName = button.dataset.list;
        all("[data-list]").forEach(function (item) { item.classList.toggle("active", item === button); });
        renderWatchlist();
      });
    });
    byId("stock-search").addEventListener("input", function (event) {
      state.search = event.target.value;
      renderWatchlist();
    });
    byId("board-filter").addEventListener("change", function (event) {
      state.board = event.target.value;
      renderWatchlist();
    });
    byId("focus-search").addEventListener("input", function (event) {
      state.focusSearch = event.target.value;
      renderFocus((state.payload && state.payload.top10) || []);
    });
    byId("focus-board-filter").addEventListener("change", function (event) {
      state.focusBoard = event.target.value;
      renderFocus((state.payload && state.payload.top10) || []);
    });
    byId("custom-search").addEventListener("input", function (event) {
      state.customSearch = event.target.value;
      renderCustomStrategies();
    });
    byId("refresh-button").addEventListener("click", function () {
      state.schedulerDirty = false;
      load();
    });
    byId("save-strategies-button").addEventListener("click", saveStrategies);
    byId("save-custom-strategies-button").addEventListener("click", saveCustomStrategies);
    byId("save-pool-button").addEventListener("click", savePool);
    byId("run-button").addEventListener("click", function () { startRun(); });
    byId("quick-run-button").addEventListener("click", function () { startRun("daily"); });
    byId("save-scheduler-button").addEventListener("click", function () { saveScheduler(true); });
    byId("disable-scheduler-button").addEventListener("click", function () { saveScheduler(false); });
    byId("scheduler-time").addEventListener("input", markSchedulerDirty);
    byId("scheduler-publish").addEventListener("change", markSchedulerDirty);
    byId("download-report-button").addEventListener("click", function (event) {
      var href = event.currentTarget.dataset.href;
      if (href) window.location.href = href;
    });
    byId("strategy-profile").addEventListener("change", function (event) {
      if (!state.strategies || event.target.value === "custom") return;
      var keys = new Set((state.strategies.profiles || {})[event.target.value] || []);
      all("[data-strategy]").forEach(function (input) {
        input.checked = keys.has(input.dataset.strategy);
        input.closest(".strategy-card").classList.toggle("disabled", !input.checked);
      });
    });
    byId("drawer-close").addEventListener("click", closeDrawer);
    byId("drawer-backdrop").addEventListener("click", closeDrawer);
    byId("focus-stock-detail").addEventListener("click", function (event) {
      var code = event.currentTarget.dataset.code;
      if (code) openDrawer(code);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeDrawer();
    });
  }

  bind();
  icons();
  load();
  window.setInterval(function () {
    if (state.mode === "local" && state.status && state.status.runner && state.status.runner.running) {
      refreshRunner();
    }
  }, 3500);
}());
