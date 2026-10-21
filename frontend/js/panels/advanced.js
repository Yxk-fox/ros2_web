/* T-6.0-02 懒加载模块：高级功能（容器管理增强/脚本执行增强/监控增强/系统自检/拓展功能/全局增强/故障注入/ROS2选择器） — 从 sj_script.js 拆出，defer 加载，全局函数不变 */

// 22. 高级功能 - 容器管理增强
// ============================================================

/**
 * 处理 loadAdvContainers 相关前端逻辑。
 */
function loadAdvContainers() {
    apiGet('/api/docker/containers?all=false').then(function(d) {
        if (!d.success || !d.containers) return;
        var html = '<option value="">-- 选择容器 --</option>';
        for (var i = 0; i < d.containers.length; i++) {
            var c = d.containers[i];
            html += '<option value="' + escapeHtml(c.id) + '">' + escapeHtml(c.name) + '</option>';
        }
        var sel1 = document.getElementById('advLogContainer');
        var sel2 = document.getElementById('foxgloveContainer');
        if (sel1) sel1.innerHTML = html;
        if (sel2) sel2.innerHTML = html;
    });
}

/**
 * 处理 onAdvLogContainerChange 相关前端逻辑。
 */
function onAdvLogContainerChange() {
    var val = document.getElementById('advLogContainer').value;
    document.getElementById('advLogStartBtn').disabled = !val;
}

/**
 * 处理 startRealtimeLogs 相关前端逻辑。
 */
function startRealtimeLogs() {
    var containerId = document.getElementById('advLogContainer').value;
    if (!containerId) { showToast('请选择容器', 'warning'); return; }
    if (advLogWs) { advLogWs.close(); }
    var container = document.getElementById('advLogContainer2');
    container.innerHTML = '<div style="opacity:0.5">正在连接...</div>';
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    advLogWs = new WebSocket(protocol + '//' + location.host + '/ws/containers/' + containerId + '/logs?token=' + encodeURIComponent(AUTH_TOKEN));
    advLogWs.onopen = function() {
        container.innerHTML = '';
        document.getElementById('advLogStartBtn').disabled = true;
        document.getElementById('advLogStopBtn').disabled = false;
    };
    advLogWs.onmessage = function(event) {
        var line = document.createElement('div');
        line.className = 'log-entry';
        var time = new Date().toLocaleTimeString();
        line.innerHTML = '<span class="time">[' + time + ']</span>' +
                        '<span class="type info">LOG</span>' +
                        '<span class="message">' + escapeHtml(event.data) + '</span>';
        container.appendChild(line);
        container.scrollTop = container.scrollHeight;
        if (container.children.length > 500) container.removeChild(container.firstChild);
    };
    advLogWs.onclose = function() {
        document.getElementById('advLogStartBtn').disabled = false;
        document.getElementById('advLogStopBtn').disabled = true;
    };
    advLogWs.onerror = function() {
        container.innerHTML += '<div style="color:var(--error)">连接错误</div>';
    };
}

/**
 * 处理 stopRealtimeLogs 相关前端逻辑。
 */
function stopRealtimeLogs() {
    if (advLogWs) { advLogWs.close(); advLogWs = null; }
    document.getElementById('advLogStartBtn').disabled = false;
    document.getElementById('advLogStopBtn').disabled = true;
}

/**
 * 提交容器为镜像（仅管理员）
 */
function commitContainer() {
    // ★★★ 检查是否为管理员 ★★★
    if (!hasPermission('advanced-docker')) {
        showToast('您没有容器管理增强的操作权限', 'warning');
        return;
    }

    var containerId = document.getElementById('commitContainer').value;
    if (!containerId) {
        showToast('请选择要提交的容器', 'warning');
        return;
    }
    var repo = document.getElementById('commitRepo').value.trim() || 'custom_image';
    var tag = document.getElementById('commitTag').value.trim() || 'latest';
    var msg = document.getElementById('commitMsg').value.trim();
    showToast('正在提交...', 'info');
    apiPost('/api/docker/container/' + containerId + '/commit', {
        repository: repo,
        tag: tag,
        message: msg
    }).then(function(d) {
        document.getElementById('commitResult').innerHTML = d.success
            ? '<span style="color:var(--success)">✅ 镜像已创建: ' + escapeHtml(d.image) + '</span>'
            : '<span style="color:var(--error)">❌ ' + escapeHtml(d.message || '') + '</span>';
        showToast(d.success ? '提交成功' : '失败', d.success ? 'success' : 'error');
    });
}

/**
 * 加载提交镜像的容器列表
 */
function loadCommitContainers() {
    apiGet('/api/docker/containers?all=true').then(function(data) {
        if (data.success && data.containers) {
            var select = document.getElementById('commitContainer');
            select.innerHTML = '<option value="">-- 选择容器 --</option>';
            data.containers.forEach(function(c) {
                var opt = document.createElement('option');
                opt.value = c.id;
                opt.textContent = c.name + (c.state === 'running' ? ' 🟢' : ' ⚪');
                select.appendChild(opt);
            });
        }
    });
}

/**
 * 提交容器选择变化处理
 */
function onCommitContainerChange() {
    // 可以在这里添加一些额外的处理逻辑
}

/**
 * 处理 openFoxglove 相关前端逻辑。
 * v3.6: Foxglove 已禁用，此函数保留占位以避免调用报错。
 */
function openFoxglove() {
    showToast('Foxglove 已禁用，请使用 VNC 远程桌面或原生 RVIZ', 'warning');
    return;
    var containerId = document.getElementById('foxgloveContainer').value;
    if (!containerId) { showToast('请选择容器', 'warning'); return; }
    apiGet('/api/docker/container/' + containerId + '/foxglove-url').then(function(d) {
        if (d.success) {
            document.getElementById('foxgloveResult').innerHTML = '<span style="color:var(--success)">✅ Foxglove URL: <a href="' + escapeHtml(d.foxglove_url || '') + '" target="_blank" rel="noopener noreferrer">' + escapeHtml(d.foxglove_url || '') + '</a></span><br><small>容器IP: ' + escapeHtml(d.container_ip || '') + '</small>';
            window.open(d.foxglove_url, '_blank');
        } else {
            document.getElementById('foxgloveResult').innerHTML = '<span style="color:var(--error)">❌ ' + escapeHtml(d.error || '') + '</span>';
        }
    });
}

/**
 * 处理 loadWhitelist 相关前端逻辑。
 */
function loadWhitelist() {
    apiGet('/api/system/whitelist').then(function(d) {
        if (!d.success) return;
        var container = document.getElementById('whitelistTags');
        var html = '';
        for (var i = 0; i < d.prefixes.length; i++) {
            html += '<span class="tag tag-running" style="cursor:pointer" onclick="removeWhitelist(\'' + escapeHtml(d.prefixes[i]) + '\')">' + escapeHtml(d.prefixes[i]) + ' ✕</span>';
        }
        container.innerHTML = html || '<span style="opacity:0.5">暂无白名单</span>';
    });
}

/**
 * 处理 addWhitelist 相关前端逻辑。
 */
function addWhitelist() {
    var prefix = document.getElementById('whitelistPrefix').value.trim();
    if (!prefix) { showToast('请输入前缀', 'warning'); return; }
    apiPost('/api/system/whitelist', { prefix: prefix }).then(function(d) {
        showToast(d.message || '', d.success ? 'success' : 'error');
        if (d.success) loadWhitelist();
    });
}

/**
 * 处理 removeWhitelist 相关前端逻辑。
 */
function removeWhitelist(prefix) {
    apiDelete('/api/system/whitelist/' + encodeURIComponent(prefix)).then(function(d) {
        showToast(d.message || '', d.success ? 'success' : 'error');
        if (d.success) loadWhitelist();
    });
}

// ========== 预留扩展区域（第1051-1100行） ==========
// 预留用于未来扩展，如容器编排、批量操作等
// ===========================================

// ============================================================
// 23. 高级功能 - 脚本执行增强
// ============================================================

/**
 * 处理 saveRetrySettings 相关前端逻辑。
 */
function saveRetrySettings() {
    if (window.userRole !== 'admin') {
        showToast('只有管理员可以修改重试设置', 'warning');
        return;
    }
    var count = document.getElementById('retryCount').value;
    var delay = document.getElementById('retryDelay').value;
    localStorage.setItem('retry_count', count);
    localStorage.setItem('retry_delay', delay);
    document.getElementById('retrySettingsStatus').textContent = '✅ 已保存';
    setTimeout(function() { document.getElementById('retrySettingsStatus').textContent = ''; }, 2000);
}

/**
 * 处理 loadScriptsForRetry 相关前端逻辑。
 */
function loadScriptsForRetry() {
    var count = localStorage.getItem('retry_count') || '3';
    var delay = localStorage.getItem('retry_delay') || '5';
    document.getElementById('retryCount').value = count;
    document.getElementById('retryDelay').value = delay;
    apiGet(appendTargetUser('/api/scripts/list')).then(function(d) {
        var tbody = document.getElementById('retryScriptsTableBody');
        if (!d.success || !d.scripts || !d.scripts.length) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">没有脚本</td></tr>';
            return;
        }
        var html = '';
        for (var i = 0; i < d.scripts.length; i++) {
            html += '<tr><td><input type="checkbox" class="retry-checkbox" value="' + escapeHtml(d.scripts[i]) + '"></td><td><code>' + escapeHtml(d.scripts[i]) + '</code></td></tr>';
        }
        tbody.innerHTML = html;
    });
}

/**
 * 处理 toggleRetryAll 相关前端逻辑。
 */
function toggleRetryAll() {
    var checked = document.getElementById('retrySelectAll').checked;
    var cbs = document.querySelectorAll('.retry-checkbox');
    for (var i = 0; i < cbs.length; i++) cbs[i].checked = checked;
}

/**
 * 批量执行脚本（带重试，仅管理员）
 */
function batchExecuteWithRetry() {
    // ★★★ 检查是否为管理员 ★★★
    if (!hasPermission('advanced-scripts')) {
        showToast('您没有脚本执行增强的操作权限', 'warning');
        return;
    }

    var selected = [];
    var cbs = document.querySelectorAll('.retry-checkbox:checked');
    for (var i = 0; i < cbs.length; i++) selected.push(cbs[i].value);
    if (!selected.length) {
        showToast('请至少选择一个脚本', 'warning');
        return;
    }
    var mode = document.getElementById('batchExecMode2').value;
    var retryCount = parseInt(document.getElementById('retryCount').value) || 0;
    var retryDelay = parseInt(document.getElementById('retryDelay').value) || 5;
    showToast('正在执行（重试' + retryCount + '次）...', 'info');
    var body = {
        scripts: selected,
        mode: mode,
        retry_count: retryCount,
        retry_delay: retryDelay
    };
    if (currentTargetUser) body.target_user = currentTargetUser;
    apiPost('/api/scripts/batch-execute', body).then(function(result) {
        var html = '<strong>执行结果:</strong><br>';
        for (var i = 0; i < result.results.length; i++) {
            var r = result.results[i];
            html += '<div>' + escapeHtml(r.name) + ': ' + (r.success ? '✅成功' : '❌失败') +
                ' (尝试' + (r.attempts || 1) + '次)</div>';
            if (r.stderr) html += '<div style="color:var(--error);font-size:11px">' +
                escapeHtml(r.stderr.substring(0, 200)) + '</div>';
        }
        document.getElementById('retryExecResult').innerHTML = html;
        showToast('✅ 执行完成', 'success');
        setTimeout(function() { loadContainers(false, 'ros2_'); }, 2000);
        // 通知引导系统车辆已启动
        var hasSuccess = result.results.some(function(r) { return r.success; });
        if (hasSuccess && typeof Onboarding !== 'undefined' && Onboarding.notifyExecuteStarted) {
            setTimeout(function() { Onboarding.notifyExecuteStarted(); }, 2500);
        }
    });
}

// ========== 预留扩展区域（第1101-1150行） ==========
// 预留用于未来扩展，如脚本调度、定时任务等
// ===========================================

// ============================================================
// 24. 高级功能 - 监控面板增强
// ============================================================

/**
 * 处理 loadGpuDetail 相关前端逻辑。
 */
function loadGpuDetail() {
    apiGet('/api/system/monitor/gpu-detail').then(function(d) {
        if (!d.success) {
            document.getElementById('gpuDetailContainer').innerHTML = '<p style="color:var(--error)">' + escapeHtml(d.error || '加载失败') + '</p>';
            return;
        }
        var html = '';
        if (d.gpu && d.gpu.length) {
            for (var i = 0; i < d.gpu.length; i++) {
                var g = d.gpu[i];
                html += '<div class="card" style="margin-bottom:12px"><div class="card-title">GPU ' + g.index + ': ' + escapeHtml(g.name) + '</div>';
                html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:13px">';
                html += '<div>利用率: <strong>' + g.utilization + '%</strong></div>';
                html += '<div>显存: <strong>' + g.mem_used + ' / ' + g.mem_total + ' MiB</strong></div>';
                html += '<div>显存带宽使用: <strong>' + g.mem_bw_percent + '%</strong></div>';
                html += '<div>温度: <strong>' + g.temperature + '°C</strong></div>';
                html += '<div>功耗: <strong>' + g.power_draw + 'W / ' + g.power_limit + 'W</strong></div>';
                html += '<div>SM时钟: <strong>' + g.sm_clock + ' MHz</strong></div>';
                html += '<div>Mem时钟: <strong>' + g.mem_clock + ' MHz</strong></div>';
                if (g.pcie && g.pcie.current_gen) {
                    html += '<div>PCIe: <strong>Gen' + g.pcie.current_gen + ' x' + g.pcie.current_width + ' (最大 Gen' + g.pcie.max_gen + ' x' + g.pcie.max_width + ')</strong></div>';
                }
                html += '</div></div>';
            }
        } else {
            html = '<p style="opacity:0.5">无 GPU 或 nvidia-smi 不可用</p>';
        }
        document.getElementById('gpuDetailContainer').innerHTML = html;
        var pbody = document.getElementById('gpuPmonTableBody');
        var pHtml = '';
        if (d.pmon && d.pmon.length) {
            for (var j = 0; j < d.pmon.length; j++) {
                var p = d.pmon[j];
                pHtml += '<tr><td>' + p.gpu + '</td><td>' + p.pid + '</td><td>' + p.type + '</td><td>' + p.sm + '</td><td>' + p.mem + '</td></tr>';
            }
        } else {
            pHtml = '<tr><td colspan="5" style="text-align:center;opacity:0.5">无 GPU 进程数据</td></tr>';
        }
        pbody.innerHTML = pHtml;
    });
}

/**
 * 处理 toggleGpuAutoRefresh 相关前端逻辑。
 */
function toggleGpuAutoRefresh() {
    gpuAutoRefresh = !gpuAutoRefresh;
    var btn = document.getElementById('gpuAutoRefreshBtn');
    if (gpuAutoRefresh) {
        btn.textContent = '⏸ 停止刷新';
        loadGpuDetail();
        gpuRefreshTimer = setInterval(loadGpuDetail, 3000);
    } else {
        btn.textContent = '⏯ 自动刷新';
        if (gpuRefreshTimer) { clearInterval(gpuRefreshTimer); gpuRefreshTimer = null; }
    }
}

// ========== 预留扩展区域（第1151-1200行） ==========
// 预留用于未来扩展，如更多GPU监控指标等
// ===========================================

// ============================================================
// 25. 高级功能 - 系统自检
// ============================================================

/**
 * 处理 runSystemCheck 相关前端逻辑。
 */
function runSystemCheck() {
    document.getElementById('systemCheckResult').innerHTML = '<span class="loading"></span> 检查中...';
    apiGet('/api/system/check').then(function(d) {
        if (!d.success) { document.getElementById('systemCheckResult').innerHTML = '<p style="color:var(--error)">检查失败</p>'; return; }
        var html = '<div style="margin-bottom:8px">总体状态: <strong style="color:' + (d.all_ok ? 'var(--success)' : 'var(--error)') + '">' + (d.all_ok ? '✅ 全部正常' : '❌ 存在问题') + '</strong></div>';
        for (var i = 0; i < d.checks.length; i++) {
            var c = d.checks[i];
            var icon = c.ok ? '✅' : '❌';
            var fixBtn = c.fixable && !c.ok ? ' <button class="btn btn-sm btn-warning" onclick="fixCheckItem(\'' + escapeHtml(c.name) + '\')">🔧 修复</button>' : '';
            html += '<div style="padding:4px 0;border-bottom:1px solid var(--border-color)">' + icon + ' ' + escapeHtml(c.name) + ': ' + (c.path || '') + ' ' + (c.detail ? JSON.stringify(c.detail) : '') + fixBtn + '</div>';
        }
        document.getElementById('systemCheckResult').innerHTML = html;
    });
}

/**
 * 处理 fixCheckItem 相关前端逻辑。
 */
function fixCheckItem(item) {
    apiPost('/api/system/check/fix', { item: item }).then(function(d) {
        showToast(d.message || '', d.success ? 'success' : 'error');
        if (d.success) runSystemCheck();
    });
}

// ========== 预留扩展区域（第1201-1250行） ==========
// 预留用于未来扩展，如自动修复增强等
// ===========================================

// ========== 预留扩展区域（第1251-1300行） ==========
// 预留用于未来扩展，如配置集导入导出等
// ===========================================

// ============================================================
// 27. 高级功能 - 拓展功能
// ============================================================

/**
 * 处理 addRemoteHost 相关前端逻辑。
 */
function addRemoteHost() {
    var name = document.getElementById('remoteName').value.trim();
    var host = document.getElementById('remoteHost').value.trim();
    var port = document.getElementById('remotePort').value.trim();
    var user = document.getElementById('remoteUser').value.trim();
    if (!name || !host) { showToast('请填写名称和主机', 'warning'); return; }
    apiPost('/api/system/remote-hosts', { name: name, host: host, port: port, user: user }).then(function(d) {
        showToast(d.message || '', d.success ? 'success' : 'error');
        if (d.success) loadRemoteHosts();
    });
}

/**
 * 处理 loadRemoteHosts 相关前端逻辑。
 */
function loadRemoteHosts() {
    apiGet('/api/system/remote-hosts').then(function(d) {
        if (!d.success) return;
        var hosts = d.hosts || [];
        var html = '';
        if (!hosts.length) {
            html = '<p style="opacity:0.5">暂无远程主机</p>';
        } else {
            for (var i = 0; i < hosts.length; i++) {
                var h = hosts[i];
                html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:6px;border-bottom:1px solid var(--border-color)">';
                html += '<span><strong>' + escapeHtml(h.name) + '</strong> - ' + escapeHtml(h.user) + '@' + escapeHtml(h.host) + ':' + escapeHtml(h.port) + '</span>';
                html += '<div style="display:flex;gap:4px"><button class="btn btn-sm btn-outline" onclick="testRemoteHost(\'' + escapeHtml(h.name) + '\')">🧪 测试</button><button class="btn btn-sm btn-error" onclick="removeRemoteHost(\'' + escapeHtml(h.name) + '\')">🗑</button></div>';
                html += '</div>';
            }
        }
        document.getElementById('remoteHostsList').innerHTML = html;
    });
}

/**
 * 处理 testRemoteHost 相关前端逻辑。
 */
function testRemoteHost(name) {
    apiPost('/api/system/remote-hosts/' + encodeURIComponent(name) + '/test').then(function(d) {
        showToast(d.success ? '✅ 连接成功' : '❌ 连接失败: ' + (d.stderr || ''), d.success ? 'success' : 'error');
    });
}

/**
 * 处理 removeRemoteHost 相关前端逻辑。
 */
function removeRemoteHost(name) {
    customConfirm('确定删除主机 ' + name + '？', function() {
        apiDelete('/api/system/remote-hosts/' + encodeURIComponent(name)).then(function(d) {
            showToast(d.message || '', d.success ? 'success' : 'error');
            if (d.success) loadRemoteHosts();
        });
    });
}

/**
 * 处理 createPlugin 相关前端逻辑。
 */
function createPlugin() {
    var name = document.getElementById('pluginName').value.trim();
    var code = document.getElementById('pluginCode').value.trim();
    if (!name) { showToast('请输入插件名称', 'warning'); return; }
    apiPost('/api/system/plugins', { name: name, code: code }).then(function(d) {
        showToast(d.message || '', d.success ? 'success' : 'error');
        if (d.success) loadPlugins();
    });
}

/**
 * 处理 loadPlugins 相关前端逻辑。
 */
function loadPlugins() {
    apiGet('/api/system/plugins').then(function(d) {
        if (!d.success) return;
        var plugins = d.plugins || [];
        var html = '';
        if (!plugins.length) {
            html = '<p style="opacity:0.5">暂无插件（插件目录: ' + escapeHtml(d.plugins_dir || '') + '）</p>';
        } else {
            for (var i = 0; i < plugins.length; i++) {
                var p = plugins[i];
                html += '<div style="display:flex;align-items:center;justify-content:space-between;padding:6px;border-bottom:1px solid var(--border-color)">';
                html += '<span><strong>' + escapeHtml(p.name) + '</strong> - ' + escapeHtml(p.description) + '</span>';
                html += '<div style="display:flex;gap:4px"><button class="btn btn-sm btn-success" onclick="executePlugin(\'' + escapeHtml(p.name) + '\')">▶ 执行</button><button class="btn btn-sm btn-error" onclick="deletePlugin(\'' + escapeHtml(p.name) + '\')">🗑</button></div>';
                html += '</div>';
            }
        }
        document.getElementById('pluginsList').innerHTML = html;
    });
}

/**
 * 处理 executePlugin 相关前端逻辑。
 */
function executePlugin(name) {
    apiPost('/api/system/plugins/' + encodeURIComponent(name) + '/execute').then(function(d) {
        showToast(d.success ? '执行结果: ' + (d.result || '') : '失败: ' + (d.error || ''), d.success ? 'success' : 'error');
    });
}

/**
 * 处理 deletePlugin 相关前端逻辑。
 */
function deletePlugin(name) {
    customConfirm('确定删除插件 ' + name + '？', function() {
        apiDelete('/api/system/plugins/' + encodeURIComponent(name)).then(function(d) {
            showToast(d.message || '', d.success ? 'success' : 'error');
            if (d.success) loadPlugins();
        });
    });
}

// ===== 辅助测试工具（mock_tools.py 集成） =====

/**
 * 加载辅助测试工具信息并渲染工具卡片网格。
 */
function loadMockToolsInfo() {
    apiGet('/api/system/mock-tools/info').then(function(d) {
        if (!d.success) return;
        var statusEl = document.getElementById('mockToolsStatus');
        if (statusEl) {
            statusEl.textContent = d.exists ? '✅ 文件就绪' : '❌ 文件不存在';
            statusEl.style.opacity = d.exists ? '0.6' : '1';
            statusEl.style.color = d.exists ? '' : '#e74c3c';
        }
        var tools = d.tools || [];
        var html = '';
        for (var i = 0; i < tools.length; i++) {
            var t = tools[i];
            html += '<div style="border:1px solid #e1e4e8;border-radius:8px;padding:10px;cursor:default;background:#fff">';
            html += '<div style="height:3px;background:' + (t.color || '#ccc') + ';border-radius:2px;margin-bottom:8px"></div>';
            html += '<div style="font-size:18px;margin-bottom:4px">' + (t.icon || '📦') + '</div>';
            html += '<div style="font-size:12px;font-weight:bold;color:#2c3e50;margin-bottom:2px">' + escapeHtml(t.name) + '</div>';
            html += '<div style="font-size:10px;color:#95a5a6">' + escapeHtml(t.desc) + '</div>';
            html += '</div>';
        }
        var grid = document.getElementById('mockToolsGrid');
        if (grid) grid.innerHTML = html;
    });
}

/**
 * 启动辅助测试工具桌面应用。
 */
function launchMockTools() {
    apiPost('/api/system/mock-tools/launch').then(function(d) {
        showToast(d.message || '', d.success ? 'success' : 'error');
    });
}

function getApiBaseUrl() {
    var port = parseInt(document.getElementById('apiPort').value) || 8875;
    var protocol = window.location.protocol;
    var hostname = window.location.hostname;
    return protocol + '//' + hostname + ':' + port;
}

function updateApiUrlDisplay() {
    var url = getApiBaseUrl();
    document.getElementById('apiBaseUrl').textContent = url;
    return url;
}

function updateApiStatus(isEnabled, isConnected) {
    var badge = document.getElementById('apiStatusBadge');
    var docsBtn = document.getElementById('openDocsBtn');
    var redocBtn = document.getElementById('openRedocBtn');

    if (!isEnabled) {
        badge.textContent = '🔴 已禁用';
        badge.style.background = '#fee2e2';
        badge.style.color = '#dc2626';
        docsBtn.disabled = true;
        redocBtn.disabled = true;
    } else if (isConnected) {
        badge.textContent = '🟢 运行中';
        badge.style.background = '#dcfce7';
        badge.style.color = '#16a34a';
        docsBtn.disabled = false;
        redocBtn.disabled = false;
    } else {
        badge.textContent = '🟡 配置中';
        badge.style.background = '#fef3c7';
        badge.style.color = '#d97706';
        docsBtn.disabled = false;
        redocBtn.disabled = false;
    }
}

/**
 * 处理 loadApiSettings 相关前端逻辑。
 */
function loadApiSettings() {
    updateApiUrlDisplay();
    document.getElementById('apiPort').addEventListener('input', updateApiUrlDisplay);

    apiGet('/api/system/api-settings').then(function(d) {
        if (!d.success || !d.settings) return;
        document.getElementById('apiPort').value = d.settings.api_port || '8875';
        document.getElementById('apiToken').value = d.settings.auth_token || '';
        document.getElementById('apiEnabled').checked = d.settings.api_enabled !== false;
        document.getElementById('apiAuthRequired').checked = d.settings.auth_required === true;
        updateApiUrlDisplay();
        updateApiStatus(d.settings.api_enabled !== false, true);
    }).catch(function() {
        updateApiStatus(true, false);
    });
}

/**
 * 处理 saveApiSettings 相关前端逻辑。
 */
function saveApiSettings() {
    if (window.userRole !== 'admin') {
        showToast('只有管理员可以修改 API 设置', 'warning');
        return;
    }
    var body = {
        api_port: parseInt(document.getElementById('apiPort').value) || 8875,
        auth_token: document.getElementById('apiToken').value.trim(),
        api_enabled: document.getElementById('apiEnabled').checked,
        auth_required: document.getElementById('apiAuthRequired').checked
    };
    apiPost('/api/system/api-settings', body).then(function(d) {
        document.getElementById('apiSettingsStatus').textContent = d.success ? '✅ 已保存' : '❌ ' + (d.error || '');
        showToast(d.message || (d.success ? 'API 设置已保存' : '保存失败'), d.success ? 'success' : 'error');
        if (d.success) {
            updateApiStatus(body.api_enabled, true);
            updateApiUrlDisplay();
        }
        setTimeout(function() { document.getElementById('apiSettingsStatus').textContent = ''; }, 3000);
    });
}

function openApiDocs() {
    var baseUrl = getApiBaseUrl();
    window.open(baseUrl + '/api/docs', '_blank');
}

function openApiRedoc() {
    var baseUrl = getApiBaseUrl();
    window.open(baseUrl + '/api/redoc', '_blank');
}

function copyApiUrl() {
    var url = getApiBaseUrl();
    navigator.clipboard.writeText(url).then(function() {
        showToast('API 地址已复制到剪贴板', 'success');
    }).catch(function() {
        var textArea = document.createElement('textarea');
        textArea.value = url;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showToast('API 地址已复制', 'success');
    });
}

function testApiConnection() {
    var resultDiv = document.getElementById('apiTestResult');
    var baseUrl = getApiBaseUrl();
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<span style="color:var(--text-muted)">⏳ 正在测试连接...</span>';

    var testUrl = baseUrl + '/openapi.json';
    var startTime = Date.now();

    fetch(testUrl, { method: 'GET', mode: 'cors' })
        .then(function(response) {
            var elapsed = Date.now() - startTime;
            if (response.ok) {
                return response.json().then(function(data) {
                    resultDiv.innerHTML = '<div style="color:#16a34a;">✅ API 连接成功！</div>' +
                        '<div style="margin-top:4px;opacity:0.8;">响应时间: ' + elapsed + 'ms</div>' +
                        '<div style="opacity:0.8;">API 标题: ' + (data.info ? data.info.title : 'Unknown') + '</div>' +
                        '<div style="opacity:0.8;">版本: ' + (data.info ? data.info.version : 'Unknown') + '</div>' +
                        '<div style="opacity:0.8;">接口数量: ' + (data.paths ? Object.keys(data.paths).length : 0) + ' 个</div>';
                    updateApiStatus(true, true);
                });
            } else {
                resultDiv.innerHTML = '<div style="color:#dc2626;">❌ 连接失败 (HTTP ' + response.status + ')</div>' +
                    '<div style="margin-top:4px;opacity:0.8;">请检查 API 服务是否在端口 ' + (parseInt(document.getElementById('apiPort').value) || 8875) + ' 上运行</div>';
                updateApiStatus(document.getElementById('apiEnabled').checked, false);
            }
        })
        .catch(function(err) {
            var elapsed = Date.now() - startTime;
            resultDiv.innerHTML = '<div style="color:#dc2626;">❌ 无法连接到 API 服务</div>' +
                '<div style="margin-top:4px;opacity:0.8;">错误: ' + err.message + '</div>' +
                '<div style="opacity:0.8;">请确认 API 服务已启动且端口 ' + (parseInt(document.getElementById('apiPort').value) || 8875) + ' 可访问</div>';
            updateApiStatus(document.getElementById('apiEnabled').checked, false);
        });
}

// ============================================================
// 独立面板 REST API 管理函数
// ============================================================

function getApiMgrBaseUrl() {
    var port = parseInt(document.getElementById('apiMgrPort').value) || 8875;
    var protocol = window.location.protocol;
    var hostname = window.location.hostname;
    return protocol + '//' + hostname + ':' + port;
}

function updateApiMgrUrlDisplay() {
    var url = getApiMgrBaseUrl();
    document.getElementById('apiMgrBaseUrl').textContent = url;
    document.getElementById('apiMgrPortText').textContent = '端口: ' + (parseInt(document.getElementById('apiMgrPort').value) || 8875);
    return url;
}

function updateApiMgrStatus(isEnabled, isConnected, apiInfo) {
    var badge = document.getElementById('apiMgrStatusBadge');
    var icon = document.getElementById('apiMgrIcon');
    var stateText = document.getElementById('apiMgrStateText');
    var docsBtn = document.getElementById('apiMgrOpenDocsBtn');
    var redocBtn = document.getElementById('apiMgrOpenRedocBtn');

    if (!isEnabled) {
        if (badge) {
            badge.textContent = '🔴 已禁用';
            badge.style.background = '#fee2e2';
            badge.style.color = '#dc2626';
        }
        if (icon) icon.textContent = '🔴';
        if (stateText) stateText.textContent = 'API 服务已禁用';
        if (docsBtn) docsBtn.disabled = true;
        if (redocBtn) redocBtn.disabled = true;
    } else if (isConnected) {
        if (badge) {
            badge.textContent = '🟢 运行中';
            badge.style.background = '#dcfce7';
            badge.style.color = '#16a34a';
        }
        if (icon) icon.textContent = '🟢';
        if (stateText) stateText.textContent = 'API 服务运行正常';
        if (docsBtn) docsBtn.disabled = false;
        if (redocBtn) redocBtn.disabled = false;
    } else {
        if (badge) {
            badge.textContent = '🟡 待连接';
            badge.style.background = '#fef3c7';
            badge.style.color = '#d97706';
        }
        if (icon) icon.textContent = '🟡';
        if (stateText) stateText.textContent = '配置完成，可尝试打开文档';
        if (docsBtn) docsBtn.disabled = false;
        if (redocBtn) redocBtn.disabled = false;
    }
}

function loadApiMgrSettings() {
    updateApiMgrUrlDisplay();
    document.getElementById('apiMgrPort').addEventListener('input', updateApiMgrUrlDisplay);

    apiGet('/api/system/api-settings').then(function(d) {
        if (!d.success || !d.settings) return;
        document.getElementById('apiMgrPort').value = d.settings.api_port || '8875';
        document.getElementById('apiMgrToken').value = d.settings.auth_token || '';
        document.getElementById('apiMgrEnabled').checked = d.settings.api_enabled !== false;
        document.getElementById('apiMgrAuthRequired').checked = d.settings.auth_required === true;
        updateApiMgrUrlDisplay();
        updateApiMgrStatus(d.settings.api_enabled !== false, true);
        testApiMgrConnection(true);
    }).catch(function() {
        updateApiMgrStatus(true, false);
    });
}

function saveApiMgrSettings() {
    if (window.userRole !== 'admin') {
        showToast('只有管理员可以修改 API 设置', 'warning');
        return;
    }
    var body = {
        api_port: parseInt(document.getElementById('apiMgrPort').value) || 8875,
        auth_token: document.getElementById('apiMgrToken').value.trim(),
        api_enabled: document.getElementById('apiMgrEnabled').checked,
        auth_required: document.getElementById('apiMgrAuthRequired').checked
    };
    apiPost('/api/system/api-settings', body).then(function(d) {
        var statusEl = document.getElementById('apiMgrSaveStatus');
        statusEl.textContent = d.success ? '✅ 已保存' : '❌ ' + (d.error || '');
        statusEl.style.color = d.success ? '#16a34a' : '#dc2626';
        showToast(d.message || (d.success ? 'API 设置已保存' : '保存失败'), d.success ? 'success' : 'error');
        if (d.success) {
            updateApiMgrStatus(body.api_enabled, true);
            updateApiMgrUrlDisplay();
        }
        setTimeout(function() { statusEl.textContent = ''; }, 3000);
    });
}

function openApiMgrDocs() {
    var port = parseInt(document.getElementById('apiMgrPort').value) || 8875;
    var currentPort = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
    var docsUrl;
    if (String(port) === String(currentPort)) {
        docsUrl = '/api/docs';
    } else {
        docsUrl = getApiMgrBaseUrl() + '/api/docs';
    }
    window.open(docsUrl, '_blank');
}

function openApiMgrRedoc() {
    var port = parseInt(document.getElementById('apiMgrPort').value) || 8875;
    var currentPort = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
    var redocUrl;
    if (String(port) === String(currentPort)) {
        redocUrl = '/api/redoc';
    } else {
        redocUrl = getApiMgrBaseUrl() + '/api/redoc';
    }
    window.open(redocUrl, '_blank');
}

function copyApiMgrUrl() {
    var url = getApiMgrBaseUrl();
    navigator.clipboard.writeText(url).then(function() {
        showToast('API 地址已复制到剪贴板', 'success');
    }).catch(function() {
        var textArea = document.createElement('textarea');
        textArea.value = url;
        document.body.appendChild(textArea);
        textArea.select();
        document.execCommand('copy');
        document.body.removeChild(textArea);
        showToast('API 地址已复制', 'success');
    });
}

function testApiMgrConnection(silent) {
    var resultDiv = document.getElementById('apiMgrTestResult');
    var port = parseInt(document.getElementById('apiMgrPort').value) || 8875;
    var currentPort = window.location.port || (window.location.protocol === 'https:' ? '443' : '80');
    
    // 如果配置的端口和当前访问端口相同，直接使用相对路径（同源）
    var testUrl;
    if (String(port) === String(currentPort)) {
        testUrl = '/openapi.json';
    } else {
        var protocol = window.location.protocol;
        var hostname = window.location.hostname;
        testUrl = protocol + '//' + hostname + ':' + port + '/openapi.json';
    }
    
    if (!silent) {
        resultDiv.style.display = 'block';
        resultDiv.innerHTML = '<span style="color:var(--text-muted)">⏳ 正在测试连接...</span>';
    }

    var startTime = Date.now();

    // 同源请求不需要 cors 模式
    var fetchOptions = { method: 'GET' };
    if (String(port) !== String(currentPort)) {
        fetchOptions.mode = 'cors';
    }

    fetch(testUrl, fetchOptions)
        .then(function(response) {
            var elapsed = Date.now() - startTime;
            if (response.ok) {
                return response.json().then(function(data) {
                    var endpointCount = data.paths ? Object.keys(data.paths).length : 0;
                    if (!silent) {
                        resultDiv.innerHTML = '<div style="color:#16a34a;font-weight:500;">✅ API 连接成功！</div>' +
                            '<div style="margin-top:6px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;">' +
                            '<div>响应时间: <strong>' + elapsed + 'ms</strong></div>' +
                            '<div>API 名称: <strong>' + (data.info ? data.info.title : 'Unknown') + '</strong></div>' +
                            '<div>版本: <strong>' + (data.info ? data.info.version : 'Unknown') + '</strong></div>' +
                            '<div>接口数量: <strong>' + endpointCount + ' 个</strong></div>' +
                            '</div>';
                    }
                    updateApiMgrStatus(true, true);
                });
            } else {
                if (!silent) {
                    resultDiv.innerHTML = '<div style="color:#dc2626;font-weight:500;">❌ 连接失败 (HTTP ' + response.status + ')</div>' +
                        '<div style="margin-top:6px;opacity:0.8;">请检查 API 服务是否在端口 ' + port + ' 上运行</div>';
                }
                updateApiMgrStatus(document.getElementById('apiMgrEnabled').checked, false);
            }
        })
        .catch(function(err) {
            if (!silent) {
                resultDiv.innerHTML = '<div style="color:#dc2626;font-weight:500;">❌ 无法连接到 API 服务</div>' +
                    '<div style="margin-top:6px;opacity:0.8;">错误: ' + err.message + '</div>' +
                    '<div style="opacity:0.8;">提示: FastAPI 默认自带 Swagger 文档，服务启动后即可访问 /api/docs</div>';
            }
            updateApiMgrStatus(document.getElementById('apiMgrEnabled').checked, false);
        });
}

// ========== 预留扩展区域（第1301-1350行） ==========
// 预留用于未来扩展，如更多API管理功能等
// ===========================================

// ============================================================
// 28. 高级功能 - 全局增强
// ============================================================

/**
 * 处理 clearGlobalErrors 相关前端逻辑。
 */
function clearGlobalErrors() {
    document.getElementById('globalErrorLog').innerHTML = '<div style="opacity:0.5">暂无错误...</div>';
}

/**
 * 处理 testGlobalError 相关前端逻辑。
 */
function testGlobalError() {
    showToast('这是一条测试错误提示', 'error');
    var container = document.getElementById('globalErrorLog');
    if (container.children.length === 1 && container.children[0].textContent === '暂无错误...') {
        container.innerHTML = '';
    }
    var entry = document.createElement('div');
    entry.className = 'log-entry';
    entry.innerHTML = '<span class="time">[' + new Date().toLocaleTimeString() + ']</span><span class="type" style="color:var(--error)">[ERROR]</span>测试错误 - 全局错误弹窗功能正常';
    container.appendChild(entry);
}

/**
 * 处理 loadResourceLeaks 相关前端逻辑。
 */
function loadResourceLeaks() {
    apiGet('/api/system/resource-leaks').then(function(d) {
        if (!d.success) return;
        var html = '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;font-size:13px">';
        html += '<div>活跃线程: <strong>' + d.active_threads + '</strong></div>';
        html += '<div>WebSocket 连接: <strong>' + d.websocket_clients + '</strong></div>';
        html += '<div>CPU: <strong>' + d.cpu_percent + '%</strong></div>';
        html += '<div>内存 RSS: <strong>' + d.memory_rss_mb + ' MB</strong></div>';
        html += '<div>内存 VMS: <strong>' + d.memory_vms_mb + ' MB</strong></div>';
        html += '<div>打开文件: <strong>' + d.open_files_count + '</strong></div>';
        html += '</div>';
        document.getElementById('resourceLeaksData').innerHTML = html;
    });
}

/**
 * 处理 checkSudo 相关前端逻辑。
 */
function checkSudo() {
    apiGet('/api/system/sudo-check').then(function(d) {
        if (!d.success) return;
        var html = '<div style="font-size:13px">';
        html += '<div>免密 sudo: <strong style="color:' + (d.no_password_sudo ? 'var(--success)' : 'var(--error)') + '">' + (d.no_password_sudo ? '✅ 已配置' : '❌ 未配置') + '</strong></div>';
        html += '<div>Docker 组成员: <strong>' + (d.in_docker_group ? '✅ 是' : '❌ 否') + '</strong></div>';
        if (d.fix_guide) html += '<div style="margin-top:8px;padding:8px;background:var(--accent-light);border-radius:var(--radius);font-family:monospace;font-size:11px;white-space:pre-wrap">' + escapeHtml(d.fix_guide) + '</div>';
        html += '</div>';
        document.getElementById('sudoCheckResult').innerHTML = html;
    });
}

/**
 * 处理 loadAuthStatus 相关前端逻辑。
 */
function loadAuthStatus() {
    apiGet('/api/system/auth/status').then(function(d) {
        if (d.success) {
            document.getElementById('authStatus').innerHTML = d.exists ? '<span style="color:var(--success)">✅ 已加密存储 (方法: ' + (d.method || 'unknown') + ')</span>' : '<span style="opacity:0.5">未保存认证信息</span>';
        }
    });
}

/**
 * 处理 saveAuthSecure 相关前端逻辑。
 */
function saveAuthSecure() {
    var username = document.getElementById('authUsername').value.trim();
    var password = document.getElementById('authPassword').value.trim();
    var token = document.getElementById('authToken').value.trim();
    if (!username) { showToast('请输入用户名', 'warning'); return; }
    apiPost('/api/system/auth/save', { username: username, password: password, token: token }).then(function(d) {
        showToast(d.message || '', d.success ? 'success' : 'error');
        if (d.success) loadAuthStatus();
    });
}

// ========== 预留扩展区域（第1351-1400行） ==========
// 预留用于未来扩展，如更多全局增强功能等
// ===========================================

// ============================================================
// 29. 高级功能 - 故障注入
// ============================================================

/**
 * 处理 loadFaultContainers 相关前端逻辑。
 */
function loadFaultContainers() {
    var allowedImages = ['ros2_humble_image:v2', 'ros2_humble_image:v1', 'robotruck20.04:latest'];
    
    apiGet('/api/docker/containers?all=false').then(function(d) {
        var sel = document.getElementById('faultContainer');
        if (!d.success || !d.containers) {
            sel.innerHTML = '<option value="">-- 无运行中的 ROS2 容器 --</option>';
            return;
        }
        
        var filteredContainers = d.containers.filter(function(c) {
            if (!c.image) return false;
            for (var i = 0; i < allowedImages.length; i++) {
                if (c.image.indexOf(allowedImages[i]) !== -1) {
                    return true;
                }
            }
            return false;
        });
        
        var html = '<option value="">-- 选择运行中的 ROS2 容器 --</option>';
        for (var i = 0; i < filteredContainers.length; i++) {
            html += '<option value="' + filteredContainers[i].id + '" data-name="' + escapeHtml(filteredContainers[i].name) + '">' + escapeHtml(filteredContainers[i].name) + ' (' + escapeHtml(filteredContainers[i].image) + ')</option>';
        }
        if (filteredContainers.length === 0) {
            html = '<option value="">-- 无运行中的仿真车容器 --</option>';
        }
        sel.innerHTML = html;
        
        // 容器列表加载完成后，如果只有一个容器，自动选中并加载话题
        if (filteredContainers.length === 1) {
            sel.value = filteredContainers[0].id;
            loadFaultContainerTopics(filteredContainers[0].id);
            updateFaultInjectBtn();
            clearFaultHistoryDisplay();
        }
    });
}

/**
 * 处理 onFaultContainerChange 相关前端逻辑。
 */
function onFaultContainerChange() {
    var containerId = document.getElementById('faultContainer').value;
    updateFaultInjectBtn();
    loadFaultContainerTopics(containerId);
    clearFaultHistoryDisplay();
    document.getElementById('faultResult').innerHTML = '';
}

/**
 * 加载选中容器的话题/节点/服务列表
 */
var faultContainerTopics = [];
var faultContainerNodes = [];
var faultContainerServices = [];
function loadFaultContainerResources(containerId) {
    faultContainerTopics = [];
    faultContainerNodes = [];
    faultContainerServices = [];
    if (!containerId) return;
    
    // 更新话题下拉
    var topicSelect = document.getElementById('faultParamTopic');
    if (topicSelect) {
        topicSelect.innerHTML = '<option value="">加载中...</option>';
    }
    // 更新节点下拉
    var nodeSelect = document.getElementById('faultParamNode');
    if (nodeSelect) {
        nodeSelect.innerHTML = '<option value="">加载中...</option>';
    }
    // 更新服务下拉
    var serviceSelect = document.getElementById('faultParamService');
    if (serviceSelect) {
        serviceSelect.innerHTML = '<option value="">加载中...</option>';
    }
    
    // 加载话题列表
    apiGet('/api/ros2/topics?container_id=' + encodeURIComponent(containerId)).then(function(d) {
        if (d.success && d.topics) {
            faultContainerTopics = d.topics;
            updateFaultTopicSelect();
        } else {
            faultContainerTopics = [];
            updateFaultTopicSelect();
        }
    }).catch(function() {
        faultContainerTopics = [];
        updateFaultTopicSelect();
    });
    
    // 加载节点列表
    apiGet('/api/ros2/nodes?container_id=' + encodeURIComponent(containerId)).then(function(d) {
        if (d.success && d.nodes) {
            faultContainerNodes = d.nodes;
            updateFaultNodeSelect();
        } else {
            faultContainerNodes = [];
            updateFaultNodeSelect();
        }
    }).catch(function() {
        faultContainerNodes = [];
        updateFaultNodeSelect();
    });
    
    // 加载服务列表
    apiGet('/api/ros2/services?container_id=' + encodeURIComponent(containerId)).then(function(d) {
        if (d.success && d.services) {
            faultContainerServices = d.services;
            updateFaultServiceSelect();
        } else {
            faultContainerServices = [];
            updateFaultServiceSelect();
        }
    }).catch(function() {
        faultContainerServices = [];
        updateFaultServiceSelect();
    });
}

// 为兼容旧代码保留别名
function loadFaultContainerTopics(containerId) {
    loadFaultContainerResources(containerId);
}

/**
 * 更新话题下拉选择框
 */
function updateFaultTopicSelect() {
    var topicSelect = document.getElementById('faultParamTopic');
    if (!topicSelect) return;
    
    var currentVal = topicSelect.value || '/cmd_vel';
    if (currentVal === '__custom__') {
        var customInput = document.getElementById('faultParamTopicCustom');
        if (customInput && customInput.value) currentVal = customInput.value;
    }
    var html = '';
    
    // 添加常用话题
    var commonTopics = ['/cmd_vel', '/scan', '/odom', '/image_raw', '/imu/data'];
    for (var i = 0; i < commonTopics.length; i++) {
        var selected = commonTopics[i] === currentVal ? ' selected' : '';
        html += '<option value="' + commonTopics[i] + '"' + selected + '>' + commonTopics[i] + '</option>';
    }
    
    // 添加分隔线和容器中检测到的话题
    if (faultContainerTopics.length > 0) {
        html += '<option disabled>── 容器内话题 ──</option>';
        for (var j = 0; j < faultContainerTopics.length; j++) {
            var topic = faultContainerTopics[j];
            if (commonTopics.indexOf(topic) === -1) {
                var sel = topic === currentVal ? ' selected' : '';
                html += '<option value="' + escapeHtml(topic) + '"' + sel + '>' + escapeHtml(topic) + '</option>';
            }
        }
    }
    
    html += '<option value="__custom__">✎ 手动输入...</option>';
    topicSelect.innerHTML = html;
    
    // 如果当前值不在列表中，切换到自定义输入
    var customInput = document.getElementById('faultParamTopicCustom');
    if (customInput) {
        if (topicSelect.value === '__custom__') {
            customInput.style.display = 'block';
        } else {
            customInput.style.display = 'none';
            customInput.value = topicSelect.value;
        }
    }
}

/**
 * 更新节点下拉选择框
 */
function updateFaultNodeSelect() {
    var nodeSelect = document.getElementById('faultParamNode');
    if (!nodeSelect) return;
    
    var currentVal = nodeSelect.value || '';
    if (currentVal === '__custom__') {
        var customInput = document.getElementById('faultParamNodeCustom');
        if (customInput && customInput.value) currentVal = customInput.value;
    }
    var html = '<option value="">-- 选择节点 --</option>';
    
    // 添加容器中检测到的节点
    for (var j = 0; j < faultContainerNodes.length; j++) {
        var node = faultContainerNodes[j];
        var sel = node === currentVal ? ' selected' : '';
        html += '<option value="' + escapeHtml(node) + '"' + sel + '>' + escapeHtml(node) + '</option>';
    }
    
    html += '<option value="__custom__">✎ 手动输入...</option>';
    nodeSelect.innerHTML = html;
    
    var customInput = document.getElementById('faultParamNodeCustom');
    if (customInput) {
        if (nodeSelect.value === '__custom__') {
            customInput.style.display = 'block';
        } else {
            customInput.style.display = 'none';
            customInput.value = nodeSelect.value;
        }
    }
}

/**
 * 更新服务下拉选择框
 */
function updateFaultServiceSelect() {
    var serviceSelect = document.getElementById('faultParamService');
    if (!serviceSelect) return;
    
    var currentVal = serviceSelect.value || '';
    if (currentVal === '__custom__') {
        var customInput = document.getElementById('faultParamServiceCustom');
        if (customInput && customInput.value) currentVal = customInput.value;
    }
    var html = '<option value="">-- 选择服务 --</option>';
    
    // 添加容器中检测到的服务
    for (var j = 0; j < faultContainerServices.length; j++) {
        var service = faultContainerServices[j];
        var sel = service === currentVal ? ' selected' : '';
        html += '<option value="' + escapeHtml(service) + '"' + sel + '>' + escapeHtml(service) + '</option>';
    }
    
    html += '<option value="__custom__">✎ 手动输入...</option>';
    serviceSelect.innerHTML = html;
    
    var customInput = document.getElementById('faultParamServiceCustom');
    if (customInput) {
        if (serviceSelect.value === '__custom__') {
            customInput.style.display = 'block';
        } else {
            customInput.style.display = 'none';
            customInput.value = serviceSelect.value;
        }
    }
}

/**
 * 切换话题输入为手动输入模式
 */
function onFaultTopicChange() {
    var select = document.getElementById('faultParamTopic');
    var customInput = document.getElementById('faultParamTopicCustom');
    if (!select || !customInput) return;
    
    if (select.value === '__custom__') {
        customInput.style.display = 'block';
        customInput.focus();
    } else {
        customInput.style.display = 'none';
        customInput.value = select.value;
    }
}

/**
 * 切换节点输入为手动输入模式
 */
function onFaultNodeChange() {
    var select = document.getElementById('faultParamNode');
    var customInput = document.getElementById('faultParamNodeCustom');
    if (!select || !customInput) return;
    
    if (select.value === '__custom__') {
        customInput.style.display = 'block';
        customInput.focus();
    } else {
        customInput.style.display = 'none';
        customInput.value = select.value;
    }
}

/**
 * 切换服务输入为手动输入模式
 */
function onFaultServiceChange() {
    var select = document.getElementById('faultParamService');
    var customInput = document.getElementById('faultParamServiceCustom');
    if (!select || !customInput) return;
    
    if (select.value === '__custom__') {
        customInput.style.display = 'block';
        customInput.focus();
    } else {
        customInput.style.display = 'none';
        customInput.value = select.value;
    }
}

/**
 * 获取故障注入的话题名
 */
function getFaultTopicValue() {
    var select = document.getElementById('faultParamTopic');
    var customInput = document.getElementById('faultParamTopicCustom');
    if (select && select.value === '__custom__' && customInput) {
        return customInput.value;
    }
    return select ? select.value : '';
}

/**
 * 获取故障注入的节点名
 */
function getFaultNodeValue() {
    var select = document.getElementById('faultParamNode');
    var customInput = document.getElementById('faultParamNodeCustom');
    if (select && select.value === '__custom__' && customInput) {
        return customInput.value;
    }
    return select ? select.value : '';
}

/**
 * 获取故障注入的服务名
 */
function getFaultServiceValue() {
    var select = document.getElementById('faultParamService');
    var customInput = document.getElementById('faultParamServiceCustom');
    if (select && select.value === '__custom__' && customInput) {
        return customInput.value;
    }
    return select ? select.value : '';
}

/**
 * 处理 selectFaultType 相关前端逻辑。
 */
function selectFaultType(type) {
    selectedFaultType = type;
    var cards = document.querySelectorAll('.fault-card');
    for (var i = 0; i < cards.length; i++) cards[i].classList.remove('active');
    var card = document.querySelector('.fault-card[data-fault="' + type + '"]');
    if (card) card.classList.add('active');

    var names = {
        topic_stop: '话题停止发布', topic_delay: '话题延迟',
        node_kill: '节点 Kill', service_timeout: '服务超时',
        cpu_stress: 'CPU 满载', memory_leak: '内存泄漏',
        network_loss: '网络丢包', gps_drift: 'GPS 漂移'
    };
    document.getElementById('faultTypeName').textContent = names[type] || type;
    document.getElementById('faultParams').style.display = 'block';

    var paramsHtml = '';
    if (type === 'topic_stop' || type === 'topic_delay' || type === 'gps_drift') {
        paramsHtml += '<div style="margin-bottom:4px">' +
                      '<label style="font-size:11px">话题名</label>' +
                      '<select id="faultParamTopic" style="width:100%" onchange="onFaultTopicChange()">' +
                      '<option value="/cmd_vel" selected>/cmd_vel</option>' +
                      '</select>' +
                      '<input type="text" id="faultParamTopicCustom" style="width:100%;margin-top:4px;display:none" placeholder="手动输入话题名，如 /my_topic">' +
                      '</div>';
    }
    if (type === 'topic_delay') {
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">延迟 (ms)</label><input type="number" id="faultParamDelay" value="1000" style="width:100%"></div>';
    }
    if (type === 'node_kill') {
        paramsHtml += '<div style="margin-bottom:4px">' +
                      '<label style="font-size:11px">节点名</label>' +
                      '<select id="faultParamNode" style="width:100%" onchange="onFaultNodeChange()">' +
                      '<option value="">-- 选择节点 --</option>' +
                      '</select>' +
                      '<input type="text" id="faultParamNodeCustom" style="width:100%;margin-top:4px;display:none" placeholder="手动输入节点名，如 /my_node">' +
                      '</div>';
    }
    if (type === 'service_timeout') {
        paramsHtml += '<div style="margin-bottom:4px">' +
                      '<label style="font-size:11px">服务名</label>' +
                      '<select id="faultParamService" style="width:100%" onchange="onFaultServiceChange()">' +
                      '<option value="">-- 选择服务 --</option>' +
                      '</select>' +
                      '<input type="text" id="faultParamServiceCustom" style="width:100%;margin-top:4px;display:none" placeholder="手动输入服务名，如 /my_service">' +
                      '</div>';
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">超时 (ms)</label><input type="number" id="faultParamTimeout" value="5000" style="width:100%"></div>';
    }
    if (type === 'cpu_stress') {
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">CPU 核心数</label><input type="number" id="faultParamCpuCount" value="1" min="1" style="width:100%"></div>';
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">持续时间 (秒)</label><input type="number" id="faultParamDuration" value="30" style="width:100%"></div>';
    }
    if (type === 'memory_leak') {
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">内存 (MB)</label><input type="number" id="faultParamMemMb" value="256" style="width:100%"></div>';
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">持续时间 (秒)</label><input type="number" id="faultParamDuration" value="30" style="width:100%"></div>';
    }
    if (type === 'network_loss') {
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">丢包率 (%)</label><input type="number" id="faultParamLossPct" value="10" min="0" max="100" style="width:100%"></div>';
    }
    if (type === 'gps_drift') {
        paramsHtml += '<div style="margin-bottom:4px"><label style="font-size:11px">漂移量 (米)</label><input type="number" id="faultParamDrift" value="5" step="0.1" style="width:100%"></div>';
    }
    document.getElementById('faultParamsContent').innerHTML = paramsHtml;
    
    // DOM 渲染完成后，如果已选中容器，加载话题/节点/服务列表
    var containerId = document.getElementById('faultContainer').value;
    if (containerId) {
        setTimeout(function() {
            loadFaultContainerResources(containerId);
        }, 100);
    }
    
    updateFaultInjectBtn();
}

/**
 * 处理 updateFaultInjectBtn 相关前端逻辑。
 */
function updateFaultInjectBtn() {
    var containerId = document.getElementById('faultContainer').value;
    document.getElementById('faultInjectBtn').disabled = !containerId || !selectedFaultType;
}

/**
 * 注入故障（仅管理员）
 */
function injectFault() {
    // ★★★ 检查是否为管理员 ★★★
    if (!hasPermission('advanced-fault')) {
        showToast('您没有故障注入的操作权限', 'warning');
        return;
    }

    var containerId = document.getElementById('faultContainer').value;
    if (!containerId || !selectedFaultType) {
        showToast('请选择容器和故障类型', 'warning');
        return;
    }

    var params = {};
    var topic = document.getElementById('faultParamTopic');
    if (topic) params.topic = getFaultTopicValue();
    var delay = document.getElementById('faultParamDelay');
    if (delay) params.delay_ms = parseInt(delay.value);
    var node = document.getElementById('faultParamNode');
    if (node) params.node = getFaultNodeValue();
    var service = document.getElementById('faultParamService');
    if (service) params.service = getFaultServiceValue();
    var timeout = document.getElementById('faultParamTimeout');
    if (timeout) params.timeout_ms = parseInt(timeout.value);
    var cpuCount = document.getElementById('faultParamCpuCount');
    if (cpuCount) params.cpu_count = parseInt(cpuCount.value);
    var duration = document.getElementById('faultParamDuration');
    if (duration) params.duration = parseInt(duration.value);
    var memMb = document.getElementById('faultParamMemMb');
    if (memMb) params.mem_mb = parseInt(memMb.value);
    var lossPct = document.getElementById('faultParamLossPct');
    if (lossPct) params.loss_pct = parseInt(lossPct.value);
    var drift = document.getElementById('faultParamDrift');
    if (drift) params.drift_m = parseFloat(drift.value);

    showToast('正在注入故障...', 'warning');
    apiPost('/api/fault/inject', {
        container_id: containerId,
        fault_type: selectedFaultType,
        params: params
    }).then(function(d) {
        var html = '<strong>注入结果:</strong><br>';
        if (d.faults) {
            for (var i = 0; i < d.faults.length; i++) {
                var f = d.faults[i];
                html += '<div>' + (f.ok ? '✅' : '❌') + ' ' + escapeHtml(f.type) + ': ' + escapeHtml(f.output || '') + '</div>';
            }
        }
        document.getElementById('faultResult').innerHTML = html;
        showToast(d.success ? '故障注入完成' : '失败: ' + (d.error || ''), d.success ? 'success' : 'error');
        loadFaultHistory();
    });
}

/**
 * 处理 clearFault 相关前端逻辑。
 */
function clearFault() {
    if (!hasPermission('advanced-fault')) {
        showToast('您没有故障注入的操作权限', 'warning');
        return;
    }
    var containerId = document.getElementById('faultContainer').value;
    if (!containerId) { showToast('请选择容器', 'warning'); return; }
    apiPost('/api/fault/clear', { container_id: containerId }).then(function(d) {
        showToast(d.success ? '已清除故障' : '清除失败', d.success ? 'success' : 'error');
        document.getElementById('faultResult').innerHTML = d.success ? '<span style="color:var(--success)">✅ 已清除所有故障</span>' : '';
    });
}

/**
 * 处理 loadFaultHistory 相关前端逻辑。
 */
function loadFaultHistory() {
    apiGet('/api/fault/history').then(function(d) {
        if (!d.success || !d.history) return;
        var history = d.history;
        var html = '';
        if (!history.length) {
            html = '<p style="opacity:0.5">暂无故障注入历史</p>';
        } else {
            for (var i = history.length - 1; i >= 0; i--) {
                var h = history[i];
                html += '<div style="padding:4px 0;border-bottom:1px solid var(--border-color);font-size:11px">';
                html += '<span style="color:var(--warning)">[' + escapeHtml(h.timestamp || '') + ']</span> ';
                html += '<strong>' + escapeHtml(h.fault_type) + '</strong> -> 容器: ' + escapeHtml(h.container_id || '');
                html += '</div>';
            }
        }
        document.getElementById('faultHistoryList').innerHTML = html;
    });
}

/**
 * 清空故障历史显示（仅前端）
 */
function clearFaultHistoryDisplay() {
    var listEl = document.getElementById('faultHistoryList');
    if (listEl) {
        listEl.innerHTML = '<p style="opacity:0.5">暂无故障注入历史</p>';
    }
}

/**
 * 清除故障历史记录（前后端）
 */
function clearFaultHistory() {
    if (!hasPermission('advanced-fault')) {
        showToast('您没有故障注入的操作权限', 'warning');
        return;
    }
    customConfirm('确定要清除所有故障历史记录吗？', function() {
        apiPost('/api/fault/history/clear', {}).then(function(d) {
            if (d.success) {
                showToast('故障历史已清除', 'success');
                clearFaultHistoryDisplay();
            } else {
                showToast('清除失败: ' + (d.error || '未知错误'), 'error');
            }
        });
    });
}

// ========== 预留扩展区域（第1401-1450行） ==========
// 预留用于未来扩展，如更多故障类型等
// ===========================================

// ============================================================
// 30. ROS2 面板容器选择器
// ============================================================

/**
 * 处理 loadRos2PanelContainers 相关前端逻辑。
 */
function loadRos2PanelContainers() {
    apiGet('/api/docker/containers?all=false').then(function(d) {
        var html = '<option value="">-- 选择运行中的 ROS2 容器 --</option>';
        if (d.success && d.containers) {
            for (var i = 0; i < d.containers.length; i++) {
                var c = d.containers[i];
                if (c.state === 'running') {
                    // ★★★ 修复bug3：使用name作为value，避免id为空时无法选中 ★★★
                    html += '<option value="' + escapeHtml(c.name) + '">' + escapeHtml(c.name) + '</option>';
                }
            }
        }
        var selectors = ['ros2SimContainer', 'ros2TopicsContainer', 'ros2NodesContainer', 'ros2ServicesContainer', 'ros2ActionsContainer'];
        for (var j = 0; j < selectors.length; j++) {
            var sel = document.getElementById(selectors[j]);
            if (sel) {
                var currentVal = sel.value;
                sel.innerHTML = html;
                if (currentVal) sel.value = currentVal;
            }
        }
        showToast('容器列表已刷新', 'success');
    });
}

/**
 * 处理 onRos2PanelContainerChange 相关前端逻辑。
 */
function onRos2PanelContainerChange(select, panelType) {
    var containerId = select.value;
    var containerName = select.options[select.selectedIndex].text;
    var statusEl = document.getElementById('ros2' + panelType.charAt(0).toUpperCase() + panelType.slice(1) + 'ContainerStatus');
    if (containerId) {
        ros2PanelContainers[panelType] = { id: containerId, name: containerName };
        if (statusEl) statusEl.innerHTML = '✅ 已选中: <strong>' + escapeHtml(containerName) + '</strong>';
    } else {
        delete ros2PanelContainers[panelType];
        if (statusEl) statusEl.innerHTML = '⚠️ 未选择容器，功能不可用';
    }
}

/**
 * 处理 getRos2PanelContainerId 相关前端逻辑。
 */
function getRos2PanelContainerId(panelType) {
    if (ros2PanelContainers[panelType] && ros2PanelContainers[panelType].id) {
        return ros2PanelContainers[panelType].id;
    }
    if (selectedContainerId) {
        return selectedContainerId;
    }
    return null;
}

// ========== 预留扩展区域（第1451-1500行） ==========
// 预留用于未来扩展，如容器选择器增强等
// ===========================================

// ============================================================
