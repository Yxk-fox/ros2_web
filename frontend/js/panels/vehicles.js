/* T-6.0-02 懒加载模块：仿真车管理（容器列表/选中/日志/命令/资源/终端入口） — 从 sj_script.js 拆出，defer 加载，全局函数不变 */

// 13. 仿真车管理
// ============================================================

/**
 * 处理 selectContainer 相关前端逻辑。
 */
function selectContainer(id, name) {
    if (selectedContainerId === id) {
        deselectContainer();
        return;
    }
    apiGet('/api/docker/containers?all=false').then(function(data) {
        if (data.success && data.containers) {
            var found = false;
            for (var i = 0; i < data.containers.length; i++) {
                if ((data.containers[i].name === id || data.containers[i].name === name) && data.containers[i].state === 'running') {
                    found = true;
                    break;
                }
            }
            if (!found) {
                showToast('容器未运行或不存在', 'warning');
                return;
            }
        }
        if (selectedContainerId !== null) {
            clearContainerHighlight();
        }
        selectedContainerId = id;
        selectedContainerName = name;
        currentContainerId = id;
        updateRos2MenuItems(true);
        updateContainerButtons();
        updateContainerSelectStatus();
        showToast('已选中容器: ' + name, 'success');
    });
}

/**
 * 处理 deselectContainer 相关前端逻辑。
 */
function deselectContainer() {
    selectedContainerId = null;
    selectedContainerName = null;
    currentContainerId = null;
    updateRos2MenuItems(false);
    updateContainerButtons();
    clearContainerHighlight();
    updateContainerSelectStatus();
    showToast('已取消选中', 'info');
}

/**
 * 处理 updateContainerButtons 相关前端逻辑。
 */
function updateContainerButtons() {
    var rows = document.querySelectorAll('#containersTableBody tr');
    var hasSelected = (selectedContainerId !== null);
    rows.forEach(function(row) {
        var containerId = row.getAttribute('data-container-id');
        var nameElem = row.querySelector('strong');
        var name = nameElem ? nameElem.textContent : '';
        var btns = row.querySelectorAll('button');
        var selectBtn = null;
        for (var i = 0; i < btns.length; i++) {
            // 查找包含"选中"或"取消"文本的按钮（考虑到图标和文字连在一起的情况）
            var text = btns[i].textContent.trim();
            if (text.includes('选中') || text.includes('取消')) {
                selectBtn = btns[i];
                break;
            }
        }
        if (!selectBtn) return;
        var isCurrentSelected = (containerId === selectedContainerId && hasSelected);
        if (isCurrentSelected) {
            // 更新按钮为"取消"状态
            selectBtn.innerHTML = '<span class="btn-icon">❌</span><span class="btn-text">取消</span>';
            selectBtn.className = 'btn btn-sm btn-warning action-btn';
            selectBtn.disabled = false;
            selectBtn.style.opacity = '1';
            selectBtn.style.cursor = 'pointer';
            selectBtn.onclick = function() { deselectContainer(); };
            row.classList.add('selected-container');
        } else {
            // 更新按钮为"选中"状态
            selectBtn.innerHTML = '<span class="btn-icon">✅</span><span class="btn-text">选中</span>';
            selectBtn.className = 'btn btn-sm btn-success action-btn';
            if (hasSelected) {
                // 如果已有选中的容器，其他按钮置灰
                selectBtn.disabled = true;
                selectBtn.style.opacity = '0.4';
                selectBtn.style.cursor = 'not-allowed';
                selectBtn.onclick = null;
            } else {
                selectBtn.disabled = false;
                selectBtn.style.opacity = '1';
                selectBtn.style.cursor = 'pointer';
                selectBtn.onclick = function() {
                    selectContainer(containerId, name);
                };
            }
            row.classList.remove('selected-container');
        }
    });
}

/**
 * 处理 updateContainerSelectStatus 相关前端逻辑。
 */
function updateContainerSelectStatus() {
    var statusEl = document.getElementById('containerSelectStatus');
    if (!statusEl) return;
    if (selectedContainerId && selectedContainerName) {
        statusEl.innerHTML = '✅ 已选中容器：<strong>' + escapeHtml(selectedContainerName) + '</strong>';
    } else {
        statusEl.innerHTML = '⚠️ 未选中容器，ROS2 功能不可用';
    }
}

/**
 * 处理 clearContainerHighlight 相关前端逻辑。
 */
function clearContainerHighlight() {
    var rows = document.querySelectorAll('#containersTableBody tr');
    for (var i = 0; i < rows.length; i++) {
        rows[i].classList.remove('selected-container');
    }
}

/**
 * 处理 updateRos2MenuItems 相关前端逻辑。
 */
function updateRos2MenuItems(enabled) {
    var targetPanels = ['simulation', 'topics', 'nodes', 'services', 'actions'];
    var allItems = document.querySelectorAll('.sidebar-nav .nav-item');
    for (var i = 0; i < allItems.length; i++) {
        var panel = allItems[i].getAttribute('data-panel');
        if (targetPanels.indexOf(panel) !== -1) {
            if (enabled) {
                allItems[i].classList.remove('disabled');
                allItems[i].style.pointerEvents = 'auto';
                allItems[i].style.opacity = '1';
            } else {
                allItems[i].classList.add('disabled');
                allItems[i].style.pointerEvents = 'none';
                allItems[i].style.opacity = '0.4';
            }
        }
    }
}

// ============================================================
// 审计日志管理功能（仅管理员）
// ============================================================

/**
 * 加载审计日志列表
 */
function loadAuditLogs() {
    var container = document.getElementById('auditLogsContainer');
    if (!container) return;
    container.innerHTML = '<div style="opacity:0.5; text-align:center; padding:20px;">加载中...</div>';
    apiGet('/api/admin/audit-logs?limit=100').then(function(data) {
        if (!data.success) {
            container.innerHTML = '<div style="color:var(--error);">加载失败: ' + escapeHtml(data.error || '') + '</div>';
            return;
        }
        var logs = data.logs || [];
        if (logs.length === 0) {
            container.innerHTML = '<div style="opacity:0.5; text-align:center; padding:20px;">暂无审计日志</div>';
            return;
        }
        var html = '<div style="max-height:400px;overflow-y:auto;">';
        html += '<table class="data-table audit-log-table" style="font-size:12px;">';
        html += '<thead><tr><th class="audit-col-time">时间</th><th class="audit-col-user">用户</th><th class="audit-col-action">操作</th><th class="audit-col-details">详情</th></tr></thead><tbody>';
        logs.reverse().forEach(function(log) {
            var time = log.timestamp ? formatTimestamp(log.timestamp) : '-';
            html += '<tr>';
            html += '<td class="audit-col-time" style="color:var(--text-secondary);">' + time + '</td>';
            html += '<td class="audit-col-user"><span class="tag tag-info">' + escapeHtml(log.username || '-') + '</span></td>';
            html += '<td class="audit-col-action"><span class="tag tag-running">' + escapeHtml(log.action || '-') + '</span></td>';
            html += '<td class="audit-col-details">' + escapeHtml(log.details || '-') + '</td>';
            html += '</tr>';
        });
        html += '</tbody></table>';
        html += '<div style="margin-top:8px;font-size:11px;color:var(--text-muted);text-align:right;">共 ' + logs.length + ' 条记录</div>';
        html += '</div>';
        container.innerHTML = html;
    });
}

/**
 * 格式化时间戳
 */
function formatTimestamp(timestamp) {
    try {
        var date = new Date(timestamp);
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
        });
    } catch (e) {
        return timestamp;
    }
}

/**
 * 清空所有审计日志
 */
function clearAllAuditLogs() {
    customConfirm('确定要清空所有审计日志吗？此操作不可恢复！', function() {
        return;
    });
    apiDelete('/api/admin/audit-logs').then(function(data) {
        if (data.success) {
            showToast(data.message || '清空成功', 'success');
            loadAuditLogs();
        } else {
            showToast('清空失败: ' + (data.error || ''), 'error');
        }
    });
}

/**
 * 显示保留最近日志弹窗
 */
function showKeepRecentModal() {
    var modal = document.getElementById('keepRecentModal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

/**
 * 关闭保留最近日志弹窗
 */
function closeKeepRecentModal() {
    var modal = document.getElementById('keepRecentModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * 确认保留最近日志
 */
function confirmKeepRecent() {
    var count = parseInt(document.getElementById('keepRecentCount').value) || 100;
    if (count < 1) {
        showToast('保留数量至少为1', 'warning');
        return;
    }
    apiDelete('/api/admin/audit-logs', { keep_recent: count }).then(function(data) {
        if (data.success) {
            showToast(data.message || '操作成功', 'success');
            closeKeepRecentModal();
            loadAuditLogs();
        } else {
            showToast('操作失败: ' + (data.error || ''), 'error');
        }
    });
}

// ============================================================
// 可视化方案配置管理
// ============================================================

// 当前可视化配置数据
var visualizationConfigData = null;

/**
 * 预加载可视化配置数据（页面初始化时调用）
 */
function preloadVisualizationConfig() {
    apiGet('/api/visualization/methods').then(function(data) {
        if (data.success) {
            visualizationConfigData = data;
        }
    }).catch(function(err) {
        console.warn('预加载可视化配置失败:', err);
    });
}

/**
 * 显示可视化方案配置弹窗
 */
function showVisualizationConfigModal() {
    var modal = document.getElementById('visualizationConfigModal');
    if (!modal) return;
    
    modal.style.display = 'block';
    loadVisualizationConfigForModal();
}

/**
 * 关闭可视化方案配置弹窗
 */
function closeVisualizationConfigModal() {
    var modal = document.getElementById('visualizationConfigModal');
    if (modal) {
        modal.style.display = 'none';
    }
}

/**
 * 加载可视化方案配置（用于弹窗）
 */
function loadVisualizationConfigForModal() {
    var methodsContainer = document.getElementById('visualizationMethodsContainer');
    var orderContainer = document.getElementById('visualizationOrderContainer');
    
    if (!methodsContainer || !orderContainer) return;
    
    methodsContainer.innerHTML = '<div style="opacity:0.5; text-align:center; padding:20px;">加载中...</div>';
    orderContainer.innerHTML = '<div style="opacity:0.5; text-align:center; padding:20px;">加载中...</div>';
    
    apiGet('/api/visualization/methods').then(function(data) {
        if (!data.success) {
            methodsContainer.innerHTML = '<div style="color:var(--error);">加载失败: ' + escapeHtml(data.error || '') + '</div>';
            orderContainer.innerHTML = '';
            return;
        }
        
        visualizationConfigData = data;
        var methods = data.methods || {};
        var defaultMethod = data.default_method || 'vnc';
        var order = data.order || ['vnc', 'rviz_x11'];
        
        // 渲染可视化方案显示部分（参考镜像分组配置样式）
        var methodsHtml = '';
        order.forEach(function(key) {
            var method = methods[key];
            if (!method) return;
            
            var isDefault = key === defaultMethod;
            var isEnabled = method.enabled;
            
            methodsHtml += `
                <label class="checkbox-label">
                    <input type="checkbox" id="viz-${key}" ${isEnabled ? 'checked' : ''} 
                           data-key="${key}" data-default="${isDefault ? 'true' : 'false'}">
                    <span>${method.name} ${isDefault ? '(默认)' : ''}</span>
                </label>
            `;
        });
        methodsContainer.innerHTML = methodsHtml;
        
        // 渲染方案排序部分（参考镜像分组配置样式）
        var orderHtml = '';
        order.forEach(function(key, index) {
            var method = methods[key];
            if (!method) return;
            
            orderHtml += `
                <div class="sort-item">
                    <span class="sort-order">${index + 1}</span>
                    <select id="viz-sort-${index}" class="form-select" data-original="${key}">
                        ${order.map(function(k) {
                            var m = methods[k];
                            return m ? `<option value="${k}" ${k === key ? 'selected' : ''}>${m.name}</option>` : '';
                        }).join('')}
                    </select>
                </div>
            `;
        });
        orderContainer.innerHTML = orderHtml;
    }).catch(function(err) {
        console.error('加载可视化配置失败:', err);
        methodsContainer.innerHTML = '<div style="color:var(--error);">网络错误，无法加载配置</div>';
        orderContainer.innerHTML = '';
    });
}

/**
 * 保存可视化方案配置
 */
function saveVisualizationConfig() {
    if (!visualizationConfigData) {
        showToast('配置数据未加载', 'warning');
        return;
    }
    
    var methods = visualizationConfigData.methods || {};
    var order = visualizationConfigData.order || ['vnc', 'rviz_x11'];
    
    // 获取启用状态
    var enabledMethods = {};
    order.forEach(function(key) {
        var checkbox = document.getElementById('viz-' + key);
        if (checkbox) {
            enabledMethods[key] = checkbox.checked;
        }
    });
    
    // 获取排序
    var newOrder = [];
    order.forEach(function(_, index) {
        var select = document.getElementById('viz-sort-' + index);
        if (select) {
            newOrder.push(select.value);
        }
    });
    
    // 验证排序是否包含所有选项
    var isValidOrder = order.length === newOrder.length && 
                       order.every(function(k) { return newOrder.includes(k); });
    
    if (!isValidOrder) {
        showToast('排序配置无效，请确保每个方案都被选中', 'error');
        return;
    }
    
    // 保存配置
    var promises = [];
    
    // 保存启用状态
    Object.keys(enabledMethods).forEach(function(key) {
        promises.push(apiPost(`/api/visualization/method/${key}`, { enabled: enabledMethods[key] }));
    });
    
    // 保存排序
    promises.push(apiPost('/api/visualization/order', { order: newOrder }));
    
    Promise.all(promises).then(function(results) {
        var allSuccess = results.every(function(r) { return r.success; });
        if (allSuccess) {
            showToast('配置已保存', 'success');
            closeVisualizationConfigModal();
        } else {
            showToast('部分配置保存失败', 'warning');
        }
    }).catch(function(err) {
        console.error('保存配置失败:', err);
        showToast('保存失败: ' + err.message, 'error');
    });
}

/**
 * 加载可视化方案配置（旧方法，兼容原有调用）
 */
function loadVisualizationMethods() {
    // 旧方法已迁移到弹窗中，此处保留为空或调用新方法
}

/**
 * 设置默认可视化方案
 */
function setDefaultVisualization(method) {
    apiPost('/api/visualization/set-default', { method: method }).then(function(data) {
        if (data.success) {
            showToast(data.message || '设置成功', 'success');
        } else {
            showToast('设置失败: ' + (data.error || ''), 'error');
            // 恢复原来的选择
            loadVisualizationMethods();
        }
    }).catch(function(err) {
        showToast('网络错误', 'error');
        loadVisualizationMethods();
    });
}

/**
 * 启动容器可视化
 */
function startVisualization(containerId, method) {
    var url = `/api/docker/container/${containerId}/visualize`;
    if (method) {
        url += `?method=${method}`;
    }
    
    showToast('正在启动可视化...', 'info');
    
    // 先打开一个窗口，避免被浏览器弹窗拦截，并显示加载动画
    var newWindow = window.open('', '_blank');
    if (newWindow) {
        var loadingHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>正在加载可视化...</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .loading-container {
            text-align: center;
            color: white;
        }
        .spinner {
            width: 60px;
            height: 60px;
            border: 4px solid rgba(255,255,255,0.3);
            border-top-color: white;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 24px;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .loading-text {
            font-size: 20px;
            font-weight: 500;
            margin-bottom: 8px;
        }
        .loading-subtext {
            font-size: 14px;
            opacity: 0.8;
        }
        .dots::after {
            content: '';
            animation: dots 1.5s steps(4, end) infinite;
        }
        @keyframes dots {
            0%, 20% { content: ''; }
            40% { content: '.'; }
            60% { content: '..'; }
            80%, 100% { content: '...'; }
        }
    </style>
</head>
<body>
    <div class="loading-container">
        <div class="spinner"></div>
        <div class="loading-text">正在启动可视化<span class="dots"></span></div>
        <div class="loading-subtext">VNC / RViz 正在连接中，请稍候</div>
    </div>
</body>
</html>`;
        newWindow.document.write(loadingHtml);
        newWindow.document.close();
    }
    
    apiPost(url, {}).then(function(data) {
        if (data.success) {
            showToast(data.message || '可视化已启动', 'success');
            if (data.url) {
                if (newWindow) {
                    newWindow.location.href = data.url;
                } else {
                    // 如果弹窗被拦截，提示用户手动点击
                    showToast('请点击此链接打开可视化: <a href="' + data.url + '" target="_blank" style="color:#fff;text-decoration:underline;">' + data.url + '</a>', 'success', 10000);
                    // 备用方案：创建临时链接并点击
                    var link = document.createElement('a');
                    link.href = data.url;
                    link.target = '_blank';
                    link.rel = 'noopener noreferrer';
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                }
            }
        } else {
            if (newWindow) {
                // 显示错误信息在窗口中
                try {
                    var errorHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>启动失败</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .error-container {
            text-align: center;
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            max-width: 400px;
        }
        .error-icon {
            font-size: 48px;
            margin-bottom: 16px;
        }
        .error-title {
            font-size: 20px;
            font-weight: 600;
            color: #dc3545;
            margin-bottom: 12px;
        }
        .error-message {
            font-size: 14px;
            color: #666;
            line-height: 1.6;
        }
        .close-btn {
            margin-top: 24px;
            padding: 8px 24px;
            background: #dc3545;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        .close-btn:hover {
            background: #c82333;
        }
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-icon">❌</div>
        <div class="error-title">可视化启动失败</div>
        <div class="error-message">${data.error || data.message || '未知错误'}</div>
        <button class="close-btn" onclick="window.close()">关闭窗口</button>
    </div>
</body>
</html>`;
                    newWindow.document.write(errorHtml);
                    newWindow.document.close();
                } catch(e) {
                    newWindow.close();
                }
            }
            showToast('启动失败: ' + (data.error || data.message || '未知错误'), 'error');
        }
    }).catch(function(err) {
        if (newWindow) {
            try {
                var errorHtml = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>网络错误</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .error-container {
            text-align: center;
            background: white;
            padding: 40px;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            max-width: 400px;
        }
        .error-icon { font-size: 48px; margin-bottom: 16px; }
        .error-title { font-size: 20px; font-weight: 600; color: #dc3545; margin-bottom: 12px; }
        .error-message { font-size: 14px; color: #666; line-height: 1.6; }
        .close-btn {
            margin-top: 24px; padding: 8px 24px; background: #dc3545; color: white;
            border: none; border-radius: 6px; cursor: pointer; font-size: 14px;
        }
        .close-btn:hover { background: #c82333; }
    </style>
</head>
<body>
    <div class="error-container">
        <div class="error-icon">⚠️</div>
        <div class="error-title">网络错误</div>
        <div class="error-message">${err.message || '无法连接到服务器，请检查网络后重试'}</div>
        <button class="close-btn" onclick="window.close()">关闭窗口</button>
    </div>
</body>
</html>`;
                newWindow.document.write(errorHtml);
                newWindow.document.close();
            } catch(e) {
                newWindow.close();
            }
        }
        showToast('网络错误: ' + err.message, 'error');
    });
}

/**
 * 切换可视化菜单显示/隐藏
 */
function toggleVisualizationMenu(btn) {
    var menu = btn._vizMenu || btn.parentElement.querySelector('.dropdown-menu');
    if (menu) {
        btn._vizMenu = menu;
        if (menu.style.display === 'none' || menu.style.display === '') {
            closeDropdowns();
            var rect = btn.getBoundingClientRect();
            menu.style.position = 'fixed';
            menu.style.zIndex = '999999';
            menu.style.left = rect.left + 'px';
            menu.style.top = (rect.bottom + 4) + 'px';
            menu.style.display = 'block';
            menu.setAttribute('data-viz-menu', 'true');
            if (menu.parentElement !== document.body) {
                document.body.appendChild(menu);
            }
        } else {
            menu.style.display = 'none';
        }
    }
    document.addEventListener('click', closeDropdownsOnce);
}

/**
 * 关闭所有下拉菜单
 */
function closeDropdowns() {
    var menus = document.querySelectorAll('.dropdown-menu');
    menus.forEach(function(menu) {
        menu.style.display = 'none';
    });
}

/**
 * 单次关闭下拉菜单（用于事件监听）
 */
function closeDropdownsOnce(e) {
    if (!e.target.closest('.dropdown')) {
        closeDropdowns();
    }
    document.removeEventListener('click', closeDropdownsOnce);
}

// ============================================================
// 用户权限管理
// ============================================================

/**
 * 加载当前用户权限并渲染菜单
 */
function loadUserPermissions() {
    if (!AUTH_TOKEN) return;
    apiGet('/api/auth/permissions').then(function(data) {
        if (data.success) {
            window.userPermissions = data.permissions || [];
            window.userRole = data.role || 'user';
            // 保存权限到 localStorage，供页面刷新时预渲染使用
            localStorage.setItem('ros2_web_permissions', JSON.stringify(window.userPermissions));
            localStorage.setItem('ros2_web_role', window.userRole);
            renderMenuByPermissions();
            updateAdminOnlyControls();
            // ★★★ 权限渲染后重新应用增强面板隐藏设置 ★★★
            initSubMenuVisibility();
            if (currentPanel) updateSubMenuVisibility(currentPanel);
            // 更新用户管理卡片显示
            var userMgmtCard = document.getElementById('userManagementCard');
            if (userMgmtCard) {
                userMgmtCard.style.display = (window.userRole === 'admin') ? 'block' : 'none';
                if (window.userRole === 'admin') {
                    loadUserList();
                }
            }
            // 更新审计日志管理卡片显示
            var auditLogsCard = document.getElementById('auditLogsCard');
            if (auditLogsCard) {
                auditLogsCard.style.display = (window.userRole === 'admin') ? 'block' : 'none';
                if (window.userRole === 'admin') {
                    loadAuditLogs();
                }
            }
            // ★★★ 权限加载完成后刷新快速开始区域，确保配置的面板正确显示 ★★★
            renderQuickStart();
            // v3.6: 加载管理员专属工作空间切换器（仅管理员调用，避免普通用户触发 403）
            if (window.userRole === 'admin') {
                loadWorkspaceUsers();
            }
        }
    }).catch(function(err) {
        console.warn('加载权限失败:', err);
        // 默认只显示首页
        window.userPermissions = ['welcome'];
        window.userRole = 'user';
        renderMenuByPermissions();
        updateAdminOnlyControls();
        // ★★★ 权限加载失败也刷新快速开始区域 ★★★
        renderQuickStart();
        // v3.6: 普通用户隐藏切换器
        var sel = document.getElementById('workspaceUserSelect');
        if (sel) sel.style.display = 'none';
    });
}

/**
 * 根据权限渲染侧边栏菜单
 */
function renderMenuByPermissions() {
    var allItems = document.querySelectorAll('.sidebar-nav .nav-item');
    var perms = window.userPermissions || [];
    var role = window.userRole || 'user';
    allItems.forEach(function(item) {
        var panel = item.dataset.panel;
        if (!panel) return;
        if (role === 'admin') {
            item.style.display = 'flex';
            return;
        }
        // 普通用户首页始终显示
        if (panel === 'welcome') { item.style.display = 'flex'; return; }
        if (perms.includes(panel)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
    // 处理子菜单
    document.querySelectorAll('.nav-item.nav-sub').forEach(function(sub) {
        var parentPanel = null;
        for (var key in subMenuMap) {
            if (subMenuMap[key] === sub.dataset.panel) {
                parentPanel = key;
                break;
            }
        }
        if (parentPanel) {
            var parentItem = document.querySelector('.nav-item[data-panel="' + parentPanel + '"]');
            if (parentItem && parentItem.style.display === 'none') {
                sub.style.display = 'none';
            }
        }
    });
    // ★★★ 处理一级菜单显隐 ★★★
    for (var sectionId in menuHierarchy) {
        if (!menuHierarchy.hasOwnProperty(sectionId)) continue;
        var section = document.getElementById(sectionId);
        if (!section) continue;
        if (role === 'admin') {
            // 管理员显示所有分组
            section.style.display = '';
        } else {
            // 普通用户：父级菜单仅在其下任一子菜单有权限时显示
            var childPanels = menuHierarchy[sectionId];
            var hasVisibleChild = false;
            for (var i = 0; i < childPanels.length; i++) {
                var childItem = document.querySelector('.nav-item[data-panel="' + childPanels[i] + '"]');
                if (childItem && childItem.style.display !== 'none') {
                    hasVisibleChild = true;
                    break;
                }
            }
            section.style.display = hasVisibleChild ? '' : 'none';
        }
    }
    // ★★★ 渲染后立即应用增强面板隐藏设置 ★★★
    initSubMenuVisibility();
    if (currentPanel) updateSubMenuVisibility(currentPanel);
}

/**
 * 仿真车运行时长管理（前端实现）
 * - 启动时间由后端权威返回（Docker State.StartedAt），不依赖客户端时钟或 localStorage
 * - 每个容器独立计时，互不干扰；容器停止后后端不再返回 started_at，前端显示“—”自动归零
 * - 每秒刷新可见容器的运行时长显示
 */
var containerRuntimeTimer = null;

// 格式化运行时长（毫秒 -> HH:MM:SS）
function formatDuration(ms) {
    if (!ms || ms < 0) return '00:00:00';
    var totalSec = Math.floor(ms / 1000);
    var h = Math.floor(totalSec / 3600);
    var m = Math.floor((totalSec % 3600) / 60);
    var s = totalSec % 60;
    function pad(n) { return (n < 10 ? '0' : '') + n; }
    return pad(h) + ':' + pad(m) + ':' + pad(s);
}

// 每秒刷新所有可见运行容器的运行时长（data-start-time 为容器真实启动时间戳）
function refreshContainerRuntimes() {
    var cells = document.querySelectorAll('#containersTableBody .runtime-duration[data-start-time]');
    for (var i = 0; i < cells.length; i++) {
        var start = parseInt(cells[i].getAttribute('data-start-time'), 10);
        if (start) {
            cells[i].textContent = formatDuration(Date.now() - start);
        }
    }
}

function ensureContainerRuntimeTimer() {
    if (containerRuntimeTimer) return;
    containerRuntimeTimer = setInterval(refreshContainerRuntimes, 1000);
}

/**
 * 加载容器列表（含权限控制）
 */
function loadContainers(all, filter) {
    if (all === undefined || all === null) all = true;
    if (filter === undefined || filter === null) filter = '';
    closeDropdowns();
    var orphanedMenus = document.body.querySelectorAll('.dropdown-menu[data-viz-menu="true"]');
    orphanedMenus.forEach(function(m) { m.remove(); });
    var tbody = document.getElementById('containersTableBody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;"><div class="skeleton skeleton-block" style="height:40px;"></div></td></tr>';
    var url = '/api/docker/containers?all=' + all;
    // ★★★ 修复bug：改按容器名前缀过滤（filter_name）。
    // 旧逻辑按镜像名过滤（filter_image=ros2_），但用户容器镜像显示为未打标签的
    // 镜像ID（如 88fc0f0bc583），不含"ros2_"字符串，导致管理员看不到用户的ROS2容器。
    if (filter) url += '&filter_name=' + encodeURIComponent(filter);

    apiGet(url).then(function(data) {
        if (!data.success) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:var(--error)">失败: ' +
                escapeHtml(data.error || '') + '</td></tr>';
            updateContainerButtons();
            updateContainerSelectStatus();
            return;
        }
        if (!data.containers || !data.containers.length) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;opacity:0.5">没有容器</td></tr>';
            updateContainerButtons();
            updateContainerSelectStatus();
            return;
        }
        // 缓存容器列表，供新手引导 checkExecuteStarted() 检测使用
        window.lastContainerList = data.containers;

        // ★★★ 判断是否为管理员 ★★★
        // var isAdmin = (window.userRole === 'admin');
        var hasDockerPerm = hasPermission('docker');

        var html = '';
        for (var i = 0; i < data.containers.length; i++) {
            var c = data.containers[i];
            var s = c.status.toLowerCase();
            var statusTag = '';
            if (s.includes('up')) statusTag = '<span class="tag tag-running">运行中</span>';
            else if (s.includes('exited')) statusTag = '<span class="tag tag-stopped">已停止</span>';
            else if (s.includes('paused')) statusTag = '<span class="tag tag-paused">已暂停</span>';
            else statusTag = '<span class="tag">' + escapeHtml(c.status) + '</span>';

            // ★★★ 优先使用后端 is_ros2 标志（名称前缀 ros2_ 或镜像名匹配）：
            // 镜像为未打标签ID的容器也能正确识别为ROS2容器（终端按钮才不会缺失）
            var isRos2Container = c.is_ros2 === true ||
                (c.image && (c.image.includes('ros2') || c.image.includes('humble') || c.image.includes('foxy')));
            
            var baseActions = '';
            var moreActions = '';
            
            // 启动/停止/重启按钮：拥有仿真车管理页面权限即可使用。（基础按钮）
            if (s.includes('up')) {
                if (hasDockerPerm) {
                    baseActions += '<button class="btn btn-sm btn-warning action-btn" onclick="stopContainer(\'' + escapeHtml(c.name) + '\')" title="停止容器"><span class="btn-icon">⏹</span><span class="btn-text">停止</span></button>';
                } else {
                    baseActions += '<span class="btn btn-sm btn-disabled" title="无权限"><span class="btn-icon">⏹</span><span class="btn-text">停止</span></span>';
                }
            } else {
                if (hasDockerPerm) {
                    baseActions += '<button class="btn btn-sm btn-success action-btn" onclick="startContainer(\'' + escapeHtml(c.name) + '\')" title="启动容器"><span class="btn-icon">▶</span><span class="btn-text">启动</span></button>';
                } else {
                    baseActions += '<span class="btn btn-sm btn-disabled" title="无权限"><span class="btn-icon">▶</span><span class="btn-text">启动</span></span>';
                }
            }

            // ★★★ 选中按钮 - 所有用户可用（用于ROS2功能查看） ★★★（基础按钮）
            baseActions += '<button class="btn btn-sm btn-outline action-btn" onclick="selectContainer(\'' + escapeHtml(c.name) + '\', \'' + escapeHtml(c.name) + '\')" title="选中容器"><span class="btn-icon">✅</span><span class="btn-text">选中</span></button>';

            // ★★★ 日志/命令/资源 - 所有用户可查看 ★★★（展开按钮）
            moreActions += '<button class="btn btn-sm btn-outline action-btn" onclick="viewContainerLogs(\'' + escapeHtml(c.name) + '\',\'' + escapeHtml(c.name) + '\')" title="查看日志"><span class="btn-icon">📜</span><span class="btn-text">日志</span></button>';
            moreActions += '<button class="btn btn-sm btn-outline action-btn" onclick="viewContainerExec(\'' + escapeHtml(c.name) + '\',\'' + escapeHtml(c.name) + '\')" title="执行命令"><span class="btn-icon">💻</span><span class="btn-text">命令</span></button>';
            moreActions += '<button class="btn btn-sm btn-outline action-btn" onclick="viewContainerUpdate(\'' + escapeHtml(c.name) + '\',\'' + escapeHtml(c.name) + '\')" title="资源配置"><span class="btn-icon">⚙</span><span class="btn-text">资源</span></button>';
            
            // ★★★ 终端 - 根据镜像类型决定是否需要source ros2环境 ★★★（展开按钮）
            if (isRos2Container) {
                moreActions += '<button class="btn btn-sm btn-info action-btn" onclick="openTerminal(\'' + escapeHtml(c.name) + '\',\'normal\')" title="普通终端（已source ROS2）"><span class="btn-icon">🖥</span><span class="btn-text">终端</span></button>';
                moreActions += '<button class="btn btn-sm btn-info action-btn" onclick="openTerminal(\'' + escapeHtml(c.name) + '\',\'root\')" title="Root终端（已source ROS2）"><span class="btn-icon">👑</span><span class="btn-text">Root</span></button>';
            } else {
                moreActions += '<button class="btn btn-sm btn-info action-btn" onclick="openTerminal(\'' + escapeHtml(c.name) + '\',\'normal\', false)" title="普通终端"><span class="btn-icon">🖥</span><span class="btn-text">终端</span></button>';
                moreActions += '<button class="btn btn-sm btn-info action-btn" onclick="openTerminal(\'' + escapeHtml(c.name) + '\',\'root\', false)" title="Root终端"><span class="btn-icon">👑</span><span class="btn-text">Root</span></button>';
            }
            
            // ★★★ 可视化方案 - 只对ROS2容器显示 ★★★（展开按钮）
            if (isRos2Container && s.includes('up')) {
                var vizMenuItems = '';
                var hasEnabledMethods = false;
                
                // 如果有配置数据，根据配置生成菜单
                if (visualizationConfigData && visualizationConfigData.methods && visualizationConfigData.order) {
                    var methods = visualizationConfigData.methods;
                    var order = visualizationConfigData.order;
                    order.forEach(function(key) {
                        // v3.6: Foxglove 已注释，仅保留 vnc 和 rviz_x11
                        if (key === 'foxglove') return;
                        var method = methods[key];
                        if (method && method.enabled) {
                            hasEnabledMethods = true;
                            var icon = '🖼️';
                            var func = '';
                            if (key === 'vnc') {
                                icon = '🖥️';
                                func = `startVisualization('${c.id}', 'vnc')`;
                            } else if (key === 'rviz_x11') {
                                icon = '🖼️';
                                func = `startVisualization('${c.id}', 'rviz_x11')`;
                            }
                            vizMenuItems += `<a href="#" class="dropdown-item" onclick="${func}; closeDropdowns();">${icon} ${method.name}</a>`;
                        }
                    });
                }
                
                // 如果配置数据中没有启用的方法，或者没有配置数据，使用默认菜单
                if (!hasEnabledMethods) {
                    vizMenuItems = `
                        <a href="#" class="dropdown-item" onclick="startVisualization('${c.id}', 'vnc'); closeDropdowns();">🖥️ VNC 远程桌面</a>
                        <a href="#" class="dropdown-item" onclick="startVisualization('${c.id}', 'rviz_x11'); closeDropdowns();">🖼️ 原生 RVIZ (X11转发)</a>
                    `;
                }
                
                moreActions += `
                    <div class="dropdown">
                        <button class="btn btn-sm btn-primary action-btn dropdown-toggle" onclick="toggleVisualizationMenu(this)" title="可视化"><span class="btn-icon">🖼</span><span class="btn-text">可视化</span><span class="btn-icon">▼</span></button>
                        <div class="dropdown-menu" style="display:none;">
                            ${vizMenuItems}
                        </div>
                    </div>
                `;
            }

            // 删除按钮：拥有仿真车管理页面权限即可使用。（展开按钮）
            if (hasDockerPerm) {
                moreActions += '<button class="btn btn-sm btn-error action-btn" onclick="removeContainer(\'' + c.id + '\',\'' + escapeHtml(c.name) + '\')" title="删除容器"><span class="btn-icon">🗑</span><span class="btn-text">删除</span></button>';
            }
            
            // 构建最终的操作按钮HTML
            var actions = '<div class="action-buttons">';
            actions += baseActions;
            if (moreActions) {
                actions += moreActions;
            }
            actions += '</div>';

            var isSelected = (selectedContainerId === c.name);
            var cloudIp = c.cloud_ip || '';
            var cloudStatusTag;
            if (cloudIp) {
                cloudStatusTag = '<a href="http://' + cloudIp + ':9201/#/mine_monitor?display=2d" target="_blank" style="color:#3b82f6;text-decoration:underline;font-weight:bold;">🌐 ' + cloudIp + '</a>';
            } else if (isRos2Container) {
                cloudStatusTag = '<span style="color:#9ca3af;font-weight:bold;">❓ 未知</span>';
            } else {
                // 非 ROS2 容器无云平台连接概念
                cloudStatusTag = '<span style="color:var(--text-secondary)">—</span>';
            }

            // ★★★ 运行时长：以后端返回的容器真实启动时间（started_at）为准
            // 容器停止后后端不返回 started_at，前端显示“—”自动归零；每个容器独立计时
            var runtimeTag;
            if (s.includes('up') && c.started_at) {
                var startTime = Date.parse(c.started_at);
                if (isNaN(startTime)) startTime = Date.now();
                runtimeTag = '<span class="runtime-duration" data-start-time="' + startTime + '" style="font-variant-numeric:tabular-nums;color:#10b981;font-weight:bold;">' + formatDuration(Date.now() - startTime) + '</span>';
            } else {
                runtimeTag = '<span style="color:var(--text-secondary)">—</span>';
            }

            // ★★★ 修复bug3：data-container-id 使用 name，避免id为空时无法匹配选中状态 ★★★
            html += '<tr data-container-id="' + escapeHtml(c.name) + '" class="' + (isSelected ? 'selected-container' : '') + '">' +
                '<td><strong>' + escapeHtml(c.name) +
                '</strong><br><small style="opacity:0.6">' + c.id +
                '</small></td>' +
                '<td>' + statusTag + '</td>' +
                '<td>' + runtimeTag + '</td>' +
                '<td>' + cloudStatusTag + '</td>' +
                '<td>' + actions + '</td>' +
                '</tr>';
        }
        tbody.innerHTML = html;
        // 启动每秒刷新定时器，实时更新运行时长
        ensureContainerRuntimeTimer();
        updateContainerButtons();
        updateContainerSelectStatus();
    });
}

/**
 * 处理 startContainer 相关前端逻辑。
 */
function startContainer(id) {
    apiPost('/api/docker/container/' + id + '/start').then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) loadContainers();
    });
}

/**
 * 处理 stopContainer 相关前端逻辑。
 */
function stopContainer(id) {
    showToast('⏳ 正在停止容器...', 'info');
    apiPost('/api/docker/container/' + id + '/stop').then(function(d) {
        if (d.success) {
            showToast('✅ 容器已停止', 'success');
            loadContainers(false, 'ros2_');
        } else {
            showToast('❌ 停止失败: ' + (d.error || d.message || '未知错误'), 'error');
        }
    }).catch(function(err) {
        showToast('❌ 网络错误: ' + err.message, 'error');
    });
}

// 当前展开的容器more-actions ID
var expandedContainerId = null;

/**
 * 切换更多操作按钮的展开/收起状态
 */
function toggleMoreActions(btn) {
    var container = btn.parentElement;
    var moreActions = container.querySelector('.more-actions');
    var icon = btn.querySelector('.btn-icon');
    var text = btn.querySelector('.btn-text');
    
    // 获取当前按钮所在的行，用于标识唯一的容器
    var row = btn.closest('tr');
    var currentContainerId = row ? row.getAttribute('data-container-id') : null;
    
    if (moreActions.style.display === 'none' || moreActions.style.display === '') {
        // 展开操作
        moreActions.style.display = 'flex';
        icon.textContent = '⬆';
        text.textContent = '收起';
        
        // 记录当前展开的容器ID
        expandedContainerId = currentContainerId;
        
        // 禁用其他所有"更多"按钮
        disableOtherMoreButtons(currentContainerId);
    } else {
        // 收起操作
        moreActions.style.display = 'none';
        icon.textContent = '⬇';
        text.textContent = '更多';
        
        // 清除展开状态
        expandedContainerId = null;
        
        // 启用所有"更多"按钮
        enableAllMoreButtons();
    }
}

/**
 * 禁用除当前容器外的所有"更多"按钮
 */
function disableOtherMoreButtons(excludeContainerId) {
    var allMoreButtons = document.querySelectorAll('.more-btn');
    allMoreButtons.forEach(function(btn) {
        var row = btn.closest('tr');
        var containerId = row ? row.getAttribute('data-container-id') : null;
        if (containerId !== excludeContainerId) {
            btn.disabled = true;
            btn.classList.add('btn-disabled');
            btn.style.opacity = '0.5';
            btn.style.cursor = 'not-allowed';
        }
    });
}

/**
 * 启用所有"更多"按钮
 */
function enableAllMoreButtons() {
    var allMoreButtons = document.querySelectorAll('.more-btn');
    allMoreButtons.forEach(function(btn) {
        btn.disabled = false;
        btn.classList.remove('btn-disabled');
        btn.style.opacity = '1';
        btn.style.cursor = 'pointer';
    });
}

/**
 * 处理 restartContainer 相关前端逻辑。
 */
function restartContainer(id) {
    apiPost('/api/docker/container/' + id + '/restart').then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) loadContainers();
    });
}

/**
 * 处理 removeContainer 相关前端逻辑。
 */
function removeContainer(id, name) {
    customConfirm('确定删除 ' + name + '？', function() {
    });
    apiDelete('/api/docker/container/' + id + '?force=true').then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) loadContainers();
    });
}

/**
 * 处理 viewContainerLogs 相关前端逻辑。
 */
function viewContainerLogs(id, name) {
    if (!id) {
        if (selectedContainerId) { id = selectedContainerId; name = selectedContainerName; }
        else { showToast('请先选中一个容器', 'warning'); return; }
    }
    currentContainerId = id;
    document.getElementById('containerLogCard').style.display = 'block';
    document.getElementById('containerLogName').textContent = name;
    loadContainerLogs();
}

var containerLogMode = 'docker';
var containerLogRefreshTimer = null;
var containerLogAutoScroll = true;

function stopContainerLogRefresh() {
    if (containerLogRefreshTimer) {
        clearInterval(containerLogRefreshTimer);
        containerLogRefreshTimer = null;
    }
}

function closeContainerLogs() {
    stopContainerLogRefresh();
    document.getElementById('containerLogCard').style.display = 'none';
}

function startContainerLogRefresh() {
    stopContainerLogRefresh();
    if (containerLogMode === 'ros2') {
        containerLogRefreshTimer = setInterval(function() {
            if (!currentContainerId) {
                stopContainerLogRefresh();
                return;
            }
            var container = document.getElementById('containerLogContent');
            if (!container) return;
            var url = '/api/docker/container/' + currentContainerId + '/roslogs?tail=300';
            apiGet(url).then(function(d) {
                var text = d.logs || d.error || '无日志';
                if (d.log_file) {
                    text = '📄 日志文件: ' + d.log_file + '\n' + '='.repeat(60) + '\n' + text;
                }
                container.textContent = text;
                if (containerLogAutoScroll) {
                    container.scrollTop = container.scrollHeight;
                }
            });
        }, 2000);
    }
}

function loadContainerLogs(type) {
    if (!currentContainerId) return;
    if (type) containerLogMode = type;
    var mode = containerLogMode || 'docker';
    var container = document.getElementById('containerLogContent');
    container.innerHTML = '<span class="loading"></span> 加载' + (mode === 'ros2' ? ' ROS2 ' : ' Docker ') + '日志中...';

    var url;
    if (mode === 'ros2') {
        url = '/api/docker/container/' + currentContainerId + '/roslogs?tail=300';
    } else {
        url = '/api/docker/container/' + currentContainerId + '/logs?tail=200';
    }
    apiGet(url).then(function(d) {
        var text = d.logs || d.error || '无日志';
        if (mode === 'ros2' && d.log_file) {
            text = '📄 日志文件: ' + d.log_file + '\n' + '='.repeat(60) + '\n' + text;
        }
        container.textContent = text;
        if (containerLogAutoScroll) {
            container.scrollTop = container.scrollHeight;
        }
        startContainerLogRefresh();
    });
}

/**
 * 处理 viewContainerExec 相关前端逻辑。
 */
function viewContainerExec(id, name) {
    if (!id) {
        if (selectedContainerId) { id = selectedContainerId; name = selectedContainerName; }
        else { showToast('请先选中一个容器', 'warning'); return; }
    }
    currentContainerId = id;
    document.getElementById('containerExecCard').style.display = 'block';
    document.getElementById('containerExecName').textContent = name;
    document.getElementById('containerExecResult').textContent = '';
    document.getElementById('containerExecCmd').value = '';
}

/**
 * 处理 execContainerCmd 相关前端逻辑。
 */
function execContainerCmd() {
    if (!currentContainerId) { showToast('请先选择容器', 'warning'); return; }
    var cmd = document.getElementById('containerExecCmd').value.trim();
    if (!cmd) { showToast('请输入命令', 'warning'); return; }
    if (cmd.includes('ros2 topic echo') && !cmd.includes('--once') && !cmd.includes('--head')) {
        showToast('⚠️ ros2 topic echo 需要添加 --once 或 --head 参数，否则会持续输出', 'warning');
    }
    var resultEl = document.getElementById('containerExecResult');
    resultEl.textContent = '⏳ 执行中...';
    apiPost('/api/docker/container/' + currentContainerId + '/exec', { command: cmd }).then(function(d) {
        var output = '';
        if (d.stdout) output += d.stdout;
        if (d.stderr) output += '\n' + d.stderr;
        resultEl.textContent = output || '✅ 执行成功（无输出）';
        if (!d.success) { showToast('执行失败: ' + (d.error || '请检查命令'), 'error'); }
    }).catch(function(err) {
        resultEl.textContent = '❌ 请求失败: ' + err.message;
    });
}

/**
 * 处理 refreshContainerExec 相关前端逻辑。
 */
function refreshContainerExec() {
    if (!currentContainerId) { showToast('请先选择容器', 'warning'); return; }
    document.getElementById('containerExecResult').textContent = '';
    document.getElementById('containerExecCmd').value = '';
    showToast('已清空，请输入新命令', 'info');
}

/**
 * 处理 viewContainerUpdate 相关前端逻辑。
 */
function viewContainerUpdate(id, name) {
    if (!id) {
        if (selectedContainerId) { id = selectedContainerId; name = selectedContainerName; }
        else { showToast('请先选中一个容器', 'warning'); return; }
    }
    currentContainerId = id;
    document.getElementById('containerUpdateCard').style.display = 'block';
    document.getElementById('containerUpdateName').textContent = name;
}

/**
 * 处理 refreshContainerUpdate 相关前端逻辑。
 */
function refreshContainerUpdate() {
    if (!currentContainerId) return;
    var name = document.getElementById('containerUpdateName').textContent;
    viewContainerUpdate(currentContainerId, name);
}

/**
 * 处理 updateContainerRes 相关前端逻辑。
 */
function updateContainerRes() {
    if (!currentContainerId) return;
    var cpus = parseFloat(document.getElementById('containerCpus').value) || null;
    var mem = parseFloat(document.getElementById('containerMem').value) || null;
    apiPost('/api/docker/container/' + currentContainerId + '/update', { cpus: cpus, memory_gb: mem })
        .then(function(d) { showToast(d.message || d.error, d.success ? 'success' : 'error'); });
}

/**
 * 处理 stopAllRos2 相关前端逻辑。
 */
function stopAllRos2() {
    if (!hasPermission('docker')) {
        showToast('您没有仿真车管理的操作权限', 'warning');
        return;
    }
    customConfirm('确定停止所有 ROS2 容器？', function() {
        showToast('⏳ 正在停止所有ROS2容器...', 'info');
        apiPost('/api/docker/stop-all-ros2').then(function(d) {
            if (d.success) {
                showToast('✅ 已停止所有ROS2容器', 'success');
                loadContainers(false, 'ros2_');
            } else {
                showToast('❌ 停止失败: ' + (d.detail || d.error || d.message || '未知错误'), 'error');
            }
        });
    });
}

/**
 * 处理 syncTime 相关前端逻辑。
 */
function syncTime() {
    if (!hasPermission('docker')) {
        showToast('您没有仿真车管理的操作权限', 'warning');
        return;
    }
    apiPost('/api/docker/sync-time').then(function(d) {
        showToast(d.success ? '时间同步完成' : ('同步失败: ' + (d.detail || d.error || d.message || '未知错误')), d.success ? 'success' : 'error');
    });
}

// ========== 预留扩展区域（第601-650行） ==========
// 预留用于未来扩展，如容器批量操作、编排等
// ===========================================

// ============================================================
