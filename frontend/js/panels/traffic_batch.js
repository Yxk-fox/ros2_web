/* T-6.0-02 懒加载模块：红绿灯模拟 + 批量生成车辆 — 从 sj_script.js 拆出，defer 加载，全局函数不变 */

// 18. 红绿灯模拟
// ============================================================

/**
 * 处理 checkTrafficStatus 相关前端逻辑。
 */
function checkTrafficStatus() {
    apiGet('/api/traffic-light/status').then(function(d) {
        updateTrafficUI(d.running);
    });
}

/**
 * 处理 updateTrafficUI 相关前端逻辑。
 */
function updateTrafficUI(running) {
    var startBtn = document.getElementById('tlStartBtn');
    var stopBtn = document.getElementById('tlStopBtn');
    var statusEl = document.getElementById('tlStatus');
    if (startBtn) startBtn.disabled = running;
    if (stopBtn) stopBtn.disabled = !running;
    if (statusEl) {
        statusEl.textContent = running ? '🟢 运行中' : '⚪ 未运行';
        statusEl.style.color = running ? 'var(--success)' : 'var(--text-secondary)';
    }
    if (running) {
        setTimeout(checkTrafficPanelStatus, 500);
    }
}

/**
 * 处理 startTrafficLight 相关前端逻辑。
 */
function startTrafficLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有红绿灯模拟的操作权限', 'warning');
        return;
    }
    var body = {
        sn: document.getElementById('tlSn').value,
        project_id: document.getElementById('tlProjectId').value,
        token: document.getElementById('tlToken').value.trim(),
        http_host: document.getElementById('tlHttpHost').value,
        mqtt_host: document.getElementById('tlMqttHost').value,
        cloud_host: document.getElementById('tlCloudHost').value,
        login_interval: parseInt(document.getElementById('tlLoginInterval').value),
        report_interval: parseInt(document.getElementById('tlReportInterval').value)
    };
    apiPost('/api/traffic-light/start', body).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateTrafficUI(true);
    });
}

/**
 * 处理 stopTrafficLight 相关前端逻辑。
 */
function stopTrafficLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有红绿灯模拟的操作权限', 'warning');
        return;
    }
    apiPost('/api/traffic-light/stop').then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateTrafficUI(false);
    });
}

/**
 * 检查计时红绿灯状态
 */
function checkTimerTrafficStatus() {
    apiGet('/api/timer-traffic-light/status').then(function(d) {
        updateTimerTrafficUI(d.running);
    });
}

/**
 * 更新计时红绿灯UI状态
 */
function updateTimerTrafficUI(running) {
    var startBtn = document.getElementById('ttmStartBtn');
    var stopBtn = document.getElementById('ttmStopBtn');
    var statusEl = document.getElementById('ttmStatus');
    if (startBtn) startBtn.disabled = running;
    if (stopBtn) stopBtn.disabled = !running;
    if (statusEl) {
        statusEl.textContent = running ? '🟢 运行中' : '⚪ 未运行';
        statusEl.style.color = running ? 'var(--success)' : 'var(--text-secondary)';
    }
}

/**
 * 启动计时红绿灯
 */
function startTimerTrafficLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有计时红绿灯模拟的操作权限', 'warning');
        return;
    }
    var body = {
        sn: document.getElementById('ttmSn').value,
        host: document.getElementById('ttmHost').value,
        port: parseInt(document.getElementById('ttmPort').value),
        red_duration: parseInt(document.getElementById('ttmRed').value),
        green_duration: parseInt(document.getElementById('ttmGreen').value),
        yellow_duration: parseInt(document.getElementById('ttmYellow').value)
    };
    apiPost('/api/timer-traffic-light/start', body).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateTimerTrafficUI(true);
    });
}

/**
 * 停止计时红绿灯
 */
function stopTimerTrafficLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有计时红绿灯模拟的操作权限', 'warning');
        return;
    }
    apiPost('/api/timer-traffic-light/stop').then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateTimerTrafficUI(false);
    });
}

/**
 * 检查人工模式计时红绿灯状态
 */
function checkManualTimerTrafficStatus() {
    apiGet('/api/manual-timer-traffic-light/status').then(function(d) {
        updateManualTimerTrafficUI(d.running, d);
    });
}

/**
 * 更新人工模式计时红绿灯UI状态
 */
function updateManualTimerTrafficUI(running, data) {
    var startBtn = document.getElementById('mtmStartBtn');
    var stopBtn = document.getElementById('mtmStopBtn');
    var stateBtn = document.getElementById('mtmStateBtn');
    var statusEl = document.getElementById('mtmStatus');
    if (startBtn) startBtn.disabled = running;
    if (stopBtn) stopBtn.disabled = !running;
    if (stateBtn) stateBtn.disabled = !running;
    if (statusEl) {
        if (running && data) {
            var label = data.state_label !== undefined ? data.state_label : '';
            statusEl.textContent = '🟢 运行中 | 灯态: ' + label + '(' + data.state + ')';
        } else {
            statusEl.textContent = '⚪ 未运行';
        }
        statusEl.style.color = running ? 'var(--success)' : 'var(--text-secondary)';
    }
    if (running && data && data.state !== undefined) {
        var stateSel = document.getElementById('mtmState');
        if (stateSel) stateSel.value = String(data.state);
    }
}

/**
 * 启动人工模式计时红绿灯
 */
function startManualTimerTrafficLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有人工模式计时红绿灯模拟的操作权限', 'warning');
        return;
    }
    var body = {
        sn: document.getElementById('mtmSn').value,
        host: document.getElementById('mtmHost').value,
        port: parseInt(document.getElementById('mtmPort').value),
        manual_time: parseInt(document.getElementById('mtmManualTime').value),
        auto_mode: parseInt(document.getElementById('mtmAutoMode').value),
        state: parseInt(document.getElementById('mtmState').value)
    };
    apiPost('/api/manual-timer-traffic-light/start', body).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateManualTimerTrafficUI(true);
    });
}

/**
 * 停止人工模式计时红绿灯
 */
function stopManualTimerTrafficLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有人工模式计时红绿灯模拟的操作权限', 'warning');
        return;
    }
    apiPost('/api/manual-timer-traffic-light/stop').then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateManualTimerTrafficUI(false);
    });
}

/**
 * 人工切换灯态
 */
function setManualTimerTrafficState() {
    if (!hasPermission('traffic')) {
        showToast('您没有人工模式计时红绿灯模拟的操作权限', 'warning');
        return;
    }
    var state = parseInt(document.getElementById('mtmState').value);
    apiPost('/api/manual-timer-traffic-light/set-state', { state: state }).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateManualTimerTrafficUI(true, d);
    });
}

// ========== 预留扩展区域（第851-900行） ==========
// 预留用于未来扩展，如更多红绿灯模式等
// ===========================================

// ============================================================
// 18.1 交通红绿灯控制面板
// ============================================================
var trafficLightMode = 1;
var trafficMainLightState = 1;
var trafficSecondLightState = 2;
var trafficMqttConnected = false;

var STATE_LABEL = {1: "绿灯", 2: "红灯", 3: "灭灯", 4: "黄灯"};
var STATE_COLOR_CLASS = {1: "green", 2: "red", 3: "", 4: "yellow"};

function toggleTrafficMode() {
    var newMode = trafficLightMode == 1 ? 2 : 1;
    apiPost('/api/traffic-light/set-mode', { mode: newMode }).then(function(d) {
        if (d.success) {
            trafficLightMode = newMode;
            showToast(d.message || (newMode === 1 ? '已切换为自动模式' : '已切换为手动模式'), 'success');
        } else {
            showToast(d.message || '切换模式失败', 'error');
        }
        updateTrafficPanelDisplay();
    }).catch(function() {
        showToast('切换模式失败', 'error');
    });
}

function onManualLightChange(lightType) {
    if (trafficLightMode != 2) {
        showToast('请先切换到手动模式', 'warning');
        var radios = document.getElementsByName(lightType === 'main' ? 'mainLightColor' : 'secondLightColor');
        for (var i = 0; i < radios.length; i++) {
            radios[i].checked = (parseInt(radios[i].value) === (lightType === 'main' ? trafficMainLightState : trafficSecondLightState));
        }
        return;
    }
    var body = {};
    if (lightType === 'main') {
        var radios = document.getElementsByName('mainLightColor');
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].checked) {
                body.light_state = parseInt(radios[i].value);
                break;
            }
        }
    } else {
        var radios = document.getElementsByName('secondLightColor');
        for (var i = 0; i < radios.length; i++) {
            if (radios[i].checked) {
                body.second_light_state = parseInt(radios[i].value);
                break;
            }
        }
    }
    apiPost('/api/traffic-light/set-light-state', body).then(function(d) {
        if (d.success) {
            trafficMainLightState = d.light_state || trafficMainLightState;
            trafficSecondLightState = d.second_light_state || trafficSecondLightState;
        } else {
            showToast(d.message || '设置灯状态失败', 'error');
            var radios = document.getElementsByName(lightType === 'main' ? 'mainLightColor' : 'secondLightColor');
            for (var i = 0; i < radios.length; i++) {
                radios[i].checked = (parseInt(radios[i].value) === (lightType === 'main' ? trafficMainLightState : trafficSecondLightState));
            }
        }
        updateTrafficPanelDisplay();
    }).catch(function() {
        showToast('设置灯状态失败', 'error');
        var radios = document.getElementsByName(lightType === 'main' ? 'mainLightColor' : 'secondLightColor');
        for (var i = 0; i < radios.length; i++) {
            radios[i].checked = (parseInt(radios[i].value) === (lightType === 'main' ? trafficMainLightState : trafficSecondLightState));
        }
    });
}

function updateTrafficLightCircle(circleId, state) {
    var circle = document.getElementById(circleId);
    if (circle) {
        circle.className = 'traffic-light-circle';
        if (STATE_COLOR_CLASS[state]) {
            circle.classList.add(STATE_COLOR_CLASS[state]);
        }
    }
}

function updateTrafficPanelDisplay() {
    var modeLabel = document.getElementById('trafficModeLabel');
    var modeBtn = document.getElementById('trafficModeBtn');
    var ctrlPanel = document.querySelector('.traffic-manual-control');
    var mainLightStatus = document.getElementById('mainLightStatus');
    var secondLightStatus = document.getElementById('secondLightStatus');
    var statusBar = document.getElementById('trafficStatusBar');

    if (modeLabel) {
        modeLabel.textContent = '当前模式: ' + (trafficLightMode === 1 ? '自动' : '手动');
        modeLabel.style.color = trafficLightMode === 1 ? '#0066CC' : '#CC6600';
    }

    if (modeBtn) {
        modeBtn.textContent = trafficLightMode === 1 ? '切换为手动' : '切换为自动';
        modeBtn.className = 'btn ' + (trafficLightMode === 1 ? 'btn-warning' : 'btn-success');
    }

    if (ctrlPanel) {
        if (trafficLightMode === 2) {
            ctrlPanel.classList.remove('disabled');
            var radios = ctrlPanel.querySelectorAll('input[type="radio"]');
            radios.forEach(function(r) { r.disabled = false; });
        } else {
            ctrlPanel.classList.add('disabled');
            var radios = ctrlPanel.querySelectorAll('input[type="radio"]');
            radios.forEach(function(r) { r.disabled = true; });
        }
    }

    updateTrafficLightCircle('mainLight', trafficMainLightState);
    updateTrafficLightCircle('secondLight', trafficSecondLightState);

    if (mainLightStatus) {
        mainLightStatus.textContent = STATE_LABEL[trafficMainLightState] || '灭灯';
    }
    if (secondLightStatus) {
        secondLightStatus.textContent = STATE_LABEL[trafficSecondLightState] || '灭灯';
    }

    if (statusBar) {
        var mqttStatus = trafficMqttConnected ? 'MQTT: 已连接' : 'MQTT: 未连接';
        var modeText = trafficLightMode === 1 ? '自动' : '手动';
        statusBar.textContent = mqttStatus + ' | 模式: ' + modeText + ' | 主灯: ' + STATE_LABEL[trafficMainLightState] + ' | 次灯: ' + STATE_LABEL[trafficSecondLightState];
    }
}

function handleTrafficLightStatus(msg) {
    trafficMainLightState = (msg.light_state !== undefined && msg.light_state !== null) ? msg.light_state : 1;
    trafficSecondLightState = (msg.second_light_state !== undefined && msg.second_light_state !== null) ? msg.second_light_state : 2;
    trafficLightMode = (msg.light_mode !== undefined && msg.light_mode !== null) ? msg.light_mode : 1;
    trafficMqttConnected = msg.mqtt_connected || false;
    updateTrafficPanelDisplay();
}

function checkTrafficPanelStatus() {
    apiGet('/api/traffic-light/light-status').then(function(d) {
        if (d.success) {
            trafficMainLightState = (d.light_state !== undefined && d.light_state !== null) ? d.light_state : 1;
            trafficSecondLightState = (d.second_light_state !== undefined && d.second_light_state !== null) ? d.second_light_state : 2;
            trafficLightMode = (d.light_mode !== undefined && d.light_mode !== null) ? d.light_mode : 1;
            trafficMqttConnected = d.mqtt_connected || false;
        } else {
            trafficMqttConnected = false;
        }
        updateTrafficPanelDisplay();
    });
    // 同步破碎站状态显示（不弹 Toast）
    apiGet('/api/crushing-traffic-light/status').then(function(d) {
        if (d.success) updateCrushingUI(d.running, d);
    }).catch(function() {});
}

function startTrafficPanelMonitor() {
    setInterval(checkTrafficPanelStatus, 2000);
}

// ============================================================
// 18.4 破碎站红绿灯模拟（T-5.3，对应 ck/lk_light_state*.py）
// ============================================================

function startCrushingLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有红绿灯模拟的操作权限', 'warning');
        return;
    }
    var body = {
        sn: document.getElementById('clSn').value,
        host: document.getElementById('clHost').value,
        port: parseInt(document.getElementById('clPort').value),
        red_duration: parseInt(document.getElementById('clRed').value),
        green_duration: parseInt(document.getElementById('clGreen').value),
        yellow_duration: parseInt(document.getElementById('clYellow').value),
        send_interval: parseFloat(document.getElementById('clInterval').value)
    };
    apiPost('/api/crushing-traffic-light/start', body).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateCrushingUI(true, {});
    });
}

function stopCrushingLight() {
    if (!hasPermission('traffic')) {
        showToast('您没有红绿灯模拟的操作权限', 'warning');
        return;
    }
    apiPost('/api/crushing-traffic-light/stop', {}).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateCrushingUI(false, {});
    });
}

function checkCrushingStatus() {
    apiGet('/api/crushing-traffic-light/status').then(function(d) {
        if (d.success) {
            updateCrushingUI(d.running, d);
            showToast(d.running ? '破碎站红绿灯运行中' : '破碎站红绿灯未运行', 'info');
        }
    });
}

function updateCrushingUI(running, status) {
    var startBtn = document.getElementById('clStartBtn');
    var stopBtn = document.getElementById('clStopBtn');
    var statusEl = document.getElementById('clStatus');
    if (!statusEl) return; // 不在 traffic 面板
    if (startBtn) startBtn.disabled = running;
    if (stopBtn) stopBtn.disabled = !running;
    var label = status && status.current_label ? status.current_label : '';
    var remain = status && status.phase_remain !== undefined ? status.phase_remain : '';
    if (running) {
        statusEl.textContent = '🟢 运行中' + (label ? ' [' + label + ' 剩 ' + remain + 's]' : '');
        statusEl.style.color = 'var(--success)';
    } else {
        statusEl.textContent = '⚪ 未运行';
        statusEl.style.color = 'var(--text-secondary)';
    }
}

// ============================================================
// 18.5 动态红绿灯面板（localStorage 持久化，4 种类型可选）
// ============================================================
// 面板配置结构：[{ id, type, title, config: {...} }]
// 状态：running（运行中），通过 polling /status 端点同步
// ===========================================

var TRAFFIC_PANEL_TYPES = {
    timer:        { label: '⏱️ 计时红绿灯',  apiBase: '/api/timer-traffic-light' },
    manual_timer: { label: '🎛️ 人工计时红绿灯', apiBase: '/api/manual-timer-traffic-light' },
    traffic:      { label: '🚦 交通红绿灯',   apiBase: '/api/traffic-light' },
    crushing:     { label: '⛏️ 破碎站红绿灯',  apiBase: '/api/crushing-traffic-light' },
};

var TRAFFIC_PANEL_DEFAULTS = {
    timer:        { sn: 'js_light', host: '139.196.75.44', port: 1234, red_duration: 15, green_duration: 35, yellow_duration: 5 },
    manual_timer: { sn: 'js_001', host: '106.14.223.60', port: 1234, manual_time: 255, auto_mode: 2, state: 0 },
    traffic:      { sn: 'hd_light', project_id: '55722339745601', http_host: '139.196.75.44:8900', mqtt_host: '139.196.75.44:1883', cloud_host: '139.196.75.44:1234', login_interval: 60, report_interval: 1, token: '' },
    crushing:     { sn: 'hz_test_light01', host: '106.14.223.60', port: 1234, red_duration: 10, green_duration: 30, yellow_duration: 3, send_interval: 1 },
};

var TRAFFIC_PANELS_KEY = 'trafficDynamicPanels';

function loadTrafficPanels() {
    try {
        return JSON.parse(localStorage.getItem(TRAFFIC_PANELS_KEY) || '[]');
    } catch (e) { return []; }
}

function saveTrafficPanels(panels) {
    localStorage.setItem(TRAFFIC_PANELS_KEY, JSON.stringify(panels));
}

function addTrafficPanel() {
    var type = document.getElementById('newPanelType').value;
    var panels = loadTrafficPanels();
    var id = 'tp_' + Date.now() + '_' + Math.floor(Math.random() * 1000);
    panels.push({
        id: id,
        type: type,
        title: TRAFFIC_PANEL_TYPES[type].label + ' #' + (panels.filter(function(p){return p.type===type;}).length + 1),
        config: Object.assign({}, TRAFFIC_PANEL_DEFAULTS[type])
    });
    saveTrafficPanels(panels);
    renderTrafficDynamicPanels();
    showToast('已新增面板', 'success');
}

function removeTrafficPanel(id) {
    if (!confirm('确认删除该红绿灯面板？运行中的实例需先停止。')) return;
    var panels = loadTrafficPanels().filter(function(p) { return p.id !== id; });
    saveTrafficPanels(panels);
    renderTrafficDynamicPanels();
    showToast('已删除面板', 'info');
}

function resetTrafficPanels() {
    if (!confirm('确认重置所有动态面板？')) return;
    localStorage.removeItem(TRAFFIC_PANELS_KEY);
    renderTrafficDynamicPanels();
    showToast('已重置为默认', 'info');
}

function renderTrafficDynamicPanels() {
    var container = document.getElementById('trafficDynamicPanels');
    var countEl = document.getElementById('trafficPanelCount');
    if (!container) return;
    var panels = loadTrafficPanels();
    if (countEl) countEl.textContent = '共 ' + panels.length + ' 个动态面板';
    if (!panels.length) {
        container.innerHTML = '<p style="opacity:0.5;font-size:13px;text-align:center;padding:14px">点击「新增面板」添加自定义红绿灯模拟器</p>';
        return;
    }
    var html = '';
    for (var i = 0; i < panels.length; i++) {
        html += renderTrafficPanelCard(panels[i]);
    }
    container.innerHTML = html;
    // 渲染后查询每个面板的运行状态
    for (var j = 0; j < panels.length; j++) {
        pollTrafficPanelStatus(panels[j]);
    }
}

function renderTrafficPanelCard(panel) {
    var typeDef = TRAFFIC_PANEL_TYPES[panel.type];
    var cfg = panel.config;
    var fields = renderTrafficPanelFields(panel.type, cfg, panel.id);
    return '<div class="card" style="margin-top:12px;border-left:3px solid var(--accent)" id="card_' + panel.id + '">' +
        '<div class="card-title" style="display:flex;justify-content:space-between;align-items:center">' +
        '<span>' + escapeHtml(panel.title) + '</span>' +
        '<button class="btn btn-sm btn-outline" onclick="removeTrafficPanel(\'' + panel.id + '\')">🗑 删除</button>' +
        '</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">' + fields + '</div>' +
        '<div class="btn-group">' +
        '<button class="btn btn-success" id="start_' + panel.id + '" onclick="startDynamicTrafficPanel(\'' + panel.id + '\')">▶ 启动</button>' +
        '<button class="btn btn-error" id="stop_' + panel.id + '" onclick="stopDynamicTrafficPanel(\'' + panel.id + '\')" disabled>⏹ 停止</button>' +
        '<button class="btn btn-outline" onclick="pollTrafficPanelStatusById(\'' + panel.id + '\')">🔄 刷新</button>' +
        '</div>' +
        '<div style="margin-top:8px;font-size:13px">状态: <span id="status_' + panel.id + '">未知</span></div>' +
        '</div>';
}

function renderTrafficPanelFields(type, cfg, panelId) {
    function field(label, key, inputHtml) {
        return '<div><label style="font-size:12px">' + label + '</label>' + inputHtml + '</div>';
    }
    function input(key, val, extra) {
        extra = extra || '';
        return '<input type="text" id="' + panelId + '_' + key + '" value="' + escapeHtml(String(val)) + '" style="width:100%;padding:6px 8px" ' + extra + ' oninput="updateTrafficPanelConfig(\'' + panelId + '\',\'' + key + '\',this.value)">';
    }
    function numInput(key, val, extra) {
        extra = extra || '';
        return '<input type="number" id="' + panelId + '_' + key + '" value="' + val + '" style="width:100%;padding:6px 8px" ' + extra + ' oninput="updateTrafficPanelConfig(\'' + panelId + '\',\'' + key + '\',this.value)">';
    }
    function selectInput(key, val, options, extraAttrs) {
        extraAttrs = extraAttrs || '';
        var opts = options.map(function(o) {
            return '<option value="' + o.v + '"' + (String(o.v) === String(val) ? ' selected' : '') + '>' + escapeHtml(o.t) + '</option>';
        }).join('');
        return '<select id="' + panelId + '_' + key + '" style="width:100%;padding:6px 8px" ' + extraAttrs + ' onchange="updateTrafficPanelConfig(\'' + panelId + '\',\'' + key + '\',this.value)">' + opts + '</select>';
    }

    var ipOptions = [
        {v:'106.14.223.60',t:'106.14.223.60'},
        {v:'139.196.75.44',t:'139.196.75.44'},
        {v:'192.168.9.252',t:'192.168.9.252'},
    ];
    var html = '';
    if (type === 'timer') {
        html += field('SN 标识', 'sn', input('sn', cfg.sn));
        html += field('端口', 'port', numInput('port', cfg.port));
        html += field('目标 IP', 'host', selectInput('host', cfg.host, ipOptions));
        html += field('红灯 (秒)', 'red_duration', numInput('red_duration', cfg.red_duration));
        html += field('绿灯 (秒)', 'green_duration', numInput('green_duration', cfg.green_duration));
        html += field('黄灯 (秒)', 'yellow_duration', numInput('yellow_duration', cfg.yellow_duration));
    } else if (type === 'manual_timer') {
        html += field('SN 标识', 'sn', input('sn', cfg.sn));
        html += field('端口', 'port', numInput('port', cfg.port));
        html += field('目标 IP', 'host', selectInput('host', cfg.host, ipOptions));
        html += field('manual_time', 'manual_time', numInput('manual_time', cfg.manual_time, 'min="0" max="255"'));
        html += field('auto_mode', 'auto_mode', selectInput('auto_mode', cfg.auto_mode, [{v:'1',t:'1-自动倒计时'},{v:'2',t:'2-人工'}]));
        html += field('灯态', 'state', selectInput('state', cfg.state, [
            {v:'0',t:'0-黄闪'},{v:'1',t:'1-黄'},{v:'2',t:'2-红'},{v:'3',t:'3-绿'},{v:'4',t:'4-绿闪'},{v:'5',t:'5-黑'}
        ]));
    } else if (type === 'traffic') {
        html += field('SN 标识', 'sn', input('sn', cfg.sn));
        html += field('矿区ID', 'project_id', input('project_id', cfg.project_id));
        html += field('HTTP 服务器', 'http_host', selectInput('http_host', cfg.http_host, [
            {v:'139.196.75.44:8900',t:'139.196.75.44:8900'},
            {v:'106.14.223.60:8900',t:'106.14.223.60:8900'},
            {v:'192.168.9.252:8900',t:'192.168.9.252:8900'},
        ]));
        html += field('MQTT 服务器', 'mqtt_host', selectInput('mqtt_host', cfg.mqtt_host, [
            {v:'139.196.75.44:1883',t:'139.196.75.44:1883'},
            {v:'106.14.223.60:1883',t:'106.14.223.60:1883'},
            {v:'192.168.9.252:1883',t:'192.168.9.252:1883'},
        ]));
        html += field('云端服务器', 'cloud_host', selectInput('cloud_host', cfg.cloud_host, [
            {v:'139.196.75.44:1234',t:'139.196.75.44:1234'},
            {v:'106.14.223.60:1234',t:'106.14.223.60:1234'},
            {v:'192.168.9.252:1234',t:'192.168.9.252:1234'},
        ]));
        html += field('登录间隔 (秒)', 'login_interval', numInput('login_interval', cfg.login_interval));
        html += field('上报间隔 (秒)', 'report_interval', numInput('report_interval', cfg.report_interval));
        html += '<div style="grid-column:span 2"><label style="font-size:12px">ID Token（可选）</label>' + input('token', cfg.token) + '</div>';
    } else if (type === 'crushing') {
        html += field('SN 标识', 'sn', input('sn', cfg.sn));
        html += field('端口', 'port', numInput('port', cfg.port));
        html += field('目标 IP', 'host', selectInput('host', cfg.host, ipOptions));
        html += field('发送间隔 (秒)', 'send_interval', numInput('send_interval', cfg.send_interval, 'step="0.5"'));
        html += field('红灯 (秒)', 'red_duration', numInput('red_duration', cfg.red_duration));
        html += field('绿灯 (秒)', 'green_duration', numInput('green_duration', cfg.green_duration));
        html += field('黄灯 (秒)', 'yellow_duration', numInput('yellow_duration', cfg.yellow_duration));
    }
    return html;
}

function updateTrafficPanelConfig(panelId, key, value) {
    var panels = loadTrafficPanels();
    for (var i = 0; i < panels.length; i++) {
        if (panels[i].id === panelId) {
            // 数值字段转 number
            var numKeys = ['port','red_duration','green_duration','yellow_duration','manual_time','auto_mode','state','login_interval','report_interval','send_interval'];
            panels[i].config[key] = (numKeys.indexOf(key) >= 0) ? Number(value) : value;
            break;
        }
    }
    saveTrafficPanels(panels);
}

function startDynamicTrafficPanel(panelId) {
    if (!hasPermission('traffic')) {
        showToast('您没有红绿灯模拟的操作权限', 'warning');
        return;
    }
    var panel = findPanelById(panelId);
    if (!panel) return;
    // 先同步最新配置（从 DOM 读取，确保用户最新输入生效）
    syncPanelConfigFromDOM(panel);
    var cfg = panel.config;
    // manual_timer 的 state 走单独 set-state API；启动时仅传启动参数
    var body = Object.assign({}, cfg);
    apiPost(TRAFFIC_PANEL_TYPES[panel.type].apiBase + '/start', body).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateDynamicPanelUI(panelId, true, {});
    });
}

function stopDynamicTrafficPanel(panelId) {
    if (!hasPermission('traffic')) {
        showToast('您没有红绿灯模拟的操作权限', 'warning');
        return;
    }
    var panel = findPanelById(panelId);
    if (!panel) return;
    apiPost(TRAFFIC_PANEL_TYPES[panel.type].apiBase + '/stop', {}).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) updateDynamicPanelUI(panelId, false, {});
    });
}

function pollTrafficPanelStatus(panel) {
    apiGet(TRAFFIC_PANEL_TYPES[panel.type].apiBase + '/status').then(function(d) {
        var running = !!(d.success && d.running);
        updateDynamicPanelUI(panel.id, running, d);
    }).catch(function() {});
}

function pollTrafficPanelStatusById(panelId) {
    var panel = findPanelById(panelId);
    if (panel) pollTrafficPanelStatus(panel);
}

function updateDynamicPanelUI(panelId, running, status) {
    var startBtn = document.getElementById('start_' + panelId);
    var stopBtn = document.getElementById('stop_' + panelId);
    var statusEl = document.getElementById('status_' + panelId);
    if (startBtn) startBtn.disabled = running;
    if (stopBtn) stopBtn.disabled = !running;
    if (statusEl) {
        if (running) {
            var label = status && status.current_label ? status.current_label : '';
            var remain = status && status.phase_remain !== undefined ? status.phase_remain : '';
            statusEl.textContent = '🟢 运行中' + (label ? ' [' + label + (remain !== '' ? ' 剩 ' + remain + 's' : '') + ']' : '');
            statusEl.style.color = 'var(--success)';
        } else {
            statusEl.textContent = '⚪ 未运行';
            statusEl.style.color = 'var(--text-secondary)';
        }
    }
}

function findPanelById(panelId) {
    var panels = loadTrafficPanels();
    for (var i = 0; i < panels.length; i++) {
        if (panels[i].id === panelId) return panels[i];
    }
    return null;
}

function syncPanelConfigFromDOM(panel) {
    var cfg = panel.config;
    for (var key in cfg) {
        if (!cfg.hasOwnProperty(key)) continue;
        var el = document.getElementById(panel.id + '_' + key);
        if (el) {
            var numKeys = ['port','red_duration','green_duration','yellow_duration','manual_time','auto_mode','state','login_interval','report_interval','send_interval'];
            cfg[key] = (numKeys.indexOf(key) >= 0) ? Number(el.value) : el.value;
        }
    }
    // 同步回 localStorage
    var panels = loadTrafficPanels();
    for (var i = 0; i < panels.length; i++) {
        if (panels[i].id === panel.id) { panels[i].config = cfg; break; }
    }
    saveTrafficPanels(panels);
}

// ============================================================
// 19. 批量生成车辆
// ============================================================
/**
 * 批量生成车辆配置（仅管理员）
 */
function batchGenerate() {
    // ★★★ 检查权限 ★★★
    if (!hasPermission('tools')) {
        showToast('您没有批量生成车辆的操作权限', 'warning');
        return;
    }

    var identifier = document.getElementById('batchIdentifier').value.trim();
    if (!identifier) {
        showToast('请输入标识', 'warning');
        return;
    }
    showToast('正在生成...', 'info');
    var div = document.getElementById('batchResult');
    apiPost('/api/batch/generate', {
        identifier: identifier
    }).then(function(d) {
        if (d.success) {
            var html = '<p style="color:var(--success)">✅ 生成完成！device_sn: <strong>' +
                escapeHtml(d.device_sn) + '</strong></p>';
            for (var i = 0; i < d.logs.length; i++) {
                html += '<div style="font-size:12px">' + escapeHtml(d.logs[i]) + '</div>';
            }
            div.innerHTML = html;
        } else {
            var errHtml = '<p style="color:var(--error)">❌ ' + escapeHtml(d.error) + '</p>';
            if (d.logs) {
                for (var j = 0; j < d.logs.length; j++) {
                    errHtml += '<div style="font-size:12px">' + escapeHtml(d.logs[j]) + '</div>';
                }
            }
            div.innerHTML = errHtml;
        }
    });
}

// ========== 预留扩展区域（第901-950行） ==========
// 预留用于未来扩展，如批量生成模板管理等
// ===========================================

// ============================================================
// Truck配置管理
// ============================================================

function loadTruckConfigList() {
    if (!hasPermission('tools')) {
        showToast('您没有操作权限', 'warning');
        return;
    }
    apiGet('/api/truck/config/list').then(function(d) {
        if (d.success) {
            var select = document.getElementById('truckConfigSelect');
            select.innerHTML = '<option value="">请选择truck配置文件</option>';
            for (var i = 0; i < d.files.length; i++) {
                select.innerHTML += '<option value="' + escapeHtml(d.files[i]) + '">' + escapeHtml(d.files[i]) + '</option>';
            }
            document.getElementById('truckConfigForm').style.display = 'none';
            document.getElementById('truckConfigEmpty').style.display = 'block';
        } else {
            showToast(d.error || '加载失败', 'error');
        }
    });
}

function loadTruckConfig() {
    if (!hasPermission('tools')) {
        showToast('您没有操作权限', 'warning');
        return;
    }
    var select = document.getElementById('truckConfigSelect');
    var filename = select.value;
    if (!filename) {
        document.getElementById('truckConfigForm').style.display = 'none';
        document.getElementById('truckConfigEmpty').style.display = 'block';
        return;
    }
    apiGet('/api/truck/config/' + encodeURIComponent(filename)).then(function(d) {
        if (d.success) {
            document.getElementById('truckStartX').value = d.start_x !== null ? d.start_x : '';
            document.getElementById('truckStartY').value = d.start_y !== null ? d.start_y : '';
            document.getElementById('truckStartYaw').value = d.start_yaw !== null ? d.start_yaw : '';
            document.getElementById('truckConfigForm').style.display = 'block';
            document.getElementById('truckConfigEmpty').style.display = 'none';
        } else {
            showToast(d.error || '加载失败', 'error');
        }
    });
}

function saveTruckConfig() {
    if (!hasPermission('tools')) {
        showToast('您没有操作权限', 'warning');
        return;
    }
    var select = document.getElementById('truckConfigSelect');
    var filename = select.value;
    if (!filename) {
        showToast('请选择配置文件', 'warning');
        return;
    }
    var start_x = parseFloat(document.getElementById('truckStartX').value);
    var start_y = parseFloat(document.getElementById('truckStartY').value);
    var start_yaw = parseFloat(document.getElementById('truckStartYaw').value);
    var data = {};
    if (!isNaN(start_x)) data.start_x = start_x;
    if (!isNaN(start_y)) data.start_y = start_y;
    if (!isNaN(start_yaw)) data.start_yaw = start_yaw;
    if (Object.keys(data).length === 0) {
        showToast('请至少填写一个参数', 'warning');
        return;
    }
    apiPut('/api/truck/config/' + encodeURIComponent(filename), data).then(function(d) {
        if (d.success) {
            showToast(d.message || '保存成功', 'success');
        } else {
            showToast(d.error || '保存失败', 'error');
        }
    });
}

function resetTruckConfig() {
    loadTruckConfig();
    showToast('已重置', 'info');
}

// ============================================================
