/* ============================================================
数据导出功能模块
@File    :  data_export.js
@Time    :  2026/08/21
@Author  :  Fox
@Version :  4.0-decoupled
@Desc    :  提取地图、录制ROS2 Bag、Web下载Bag三个功能
            通过 MutationObserver 向容器列表「更多」菜单注入按钮
            不修改 sj_script.js 任何代码
依赖：
  - sj_script.js -> apiGet, apiPost, showToast, escapeHtml, hasPermission
============================================================ */

(function() {
    if (window.__dataExportLoaded) return;
    window.__dataExportLoaded = true;

    var INJECTED_FLAG = 'data-export-injected';

    function _downloadFile(fileName) {
        var url = '/api/data-export/bag/download?file=' + encodeURIComponent(fileName);
        var token = localStorage.getItem('ros2_web_token') || '';
        fetch(url, {
            method: 'GET',
            headers: { 'Authorization': 'Bearer ' + token }
        }).then(function(res) {
            if (!res.ok) throw new Error('下载失败: HTTP ' + res.status);
            var disp = res.headers.get('content-disposition') || '';
            var m = /filename="?([^";]+)"?/.exec(disp);
            var fname = m ? m[1] : fileName;
            return res.blob().then(function(b) {
                var blobUrl = URL.createObjectURL(b);
                var a = document.createElement('a');
                a.href = blobUrl;
                a.download = fname;
                document.body.appendChild(a);
                a.click();
                setTimeout(function() { URL.revokeObjectURL(blobUrl); a.remove(); }, 1000);
            });
        }).catch(function(e) {
            showToast('下载失败: ' + e.message, 'error');
        });
    }

    function _isRos2Container(containerName) {
        return containerName && (
            containerName.indexOf('ros2') >= 0 ||
            containerName.indexOf('humble') >= 0 ||
            containerName.indexOf('foxy') >= 0
        );
    }

    function _injectButtonsIntoRow(row) {
        if (!row || row.hasAttribute(INJECTED_FLAG)) return;

        var actionButtons = row.querySelector('.action-buttons');
        if (!actionButtons) return;

        var containerName = row.getAttribute('data-container-id');
        if (!containerName) return;

        var isRos2 = _isRos2Container(containerName);

        if (!isRos2) return;

        // 两排布局：注入到第二排；兼容旧版单排布局
        var target = row.querySelector('.action-row-extra[data-export-row="1"]') || actionButtons;

        var btnExtract = document.createElement('button');
        btnExtract.className = 'btn btn-sm btn-outline action-btn';
        btnExtract.innerHTML = '<span class="btn-icon">🗺️</span><span class="btn-text">提取地图</span>';
        btnExtract.onclick = function() {
            _openHdmapModal(containerName);
            closeDropdowns && closeDropdowns();
        };

        var btnRecord = document.createElement('button');
        btnRecord.className = 'btn btn-sm btn-outline action-btn';
        btnRecord.innerHTML = '<span class="btn-icon">⏺️</span><span class="btn-text">录制Bag</span>';
        btnRecord.onclick = function() {
            _openBagRecordModal(containerName);
            closeDropdowns && closeDropdowns();
        };

        var btnDownload = document.createElement('button');
        btnDownload.className = 'btn btn-sm btn-outline action-btn';
        btnDownload.innerHTML = '<span class="btn-icon">📦</span><span class="btn-text">下载Bags</span>';
        btnDownload.onclick = function() {
            _openBagListModal(containerName);
            closeDropdowns && closeDropdowns();
        };

        // 顺序：…删除、提取地图、录制Bag、下载Bags、下载日志
        var logBtn = target.querySelector('[onclick^="downloadContainerLogs"]');
        if (logBtn) {
            target.insertBefore(btnExtract, logBtn);
            target.insertBefore(btnRecord, logBtn);
            target.insertBefore(btnDownload, logBtn);
        } else {
            target.appendChild(btnExtract);
            target.appendChild(btnRecord);
            target.appendChild(btnDownload);
        }

        row.setAttribute(INJECTED_FLAG, 'true');
    }

    function _scanAndInject() {
        var rows = document.querySelectorAll('#containersTableBody tr[data-container-id]');
        rows.forEach(function(row) {
            _injectButtonsIntoRow(row);
        });
    }

    function _startObserver() {
        var target = document.getElementById('containersTableBody');
        if (!target) {
            setTimeout(_startObserver, 300);
            return;
        }

        var observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.addedNodes && mutation.addedNodes.length > 0) {
                    _scanAndInject();
                }
            });
        });

        observer.observe(target, { childList: true, subtree: true });

        _scanAndInject();
    }

    function _createModal(title, width) {
        var overlay = document.createElement('div');
        overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:9999;';

        var modal = document.createElement('div');
        modal.style.cssText = 'background:var(--bg-primary,#fff);border-radius:12px;padding:20px;min-width:' + (width || '500px') + ';max-width:95vw;max-height:90vh;box-shadow:0 20px 60px rgba(0,0,0,0.3);display:flex;flex-direction:column;border:1px solid var(--border-color,#e5e7eb);';

        var header = document.createElement('div');
        header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border-color,#e5e7eb);';
        header.innerHTML = '<h3 style="margin:0;color:var(--text-primary,#1f2937);font-size:16px;font-weight:600;">' + title + '</h3>';

        var closeBtn = document.createElement('button');
        closeBtn.className = 'btn btn-sm btn-error';
        closeBtn.innerHTML = '✕';
        closeBtn.onclick = function() {
            document.body.removeChild(overlay);
        };
        header.appendChild(closeBtn);

        var body = document.createElement('div');
        body.style.cssText = 'flex:1;overflow:auto;color:var(--text-primary,#1f2937);';

        modal.appendChild(header);
        modal.appendChild(body);
        overlay.appendChild(modal);

        overlay.addEventListener('click', function(e) {
            if (e.target === overlay) {
                document.body.removeChild(overlay);
            }
        });

        document.body.appendChild(overlay);
        return body;
    }

    function _openHdmapModal(containerName) {
        var body = _createModal('🗺️ 提取地图 - ' + containerName, '500px');

        body.innerHTML = '<div style="margin-bottom:12px;"><label style="display:block;margin-bottom:4px;font-weight:500;">车辆SN</label><select id="hdmap-sn-select" style="width:100%;padding:8px;border:1px solid var(--border-color,#e5e7eb);border-radius:6px;"></select></div>' +
            '<div id="hdmap-status" style="margin:12px 0;"></div>' +
            '<div style="display:flex;gap:8px;justify-content:flex-end;"><button id="hdmap-extract-btn" class="btn btn-primary">提取地图</button></div>';

        var snSelect = body.querySelector('#hdmap-sn-select');
        var extractBtn = body.querySelector('#hdmap-extract-btn');
        var statusDiv = body.querySelector('#hdmap-status');

        statusDiv.innerHTML = '<span style="color:var(--text-secondary);">加载SN列表中...</span>';

        apiGet('/api/data-export/hdmap/sn-list?container_name=' + encodeURIComponent(containerName)).then(function(data) {
            if (data.success && data.sn_list && data.sn_list.length > 0) {
                snSelect.innerHTML = '';
                data.sn_list.forEach(function(sn) {
                    var opt = document.createElement('option');
                    opt.value = sn;
                    opt.textContent = sn;
                    snSelect.appendChild(opt);
                });
                statusDiv.innerHTML = '<span style="color:#10b981;">找到 ' + data.sn_list.length + ' 个地图目录</span>';
            } else {
                snSelect.innerHTML = '<option value="">未找到地图目录</option>';
                extractBtn.disabled = true;
                extractBtn.style.opacity = '0.5';
                statusDiv.innerHTML = '<span style="color:#ef4444;">容器内未找到可用的地图目录，请确认容器已运行且hdmap数据存在</span>';
            }
        }).catch(function(err) {
            statusDiv.innerHTML = '<span style="color:#ef4444;">加载SN列表失败: ' + err.message + '</span>';
        });

        extractBtn.onclick = function() {
            var sn = snSelect.value;
            if (!sn) {
                showToast('请选择SN', 'error');
                return;
            }
            extractBtn.disabled = true;
            extractBtn.style.opacity = '0.5';
            extractBtn.textContent = '提取中...';
            statusDiv.innerHTML = '<span style="color:#f59e0b;">正在提取地图，可能需要几十秒...</span>';

            apiPost('/api/data-export/hdmap/extract', {
                container_name: containerName,
                sn: sn
            }).then(function(data) {
                if (data.success) {
                    statusDiv.innerHTML = '<span style="color:#10b981;">✅ 提取成功</span>' +
                        '<div style="margin-top:8px;padding:8px;background:var(--bg-secondary,#f3f4f6);border-radius:6px;font-size:13px;">' +
                        '<div>文件名: ' + escapeHtml(data.file_name) + '</div>' +
                        '<div>大小: ' + data.size_mb + ' MB</div>' +
                        '</div>' +
                        '<div style="margin-top:8px;"><button id="hdmap-download-btn" class="btn btn-sm btn-primary">📥 下载到本地</button></div>';
                    var dlBtn = statusDiv.querySelector('#hdmap-download-btn');
                    if (dlBtn) {
                        dlBtn.onclick = function() {
                            _downloadFile(data.file_name);
                        };
                    }
                    showToast('地图提取成功', 'success');
                } else {
                    statusDiv.innerHTML = '<span style="color:#ef4444;">❌ 提取失败: ' + escapeHtml(data.error || data.message || '未知错误') + '</span>';
                    extractBtn.disabled = false;
                    extractBtn.style.opacity = '1';
                    extractBtn.textContent = '提取地图';
                }
            }).catch(function(err) {
                statusDiv.innerHTML = '<span style="color:#ef4444;">❌ 请求失败: ' + escapeHtml(err.message) + '</span>';
                extractBtn.disabled = false;
                extractBtn.style.opacity = '1';
                extractBtn.textContent = '提取地图';
            });
        };
    }

    function _openBagRecordModal(containerName) {
        var body = _createModal('⏺️ 录制ROS2 Bag - ' + containerName, '500px');

        body.innerHTML = '<div id="bag-status" style="margin:12px 0;padding:12px;background:var(--bg-secondary,#f3f4f6);border-radius:6px;"></div>' +
            '<div style="display:flex;gap:8px;justify-content:flex-end;"><button id="bag-start-btn" class="btn btn-primary">开始录制</button><button id="bag-stop-btn" class="btn btn-error" style="display:none;">停止并导出</button></div>';

        var statusDiv = body.querySelector('#bag-status');
        var startBtn = body.querySelector('#bag-start-btn');
        var stopBtn = body.querySelector('#bag-stop-btn');
        var pollTimer = null;

        function refreshStatus() {
            apiGet('/api/data-export/bag/status?container_name=' + encodeURIComponent(containerName)).then(function(data) {
                if (data.status === 'recording') {
                    statusDiv.innerHTML = '<div style="color:#ef4444;font-weight:600;">🔴 录制中...</div>' +
                        '<div style="margin-top:4px;color:var(--text-secondary);">已录制: ' + data.elapsed_seconds + ' 秒</div>' +
                        '<div style="margin-top:4px;color:var(--text-secondary);">时间戳: ' + escapeHtml(data.timestamp) + '</div>';
                    startBtn.style.display = 'none';
                    stopBtn.style.display = '';
                } else if (data.status === 'idle') {
                    statusDiv.innerHTML = '<div style="color:var(--text-secondary);">无进行中的录制任务</div>' +
                        '<div style="margin-top:4px;font-size:12px;color:var(--text-muted);">提示：录制期间容器内需持续运行，点击"停止并导出"结束录制并打包下载</div>';
                    startBtn.style.display = '';
                    stopBtn.style.display = 'none';
                } else {
                    statusDiv.innerHTML = '<div style="color:var(--text-secondary);">状态: ' + escapeHtml(data.status) + '</div>';
                }
            }).catch(function(err) {
                statusDiv.innerHTML = '<div style="color:#ef4444;">获取状态失败: ' + escapeHtml(err.message) + '</div>';
            });
        }

        refreshStatus();
        pollTimer = setInterval(refreshStatus, 3000);

        var checkInterval = setInterval(function() {
            if (!document.body.contains(body)) {
                clearInterval(checkInterval);
                clearInterval(pollTimer);
            }
        }, 500);

        startBtn.onclick = function() {
            startBtn.disabled = true;
            startBtn.style.opacity = '0.5';
            startBtn.textContent = '启动中...';

            apiPost('/api/data-export/bag/start', {
                container_name: containerName
            }).then(function(data) {
                if (data.success) {
                    showToast('录制已启动', 'success');
                    refreshStatus();
                } else {
                    showToast('启动失败: ' + (data.error || data.message), 'error');
                    startBtn.disabled = false;
                    startBtn.style.opacity = '1';
                    startBtn.textContent = '开始录制';
                }
            }).catch(function(err) {
                showToast('请求失败: ' + err.message, 'error');
                startBtn.disabled = false;
                startBtn.style.opacity = '1';
                startBtn.textContent = '开始录制';
            });
        };

        stopBtn.onclick = function() {
            if (!confirm('确定要停止录制并导出bag吗？')) return;

            stopBtn.disabled = true;
            stopBtn.style.opacity = '0.5';
            stopBtn.textContent = '停止中...';
            statusDiv.innerHTML = '<div style="color:#f59e0b;">正在停止录制并打包导出，可能需要几十秒...</div>';

            apiPost('/api/data-export/bag/stop', {
                container_name: containerName
            }).then(function(data) {
                if (data.success) {
                    clearInterval(pollTimer);
                    statusDiv.innerHTML = '<div style="color:#10b981;font-weight:600;">✅ 导出成功</div>' +
                        '<div style="margin-top:8px;padding:8px;background:var(--bg-secondary,#f3f4f6);border-radius:6px;font-size:13px;">' +
                        '<div>文件名: ' + escapeHtml(data.file_name) + '</div>' +
                        '<div>大小: ' + data.size_mb + ' MB</div>' +
                        '<div>录制时长: ' + data.duration_seconds + ' 秒</div>' +
                        '</div>' +
                        '<div style="margin-top:8px;"><button id="bag-download-btn" class="btn btn-sm btn-primary">📥 下载到本地</button></div>';
                    var dlBtn = statusDiv.querySelector('#bag-download-btn');
                    if (dlBtn) {
                        dlBtn.onclick = function() {
                            _downloadFile(data.file_name);
                        };
                    }
                    showToast('Bag导出成功', 'success');
                    startBtn.style.display = '';
                    stopBtn.style.display = 'none';
                } else {
                    showToast('停止失败: ' + (data.error || data.message), 'error');
                    stopBtn.disabled = false;
                    stopBtn.style.opacity = '1';
                    stopBtn.textContent = '停止并导出';
                }
            }).catch(function(err) {
                showToast('请求失败: ' + err.message, 'error');
                stopBtn.disabled = false;
                stopBtn.style.opacity = '1';
                stopBtn.textContent = '停止并导出';
            });
        };
    }

    function _openBagListModal(containerName) {
        var body = _createModal('📦 我的Bags - ' + containerName, '650px');

        body.innerHTML = '<div id="bag-list-status" style="margin:12px 0;"></div>' +
            '<div style="max-height:400px;overflow:auto;"><table id="bag-list-table" style="width:100%;border-collapse:collapse;"><thead><tr style="border-bottom:2px solid var(--border-color,#e5e7eb);"><th style="width:30px;padding:8px;text-align:center;"><input type="checkbox" id="bag-select-all" style="cursor:pointer;"></th><th style="text-align:left;padding:8px;">文件名</th><th style="text-align:right;padding:8px;">大小</th><th style="text-align:right;padding:8px;width:180px;">操作</th></tr></thead><tbody></tbody></table></div>' +
            '<div style="display:flex;gap:8px;justify-content:space-between;align-items:center;margin-top:12px;">' +
            '<div><span id="bag-selected-count" style="color:var(--text-secondary);font-size:13px;">已选 0 个</span></div>' +
            '<div style="display:flex;gap:8px;">' +
            '<button id="bag-list-delete-selected" class="btn btn-sm btn-error" style="display:none;">🗑️ 删除选中</button>' +
            '<button id="bag-list-refresh" class="btn btn-sm btn-outline">🔄 刷新</button>' +
            '</div></div>';

        var statusDiv = body.querySelector('#bag-list-status');
        var tbody = body.querySelector('#bag-list-table tbody');
        var refreshBtn = body.querySelector('#bag-list-refresh');
        var deleteSelectedBtn = body.querySelector('#bag-list-delete-selected');
        var selectAllCb = body.querySelector('#bag-select-all');
        var selectedCountSpan = body.querySelector('#bag-selected-count');

        function updateSelectedCount() {
            var checked = tbody.querySelectorAll('.bag-row-check:checked');
            selectedCountSpan.textContent = '已选 ' + checked.length + ' 个';
            deleteSelectedBtn.style.display = checked.length > 0 ? '' : 'none';
            var totalCheckboxes = tbody.querySelectorAll('.bag-row-check').length;
            selectAllCb.checked = (totalCheckboxes > 0 && checked.length === totalCheckboxes);
            selectAllCb.indeterminate = (checked.length > 0 && checked.length < totalCheckboxes);
        }

        function deleteFiles(filenames, callback) {
            if (!filenames || filenames.length === 0) return;
            apiPost('/api/data-export/bag/delete', { filenames: filenames }).then(function(data) {
                if (data.success) {
                    showToast('已删除 ' + data.deleted_count + ' 个文件', 'success');
                    if (data.failed && data.failed.length > 0) {
                        showToast(data.failed.length + ' 个文件删除失败', 'warning');
                    }
                } else {
                    showToast('删除失败', 'error');
                }
                if (callback) callback();
            }).catch(function(err) {
                showToast('删除请求失败: ' + err.message, 'error');
                if (callback) callback();
            });
        }

        function loadList() {
            statusDiv.innerHTML = '<span style="color:var(--text-secondary);">加载中...</span>';
            tbody.innerHTML = '';

            var url = '/api/data-export/bag/list';
            if (containerName) {
                url += '?container_name=' + encodeURIComponent(containerName);
            }

            apiGet(url).then(function(data) {
                if (data.success && data.files && data.files.length > 0) {
                    tbody.innerHTML = '';
                    data.files.forEach(function(f) {
                        var tr = document.createElement('tr');
                        tr.style.borderBottom = '1px solid var(--border-color,#e5e7eb);';
                        var mtime = new Date(f.mtime * 1000);
                        var timeStr = mtime.toLocaleString();
                        tr.innerHTML = '<td style="padding:8px;text-align:center;"><input type="checkbox" class="bag-row-check" data-filename="' + escapeHtml(f.name) + '" style="cursor:pointer;"></td>' +
                            '<td style="padding:8px;"><div style="font-weight:500;">' + escapeHtml(f.name) + '</div><div style="font-size:12px;color:var(--text-muted);">' + timeStr + '</div></td>' +
                            '<td style="padding:8px;text-align:right;">' + f.size_mb + ' MB</td>' +
                            '<td style="padding:8px;text-align:right;"><button class="btn btn-sm btn-primary bag-dl-btn" data-filename="' + escapeHtml(f.name) + '">📥 下载</button> <button class="btn btn-sm btn-error bag-del-btn" data-filename="' + escapeHtml(f.name) + '">🗑️ 删除</button></td>';
                        tbody.appendChild(tr);
                    });

                    tbody.querySelectorAll('.bag-dl-btn').forEach(function(btn) {
                        btn.onclick = function() {
                            _downloadFile(btn.getAttribute('data-filename'));
                        };
                    });

                    tbody.querySelectorAll('.bag-del-btn').forEach(function(btn) {
                        btn.onclick = function() {
                            var fname = btn.getAttribute('data-filename');
                            if (typeof customConfirm === 'function') {
                                customConfirm('确定要删除文件 "' + fname + '" 吗？', function() {
                                    deleteFiles([fname], loadList);
                                });
                            } else {
                                if (confirm('确定要删除文件 "' + fname + '" 吗？')) {
                                    deleteFiles([fname], loadList);
                                }
                            }
                        };
                    });

                    tbody.querySelectorAll('.bag-row-check').forEach(function(cb) {
                        cb.onchange = updateSelectedCount;
                    });

                    statusDiv.innerHTML = '<span style="color:#10b981;">共 ' + data.files.length + ' 个文件</span>';
                } else {
                    tbody.innerHTML = '<tr><td colspan="4" style="padding:24px;text-align:center;color:var(--text-secondary);">暂无bag文件</td></tr>';
                    statusDiv.innerHTML = '<span style="color:var(--text-secondary);">bag目录为空</span>';
                }
                updateSelectedCount();
            }).catch(function(err) {
                statusDiv.innerHTML = '<span style="color:#ef4444;">加载失败: ' + escapeHtml(err.message) + '</span>';
            });
        }

        selectAllCb.onchange = function() {
            var checkboxes = tbody.querySelectorAll('.bag-row-check');
            checkboxes.forEach(function(cb) {
                cb.checked = selectAllCb.checked;
            });
            updateSelectedCount();
        };

        deleteSelectedBtn.onclick = function() {
            var checked = tbody.querySelectorAll('.bag-row-check:checked');
            var filenames = [];
            checked.forEach(function(cb) {
                filenames.push(cb.getAttribute('data-filename'));
            });
            if (filenames.length === 0) return;
            if (typeof customConfirm === 'function') {
                customConfirm('确定要删除选中的 ' + filenames.length + ' 个文件吗？', function() {
                    deleteFiles(filenames, loadList);
                });
            } else {
                if (confirm('确定要删除选中的 ' + filenames.length + ' 个文件吗？')) {
                    deleteFiles(filenames, loadList);
                }
            }
        };

        refreshBtn.onclick = loadList;
        loadList();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() {
            setTimeout(_startObserver, 500);
        });
    } else {
        setTimeout(_startObserver, 500);
    }
})();