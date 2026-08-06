/* ============================================================
终端模拟模块（按需加载）
从 sj_script.js 第 21 节拆分而来，首次打开终端时与 xterm CDN 一起动态加载，
避免首屏被迫下载 xterm.js（~150KB）。

依赖（加载本文件前已由 loadTerminalModule 保证就绪）：
  - xterm.js        -> window.Terminal
  - xterm-addon-fit -> window.FitAddon
  - sj_script.js    -> AUTH_TOKEN, showToast（全局）
============================================================ */

/**
 * 处理 openTerminal 相关前端逻辑。
 * @param {string} containerId - 容器ID
 * @param {string} mode - 终端模式 (normal/root)
 * @param {boolean} sourceRos2 - 是否需要加载ROS2环境（默认true）
 */
function _openTerminalImpl(containerId, mode, sourceRos2) {
    sourceRos2 = sourceRos2 === undefined ? true : sourceRos2;

    var overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:9999;backdrop-filter:blur(4px);';
    var modal = document.createElement('div');
    modal.style.cssText = 'background:#1e1e1e;border-radius:12px;padding:16px;min-width:800px;min-height:500px;width:800px;height:600px;max-width:95vw;max-height:95vh;box-shadow:0 20px 60px rgba(0,0,0,0.7);border:1px solid #3c3c3c;display:flex;flex-direction:column;resize:both;overflow:hidden;transition:all 0.3s ease;';
    modal.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;"><h3 style="color:#d4d4d4;margin:0;font-size:14px;">🖥️ 终端: ' + containerId.substring(0, 12) + '... (' + (mode === 'root' ? 'Root' : '普通') + ')</h3><div style="display:flex;gap:8px;"><span style="color:#888;font-size:12px;">拖拽右下角调整大小</span><button class="btn btn-outline" onclick="copyTerminalContent()" style="padding:4px 12px;font-size:12px;">📋 复制内容</button><button class="btn btn-outline" onclick="clearTerminal()" style="padding:4px 12px;font-size:12px;">🗑️ 清屏</button><button class="btn btn-outline" onclick="toggleTerminalSize()" style="padding:4px 12px;font-size:12px;">⛶ 最大化</button><button class="btn btn-error" onclick="closeTerminal()" style="padding:4px 12px;font-size:12px;">关闭</button></div></div><div id="terminal-container" style="flex:1;background:#1e1e1e;border-radius:4px;overflow:hidden;"></div><div id="terminal-resize-handle" style="position:absolute;bottom:16px;right:16px;width:16px;height:16px;border-right:2px solid #444;border-bottom:2px solid #444;cursor:se-resize;"></div>';
    modal.style.position = 'relative';
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    var term = new Terminal({
        cursorBlink: true,
        theme: {
            background: '#1e1e1e',
            foreground: '#d4d4d4',
            cursor: '#d4d4d4',
            cursorAccent: '#d4d4d4',
            selection: '#264f78',
            black: '#000000',
            red: '#c50f1f',
            green: '#13a10e',
            yellow: '#c19c00',
            blue: '#0037da',
            magenta: '#881798',
            cyan: '#3a96dd',
            white: '#cccccc',
            brightBlack: '#767676',
            brightRed: '#e74856',
            brightGreen: '#16c60c',
            brightYellow: '#f9f1a5',
            brightBlue: '#3b78ff',
            brightMagenta: '#b4009e',
            brightCyan: '#61d6d6',
            brightWhite: '#f2f2f2'
        },
        localEcho: 'auto',
        fontFamily: '"Fira Code", "JetBrains Mono", "Consolas", monospace',
        fontSize: 14,
        lineHeight: 1.4
    });
    var fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal-container'));
    setTimeout(function() { fitAddon.fit(); }, 100);

    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = protocol + '//' + location.host + '/ws/containers/' + containerId + '/shell?token=' + encodeURIComponent(AUTH_TOKEN) + '&mode=' + mode;
    var socket = new WebSocket(wsUrl);
    socket.binaryType = 'arraybuffer';

    socket.onopen = function() {
        term.write('\x1b[32m✅ 连接已建立...\x1b[0m\r\n');
        if (sourceRos2) {
            term.write('\x1b[33m⏳ 正在加载 ROS2 环境...\x1b[0m\r\n');
            setTimeout(function() {
                if (socket.readyState === WebSocket.OPEN) {
                    var encoder = new TextEncoder();
                    var commands = [
                        'source /home/boonray/install/setup.bash 2>/dev/null\n',
                        'source /root/robotruck_ros2/install/setup.bash 2>/dev/null\n',
                        'echo "✅ ROS2 环境已加载"\n'
                    ];
                    commands.forEach(function(cmd, index) {
                        setTimeout(function() {
                            if (socket.readyState === WebSocket.OPEN) {
                                socket.send(encoder.encode(cmd));
                            }
                        }, index * 200);
                    });
                }
            }, 600);
        }
    };

    socket.onmessage = function(event) {
        if (typeof event.data === 'string') { term.write(event.data); }
        else { var decoder = new TextDecoder(); term.write(decoder.decode(new Uint8Array(event.data))); }
    };

    socket.onerror = function(event) {
        term.write('\x1b[31m❌ 连接错误\x1b[0m\r\n');
        console.error('WebSocket error:', event);
    };
    socket.onclose = function(event) {
        if (event.code === 1006) {
            term.write('\x1b[31m❌ 连接异常断开（可能是容器未运行或网络问题）\x1b[0m\r\n');
            term.write('\x1b[33m⚠️ 请确认容器处于运行状态，且网络可达\x1b[0m\r\n');
            console.error('WebSocket close code 1006, container:', containerId);
        } else if (event.code === 1008) {
            term.write('\x1b[31m❌ 连接被拒绝（权限不足或令牌过期）\x1b[0m\r\n');
            term.write('\x1b[33m⚠️ 请检查登录状态或重新登录\x1b[0m\r\n');
        } else if (event.code === 1011) {
            term.write('\x1b[31m❌ 服务器内部错误\x1b[0m\r\n');
            term.write('\x1b[33m⚠️ 容器可能未运行或不存在\x1b[0m\r\n');
        } else {
            term.write('\x1b[33m⚠️ 连接已关闭 (代码: ' + event.code + ')\x1b[0m\r\n');
        }
    };

    term.onData(function(data) {
        if (socket.readyState === WebSocket.OPEN) {
            var encoder = new TextEncoder();
            socket.send(encoder.encode(data));
        }
    });

    var resizeObserver = new ResizeObserver(function() {
        try { fitAddon.fit(); } catch (e) { /* ignore */ }
    });
    var container = document.getElementById('terminal-container');
    resizeObserver.observe(container);

    window._currentTerminal = {
        term: term,
        socket: socket,
        overlay: overlay,
        resizeObserver: resizeObserver,
        container: container,
        modal: modal,
        fitAddon: fitAddon
    };
}

/**
 * 处理 closeTerminal 相关前端逻辑。
 */
function closeTerminal() {
    var t = window._currentTerminal;
    if (t) {
        try { t.socket.close(); } catch (e) { /* ignore */ }
        try { t.term.dispose(); } catch (e) { /* ignore */ }
        try { t.resizeObserver.disconnect(); } catch (e) { /* ignore */ }
        if (t.overlay && t.overlay.parentNode) t.overlay.parentNode.removeChild(t.overlay);
        window._currentTerminal = null;
    }
}

/**
 * 复制终端内容
 */
function copyTerminalContent() {
    var t = window._currentTerminal;
    if (!t || !t.term) return;

    try {
        // 获取终端所有内容（兼容不同版本的 xterm.js）
        var content = '';
        var buffer = t.term.buffer;

        if (buffer && buffer.active) {
            // 尝试不同的 API 获取方式
            if (typeof buffer.active.getLines === 'function') {
                content = buffer.active.getLines().map(function(line) {
                    return line.translateToString();
                }).join('\n');
            } else if (buffer.active.lines && Array.isArray(buffer.active.lines)) {
                // 某些版本使用 lines 属性
                content = buffer.active.lines.map(function(line) {
                    return line ? (typeof line.translateToString === 'function' ? line.translateToString() : String(line)) : '';
                }).join('\n');
            } else if (buffer.active.getLineCount && buffer.active.getLine) {
                // 另一种 API 方式
                var count = buffer.active.getLineCount();
                var lines = [];
                for (var i = 0; i < count; i++) {
                    var line = buffer.active.getLine(i);
                    if (line) {
                        lines.push(typeof line.translateToString === 'function' ? line.translateToString() : String(line));
                    }
                }
                content = lines.join('\n');
            }
        }

        // 如果无法通过 API 获取，尝试其他方法
        if (!content) {
            // 获取终端元素的文本内容
            var container = document.getElementById('terminal-container');
            if (container) {
                content = container.innerText || container.textContent || '';
            }
        }

        if (!content) {
            showToast('⚠️ 终端无内容可复制', 'warning');
            return;
        }

        // 使用 Clipboard API 复制（支持回退方案）
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            // 使用现代 Clipboard API
            navigator.clipboard.writeText(content).then(function() {
                showToast('✅ 终端内容已复制到剪贴板', 'success');
            }).catch(function(err) {
                console.error('Clipboard API 复制失败:', err);
                // 回退到传统方法
                fallbackCopyToClipboard(content);
            });
        } else {
            // 不支持 Clipboard API，使用回退方案
            fallbackCopyToClipboard(content);
        }
    } catch (e) {
        console.error('复制失败:', e);
        showToast('❌ 复制失败', 'error');
    }
}

/**
 * 回退复制方法（兼容旧浏览器或不支持 Clipboard API 的情况）
 */
function fallbackCopyToClipboard(text) {
    try {
        // 创建临时 textarea 元素
        var textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.cssText = 'position:fixed;top:-1000px;left:-1000px;width:1px;height:1px;opacity:0;';
        document.body.appendChild(textarea);

        // 选中并复制
        textarea.select();
        textarea.setSelectionRange(0, text.length);

        var success = document.execCommand('copy');

        // 清理
        document.body.removeChild(textarea);

        if (success) {
            showToast('✅ 终端内容已复制到剪贴板', 'success');
        } else {
            showToast('❌ 复制失败，请手动选择复制', 'error');
        }
    } catch (e) {
        console.error('回退复制失败:', e);
        showToast('❌ 复制失败，请手动选择复制', 'error');
    }
}

/**
 * 清屏
 */
function clearTerminal() {
    var t = window._currentTerminal;
    if (!t || !t.term) return;

    try {
        t.term.clear();
        showToast('✅ 终端已清空', 'success');
    } catch (e) {
        console.error('清屏失败:', e);
    }
}

/**
 * 切换终端大小（最大化/还原）
 */
function toggleTerminalSize() {
    var t = window._currentTerminal;
    if (!t || !t.modal) return;

    var isMaximized = t.modal.classList.contains('maximized');

    if (isMaximized) {
        // 还原到正常大小
        t.modal.classList.remove('maximized');
        t.modal.style.width = '800px';
        t.modal.style.height = '600px';
        t.modal.style.borderRadius = '12px';
        t.modal.style.padding = '16px';
        // 更新按钮文字
        document.querySelector('.btn-outline[onclick="toggleTerminalSize()"]').textContent = '⛶ 最大化';
    } else {
        // 最大化
        t.modal.classList.add('maximized');
        t.modal.style.width = 'calc(100vw - 20px)';
        t.modal.style.height = 'calc(100vh - 20px)';
        t.modal.style.borderRadius = '4px';
        t.modal.style.padding = '20px';
        // 更新按钮文字
        document.querySelector('.btn-outline[onclick="toggleTerminalSize()"]').textContent = '⬜ 还原';
    }

    // 重新适配终端大小
    if (t.term && t.fitAddon) {
        setTimeout(function() { t.fitAddon.fit(); }, 100);
    }
}
