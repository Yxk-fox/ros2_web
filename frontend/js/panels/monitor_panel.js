/* T-6.0-02 懒加载模块：系统监控（实时监控/趋势视图/运行报告/告警中心） — 从 sj_script.js 拆出，defer 加载，全局函数不变 */

// 16. 系统监控
// ============================================================

/**
 * 处理 loadMonitor 相关前端逻辑。
 */
function loadMonitor() {
    apiGet('/api/system/monitor').then(function(d) {
        if (!d.success) { showToast('监控加载失败: ' + (d.error || '未知错误'), 'error'); return; }
        var grid = document.getElementById('monitorGrid');
        var cpuClass = d.cpu.total > 80 ? 'fill-error' : (d.cpu.total > 50 ? 'fill-warning' : 'fill-success');
        var memClass = d.memory.percent > 80 ? 'fill-error' : (d.memory.percent > 50 ? 'fill-warning' : 'fill-success');
        grid.innerHTML =
            '<div class="monitor-item"><div class="label">CPU 使用率</div><div class="value">' + d.cpu.total.toFixed(1) + '%</div><div class="progress-bar"><div class="fill ' + cpuClass + '" style="width:' + d.cpu.total + '%"></div></div></div>' +
            '<div class="monitor-item"><div class="label">内存</div><div class="value">' + d.memory.percent.toFixed(1) + '%</div><div class="progress-bar"><div class="fill ' + memClass + '" style="width:' + d.memory.percent + '%"></div></div><div style="font-size:12px;margin-top:4px">' + d.memory.used_mb + 'MB / ' + d.memory.total_mb + 'MB</div></div>' +
            '<div class="monitor-item"><div class="label">Swap</div><div class="value">' + d.swap.percent.toFixed(1) + '%</div><div style="font-size:12px">' + d.swap.used_mb + 'MB / ' + d.swap.total_mb + 'MB</div></div>' +
            '<div class="monitor-item"><div class="label">平均负载</div><div class="value">' + d.cpu.load_avg.map(function(v) { return v.toFixed(2); }).join(' / ') + '</div><div style="font-size:12px">核心数: ' + d.cpu.cores + '</div></div>';
        var gpuDiv = document.getElementById('gpuInfo');
        if (d.gpu && d.gpu.length) {
            var gpuHtml = '';
            for (var i = 0; i < d.gpu.length; i++) {
                var g = d.gpu[i];
                gpuHtml += '<div style="margin-bottom:8px;padding:8px;background:var(--accent-light);border-radius:var(--radius)"><strong>GPU ' + g.index + ': ' + escapeHtml(g.name) + '</strong><br>利用率: ' + g.utilization + '% | 显存: ' + g.mem_used + 'MiB / ' + g.mem_total + 'MiB | 温度: ' + g.temperature + '°C | 功耗: ' + g.power + 'W</div>';
            }
            gpuDiv.innerHTML = gpuHtml;
        } else {
            gpuDiv.innerHTML = '<p style="opacity:0.5">无 GPU 或 nvidia-smi 不可用</p>';
        }
        var pbody = document.getElementById('processesTableBody');
        var pHtml = '';
        for (var j = 0; j < d.processes.length; j++) {
            var p = d.processes[j];
            pHtml += '<tr><td>' + p.pid + '</td><td>' + escapeHtml(p.user) + '</td><td>' + p.cpu + '</td><td>' + p.mem + '</td><td style="font-size:11px">' + escapeHtml(p.command) + '</td></tr>';
        }
        pbody.innerHTML = pHtml;
    });
}

/**
 * 处理 toggleAutoRefresh 相关前端逻辑。
 */
function toggleAutoRefresh() {
    monitorAutoRefresh = !monitorAutoRefresh;
    var btn = document.getElementById('autoRefreshBtn');
    if (monitorAutoRefresh) {
        btn.textContent = '⏸ 停止刷新';
        loadMonitor();
        monitorTimer = setInterval(loadMonitor, 3000);
    } else {
        btn.textContent = '⏯ 自动刷新';
        if (monitorTimer) { clearInterval(monitorTimer); monitorTimer = null; }
    }
}

// ========== 趋势视图（T-5.2-03，v5.2）==========
// 资源监控历史曲线：轻量 SVG 折线，无第三方图表库依赖
// 数据源：GET /api/system/metrics/history（后端 SQLite 30s 采样，降采样聚合）
// ===========================================

/** 趋势指标定义：key 对应后端 METRIC_COLUMNS，pct=true 时 y 轴固定 0-100 */
var TREND_METRICS = {
    cpu:            { label: 'CPU 使用率',      unit: '%',   pct: true },
    mem:            { label: '内存使用率',      unit: '%',   pct: true },
    mem_used:       { label: '内存用量',        unit: 'MB',  pct: false },
    swap:           { label: 'Swap 使用率',     unit: '%',   pct: true },
    load:           { label: '系统负载 (1m)',   unit: '',    pct: false },
    gpu_util:       { label: 'GPU 利用率',      unit: '%',   pct: true },
    gpu_mem:        { label: 'GPU 显存',        unit: 'MB',  pct: false },
    gpu_temp:       { label: 'GPU 温度',        unit: '°C',  pct: false },
    container_cpu:  { label: '容器 CPU',        unit: '%',   pct: true },
    container_mem:  { label: '容器内存',        unit: 'MB',  pct: false },
    container_count:{ label: '容器数量',        unit: '个',  pct: false }
};

/** 趋势视图当前状态 */
var trendState = { metric: 'cpu', range: '1h', lastPoints: [], trendInited: false };

/**
 * 初始化趋势视图下拉与默认按钮态（幂等，进入监控面板时调用）。
 */
function initTrendView() {
    if (trendState.trendInited) return;
    var sel = document.getElementById('trendMetric');
    if (!sel) return;
    var opts = '';
    for (var k in TREND_METRICS) {
        opts += '<option value="' + k + '"' + (k === trendState.metric ? ' selected' : '') + '>' + TREND_METRICS[k].label + '</option>';
    }
    sel.innerHTML = opts;
    updateTrendRangeBtns();
    trendState.trendInited = true;
}

/**
 * 更新范围按钮组的选中态。
 */
function updateTrendRangeBtns() {
    var btns = document.querySelectorAll('#trendRangeBtns button');
    for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        b.className = (b.getAttribute('data-range') === trendState.range) ? 'btn btn-sm' : 'btn btn-sm btn-outline';
    }
}

/**
 * 切换趋势指标并重新加载。
 */
function setTrendMetric(m) {
    if (!TREND_METRICS[m]) return;
    trendState.metric = m;
    loadTrend();
}

/**
 * 切换时间范围并重新加载。
 */
function setTrendRange(r) {
    trendState.range = r;
    updateTrendRangeBtns();
    loadTrend();
}

/**
 * 拉取历史曲线数据并渲染。
 */
function loadTrend() {
    var chart = document.getElementById('trendChart');
    if (!chart) return;
    chart.innerHTML = '<div style="padding:40px;text-align:center;opacity:0.5;font-size:13px">加载中...</div>';
    apiGet('/api/system/metrics/history?metric=' + trendState.metric + '&range=' + trendState.range).then(function(d) {
        if (!d.success) {
            chart.innerHTML = '<div style="padding:40px;text-align:center;color:var(--danger,#e74c3c);font-size:13px">加载失败: ' + escapeHtml(d.error || '未知错误') + '</div>';
            return;
        }
        trendState.lastPoints = d.points || [];
        renderTrendChart(trendState.lastPoints, d.metric, d.range);
    }).catch(function() {
        chart.innerHTML = '<div style="padding:40px;text-align:center;color:var(--danger,#e74c3c);font-size:13px">网络错误，请稍后重试</div>';
    });
}

/**
 * 渲染 SVG 折线图（自适应容器宽度，resize 防抖重绘）。
 * @param {Array<{ts:number,value:number}>} points 降采样后的数据点
 */
function renderTrendChart(points, metric, rangeStr) {
    var wrap = document.getElementById('trendChart');
    var summary = document.getElementById('trendSummary');
    if (!wrap) return;
    var def = TREND_METRICS[metric] || { label: metric, unit: '', pct: false };

    if (!points || points.length < 2) {
        wrap.innerHTML = '<div style="padding:40px;text-align:center;opacity:0.5;font-size:13px">暂无足够数据（采样守护启动后每 30s 记录一个点，稍后再试）</div>';
        if (summary) summary.textContent = '';
        return;
    }

    // 画布与边距
    var W = Math.max(wrap.clientWidth || 640, 320), H = 200;
    var padL = 46, padR = 14, padT = 14, padB = 26;

    // y 轴量程：百分比类固定 0-100，其余自适应（上下留 15% 余量）
    var vals = [];
    for (var i = 0; i < points.length; i++) if (points[i].value != null) vals.push(points[i].value);
    var vMax = Math.max.apply(null, vals), vMin = Math.min.apply(null, vals);
    var yMin = 0, yMax = 100;
    if (!def.pct) {
        if (vMax === vMin) { yMin = Math.max(0, vMax - 1); yMax = vMax + 1; }
        else {
            var pad = (vMax - vMin) * 0.15;
            yMin = vMin > 0 ? Math.max(0, vMin - pad) : vMin;
            yMax = vMax + pad;
        }
    }

    // x 轴时间域
    var t0 = points[0].ts, t1 = points[points.length - 1].ts;
    if (t1 === t0) t1 = t0 + 1;
    function px(ts) { return padL + (ts - t0) / (t1 - t0) * (W - padL - padR); }
    function py(v) { return padT + (1 - (v - yMin) / (yMax - yMin)) * (H - padT - padB); }

    var parts = [];

    // 横向网格线 + y 轴刻度（5 条）
    for (var g = 0; g <= 4; g++) {
        var gy = padT + g / 4 * (H - padT - padB);
        var gv = yMax - g / 4 * (yMax - yMin);
        parts.push('<line x1="' + padL + '" y1="' + gy.toFixed(1) + '" x2="' + (W - padR) + '" y2="' + gy.toFixed(1) + '" stroke="rgba(128,128,128,0.15)" stroke-width="1"/>');
        parts.push('<text x="' + (padL - 6) + '" y="' + (gy + 4).toFixed(1) + '" text-anchor="end" font-size="10" fill="rgba(128,128,128,0.8)">' + formatTrendNum(gv) + '</text>');
    }

    // x 轴时间标签（4 个）
    var longFmt = (rangeStr === '24h' || rangeStr === '7d');
    for (var k = 0; k <= 3; k++) {
        var tx = padL + k / 3 * (W - padL - padR);
        var ts = t0 + k / 3 * (t1 - t0);
        var dt = new Date(ts * 1000);
        var label = longFmt
            ? ((dt.getMonth() + 1) + '/' + dt.getDate() + ' ' + String(dt.getHours()).padStart(2, '0') + ':00')
            : (String(dt.getHours()).padStart(2, '0') + ':' + String(dt.getMinutes()).padStart(2, '0'));
        parts.push('<text x="' + tx.toFixed(1) + '" y="' + (H - 8) + '" text-anchor="' + (k === 0 ? 'start' : (k === 3 ? 'end' : 'middle')) + '" font-size="10" fill="rgba(128,128,128,0.8)">' + label + '</text>');
    }

    // 折线 + 渐变面积
    var lineD = '', firstX = 0, lastX = 0;
    var circles = '';
    for (var j = 0; j < points.length; j++) {
        var v = points[j].value;
        if (v == null) continue;
        var cx = px(points[j].ts), cy = py(v);
        if (lineD === '') { lineD = 'M' + cx.toFixed(1) + ' ' + cy.toFixed(1); firstX = cx; }
        else lineD += ' L' + cx.toFixed(1) + ' ' + cy.toFixed(1);
        lastX = cx;
        // hover 数据点（<title> 原生提示）
        var dt2 = new Date(points[j].ts * 1000);
        circles += '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="2.5" fill="var(--accent)" class="trend-dot"><title>' +
            String(dt2.getHours()).padStart(2, '0') + ':' + String(dt2.getMinutes()).padStart(2, '0') + '  ' + formatTrendNum(v) + def.unit + '</title></circle>';
    }
    var areaD = lineD + ' L' + lastX.toFixed(1) + ' ' + (H - padB) + ' L' + firstX.toFixed(1) + ' ' + (H - padB) + ' Z';

    parts.push('<defs><linearGradient id="trendGrad" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0%" stop-color="var(--accent)" stop-opacity="0.25"/>' +
        '<stop offset="100%" stop-color="var(--accent)" stop-opacity="0.02"/>' +
        '</linearGradient></defs>');
    parts.push('<path d="' + areaD + '" fill="url(#trendGrad)"/>');
    parts.push('<path d="' + lineD + '" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>');
    parts.push(circles);

    wrap.innerHTML = '<svg width="' + W + '" height="' + H + '" style="display:block">' + parts.join('') + '</svg>';

    // 摘要：当前 / 均值 / 峰值
    var avg = vals.reduce(function(a, b) { return a + b; }, 0) / vals.length;
    if (summary) {
        summary.textContent = '当前 ' + formatTrendNum(vals[vals.length - 1]) + def.unit +
            ' · 均值 ' + formatTrendNum(avg) + def.unit +
            ' · 峰值 ' + formatTrendNum(vMax) + def.unit +
            ' · ' + points.length + ' 个数据点' +
            (def.pct ? '' : '（' + def.label + '）');
    }
}

/**
 * 趋势数值格式化（整数不带小数，小数保留 1 位）。
 */
function formatTrendNum(v) {
    return (Math.abs(v) >= 100 || Number.isInteger(v)) ? Math.round(v) : Math.round(v * 10) / 10;
}

/** resize 防抖重绘趋势图 */
var trendResizeTimer = null;
window.addEventListener('resize', function() {
    if (trendResizeTimer) clearTimeout(trendResizeTimer);
    trendResizeTimer = setTimeout(function() {
        if (trendState.lastPoints.length >= 2) {
            renderTrendChart(trendState.lastPoints, trendState.metric, trendState.range);
        }
    }, 250);
});
// ===========================================

// ========== 运行报告（T-5.2-04，v5.2）==========
// 脚本运行记录聚合视图：汇总统计 + 分组表格 + CSV 导出
// 数据源：GET /api/scripts/run-report（后端 SQLite run_records 表）
// ===========================================

/** 运行报告当前状态 */
var reportState = { range: '7d', lastData: null };

/**
 * 初始化范围按钮选中态（进入脚本面板时调用）。
 */
function initReportRangeBtns() {
    updateReportRangeBtns();
}

function updateReportRangeBtns() {
    var btns = document.querySelectorAll('#reportRangeBtns button');
    for (var i = 0; i < btns.length; i++) {
        var b = btns[i];
        b.className = (b.getAttribute('data-range') === reportState.range) ? 'btn btn-sm' : 'btn btn-sm btn-outline';
    }
}

function setReportRange(r) {
    reportState.range = r;
    updateReportRangeBtns();
    loadRunReport();
}

/**
 * 拉取运行报告数据并渲染。
 */
function loadRunReport() {
    var summary = document.getElementById('reportSummary');
    if (!summary) return;
    summary.innerHTML = '<span style="opacity:0.5;font-size:13px">加载中...</span>';
    apiGet('/api/scripts/run-report?range=' + reportState.range).then(function(d) {
        if (!d.success) {
            summary.innerHTML = '<span style="color:var(--danger,#e74c3c);font-size:13px">加载失败: ' + escapeHtml(d.error || '') + '</span>';
            return;
        }
        reportState.lastData = d;
        renderReportSummary(d.summary);
        renderReportTables(d);
        renderReportRecent(d.recent);
    }).catch(function() {
        summary.innerHTML = '<span style="color:var(--danger,#e74c3c);font-size:13px">网络错误</span>';
    });
}

/**
 * 渲染汇总卡片。
 */
function renderReportSummary(s) {
    var el = document.getElementById('reportSummary');
    if (!el || !s) return;
    var cards = [
        { label: '总操作', value: s.total, color: 'var(--accent)' },
        { label: '成功', value: s.success, color: '#22c55e' },
        { label: '失败', value: s.fail, color: '#ef4444' },
        { label: '成功率', value: s.success_rate + '%', color: s.success_rate >= 80 ? '#22c55e' : (s.success_rate >= 50 ? '#f59e0b' : '#ef4444') },
        { label: '涉及容器', value: s.container_count, color: 'var(--accent)' },
        { label: '操作用户', value: s.user_count, color: 'var(--accent)' },
    ];
    el.innerHTML = cards.map(function(c) {
        return '<div style="display:flex;flex-direction:column;align-items:center;padding:8px 16px;background:var(--bg-input);border-radius:var(--radius);min-width:80px">' +
            '<span style="font-size:20px;font-weight:700;color:' + c.color + '">' + c.value + '</span>' +
            '<span style="font-size:11px;color:var(--text-secondary);margin-top:2px">' + c.label + '</span></div>';
    }).join('');
}

/**
 * 渲染分组表格（按脚本 / 按用户 / 按版本）。
 */
function renderReportTables(d) {
    var el = document.getElementById('reportTables');
    if (!el) return;
    function makeTable(title, rows, keyField) {
        var html = '<div style="overflow-x:auto"><table class="data-table" style="font-size:12px"><thead><tr><th>' + title + '</th><th>次数</th><th>成功</th><th>失败</th></tr></thead><tbody>';
        if (!rows.length) {
            html += '<tr><td colspan="4" style="text-align:center;opacity:0.5">无数据</td></tr>';
        } else {
            for (var i = 0; i < rows.length; i++) {
                var r = rows[i];
                html += '<tr><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + escapeHtml(r[keyField] || '') + '">' + escapeHtml(r[keyField] || '') + '</td>' +
                    '<td>' + r.count + '</td><td style="color:#22c55e">' + r.success + '</td><td style="color:#ef4444">' + r.fail + '</td></tr>';
            }
        }
        html += '</tbody></table></div>';
        return html;
    }
    el.innerHTML =
        makeTable('脚本', d.by_script, 'script_name') +
        makeTable('用户', d.by_user, 'username');
    el.innerHTML += '<div style="grid-column:1/-1">' + makeTable('版本', d.by_version, 'version') + '</div>';
}

/**
 * 渲染最近操作明细。
 */
function renderReportRecent(recent) {
    var el = document.getElementById('reportRecent');
    if (!el) return;
    if (!recent || !recent.length) {
        el.innerHTML = '<p style="opacity:0.5;font-size:13px;text-align:center;padding:20px">暂无操作记录</p>';
        return;
    }
    var html = '<div style="font-size:13px;font-weight:600;margin-bottom:6px">最近操作</div><div style="overflow-x:auto"><table class="data-table" style="font-size:12px"><thead><tr><th>时间</th><th>操作</th><th>用户</th><th>脚本/容器</th><th>结果</th></tr></thead><tbody>';
    for (var i = 0; i < recent.length; i++) {
        var r = recent[i];
        var dt = new Date(r.ts * 1000);
        var timeStr = String(dt.getMonth() + 1).padStart(2, '0') + '/' + String(dt.getDate()).padStart(2, '0') + ' ' +
            String(dt.getHours()).padStart(2, '0') + ':' + String(dt.getMinutes()).padStart(2, '0');
        var name = r.script_name || r.container_name || '-';
        var actionLabel = r.action === 'start' ? '🟢 启动' : '🔴 停止';
        var resultLabel = r.success ? '<span style="color:#22c55e">成功</span>' : '<span style="color:#ef4444" title="' + escapeHtml(r.error || '') + '">失败</span>';
        html += '<tr><td>' + timeStr + '</td><td>' + actionLabel + '</td><td>' + escapeHtml(r.username) + '</td>' +
            '<td style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="' + escapeHtml(name) + '">' + escapeHtml(name) + '</td>' +
            '<td>' + resultLabel + '</td></tr>';
    }
    html += '</tbody></table></div>';
    el.innerHTML = html;
}

/**
 * 导出运行报告为 CSV。
 */
function exportRunReportCSV() {
    if (!reportState.lastData) {
        showToast('请先加载数据', 'warning');
        return;
    }
    var d = reportState.lastData;
    var lines = [];
    lines.push('# 运行报告 (' + d.range + ')');
    lines.push('# 汇总: 总' + d.summary.total + ' / 成功' + d.summary.success + ' / 失败' + d.summary.fail + ' / 成功率' + d.summary.success_rate + '%');
    lines.push('');
    lines.push('时间,操作,用户,脚本名,容器名,版本,结果,错误');
    for (var i = 0; i < d.recent.length; i++) {
        var r = d.recent[i];
        var dt = new Date(r.ts * 1000);
        var timeStr = dt.toLocaleString('zh-CN');
        lines.push([
            timeStr, r.action, r.username, r.script_name || '',
            r.container_name || '', r.version || '',
            r.success ? '成功' : '失败', (r.error || '').replace(/,/g, '，')
        ].map(function(v) { return '"' + String(v).replace(/"/g, '""') + '"'; }).join(','));
    }
    // BOM + UTF-8 确保 Excel 正确识别中文
    var blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'run_report_' + d.range + '_' + new Date().toISOString().slice(0, 10) + '.csv';
    a.click();
    URL.revokeObjectURL(url);
    showToast('CSV 已导出', 'success');
}
// ===========================================

// ========== 告警中心（T-5.2-05，v5.2）==========
// 接收 WebSocket alert 消息 → Toast 通知 + 告警中心列表
// ===========================================

/** 告警中心状态：最多保留 50 条 */
var alertCenterState = { items: [], MAX: 50, unseen: 0 };

/**
 * 处理 WebSocket 推送的告警消息。
 * @param {Object} msg  { type:'alert', alerts:[...], timestamp }
 */
function handleAlertMessage(msg) {
    var alerts = msg.alerts || [];
    if (!alerts.length) return;
    for (var i = 0; i < alerts.length; i++) {
        var a = alerts[i];
        alertCenterState.items.unshift(a);
        // Toast：critical 用 error，warning 用 warning
        var toastType = a.level === 'critical' ? 'error' : 'warning';
        showToast(a.message, toastType);
    }
    // 截断保留上限
    if (alertCenterState.items.length > alertCenterState.MAX) {
        alertCenterState.items = alertCenterState.items.slice(0, alertCenterState.MAX);
    }
    // 若告警中心已展开，不累计未读（用户正在查看）
    var content = document.getElementById('monitor-alerts-content');
    var isExpanded = content && content.classList.contains('expanded');
    if (!isExpanded) {
        alertCenterState.unseen += alerts.length;
    }
    renderAlertCenter();
}

/**
 * 渲染告警中心列表 + 未读徽章。
 */
function renderAlertCenter() {
    var list = document.getElementById('alertCenterList');
    var badge = document.getElementById('alertBadge');
    if (!list) return;

    if (!alertCenterState.items.length) {
        list.innerHTML = '<p style="opacity:0.5;font-size:13px;text-align:center;padding:20px">暂无告警</p>';
    } else {
        var html = '';
        for (var i = 0; i < alertCenterState.items.length; i++) {
            var a = alertCenterState.items[i];
            var dt = new Date((a.timestamp || 0) * 1000);
            var timeStr = String(dt.getHours()).padStart(2, '0') + ':' + String(dt.getMinutes()).padStart(2, '0') + ':' + String(dt.getSeconds()).padStart(2, '0');
            var bg = a.level === 'critical' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)';
            var border = a.level === 'critical' ? '#ef4444' : '#f59e0b';
            html += '<div style="background:' + bg + ';border-left:3px solid ' + border + ';padding:8px 10px;border-radius:4px;margin-bottom:6px;font-size:12px">' +
                '<div style="display:flex;justify-content:space-between;align-items:center">' +
                '<span style="font-weight:600;color:' + border + '">[' + a.level.toUpperCase() + '] ' + escapeHtml(a.label || a.metric) + '</span>' +
                '<span style="color:var(--text-secondary);font-size:11px">' + timeStr + '</span>' +
                '</div>' +
                '<div style="margin-top:3px;color:var(--text-primary)">' + escapeHtml(a.message) + '</div>' +
                '</div>';
        }
        list.innerHTML = html;
    }

    // 未读徽章
    if (badge) {
        if (alertCenterState.unseen > 0) {
            badge.style.display = 'inline-block';
            badge.textContent = alertCenterState.unseen > 99 ? '99+' : alertCenterState.unseen;
        } else {
            badge.style.display = 'none';
        }
    }
}

/**
 * 清空告警中心。
 */
function clearAlertCenter() {
    alertCenterState.items = [];
    alertCenterState.unseen = 0;
    renderAlertCenter();
    showToast('告警中心已清空', 'info');
}

/**
 * 展开告警中心时清除未读计数。
 */
function markAlertsSeen() {
    alertCenterState.unseen = 0;
    var badge = document.getElementById('alertBadge');
    if (badge) badge.style.display = 'none';
}
// ===========================================


/**
 * 切换 apt 软件源。
 */
function changeSource(source) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    customConfirm('确定切换至 ' + source + ' 源？', function() {
    });
    showToast('正在切换...', 'info');
    apiPost('/api/system/apt-source', { source: source }).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
    });
}

/**
 * 安装软件包。
 */
function installPkg(pkg) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    if (!pkg) { showToast('请输入软件包名', 'warning'); return; }
    customConfirm('确定安装 ' + pkg + '？', function() {
    });
    showToast('正在安装...', 'info');
    apiPost('/api/system/install', { package: pkg }).then(function(d) {
        showToast(d.success ? '安装成功' : '失败: ' + (d.error || ''), d.success ? 'success' : 'error');
    });
}

/**
 * 卸载软件包。
 */
function uninstallPkg(pkg) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    if (!pkg) { showToast('请输入软件包名', 'warning'); return; }
    customConfirm('确定卸载 ' + pkg + '？', function() {
    });
    showToast('正在卸载...', 'info');
    apiPost('/api/system/uninstall', { package: pkg }).then(function(d) {
        showToast(d.success ? '卸载成功' : '失败: ' + (d.error || ''), d.success ? 'success' : 'error');
    });
}

/**
 * 同步文件夹。
 */
function syncFolder(type) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    customConfirm('确定同步 ' + type + (currentTargetUser ? '（目标用户: ' + currentTargetUser + '）' : '') + '？', function() {
        showToast('正在同步...', 'info');
        apiPost('/api/system/sync', { type: type, target_user: currentTargetUser || null }).then(function(d) {
            showToast(d.message || d.error, d.success ? 'success' : 'error');
        });
    });
}

/**
 * 清理目录。
 */
function cleanDir(type) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    var tip = '确定清空 ' + type + ' 目录？此操作不可撤销！';
    if (currentTargetUser) tip += '\n\n目标用户: ' + currentTargetUser;
    customConfirm(tip, function() {
        showToast('正在清理...', 'info');
        var body = { type: type };
        if (currentTargetUser) body.target_user = currentTargetUser;
        apiPost('/api/system/clean', body).then(function(d) {
            var msg = d && d.success ? (d.message || '已清理') : _errMsg(d, '清理失败');
            showToast(msg, d && d.success ? 'success' : 'error');
            if (d && d.success) checkInstallStatus(true);
        });
    });
}

/**
 * 处理 saveFtpServer 相关前端逻辑。
 */
function saveFtpServer() {
    var ip = document.getElementById('ftpServerInput').value.trim();
    localStorage.setItem('ftpServer', ip);
    alert('已保存 FTP 服务器 IP：' + ip);
}

/**
 * 处理 getFtpServer 相关前端逻辑。
 */
function getFtpServer() {
    return localStorage.getItem('ftpServer') || '192.168.9.150';
}

/**
 * 处理 openFolder 相关前端逻辑。
 * v3.6：改为打开 Web 文件管理器（不再依赖 FTP/Nautilus）。
 */
function openFolder(type) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    openFileManager(type, '');
}

// ============================================================
// v3.6 Web 文件管理器（在浏览器内浏览/下载/上传/删除/新建目录）
// ============================================================
var _fmState = { folderType: '', subpath: '', targetUser: null };

function openFileManager(folderType, subpath) {
    var modal = document.getElementById('fileManagerModal');
    if (!modal) return;
    _fmState.folderType = folderType;
    _fmState.subpath = subpath || '';
    _fmState.targetUser = currentTargetUser || null;

    var titleEl = document.getElementById('fileManagerTitle');
    var labelMap = { bags: 'Bag 数据', logs: '日志', install: 'Install', bk: 'bk 目录', scripts: 'Scripts' };
    var label = labelMap[folderType] || folderType;
    var tu = _fmState.targetUser;
    if (titleEl) {
        titleEl.textContent = '📁 文件管理 - ' + label + (tu ? '（👤 ' + tu + '）' : '');
    }

    modal.style.display = 'flex';

    if (folderType === 'bags') {
        var listEl = document.getElementById('fileManagerList');
        if (listEl) {
            listEl.innerHTML = '<div style="text-align:center;padding:32px;color:var(--text-muted);">' +
                               '<div style="font-size:32px;margin-bottom:8px;">⏳</div>' +
                               '<div>正在同步容器中的Bag数据，请稍候...</div>' +
                               '</div>';
        }
        var body = {};
        if (currentTargetUser) body.target_user = currentTargetUser;
        apiPost('/api/files/sync-bags', body).then(function(d) {
            if (d && d.success) {
                if (d.synced_count > 0) {
                    showToast('✓ ' + d.message, 'success');
                }
                loadFileList();
            } else {
                showToast('Bag同步提示: ' + (d && (d.error || d.message) || '完成'), 'info');
                loadFileList();
            }
        }).catch(function(e) {
            showToast('Bag同步失败: ' + e.message, 'warning');
            loadFileList();
        });
    } else {
        loadFileList();
    }
}

function closeFileManager() {
    var modal = document.getElementById('fileManagerModal');
    if (modal) modal.style.display = 'none';
}

function loadFileList() {
    var listEl = document.getElementById('fileManagerList');
    var breadcrumbEl = document.getElementById('fileManagerBreadcrumb');
    if (!listEl) return;
    listEl.innerHTML = '<div style="text-align:center;padding:16px;color:var(--text-muted);">加载中...</div>';

    var params = 'folder_type=' + encodeURIComponent(_fmState.folderType) +
                 '&subpath=' + encodeURIComponent(_fmState.subpath || '');
    if (_fmState.targetUser) params += '&target_user=' + encodeURIComponent(_fmState.targetUser);

    apiGet('/api/files/list?' + params).then(function(d) {
        if (!d.success) {
            listEl.innerHTML = '<div style="color:#dc3545;text-align:center;padding:16px;">加载失败</div>';
            return;
        }
        if (!d.exists) {
            listEl.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-muted);">' +
                               '<div style="font-size:36px;margin-bottom:8px;">📂</div>' +
                               '<div>目录不存在</div>' +
                               '<div style="font-size:12px;margin-top:4px;">' + escapeHtml(d.path) + '</div>' +
                               '<div style="font-size:12px;margin-top:8px;color:#b8550a;">💡 ' + getFileTypeHint(_fmState.folderType) + '</div>' +
                               '</div>';
            if (breadcrumbEl) breadcrumbEl.innerHTML = '';
            return;
        }

        // 面包屑
        if (breadcrumbEl) {
            var bc = '<a href="javascript:void(0)" onclick="fmGoTo(\'\')" style="color:#2c5aa0;">' + (_fmState.folderType) + '</a>';
            if (d.rel) {
                var parts = d.rel.split('/');
                var acc = '';
                for (var i = 0; i < parts.length; i++) {
                    acc = (acc ? acc + '/' : '') + parts[i];
                    bc += ' / <a href="javascript:void(0)" onclick="fmGoTo(\'' + escapeHtml(acc) + '\')" style="color:#2c5aa0;">' + escapeHtml(parts[i]) + '</a>';
                }
            }
            breadcrumbEl.innerHTML = bc;
        }

        // 文件列表
        var items = d.items || [];
        if (items.length === 0) {
            listEl.innerHTML = '<div style="text-align:center;padding:24px;color:var(--text-muted);">（空目录）</div>';
            return;
        }
        var html = '<table class="data-table"><thead><tr>' +
                   '<th style="width:40px;"></th><th>名称</th><th>大小</th><th>修改时间</th><th style="width:160px;">操作</th>' +
                   '</tr></thead><tbody>';
        // 父目录返回
        if (d.parent !== null && d.parent !== undefined) {
            html += '<tr><td>📁</td><td colspan="4"><a href="javascript:void(0)" onclick="fmGoTo(\'' + escapeHtml(d.parent || '') + '\')" style="color:#2c5aa0;">.. （上级目录）</a></td></tr>';
        }
        for (var j = 0; j < items.length; j++) {
            var it = items[j];
            var icon = it.is_dir ? '📁' : fmFileIcon(it.name);
            var sz = it.is_dir ? '-' : formatSize(it.size);
            var mt = new Date(it.mtime * 1000).toLocaleString('zh-CN', {hour12:false}).replace(/\//g, '-');
            var sub = (d.rel ? d.rel + '/' : '') + it.name;
            var safeSub = escapeHtml(sub);
            html += '<tr>';
            if (it.is_dir) {
                html += '<td>' + icon + '</td>';
                html += '<td><a href="javascript:void(0)" onclick="fmGoTo(\'' + safeSub + '\')" style="color:#2c5aa0;">' + escapeHtml(it.name) + '</a></td>';
            } else {
                html += '<td>' + icon + '</td>';
                html += '<td>' + escapeHtml(it.name) + '</td>';
            }
            html += '<td style="color:var(--text-muted);">' + sz + '</td>';
            html += '<td style="font-size:12px;color:var(--text-muted);">' + mt + '</td>';
            html += '<td>';
            html += '<button class="btn btn-sm btn-outline" onclick="fmRename(\'' + safeSub + '\', \'' + escapeHtml(it.name) + '\')">✏️ 重命名</button> ';
            if (!it.is_dir) {
                html += '<button class="btn btn-sm btn-outline" onclick="fmDownload(\'' + safeSub + '\')">⬇ 下载</button> ';
            }
            html += '<button class="btn btn-sm btn-danger" onclick="fmDelete(\'' + safeSub + '\', ' + (it.is_dir ? 'true' : 'false') + ')">🗑 删除</button>';
            html += '</td>';
            html += '</tr>';
        }
        html += '</tbody></table>';
        listEl.innerHTML = html;
    }).catch(function(e) {
        listEl.innerHTML = '<div style="color:#dc3545;text-align:center;padding:16px;">加载失败: ' + escapeHtml(e.message || '') + '</div>';
    });
}

function fmGoTo(subpath) {
    _fmState.subpath = subpath || '';
    loadFileList();
}

function fmDownload(subpath) {
    var params = 'folder_type=' + encodeURIComponent(_fmState.folderType) +
                 '&subpath=' + encodeURIComponent(subpath);
    if (_fmState.targetUser) params += '&target_user=' + encodeURIComponent(_fmState.targetUser);
    // 使用 fetch 带 token 下载 blob
    fetch(API_BASE + '/api/files/download?' + params, {
        method: 'GET',
        headers: { 'Authorization': 'Bearer ' + (AUTH_TOKEN || '') }
    }).then(function(res) {
        if (!res.ok) throw new Error('下载失败');
        var disp = res.headers.get('content-disposition') || '';
        var m = /filename="?([^";]+)"?/.exec(disp);
        var fname = m ? m[1] : 'download';
        return res.blob().then(function(b) {
            var url = URL.createObjectURL(b);
            var a = document.createElement('a');
            a.href = url;
            a.download = fname;
            document.body.appendChild(a);
            a.click();
            setTimeout(function() { URL.revokeObjectURL(url); a.remove(); }, 1000);
        });
    }).catch(function(e) { showToast('下载失败: ' + e.message, 'error'); });
}

function fmDelete(subpath, isDir) {
    var tip = isDir ? '确定删除整个目录（含子内容）？' : '确定删除该文件？';
    tip += '\n\n' + subpath;
    customConfirm(tip + '\n\n此操作不可撤销！', function() {
        apiPost('/api/files/delete', {
            folder_type: _fmState.folderType,
            subpath: subpath,
            target_user: _fmState.targetUser
        }).then(function(d) {
            if (d && d.success) {
                showToast('✓ 已删除', 'success');
                loadFileList();
            } else {
                showToast('删除失败: ' + (d && (d.error || d.message) || ''), 'error');
            }
        });
    });
}

function fmRename(subpath, oldName) {
    var newName = prompt('请输入新名称：', oldName);
    if (!newName) return;
    newName = newName.trim();
    if (!newName || newName === oldName) return;
    if (newName.includes('/') || newName.includes('\\')) {
        showToast('名称不能包含路径分隔符', 'warning');
        return;
    }
    apiPost('/api/files/rename', {
        folder_type: _fmState.folderType,
        subpath: subpath,
        new_name: newName,
        target_user: _fmState.targetUser
    }).then(function(d) {
        if (d && d.success) {
            showToast('✓ 已重命名', 'success');
            loadFileList();
        } else {
            showToast('重命名失败: ' + (d && (d.error || d.message) || ''), 'error');
        }
    });
}

function fmMkdirPrompt() {
    var name = prompt('请输入新目录名：');
    if (!name) return;
    name = name.trim().replace(/[\\\/]+/g, '/').replace(/^\/+|\/+$/g, '');
    if (!name) { showToast('目录名无效', 'warning'); return; }
    var sub = (_fmState.subpath ? _fmState.subpath + '/' : '') + name;
    apiPost('/api/files/mkdir', {
        folder_type: _fmState.folderType,
        subpath: sub,
        target_user: _fmState.targetUser
    }).then(function(d) {
        if (d && d.success) {
            showToast('✓ 已创建目录', 'success');
            loadFileList();
        } else {
            showToast('创建失败: ' + (d && (d.error || d.message) || ''), 'error');
        }
    });
}

function fmUploadInput(input) {
    if (!input.files || !input.files.length) return;
    var formData = new FormData();
    formData.append('folder_type', _fmState.folderType);
    formData.append('subpath', _fmState.subpath || '');
    if (_fmState.targetUser) formData.append('target_user', _fmState.targetUser);
    for (var i = 0; i < input.files.length; i++) {
        formData.append('files', input.files[i]);
    }
    showToast('正在上传 ' + input.files.length + ' 个文件...', 'info');
    fetch(API_BASE + '/api/files/upload', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + (AUTH_TOKEN || '') },
        body: formData
    }).then(function(res) { return res.json(); })
      .then(function(d) {
          if (d && d.success) {
              showToast('✓ 已上传 ' + d.count + ' 个文件', 'success');
              loadFileList();
          } else {
              showToast('上传失败: ' + (d && (d.error || d.message) || ''), 'error');
          }
      })
      .catch(function(e) { showToast('上传失败: ' + e.message, 'error'); });
    input.value = '';
}

function fmFileIcon(name) {
    var ext = (name.split('.').pop() || '').toLowerCase();
    var m = {
        'log':'📝','txt':'📝','md':'📝','csv':'📊',
        'yaml':'⚙️','yml':'⚙️','json':'⚙️','xml':'⚙️','ini':'⚙️','conf':'⚙️',
        'bag':'📦','db3':'📦','sqlite':'📦',
        'py':'🐍','sh':'🔧','bash':'🔧',
        'png':'🖼️','jpg':'🖼️','jpeg':'🖼️','gif':'🖼️','svg':'🖼️',
        'zip':'🗜️','tar':'🗜️','gz':'🗜️','bz2':'🗜️','tgz':'🗜️',
        'pdf':'📄','html':'🌐','js':'📜','css':'🎨'
    };
    return m[ext] || '📄';
}

function getFileTypeHint(folderType) {
    var hints = {
        bags: '启动仿真车辆后自动生成',
        logs: '启动仿真车辆后自动生成',
        install: '请先上传安装包',
        bk: '请工单联系管理员',
        scripts: '由系统自动管理'
    };
    return hints[folderType] || '请联系管理员';
}

/**
 * 处理 doSwitchCert 相关前端逻辑。
 */
function doSwitchCert(env) {
    var body = { env: env };
    if (currentTargetUser) body.target_user = currentTargetUser;
    return apiPost('/api/system/certificates', body);
}
function doSwitchCloudIp(ip) {
    var body = { ip: ip };
    if (currentTargetUser) body.target_user = currentTargetUser;
    return apiPost('/api/system/cloud-config', body);
}

window.switchCert = function(env) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    var targetEnv = env;
    if (!targetEnv) { var el = document.getElementById('certSelect'); if (el) targetEnv = el.value; }
    if (!targetEnv) { showToast('未指定环境', 'warning'); return; }
    customConfirm('确定切换至 ' + targetEnv + ' 环境证书？', function() {
        showToast('正在切换...', 'info');
        doSwitchCert(targetEnv).then(function(d) {
            var msg = d && d.success ? (d.message || '切换成功') : _errMsg(d, '切换失败');
            showToast(msg, d && d.success ? 'success' : 'error');
        });
    });
};

window.switchCloudIp = function(ip) {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    var targetIp = ip;
    if (!targetIp) { var el = document.getElementById('cloudIpSelect'); if (el) targetIp = el.value; }
    if (!targetIp) { showToast('未指定IP', 'warning'); return; }
    customConfirm('确定切换云配置 IP 至 ' + targetIp + '？', function() {
        showToast('正在切换...', 'info');
        doSwitchCloudIp(targetIp).then(function(d) {
            var msg = d && d.success ? (d.message || '切换成功') : _errMsg(d, '切换失败');
            showToast(msg, d && d.success ? 'success' : 'error');
        });
    });
};

/**
 * 云配置 IP 及证书切换。
 */
function handleEnvSwitch() {
    if (!hasPermission('tools')) {
        showToast('您没有其他工具的操作权限', 'warning');
        return;
    }
    var select = document.getElementById('envSwitchSelect');
    var env = select.value;
    var ip = ENV_IP_MAP[env];
    var btn = document.getElementById('envSwitchBtn');
    if (btn.disabled) return;
    btn.disabled = true;
    btn.textContent = '⏳ 切换中...';
    showToast('🔄 开始切换至 ' + env + ' 环境 (IP: ' + ip + ') ...', 'info');

    var certOk = false, ipOk = false;
    var certErr = '', ipErr = '';

    doSwitchCert(env).then(function(certRes) {
        if (certRes.success) certOk = true;
        else certErr = _errMsg(certRes, '证书切换失败');
        return doSwitchCloudIp(ip);
    }).then(function(ipRes) {
        if (ipRes.success) ipOk = true;
        else ipErr = _errMsg(ipRes, 'IP 切换失败');
    }).catch(function(e) {
        if (!certOk) certErr = (e && e.message) || '证书切换请求异常';
        if (!ipOk) ipErr = (e && e.message) || 'IP 切换请求异常';
    }).then(function() {
        btn.disabled = false;
        btn.textContent = '🔄 切换';
        if (certOk && ipOk) {
            localStorage.setItem('ros2_web_cloud_env', env);
            localStorage.setItem('ros2_web_cloud_ip', ip);
            showToast('✅ 全部切换成功！当前环境 ' + env + '，IP ' + ip, 'success');
        } else {
            var details = [];
            if (!certOk) details.push('证书: ' + certErr);
            if (!ipOk) details.push('IP: ' + ipErr);
            showToast('❌ 切换失败：' + details.join('；'), 'error');
        }
    });
}

function initCloudEnv() {
    apiGet('/api/system/cloud-env').then(function(data) {
        if (data.success && data.current_env) {
            var select = document.getElementById('envSwitchSelect');
            if (select) {
                select.value = data.current_env;
            }
            localStorage.setItem('ros2_web_cloud_env', data.current_env);
            localStorage.setItem('ros2_web_cloud_ip', data.current_ip);
        } else {
            var savedEnv = localStorage.getItem('ros2_web_cloud_env');
            if (savedEnv) {
                var select = document.getElementById('envSwitchSelect');
                if (select) {
                    select.value = savedEnv;
                }
            }
        }
    }).catch(function() {
        var savedEnv = localStorage.getItem('ros2_web_cloud_env');
        if (savedEnv) {
            var select = document.getElementById('envSwitchSelect');
            if (select) {
                select.value = savedEnv;
            }
        }
    });
}

// ========== 预留扩展区域（第801-850行） ==========
// 预留用于未来扩展，如更多工具等
// ===========================================

// ============================================================
