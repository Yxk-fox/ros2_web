/* ============================================================
版权所有：上海伯镭科技有限公司
@File    :  sj_script.js
@Time    :  2026/06/26 10:26:00
@Author  :  Fox
@Version :  3.5
@Desc    :  ROS2 Web 管理工具 - 前端业务逻辑
            包含：认证管理、面板切换、Docker管理、ROS2功能、
            脚本管理、系统监控、主题设置、终端模拟等

            代码结构：
            1. 全局变量与配置
            2. 认证管理（登录、注册、注销、Token管理）
            3. 初始化与导航
            4. API 工具函数
            5. Toast 通知
            6. WebSocket 连接
            7. 系统状态
            8. 仿真控制
            9. 话题管理（含筛选、Pub、Kill）
            10. 节点管理（含筛选、Kill）
            11. 服务管理（含筛选、Kill）
            12. Action 管理
            13. Docker 管理（含选中、日志、命令、资源、终端）
            14. 脚本管理（含生成、列表、编辑、执行）
            15. 镜像管理
            16. 系统监控
            17. 其他工具
            18. 红绿灯模拟
            19. 批量生成车辆
            20. 主题设置
            21. 终端模拟（xterm）
            22. 子菜单控制
            23. 修改密码
            24. 工具函数
============================================================ */

// 全局错误捕获，便于排查页面报错
window.addEventListener('error', function(e) {
    if (window.console && console.error) {
        console.error('[SJ Script Error]', e.message, e.filename, e.lineno + ':' + e.colno);
    }
});

// ============================================================
// 1. 全局变量与配置
// ============================================================

var API_BASE = '';
var ws = null;
var wsReconnectTimer = null;
var currentPanel = 'welcome';
var currentContainerId = null;
var monitorTimer = null;
var monitorAutoRefresh = false;
var ros2ContainerRunning = false;

// Token 管理
var AUTH_TOKEN = localStorage.getItem('ros2_web_token') || null;
var CURRENT_USER = null;
var USER_ROLE = null;

var ENV_IP_MAP = {
    '106': '106.14.223.60',
    '139': '139.196.75.44',
    '192': '192.168.9.252'
};

// 全局变量：当前选中的容器
var selectedContainerId = null;
var selectedContainerName = null;

// 子菜单映射（二级→三级菜单）
var subMenuMap = {
    'scripts': 'advanced-scripts',
    'docker': 'advanced-docker'
};

// 一级菜单层级定义（section ID → 包含的子菜单面板）
var menuHierarchy = {
    'nav-section-containers': ['scripts', 'advanced-scripts', 'vehicle', 'docker', 'advanced-docker', 'images'],
    'nav-section-toolbox': ['traffic', 'advanced-fault', 'tools'],
    'nav-section-ros2': ['simulation', 'topics', 'nodes', 'services', 'actions'],
    'nav-section-tickets': ['tickets'],
    'nav-section-advanced': ['advanced-extend'],
    'nav-section-settings': ['monitor', 'api-manager', 'theme', 'settings']
};

var subMenuItems = {
    'scripts': null,
    'docker': null
};

// 主题颜色配置
var defaultColors = {
    dark: {
        '--bg-primary': '#111827',
        '--bg-secondary': '#1f2937',
        '--bg-card': '#1f2937',
        '--bg-input': '#374151',
        '--text-primary': '#f3f4f6',
        '--text-secondary': '#9ca3af',
        '--text-muted': '#6b7280',
        '--border-color': '#374151',
        '--accent': '#60a5fa',
        '--accent-hover': '#3b82f6',
        '--accent-light': '#e0edff',
        '--success': '#34d399',
        '--warning': '#fbbf24',
        '--error': '#f87171',
        '--info': '#60a5fa',
        '--sidebar-bg': '#111827',
        '--sidebar-text': '#f3f4f6',
        '--sidebar-hover': '#1f2937',
        '--sidebar-active': '#1f2937',
        '--sidebar-border': '#1f2937',
        '--header-bg': '#1f2937',
        '--header-text': '#f3f4f6',
        '--log-bg': '#0f172a',
        '--log-text': '#a7f3d0'
    },
    light: {
        '--bg-primary': '#f1f5f9',
        '--bg-secondary': '#ffffff',
        '--bg-card': '#ffffff',
        '--bg-input': '#f8fafc',
        '--text-primary': '#0f172a',
        '--text-secondary': '#475569',
        '--text-muted': '#94a3b8',
        '--border-color': '#e2e8f0',
        '--accent': '#3b82f6',
        '--accent-hover': '#2563eb',
        '--accent-light': '#e0edff',
        '--success': '#22c55e',
        '--warning': '#f59e0b',
        '--error': '#ef4444',
        '--info': '#3b82f6',
        '--sidebar-bg': '#ffffff',
        '--sidebar-text': '#0f172a',
        '--sidebar-hover': '#f1f5f9',
        '--sidebar-active': '#f1f5f9',
        '--sidebar-border': '#e2e8f0',
        '--header-bg': '#ffffff',
        '--header-text': '#0f172a',
        '--log-bg': '#f8fafc',
        '--log-text': '#0f172a'
    },
    'eye-care': {
        '--bg-primary': '#f7f0e6',
        '--bg-secondary': '#fcf8f0',
        '--bg-card': '#fcf8f0',
        '--bg-input': '#f7f0e6',
        '--text-primary': '#3d2b1f',
        '--text-secondary': '#6b5342',
        '--text-muted': '#a68b76',
        '--border-color': '#e0d3c4',
        '--accent': '#b8956e',
        '--accent-hover': '#a07d59',
        '--accent-light': '#e0edff',
        '--success': '#7a9c5a',
        '--warning': '#d4a373',
        '--error': '#c45a5a',
        '--info': '#7a9c5a',
        '--sidebar-bg': '#f7f0e6',
        '--sidebar-text': '#3d2b1f',
        '--sidebar-hover': '#f0e6d8',
        '--sidebar-active': '#f0e6d8',
        '--sidebar-border': '#e0d3c4',
        '--header-bg': '#fcf8f0',
        '--header-text': '#3d2b1f',
        '--log-bg': '#f7f0e6',
        '--log-text': '#3d2b1f'
    }
};

// ROS2 面板容器选择器
var ros2PanelContainers = {};

// 脚本展开状态
var scriptsExpanded = false;

// 高级日志WebSocket
var advLogWs = null;

// GPU自动刷新
var gpuAutoRefresh = false;
var gpuRefreshTimer = null;

// 故障注入
var selectedFaultType = '';

// 默认路径加载标志
var defaultPathsLoaded = false;

// ========== 预留扩展区域（第1-50行） ==========
// 预留用于未来扩展，如新增全局变量、配置项等
// 1. 新增全局变量
// 2. 新增配置项
// 3. ... 最多预留50行
// ===========================================

// ============================================================
// 2. 认证管理
// ============================================================

/**
 * 获取当前认证Token
 */
function getAuthToken() {
    return AUTH_TOKEN;
}

/**
 * 设置认证Token
 */
function setAuthToken(token) {
    AUTH_TOKEN = token;
    if (token) {
        localStorage.setItem('ros2_web_token', token);
    } else {
        localStorage.removeItem('ros2_web_token');
    }
}

/**
 * 获取请求头（包含认证Token）
 */
function getAuthHeaders() {
    var headers = { 'Content-Type': 'application/json' };
    if (AUTH_TOKEN) {
        headers['Authorization'] = 'Bearer ' + AUTH_TOKEN;
    }
    return headers;
}

/**
 * 检查是否已登录
 */
function isLoggedIn() {
    return AUTH_TOKEN !== null;
}

/**
 * 显示登录遮罩
 */
function showAuthOverlay() {
    var overlay = document.getElementById('authOverlay');
    if (overlay) overlay.style.display = 'flex';
}

/**
 * 隐藏登录遮罩
 */
function hideAuthOverlay() {
    var overlay = document.getElementById('authOverlay');
    if (overlay) overlay.style.display = 'none';
}

/**
 * 切换登录/注册Tab
 */
function switchAuthTab(tab) {
    var tabs = document.querySelectorAll('.auth-tab');
    tabs.forEach(function(t) { t.classList.remove('active'); });
    var loginForm = document.getElementById('loginForm');
    var registerForm = document.getElementById('registerForm');
    if (tab === 'login') {
        document.querySelector('.auth-tab[data-tab="login"]').classList.add('active');
        loginForm.style.display = 'block';
        registerForm.style.display = 'none';
    } else {
        document.querySelector('.auth-tab[data-tab="register"]').classList.add('active');
        loginForm.style.display = 'none';
        registerForm.style.display = 'block';
    }
}

/**
 * 处理登录
 */
function handleLogin() {
    var username = document.getElementById('loginUsername').value.trim();
    var password = document.getElementById('loginPassword').value.trim();
    var rememberMe = document.getElementById('loginRememberMe') ? document.getElementById('loginRememberMe').checked : false;
    var rememberDaysEl = document.getElementById('loginRememberDays');
    var rememberDays = rememberMe && rememberDaysEl ? parseInt(rememberDaysEl.value) : 1;
    var errorEl = document.getElementById('loginError');

    if (!username || !password) {
        errorEl.textContent = '请输入邮箱和密码';
        errorEl.style.display = 'block';
        return;
    }

    errorEl.style.display = 'none';
    showToast('正在登录...', 'info');

    fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username, password: password, remember_me: rememberMe, remember_days: rememberDays })
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (data.success && data.access_token) {
            setAuthToken(data.access_token);
            var displayName = data.username || data.email || username;
            CURRENT_USER = data.email || username;
            USER_ROLE = data.role || 'user';
            window.userRole = USER_ROLE;
            window.userPermissions = [];
            localStorage.setItem('ros2_web_user', CURRENT_USER);
            localStorage.setItem('ros2_web_role', USER_ROLE);
            hideAuthOverlay();
            updateUserInfo();
            // ★★★ 立即根据角色预渲染菜单（管理员显示所有菜单）★★★
            renderMenuByPermissions();
            initNavigation();
            buildColorSliders();
            updateWelcomeStatus();
            loadDefaultPaths();
            loadSettings();
            checkInstallStatus();
            // ★★★ 强制禁用 ROS2 菜单，直到用户选中容器 ★★★
            updateRos2MenuItems(false);
            // 子菜单
            getSubMenuItems();
            loadSubMenuSettings();
            initSubMenuVisibility();
            if (currentPanel) {
                setTimeout(function() { updateSubMenuVisibility(currentPanel); }, 200);
            }
            // 初始化快速开始
            initQuickStart();
            showToast('登录成功！欢迎 ' + displayName, 'success');
            connectWebSocket();
            checkSystemStatus();
            runIdle(function() {
                loadContainers();
                loadCardConfigs();
                loadCardConfigColumns();
                initCloudEnv();
            });
            loadUserPermissions();
            // 新手引导：首次登录检查
            if (typeof Onboarding !== 'undefined' && Onboarding.checkFirstLogin) {
                setTimeout(function() { Onboarding.checkFirstLogin(); }, 500);
            }
        } else {
            errorEl.textContent = data.detail || '登录失败，请检查邮箱和密码';
            errorEl.style.display = 'block';
            showToast('登录失败: ' + (data.detail || '未知错误'), 'error');
        }
    })
    .catch(function(err) {
        errorEl.textContent = '网络错误，请检查服务器连接';
        errorEl.style.display = 'block';
        showToast('网络错误: ' + err.message, 'error');
    });
}

/**
 * 处理注册
 */
function handleRegister() {
    var username = document.getElementById('registerUsername').value.trim();
    var password = document.getElementById('registerPassword').value.trim();
    var passwordConfirm = document.getElementById('registerPasswordConfirm').value.trim();
    var errorEl = document.getElementById('registerError');

    // 1. 非空检查（用户名不能为空）
    if (!username) {
        errorEl.textContent = '请输入用户名';
        errorEl.style.display = 'block';
        return;
    }
    // 2. ★★★ 格式校验（优先） ★★★
    if (!isValidBoonrayEmail(username)) {
        errorEl.textContent = '账号格式必须为 名.姓@boonray.com（如 john.doe@boonray.com）';
        errorEl.style.display = 'block';
        return;
    }
    // 3. 用户名长度（格式正确后再检查长度，至少3位）
    if (username.length < 3) {
        errorEl.textContent = '用户名至少3位';
        errorEl.style.display = 'block';
        return;
    }
    // 4. 密码非空及长度
    if (!password || password.length < 6) {
        errorEl.textContent = '密码至少6位';
        errorEl.style.display = 'block';
        return;
    }
    // 5. 密码一致性
    if (password !== passwordConfirm) {
        errorEl.textContent = '两次密码输入不一致';
        errorEl.style.display = 'block';
        return;
    }
    // 6. 密码格式校验
    if (!isValidPassword(password)) {
        errorEl.textContent = '密码必须：首字母大写、包含字母、包含特殊符号、不能有连续数字（如123、456）';
        errorEl.style.display = 'block';
        return;
    }

    // 所有校验通过，执行注册请求...
    errorEl.style.display = 'none';
    showToast('正在注册...', 'info');

    fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username, password: password, role: 'user' })
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (data.success) {
            showToast('注册成功！请登录', 'success');
            switchAuthTab('login');
            document.getElementById('loginUsername').value = username;
            document.getElementById('loginPassword').value = '';
        } else {
            errorEl.textContent = data.detail || '注册失败';
            errorEl.style.display = 'block';
            showToast('注册失败: ' + (data.detail || '未知错误'), 'error');
        }
    })
    .catch(function(err) {
        errorEl.textContent = '网络错误，请检查服务器连接';
        errorEl.style.display = 'block';
        showToast('网络错误: ' + err.message, 'error');
    });
}

/**
 * 处理退出登录
 */
function handleLogout() {
    // 防止重复触发退出确认框
    if (window.isLoggingOut) return;
    window.isLoggingOut = true;
    
    customConfirm('确定要退出登录吗？', function() {
        // 调用后端注销接口（可选）
        if (AUTH_TOKEN) {
            fetch('/api/auth/logout', {
                method: 'POST',
                headers: getAuthHeaders()
            }).then(function(response) {
                if (response.status === 401) {
                    console.debug('Logout: Token already expired or invalid');
                }
            }).catch(function() {});
        }

        setAuthToken(null);
        CURRENT_USER = null;
        USER_ROLE = null;
        localStorage.removeItem('ros2_web_user');
        localStorage.removeItem('ros2_web_role');
        localStorage.removeItem('ros2_web_token');
        localStorage.removeItem('ros2_web_permissions');
        localStorage.removeItem('ros2_web_theme');
        sessionStorage.clear();
        if (ws) {
            try { ws.close(); } catch(e) {}
            ws = null;
        }
        updateUserInfo();
        showAuthOverlay();
        showToast('已退出登录', 'info');
    }, '退出', function() { window.isLoggingOut = false; });
}

/**
 * 更新用户信息显示
 */
function updateUserInfo() {
    var userEl = document.getElementById('sidebarUserInfo');
    var roleEl = document.getElementById('userRoleDisplay');
    var sysUserEl = document.getElementById('sysCurrentUser');
    var sysRoleEl = document.getElementById('sysCurrentRole');

    if (CURRENT_USER) {
        if (userEl) userEl.textContent = '👤 ' + CURRENT_USER + (USER_ROLE === 'admin' ? ' (管理员)' : '');
        if (roleEl) roleEl.textContent = USER_ROLE || 'user';
        if (sysUserEl) sysUserEl.textContent = CURRENT_USER;
        if (sysRoleEl) sysRoleEl.textContent = USER_ROLE || 'user';
    } else {
        if (userEl) userEl.textContent = '未登录';
        if (roleEl) roleEl.textContent = '未登录';
        if (sysUserEl) sysUserEl.textContent = '未登录';
        if (sysRoleEl) sysRoleEl.textContent = '-';
    }
}

/**
 * 修改密码
 */
function changePassword() {
    var newPwd = document.getElementById('newPassword').value.trim();
    var confirmPwd = document.getElementById('newPasswordConfirm').value.trim();
    var resultEl = document.getElementById('passwordChangeResult');

    if (!newPwd || newPwd.length < 6) {
        resultEl.innerHTML = '<span style="color:var(--error)">密码至少6位</span>';
        return;
    }
    if (newPwd !== confirmPwd) {
        resultEl.innerHTML = '<span style="color:var(--error)">两次密码输入不一致</span>';
        return;
    }

    resultEl.innerHTML = '<span style="color:var(--info)">正在修改...</span>';

    fetch('/api/auth/change-password', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({ new_password: newPwd })
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (data.success) {
            resultEl.innerHTML = '<span style="color:var(--success)">✅ 密码修改成功</span>';
            showToast('密码修改成功', 'success');
            document.getElementById('newPassword').value = '';
            document.getElementById('newPasswordConfirm').value = '';
        } else {
            resultEl.innerHTML = '<span style="color:var(--error)">❌ ' + escapeHtml(data.detail || '修改失败') + '</span>';
        }
    })
    .catch(function(err) {
        resultEl.innerHTML = '<span style="color:var(--error)">❌ 网络错误: ' + escapeHtml(err.message) + '</span>';
    });
}

// ========== 预留扩展区域（第51-100行） ==========
// 预留用于未来扩展，如双因素认证、OAuth等
// 51. 双因素认证
// 52. OAuth 登录
// 53. ... 最多预留50行
// ===========================================

// ============================================================
// 3. 初始化与导航
// ============================================================

// ★★★ 空闲时执行工具：首屏关键路径优先，非关键任务延迟到浏览器空闲时执行 ★★★
function runIdle(fn) {
    if (window.requestIdleCallback) {
        window.requestIdleCallback(fn, { timeout: 2000 });
    } else {
        setTimeout(fn, 120);
    }
}

// ★★★ 注册 Service Worker：F5 刷新时从缓存秒返静态资源，绕过网络 ★★★
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('sw.js').then(function(reg) {
            console.log('[SW] 注册成功，F5刷新将加速');
        }).catch(function(err) {
            console.warn('[SW] 注册失败:', err);
        });
    });
}

document.addEventListener('DOMContentLoaded', function() {
    // 检查登录状态
    var token = localStorage.getItem('ros2_web_token');
    var user = localStorage.getItem('ros2_web_user');
    var role = localStorage.getItem('ros2_web_role');

    if (token && user) {
        AUTH_TOKEN = token;
        CURRENT_USER = user;
        USER_ROLE = role || 'user';
        window.userRole = USER_ROLE;
        // 从 localStorage 读取权限，供预渲染使用
        try {
            window.userPermissions = JSON.parse(localStorage.getItem('ros2_web_permissions') || '[]');
        } catch(e) {
            window.userPermissions = [];
        }
        updateUserInfo();
        hideAuthOverlay();
        // ★★★ 立即用本地role预渲染菜单，不等API ★★★
        renderMenuByPermissions();
        initNavigation();
        connectWebSocket();
        checkSystemStatus();
        buildColorSliders();
        updateWelcomeStatus();
        loadDefaultPaths();
        loadSettings();
        checkInstallStatus();
        // ★★★ 异步加载详细权限后刷新菜单（仅调用一次，去除重复调用） ★★★
        loadUserPermissions();
        // ★★★ 强制禁用 ROS2 菜单，直到用户选中容器 ★★★
        updateRos2MenuItems(false);
        // 子菜单
        getSubMenuItems();
        loadSubMenuSettings();
        initSubMenuVisibility();
        if (currentPanel) {
            setTimeout(function() { updateSubMenuVisibility(currentPanel); }, 200);
        }
        // 加载用户信息
        loadUserInfo();
        // 初始化快速开始
        initQuickStart();
        // ★★★ 非首屏关键数据延迟到浏览器空闲时加载，避免阻塞首屏（首屏并发请求 18→5） ★★★
        // 面板专属数据（loadTruckConfigList / loadHelpPages / preloadVisualizationConfig）
        // 改为切到对应面板时按需加载，进一步减少首屏请求数
        runIdle(function() {
            loadContainers();
            loadCardConfigs();
            loadCardConfigColumns();
            initCloudEnv();
        });
    } else {
        // 未登录分支也调用，确保菜单正确
        showAuthOverlay();
        // ... 初始化代码 ...
        // ★★★ 未登录时使用默认权限 ★★★
        window.userPermissions = ['welcome'];
        window.userRole = 'user';
        renderMenuByPermissions();
        loadTheme();
        initNavigation();
        buildColorSliders();
        loadSettings();
        getSubMenuItems();
        loadSubMenuSettings();
        initSubMenuVisibility();
        // ★★★ 未登录也禁用菜单 ★★★
        updateRos2MenuItems(false);
        // 初始化快速开始
        initQuickStart();
    }

    // 侧边栏折叠状态
    var sidebarCollapsed = localStorage.getItem('sidebarCollapsed') === 'true';
    if (sidebarCollapsed) {
        document.getElementById('sidebar').classList.add('collapsed');
    }
    var btn = document.getElementById('sidebarToggleBtn');
    if (btn) {
        btn.textContent = sidebarCollapsed ? '▶' : '◀';
    }

    // 回车键触发登录
    document.getElementById('loginPassword').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') handleLogin();
    });
    document.getElementById('loginUsername').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') handleLogin();
    });
    document.getElementById('registerPassword').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') handleRegister();
    });
    document.getElementById('registerPasswordConfirm').addEventListener('keydown', function(e) {
        if (e.key === 'Enter') handleRegister();
    });
});

/**
 * 加载用户信息
 */
function loadUserInfo() {
    if (!AUTH_TOKEN) return;
    fetch('/api/auth/me', {
        method: 'GET',
        headers: getAuthHeaders()
    })
    .then(function(res) { return res.json(); })
    .then(function(data) {
        if (data.success) {
            CURRENT_USER = data.username;
            USER_ROLE = data.role;
            localStorage.setItem('ros2_web_user', data.username);
            localStorage.setItem('ros2_web_role', data.role);
            updateUserInfo();
        }
    })
    .catch(function() {});
}

/**
 * 切换侧边栏折叠状态
 */
function toggleSidebar() {
    var sidebar = document.getElementById('sidebar');
    sidebar.classList.toggle('collapsed');
    localStorage.setItem('sidebarCollapsed', sidebar.classList.contains('collapsed'));
    var btn = document.getElementById('sidebarToggleBtn');
    if (btn) {
        btn.textContent = sidebar.classList.contains('collapsed') ? '▶' : '◀';
    }
}

/**
 * 初始化导航菜单
 */
var navigationInitialized = false;
function initNavigation() {
    if (navigationInitialized) return;
    navigationInitialized = true;
    var items = document.querySelectorAll('.sidebar-nav .nav-item');
    for (var i = 0; i < items.length; i++) {
        (function(item) {
            item.addEventListener('click', function(e) {
                if (this.classList.contains('disabled')) {
                    showToast('请先启动 ROS2 容器', 'warning');
                    return;
                }
                var panel = this.dataset.panel;
                if (panel) {
                    document.querySelectorAll('.nav-item').forEach(function(el) {
                        el.classList.remove('active');
                    });
                    this.classList.add('active');
                    switchPanel(panel);
                    for (var key in subMenuMap) {
                        if (subMenuMap[key] === panel) {
                            updateSubMenuVisibility(key);
                            break;
                        }
                    }
                }
            });
        })(items[i]);
    }
    loadSubMenuSettings();
}

/**
 * 切换面板
 */
function switchPanel(panel) {
    currentPanel = panel;
    document.querySelectorAll('.panel').forEach(function(p) {
        p.classList.remove('active');
    });
    var target = document.getElementById('panel-' + panel);
    if (target) target.classList.add('active');

    // v3.6：切换到 install 操作面板时，管理员刷新工作空间路径展示
    if (panel === 'tools' && window.userRole === 'admin') {
        checkInstallStatus();
    }

    var titles = {
        welcome: '👋 欢迎',
        docker: '🐳 Docker 管理',
        scripts: '📜 脚本生成',
        vehicle: '🚛 仿真车启动',
        images: '💿 镜像管理',
        traffic: '🚦 红绿灯模拟',
        batch: '🚛 车辆配置生成',
        monitor: '📊 系统监控',
        tools: '⚙️ install 配置',
        simulation: '🎮 仿真控制',
        topics: '📡 话题查看',
        nodes: '🔷 节点管理',
        services: '🔧 服务管理',
        actions: '⚡ Action 管理',
        'api-manager': '📡 REST API 管理',
        theme: '🎨 主题设置',
        settings: '⚙️ 系统设置',
        'advanced-docker': '🐳 容器管理增强',
        'advanced-scripts': '📜 脚本执行增强',
        'advanced-extend': '🔌 拓展功能',
        'advanced-fault': '💥 故障注入',
        'tickets': '🎫 工单管理'
    };
    document.getElementById('panelTitle').textContent = titles[panel] || panel;

    // 子菜单更新
    var parentPanel = null;
    for (var key in subMenuMap) {
        if (subMenuMap[key] === panel) {
            parentPanel = key;
            break;
        }
    }
    if (parentPanel) {
        updateSubMenuVisibility(parentPanel);
    } else if (panel === 'scripts' || panel === 'docker') {
        updateSubMenuVisibility(panel);
    } else {
        var showSubMenus = localStorage.getItem('showSubMenus') !== 'false';
        if (!showSubMenus) {
            for (var key in subMenuItems) {
                if (subMenuItems[key]) {
                    subMenuItems[key].style.display = 'none';
                }
            }
        }
    }

    // Docker面板特殊处理
    if (panel === 'docker') {
        setTimeout(function() {
            updateContainerButtons();
            updateContainerSelectStatus();
        }, 100);
    }

    // 自动刷新
    if (panel === 'topics') loadTopics();
    if (panel === 'nodes') loadNodes();
    if (panel === 'services') loadServices();
    if (panel === 'actions') loadActions();
    if (panel === 'docker') loadContainers(false, 'ros2_');
    if (panel === 'scripts') { loadLaunchFiles(); }
    if (panel === 'images') loadImages();
    if (panel === 'monitor') loadMonitor();
    if (panel === 'settings') {
        checkSystemStatus();
        var container = document.getElementById('systemLogContainer');
        if (container && container.children.length === 1 && container.children[0].textContent === '系统日志将在此显示...') {
            container.innerHTML = '';
        }
        // 检查帮助文档配置卡片是否已展开，如果是则加载内容
        var helpContent = document.getElementById('settings-help-content');
        if (helpContent && helpContent.classList.contains('expanded')) {
            loadHelpContent();
        }
        updateUserInfo();
        if (window.userRole === 'admin') {
            loadUserList();
        }
    }
    if (panel === 'traffic') { checkTrafficStatus(); checkTimerTrafficStatus(); startTrafficPanelMonitor(); }
    if (panel === 'welcome') { updateWelcomeStatus(); checkInstallStatus(); }
    if (panel === 'vehicle') {
        loadScripts();
        // ★★★ 按需加载仿真车配置列表（首次进入面板时加载） ★★★
        if (typeof _truckConfigLoaded === 'undefined' || !_truckConfigLoaded) {
            _truckConfigLoaded = true;
            loadTruckConfigList();
        }
    }
    if (panel === 'scripts') loadDefaultPaths(true);
    if (panel === 'advanced-docker') { loadAdvContainers(); loadWhitelist(); loadCommitContainers(); }
    if (panel === 'advanced-scripts') loadScriptsForRetry();
    if (panel === 'api-manager') { loadApiMgrSettings(); }

    if (panel === 'advanced-extend') { loadRemoteHosts(); loadPlugins(); loadApiSettings(); }
    if (panel === 'advanced-fault') { 
        loadFaultContainers(); 
        clearFaultHistoryDisplay();
    }
    if (panel === 'tickets') { loadTicketsMeta(); loadTickets(1); }
    if (panel === 'settings') {
        if (!helpPagesLoaded) {
            loadHelpPages().then(function() {
                if (helpPagesCache.length > 0) {
                    loadHelpContent(helpPagesCache[0].id);
                }
            });
        }
    }
    
    loadHelpContent(panel);
    
    // 如果帮助面板正在显示，自动同步帮助内容
    var helpModal = document.getElementById('helpPanelModal');
    if (helpModal && helpModal.classList.contains('visible')) {
        syncHelpTabWithCurrentPanel();
    }
    
    // 通知引导系统面板已切换
    if (typeof Onboarding !== 'undefined' && Onboarding.notifyPanelSwitch) {
        setTimeout(function() { Onboarding.notifyPanelSwitch(panel); }, 500);
    }
}

/**
 * 刷新当前面板
 */
function refreshCurrentPanel() {
    switchPanel(currentPanel);
}

// ========== 预留扩展区域（第101-150行） ==========
// 预留用于未来扩展，如面板切换动画、路由等
// 101. 面板切换动画
// 102. 路由管理
// 103. ... 最多预留50行
// ===========================================

// ============================================================
// 4. API 工具函数（带认证）
// ============================================================

/**
 * 处理 apiGet 相关前端逻辑。
 */
/**
 * 从 API 返回对象中安全提取错误消息，避免 [object Object]。
 * @param {object} d - apiPost/apiGet 返回的对象
 * @param {string} fallback - 默认提示
 */
function _errMsg(d, fallback) {
    if (!d) return fallback || '操作失败';
    if (typeof d === 'string') return d;
    var msg = d.error || d.message || d.detail;
    if (msg === undefined || msg === null) return fallback || '操作失败';
    if (typeof msg === 'string') return msg;
    if (Array.isArray(msg)) {
        return msg.map(function(e) {
            if (e && e.loc) return e.loc.join('.') + ': ' + (e.msg || '');
            return String(e);
        }).join('; ');
    }
    if (typeof msg === 'object') {
        try { return JSON.stringify(msg); } catch(_) { return fallback || '操作失败'; }
    }
    return String(msg);
}

function _parseErrorResponse(res, text) {
    try {
        var json = JSON.parse(text);
        var err = json.detail || json.error || json.message;
        // FastAPI 422 验证错误时 detail 是数组 [{type,loc,msg,input}]，需转为可读字符串
        if (Array.isArray(err)) {
            err = err.map(function(e) {
                if (e && e.loc) return (e.loc.join('.') + ': ' + (e.msg || ''));
                return String(e);
            }).join('; ');
        } else if (err && typeof err === 'object') {
            err = JSON.stringify(err);
        } else if (err === undefined || err === null) {
            err = '服务器错误 ' + res.status;
        }
        return { success: false, error: String(err) };
    } catch(e) {
        return { success: false, error: '服务器错误 ' + res.status + ': ' + text.substring(0, 200) };
    }
}

function apiGet(path) {
    return fetch(API_BASE + path, {
        method: 'GET',
        headers: getAuthHeaders()
    })
    .then(function(res) {
        if (res.status === 401) {
            handleLogout();
            return { success: false, error: '未授权，请重新登录' };
        }
        if (!res.ok) {
            return res.text().then(function(text) {
                return _parseErrorResponse(res, text);
            });
        }
        return res.json();
    })
    .catch(function(e) {
        showToast('请求失败: ' + e.message, 'error');
        return { success: false, error: e.message };
    });
}

/**
 * 自定义确认对话框（替代系统 confirm()）
 * @param {string} message - 提示消息
 * @param {function} onConfirm - 用户点击"确定"时的回调
 * @param {string} okText - 确定按钮文字（可选）
 * @param {function} onCancel - 用户点击"取消"时的回调（可选）
 */
function customConfirm(message, onConfirm, okText, onCancel) {
    var modal = document.getElementById('customConfirmModal');
    var msgEl = document.getElementById('customConfirmMessage');
    var okBtn = document.getElementById('customConfirmOk');
    var cancelBtn = document.getElementById('customConfirmCancel');
    if (!modal || !msgEl || !okBtn || !cancelBtn) {
        if (confirm(message)) { if (onConfirm) onConfirm(); }
        else { if (onCancel) onCancel(); }
        return;
    }
    msgEl.textContent = message;
    okBtn.textContent = okText || '确定';
    modal.style.display = 'flex';
    var newOk = okBtn.cloneNode(true);
    var newCancel = cancelBtn.cloneNode(true);
    okBtn.parentNode.replaceChild(newOk, okBtn);
    cancelBtn.parentNode.replaceChild(newCancel, cancelBtn);
    newOk.addEventListener('click', function() {
        modal.style.display = 'none';
        if (onConfirm) onConfirm();
    });
    newCancel.addEventListener('click', function() {
        modal.style.display = 'none';
        if (onCancel) onCancel();
    });
    modal.addEventListener('click', function(e) {
        if (e.target === modal) { modal.style.display = 'none'; if (onCancel) onCancel(); }
    });
}

/**
 * 处理 apiPost 相关前端逻辑。
 */
function apiPost(path, body) {
    body = body || {};
    return fetch(API_BASE + path, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify(body)
    })
    .then(function(res) {
        if (res.status === 401) {
            handleLogout();
            return { success: false, error: '未授权，请重新登录' };
        }
        if (!res.ok) {
            return res.text().then(function(text) {
                return _parseErrorResponse(res, text);
            });
        }
        return res.json();
    })
    .catch(function(e) {
        showToast('请求失败: ' + e.message, 'error');
        return { success: false, error: e.message };
    });
}

/**
 * 处理 apiDelete 相关前端逻辑。
 */
function apiDelete(path, data) {
    var options = {
        method: 'DELETE',
        headers: getAuthHeaders()
    };
    if (data) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(data);
    }
    return fetch(API_BASE + path, options)
    .then(function(res) {
        if (res.status === 401) {
            handleLogout();
            return { success: false, error: '未授权，请重新登录' };
        }
        if (!res.ok) {
            return res.text().then(function(text) {
                return _parseErrorResponse(res, text);
            });
        }
        return res.json();
    })
    .catch(function(e) {
        showToast('请求失败: ' + e.message, 'error');
        return { success: false, error: e.message };
    });
}

/**
 * 处理 apiPut 相关前端逻辑。
 */
function apiPut(path, body) {
    body = body || {};
    return fetch(API_BASE + path, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify(body)
    })
    .then(function(res) {
        if (res.status === 401) {
            handleLogout();
            return { success: false, error: '未授权，请重新登录' };
        }
        if (!res.ok) {
            return res.text().then(function(text) {
                return _parseErrorResponse(res, text);
            });
        }
        return res.json();
    })
    .catch(function(e) {
        showToast('请求失败: ' + e.message, 'error');
        return { success: false, error: e.message };
    });
}

// ========== 预留扩展区域（第151-200行） ==========
// 预留用于未来扩展，如API缓存、重试机制等
// 151. API 缓存
// 152. 重试机制
// 153. ... 最多预留50行
// ===========================================

// ============================================================
// 5. Toast 通知
// ============================================================

/**
 * 处理 showToast 相关前端逻辑。
 */
function showToast(msg, type) {
    type = type || 'info';
    var container = document.getElementById('toastContainer');
    
    while (container.children.length >= 3) {
        container.removeChild(container.firstChild);
    }
    
    var toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = msg;
    container.appendChild(toast);
    
    setTimeout(function() {
        toast.classList.add('removing');
        setTimeout(function() {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 300);
    }, 3000);
}

// ========== 预留扩展区域（第201-250行） ==========
// 预留用于未来扩展，如Toast样式增强、动画等
// ===========================================

// ============================================================
// 6. WebSocket 连接
// ============================================================

/**
 * 处理 connectWebSocket 相关前端逻辑。
 */
function connectWebSocket() {
    // 如果已经有连接，先关闭
    if (ws) {
        try {
            ws.close(1000, '重新连接');
        } catch (e) {}
        ws = null;
    }
    
    if (!AUTH_TOKEN) {
        document.getElementById('wsStatus').innerHTML = '🔴 未认证';
        return;
    }
    
    var protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = protocol + '//' + location.host + '/ws?token=' + encodeURIComponent(AUTH_TOKEN);
    
    try {
        ws = new WebSocket(wsUrl);
        var connectTimeout = setTimeout(function() {
            if (ws && ws.readyState === WebSocket.CONNECTING) {
                console.warn('WebSocket 连接超时，正在关闭');
                try { ws.close(1002, '连接超时'); } catch (e) {}
                ws = null;
                document.getElementById('wsStatus').innerHTML = '🔴 连接超时';
                document.getElementById('sysWsStatus').textContent = '❌ 连接超时';
            }
        }, 10000); // 10秒超时
        
        ws.onopen = function() {
            clearTimeout(connectTimeout);
            document.getElementById('wsStatus').innerHTML = '🟢 已连接';
            document.getElementById('sysWsStatus').textContent = '已连接';
            addSystemLog('info', 'WebSocket 连接已建立', Date.now());
        };
        ws.onmessage = function(event) {
            try {
                var msg = JSON.parse(event.data);
                if (msg.type === 'log') {
                    addSystemLog(msg.log_type, msg.data, msg.timestamp);
                } else if (msg.type === 'ping') {
                    // 心跳消息，忽略
                } else if (msg.type === 'traffic_light_status') {
                    handleTrafficLightStatus(msg);
                } else if (msg.type === 'ticket_event') {
                    handleTicketEvent(msg);
                }
            } catch (e) { /* ignore */ }
        };
        ws.onclose = function(event) {
            clearTimeout(connectTimeout);
            document.getElementById('wsStatus').innerHTML = '🔴 已断开';
            document.getElementById('sysWsStatus').textContent = '❌ 已断开';
            console.debug('WebSocket 已断开:', event.code, event.reason);
            
            // 只有在正常认证状态下才自动重连
            if (AUTH_TOKEN && event.code !== 1000) { // 1000 是正常关闭
                setTimeout(connectWebSocket, 5000);
            }
        };
        ws.onerror = function(event) {
            clearTimeout(connectTimeout);
            document.getElementById('wsStatus').innerHTML = '🔴 连接错误';
            document.getElementById('sysWsStatus').textContent = '❌ 连接失败';
            console.error('WebSocket 连接错误:', event);
        };
    } catch (e) {
        console.error('WebSocket 连接失败:', e);
        document.getElementById('wsStatus').innerHTML = '🔴 连接失败';
        document.getElementById('sysWsStatus').textContent = '❌ 连接失败';
    }
}

/**
 * 检查用户是否有指定面板的权限
 * @param {string} panel - 面板标识，如 'traffic', 'docker', 'scripts' 等
 * @returns {boolean} 是否有权限
 */
function hasPermission(panel) {
    // 管理员拥有所有权限
    if (window.userRole === 'admin') return true;
    // 普通用户检查权限列表
    return (window.userPermissions || []).includes(panel);
}

/**
 * 检查用户是否是管理员
 * @returns {boolean}
 */
function isAdmin() {
    return window.userRole === 'admin';
}

/**
 * 根据当前权限显示或隐藏原管理员按钮。
 */
function updateAdminOnlyControls() {
    var visible = isAdmin() || hasPermission('docker');
    document.querySelectorAll('.admin-only').forEach(function(el) {
        el.style.display = visible ? '' : 'none';
    });
}

/**
 * 处理 addSystemLog 相关前端逻辑。
 */
function addSystemLog(type, data, timestamp) {
    var container = document.getElementById('systemLogContainer');
    if (!container) return;
    if (container.children.length === 1 && container.children[0].textContent === '系统日志将在此显示...') {
        container.innerHTML = '';
    }
    var entry = document.createElement('div');
    entry.className = 'log-entry';
    
    // 使用终端风格的时间格式：YYYY-MM-DD HH:MM:SS,mmm
    var now = timestamp ? new Date(timestamp) : new Date();
    var timeStr = now.getFullYear() + '-' + 
                  String(now.getMonth() + 1).padStart(2, '0') + '-' + 
                  String(now.getDate()).padStart(2, '0') + ' ' + 
                  String(now.getHours()).padStart(2, '0') + ':' + 
                  String(now.getMinutes()).padStart(2, '0') + ':' + 
                  String(now.getSeconds()).padStart(2, '0') + ',' + 
                  String(now.getMilliseconds()).padStart(3, '0');
    
    var typeClass = type || 'info';
    var typeStr = typeClass.toUpperCase();
    
    // 检查是否是来自后端的完整日志格式
    if (data && data.includes(' - ') && (data.includes('[INFO]') || data.includes('[WARNING]') || data.includes('[ERROR]'))) {
        // 如果已经是完整格式，直接显示
        entry.textContent = data;
    } else {
        // 否则构建终端风格的日志格式
        entry.innerHTML = '<span style="color:#666">' + timeStr + '</span>' +
                          '<span style="margin:0 4px;color:#666">-</span>' +
                          '<span style="color:#333;font-weight:bold">ros2-web</span>' +
                          '<span style="margin:0 4px;color:#666">-</span>' +
                          '<span style="color:' + (typeClass === 'error' ? '#dc2626' : typeClass === 'warning' ? '#d97706' : '#2563eb') + '">' + typeStr + '</span>' +
                          '<span style="margin:0 4px;color:#666">-</span>' +
                          '<span style="color:#333">' + escapeHtml(data) + '</span>';
    }
    
    container.appendChild(entry);
    container.scrollTop = container.scrollHeight;
    if (container.children.length > 200) {
        container.removeChild(container.firstChild);
    }
}

/**
 * 清理动态 HTML 片段，移除脚本、事件属性和 javascript: URL，降低 XSS 风险。
 */
function sanitizeHTML(html) {
    if (!html) return '';
    var template = document.createElement('template');
    template.innerHTML = String(html);
    template.content.querySelectorAll('script, iframe, object, embed').forEach(function(node) {
        node.remove();
    });
    template.content.querySelectorAll('*').forEach(function(node) {
        Array.prototype.slice.call(node.attributes).forEach(function(attr) {
            var name = attr.name.toLowerCase();
            var value = String(attr.value || '').trim().toLowerCase();
            if (name.indexOf('on') === 0 || value.indexOf('javascript:') === 0) {
                node.removeAttribute(attr.name);
            }
        });
    });
    return template.innerHTML;
}

/**
 * 安全设置元素 HTML 内容，仅用于已清理或已转义的片段。
 */
function setSafeHTML(element, html) {
    if (!element) return;
    element.innerHTML = sanitizeHTML(html);
}

/**
 * 处理 escapeHtml 相关前端逻辑。
 */
function escapeHtml(str) {
    if (!str) return '';
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ========== 预留扩展区域（第251-300行） ==========
// 预留用于未来扩展，如WebSocket重连策略优化等
// ===========================================

// ============================================================
// 7. 系统状态
// ============================================================

/**
 * 处理 checkSystemStatus 相关前端逻辑。
 */
function checkSystemStatus() {
    if (!AUTH_TOKEN) return;
    apiGet('/api/system/status').then(function(data) {
        if (data.success) {
            document.getElementById('ros2Status').className = 'status-dot ' + (data.ros2_available ? 'online' : 'offline');
            document.getElementById('dockerStatus').className = 'status-dot ' + (data.docker_available ? 'online' : 'offline');
            document.getElementById('sysRos2Status').textContent = data.ros2_available ? '可用' : '❌ 不可用';
            document.getElementById('sysDockerStatus').textContent = data.docker_available ? '已连接' : '❌ 未连接';
            document.getElementById('sysInstallStatus').textContent = data.install_dir_exists ? '存在' : '❌ 不存在';
            updateWelcomeStatus();
        }
    });
}

/**
 * 处理 updateWelcomeStatus 相关前端逻辑。
 */
function updateWelcomeStatus() {
    var ros2 = document.getElementById('sysRos2Status') ? document.getElementById('sysRos2Status').textContent : '❓';
    var docker = document.getElementById('sysDockerStatus') ? document.getElementById('sysDockerStatus').textContent : '❓';
    var install = document.getElementById('sysInstallStatus') ? document.getElementById('sysInstallStatus').textContent : '❓';
    var welRos2 = document.getElementById('welcomeRos2Status'); if (welRos2) welRos2.textContent = ros2;
    var welDocker = document.getElementById('welcomeDockerStatus'); if (welDocker) welDocker.textContent = docker;
    var welInstall = document.getElementById('welcomeInstallStatus'); if (welInstall) welInstall.textContent = install;

    // 计算稳定运行时间：当前日期 - 2026/04/10
    var uptimeEl = document.getElementById('welcomeUptime');
    if (uptimeEl) {
        var startDate = new Date('2026-04-10T00:00:00');
        var now = new Date();
        var diffMs = now - startDate;
        if (diffMs >= 0) {
            var days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
            var hours = Math.floor((diffMs % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            var mins = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60));
            uptimeEl.textContent = days + '天' + hours + '小时' + mins + '分';
        } else {
            uptimeEl.textContent = '0天0小时';
        }
    }
}

// ============================================================
// 7.5 安装包管理（上传、检测、目录树）
// ============================================================

/**
 * 检测安装目录状态，显示上传控件或目录树
 */
// v3.6 当前切换的目标用户工作空间（仅管理员可用；普通用户始终为 null）
var currentTargetUser = null;

function getTargetUserParam() {
    return currentTargetUser ? '?target_user=' + encodeURIComponent(currentTargetUser) : '';
}

function appendTargetUser(url) {
    if (!currentTargetUser) return url;
    var sep = url.indexOf('?') >= 0 ? '&' : '?';
    return url + sep + 'target_user=' + encodeURIComponent(currentTargetUser);
}

function checkInstallStatus(forceRefresh) {
    var container = document.getElementById('installStatusContent');
    if (!container) return;
    container.innerHTML = '<div class="skeleton skeleton-block"></div><div class="skeleton skeleton-line" style="width:60%"></div><div class="skeleton skeleton-line" style="width:40%"></div>';

    var url = '/api/install/status' + getTargetUserParam();
    if (forceRefresh) {
        url += (url.indexOf('?') >= 0 ? '&' : '?') + 'refresh=1';
    }
    apiGet(url).then(function(data) {
        if (!data.success) {
            container.innerHTML = '<p style="color:var(--text-secondary)">检测失败: ' + (data.error || '未知错误') + '</p>';
            return;
        }
        renderInstallStatus(data);
        updateToolsWorkspaceBar(data);
    }).catch(function(err) {
        container.innerHTML = '<p style="color:var(--text-secondary)">检测失败</p>';
    });
}

/**
 * 更新 "⚙️ install 配置" 面板顶部的工作空间路径展示栏（只读）。
 * 管理员切换到普通用户空间时显示，展示当前操作的 install/bk/bags/logs 路径。
 * 各目录不存在时给出友好提示：
 *   - install 不存在：提示先上传安装包
 *   - bk 不存在：提示联系管理员
 *   - bags/logs 不存在：提示启动仿真车辆会自动生成
 */
function updateToolsWorkspaceBar(data) {
    var bar = document.getElementById('toolsWorkspaceBar');
    if (!bar) return;
    var isAdmin = window.userRole === 'admin';
    var tu = data.target_user || null;

    if (!isAdmin) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'block';

    var label = document.getElementById('toolsWorkspaceLabel');
    var pInstall = document.getElementById('toolsPathInstall');
    var pBk = document.getElementById('toolsPathBk');
    var pBags = document.getElementById('toolsPathBags');
    var pLogs = document.getElementById('toolsPathLogs');

    if (tu) {
        label.textContent = '当前操作空间：👤 ' + tu;
        label.style.color = '#b8550a';
    } else {
        label.textContent = '当前操作空间：📌 我的工作空间（admin）';
        label.style.color = '#2c5aa0';
    }

    var ds = data.dirs_status || {};

    function renderDir(spanEl, path, dirKey, hintIfMissing) {
        if (!spanEl) return;
        var info = ds[dirKey];
        var exists = info ? info.exists : (path ? true : false);
        if (exists) {
            spanEl.innerHTML = '<span style="color:#2d7d32;font-weight:600;">✓</span> <span style="color:#333;">' + escapeHtml(path || '-') + '</span>';
        } else {
            spanEl.innerHTML = '<span style="color:#c62828;font-weight:600;">✗</span> <span style="color:#999;text-decoration:line-through;">' + escapeHtml(path || '-') + '</span> <span style="color:#c62828;font-size:10px;margin-left:6px;">（' + hintIfMissing + '）</span>';
        }
    }

    renderDir(pInstall, data.host_install, 'install', '请先上传安装包');
    renderDir(pBk,      data.host_bk,      'bk',      '请工单联系管理员');
    renderDir(pBags,    data.host_bags,    'bags',    '请工单联系管理员');
    renderDir(pLogs,    data.host_logs,    'logs',    '启动仿真车辆后自动生成');
}

function renderInstallStatus(data) {
    var container = document.getElementById('installStatusContent');
    var html = '';

    if (data.exists && data.has_setup_bash) {
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">';
        html += '<span style="font-size:24px;">✅</span>';
        html += '<div><div style="font-weight:600;color:var(--text-primary);">安装包已就绪';
        if (data.target_user) html += ' <span style="font-size:12px;color:var(--text-secondary);">（用户: ' + escapeHtml(data.target_user) + '）</span>';
        html += '</div>';
        html += '<div style="font-size:13px;color:var(--text-secondary);">' + data.host_install + '</div></div></div>';
        html += '<div style="margin:8px 0;">';
        html += '<button class="btn btn-sm btn-outline" id="toggleTreeBtn" onclick="toggleInstallTree()">📂 查看目录内容</button>';
        html += '</div>';
        html += '<div class="install-tree" id="installTreeContainer" style="display:none;"></div>';
        html += '<div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">';
        html += '<button class="btn btn-sm btn-outline" onclick="checkInstallStatus()">🔄 刷新</button>';
        html += '<button class="btn btn-sm btn-outline" onclick="showUploadZone()">📤 重新上传</button>';
        // 普通用户可删除自己空间的install，管理员可删除任意用户的
        var canDelete = !data.target_user || window.userRole === 'admin';
        if (canDelete) {
            html += '<button class="btn btn-sm btn-danger" onclick="deleteInstall()" style="margin-left:auto;">🗑️ 删除安装包</button>';
        }
        html += '</div>';
        // 显示 v3.6 部署栏
        var deployBar = document.getElementById('installDeployBar');
        if (deployBar) deployBar.style.display = 'block';
    } else if (data.exists && !data.has_setup_bash) {
        html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;">';
        html += '<span style="font-size:24px;">⚠️</span>';
        html += '<div><div style="font-weight:600;color:#856404;">install目录存在但setup.bash缺失</div>';
        html += '<div style="font-size:13px;color:var(--text-secondary);">请重新上传正确的安装包</div></div></div>';
        html += renderUploadZone();
        var deployBar2 = document.getElementById('installDeployBar');
        if (deployBar2) deployBar2.style.display = 'none';
    } else {
        html += '<div style="text-align:center;padding:10px 0;color:var(--text-secondary);margin-bottom:12px;">';
        html += '<div style="font-size:32px;margin-bottom:8px;">📭</div>';
        html += '<div>未检测到安装包，请上传 install.zip / .tar.gz / .tgz / .tar.bz2</div></div>';
        html += renderUploadZone();
        var deployBar3 = document.getElementById('installDeployBar');
        if (deployBar3) deployBar3.style.display = 'none';
    }

    container.innerHTML = html;

    if (data.exists && data.has_setup_bash && data.tree) {
        renderTree(document.getElementById('installTreeContainer'), data.tree, 0);
    }
}

function renderUploadZone() {
    var html = '<div class="upload-zone" id="uploadZone" onclick="document.getElementById(\'installFileInput\').click()">';
    html += '<div style="font-size:36px;margin-bottom:8px;">📁</div>';
    html += '<div style="font-weight:600;margin-bottom:4px;">点击或拖拽文件到此处上传</div>';
    html += '<div style="font-size:13px;color:var(--text-secondary);"></div>';
    html += '<input type="file" id="installFileInput" accept=".zip,.tar.gz,.tgz,.tar.bz2,.tar" style="display:none;" onchange="handleInstallUpload(this)">';
    html += '</div>';
    html += '<div class="progress-bar-container" id="uploadProgress">';
    html += '<div class="progress-bar-fill" id="uploadProgressBar"></div></div>';
    html += '<div id="uploadStatusText" style="text-align:center;margin-top:8px;font-size:13px;color:var(--text-secondary);"></div>';
    return html;
}

function showUploadZone() {
    var container = document.getElementById('installStatusContent');
    container.innerHTML = renderUploadZone();
}

function deleteInstall() {
    if (!confirm('确定要删除当前install安装包吗？\n\n注意：删除后会自动备份，如需恢复可联系管理员。')) {
        return;
    }

    showToast('正在删除安装包...', 'info');
    // target_user 通过 query 参数传递（与 upload/clear-all 一致），后端定义为查询参数
    apiPost(appendTargetUser('/api/install/delete'), {}).then(function(d) {
        if (d.success) {
            showToast(d.message || '删除成功', 'success');
            // 刷新状态
            setTimeout(function() {
                checkInstallStatus(true);
            }, 500);
        } else {
            showToast(d.error || '删除失败', 'error');
        }
    }).catch(function(err) {
        showToast('删除请求失败: ' + err.message, 'error');
    });
}

function handleInstallUpload(input) {
    var file = input.files[0];
    if (!file) return;
    // v3.6: 支持多种压缩格式
    var name = file.name.toLowerCase();
    var supported = ['.zip', '.tar.gz', '.tgz', '.tar.bz2', '.tar'];
    var ok = false;
    for (var i = 0; i < supported.length; i++) {
        if (name.endsWith(supported[i])) { ok = true; break; }
    }
    if (!ok) {
        showToast('仅支持 .zip / .tar.gz / .tgz / .tar.bz2 / .tar 格式文件', 'warning');
        return;
    }

    var zone = document.getElementById('uploadZone');
    var progressContainer = document.getElementById('uploadProgress');
    var progressBar = document.getElementById('uploadProgressBar');
    var statusText = document.getElementById('uploadStatusText');

    if (zone) zone.classList.add('uploading');
    if (progressContainer) progressContainer.style.display = 'block';
    if (statusText) statusText.textContent = '正在上传 ' + file.name + ' (' + formatSize(file.size) + ')...';

    var formData = new FormData();
    formData.append('file', file);

    var xhr = new XMLHttpRequest();
    xhr.open('POST', appendTargetUser(API_BASE + '/api/install/upload'));

    var token = getAuthToken();
    if (token) xhr.setRequestHeader('Authorization', 'Bearer ' + token);

    xhr.upload.onprogress = function(e) {
        if (e.lengthComputable) {
            var pct = Math.round((e.loaded / e.total) * 100);
            if (progressBar) progressBar.style.width = pct + '%';
            if (statusText) statusText.textContent = '正在上传... ' + pct + '% (' + formatSize(e.loaded) + '/' + formatSize(e.total) + ')';
        }
    };

    xhr.onload = function() {
        if (zone) zone.classList.remove('uploading');
        try {
            var resp = JSON.parse(xhr.responseText);
            if (resp.success) {
                showToast('安装包上传并解压成功' + (resp.target_user ? '（用户: ' + resp.target_user + '）' : ''), 'success');
                checkInstallStatus(true);
                checkSystemStatus();
                if (typeof Onboarding !== 'undefined' && Onboarding.notifyUploadComplete) {
                    setTimeout(function() { Onboarding.notifyUploadComplete(); }, 2000);
                }
            } else {
                if (statusText) statusText.innerHTML = '<span style="color:#dc3545;">❌ ' + (resp.error || '上传失败') + '</span>';
                showToast(resp.error || '上传失败', 'error');
            }
        } catch (e) {
            if (statusText) statusText.innerHTML = '<span style="color:#dc3545;">❌ 解析响应失败</span>';
        }
    };

    xhr.onerror = function() {
        if (zone) zone.classList.remove('uploading');
        if (statusText) statusText.innerHTML = '<span style="color:#dc3545;">❌ 网络错误</span>';
    };

    xhr.send(formData);
}

function toggleInstallTree() {
    var treeContainer = document.getElementById('installTreeContainer');
    var toggleBtn = document.getElementById('toggleTreeBtn');
    if (!treeContainer || !toggleBtn) return;

    if (treeContainer.style.display === 'none') {
        treeContainer.style.display = 'block';
        toggleBtn.innerHTML = '📁 收起目录';
    } else {
        treeContainer.style.display = 'none';
        toggleBtn.innerHTML = '📂 查看目录内容';
    }
}

function renderTree(container, node, depth) {
    if (!container || !node) return;
    var indent = depth * 16;
    var icon = node.type === 'dir' ? '📁' : '📄';
    var cls = node.type === 'dir' ? 'tree-dir' : 'tree-file';
    var name = node.name || node.path;

    var div = document.createElement('div');
    div.style.paddingLeft = indent + 'px';
    div.className = cls;
    div.innerHTML = icon + ' ' + name;
    container.appendChild(div);

    if (node.children) {
        for (var i = 0; i < node.children.length; i++) {
            renderTree(container, node.children[i], depth + 1);
        }
    }
}

function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
}

// 拖拽上传支持
document.addEventListener('DOMContentLoaded', function() {
    document.addEventListener('dragover', function(e) {
        var zone = document.getElementById('uploadZone');
        if (zone) { e.preventDefault(); zone.classList.add('dragover'); }
    });
    document.addEventListener('dragleave', function(e) {
        var zone = document.getElementById('uploadZone');
        if (zone) zone.classList.remove('dragover');
    });
    document.addEventListener('drop', function(e) {
        var zone = document.getElementById('uploadZone');
        if (zone) {
            e.preventDefault();
            zone.classList.remove('dragover');
            var file = e.dataTransfer.files[0];
            if (file && file.name.toLowerCase().endsWith('.zip')) {
                var input = document.getElementById('installFileInput');
                if (input) {
                    var dt = new DataTransfer();
                    dt.items.add(file);
                    input.files = dt.files;
                    handleInstallUpload(input);
                }
            }
        }
    });
});

/**
 * 处理 restartService 相关前端逻辑。
 */
function restartService() {
    customConfirm('确定要重启 Web 服务吗？', function() {
    });
    showToast('正在重启...', 'warning');
    apiPost('/api/system/restart').then(function() {
        setTimeout(function() { location.reload(); }, 3000);
    });
}

// ========== 预留扩展区域（第301-350行） ==========
// 预留用于未来扩展，如系统状态轮询增强等
// ===========================================

// ============================================================
// 8. 仿真控制
// ============================================================

/**
 * 处理 startSimulation 相关前端逻辑。
 */
function startSimulation() {
    var cmd = document.getElementById('launchCmd').value.trim();
    if (!cmd) { showToast('请输入启动命令', 'warning'); return; }
    var containerId = getRos2PanelContainerId('sim');
    if (!containerId) {
        showToast('请先在上方选择目标容器', 'warning');
        return;
    }
    showToast('正在启动...', 'info');
    apiPost('/api/ros2/simulation/start', { command: cmd, container_id: containerId }).then(function(data) {
        showToast(data.success ? '启动成功' : '失败: ' + (data.error || ''), data.success ? 'success' : 'error');
    });
}

/**
 * 处理 updateSliderVal 相关前端逻辑。
 */
function updateSliderVal() {
    var linear = parseFloat(document.getElementById('linearSlider').value);
    var angular = parseFloat(document.getElementById('angularSlider').value);
    document.getElementById('linearVal').textContent = linear.toFixed(2);
    document.getElementById('angularVal').textContent = angular.toFixed(2);
}

/**
 * 处理 sendSliderVel 相关前端逻辑。
 */
function sendSliderVel() {
    var lx = parseFloat(document.getElementById('linearSlider').value);
    var az = parseFloat(document.getElementById('angularSlider').value);
    var topic = document.getElementById('cmdVelTopic').value.trim() || '/cmd_vel';
    sendVelRaw(lx, az, topic);
}

/**
 * 处理 sendVel 相关前端逻辑。
 */
function sendVel(lx, az) {
    var topic = document.getElementById('cmdVelTopic').value.trim() || '/cmd_vel';
    sendVelRaw(lx, az, topic);
}

/**
 * 处理 sendVelRaw 相关前端逻辑。
 */
function sendVelRaw(lx, az, topic) {
    var containerId = getRos2PanelContainerId('sim');
    apiPost('/api/ros2/cmd_vel', { linear_x: lx, angular_z: az, topic: topic, container_id: containerId }).then(function(data) {
        if (!data.success) showToast('发送失败: ' + (data.error || ''), 'error');
    });
}

// ========== 预留扩展区域（第351-400行） ==========
// 预留用于未来扩展，如仿真参数预设、录制回放等
// ===========================================

// ============================================================
// 9. 话题管理
// ============================================================

/**
 * 处理 filterTopics 相关前端逻辑。
 */
function filterTopics() {
    var keyword = document.getElementById('topicFilter').value.toLowerCase();
    var rows = document.querySelectorAll('#topicsTableBody tr');
    rows.forEach(function(row) {
        var name = row.getAttribute('data-topic-name') || '';
        row.style.display = name.toLowerCase().includes(keyword) ? '' : 'none';
    });
}

/**
 * 加载话题列表（含权限控制）
 */
function loadTopics() {
    var containerId = getRos2PanelContainerId('topics');
    var tbody = document.getElementById('topicsTableBody');
    if (!containerId) {
        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">请先在上方选择目标容器</td></tr>';
        return;
    }
    tbody.innerHTML = '<tr><td colspan="2" style="text-align:center"><span class="loading"></span> 加载中...</td></tr>';
    apiGet('/api/ros2/topics?container_id=' + encodeURIComponent(containerId)).then(function(data) {
        if (!data.success) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--error)">失败: ' +
                escapeHtml(data.error || '') + '</td></tr>';
            return;
        }
        if (!data.topics || !data.topics.length) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">没有活跃话题</td></tr>';
            return;
        }

        // ★★★ 判断是否为管理员 ★★★
        var isAdmin = (window.userRole === 'admin');

        var html = '';
        for (var i = 0; i < data.topics.length; i++) {
            var t = data.topics[i];
            html += '<tr data-topic-name="' + escapeHtml(t) + '">' +
                '<td><code>' + escapeHtml(t) + '</code></td>' +
                '<td>' +
                '<button class="btn btn-sm" onclick="viewTopic(\'' + escapeHtml(t) + '\')">📋 查看</button> ' +
                '<button class="btn btn-sm btn-outline" onclick="echoTopic(\'' + escapeHtml(t) + '\')">👁 Echo</button> ';
            if (isAdmin) {
                html += '<button class="btn btn-sm btn-success" onclick="pubTopic(\'' + escapeHtml(t) + '\')">📤 Pub</button> ';
                html += '<button class="btn btn-sm btn-error" onclick="killTopic(\'' + escapeHtml(t) + '\')">⏹ 停止</button>';
            } else {
                html += '<span style="color:var(--text-muted);font-size:11px;">只读</span>';
            }
            html += '</td></tr>';
        }
        tbody.innerHTML = html;
    });
}

/**
 * 处理 pubTopic 相关前端逻辑。
 */
function pubTopic(name) {
    var containerId = getRos2PanelContainerId('topics');
    if (!containerId) {
        showToast('请先选择容器', 'warning');
        return;
    }
    var cleanName = name.startsWith('/') ? name.substring(1) : name;
    apiGet('/api/ros2/topic/' + encodeURIComponent(cleanName) + '/info?container_id=' + encodeURIComponent(containerId)).then(function(data) {
        var msgType = 'std_msgs/msg/String';
        if (data.info) {
            var match = data.info.match(/Type:\s*([^\n]+)/);
            if (match) msgType = match[1].trim();
        }
        var msg = prompt('请输入要发布的消息（JSON格式）:', '{"data": "hello"}');
        if (msg === null) return;
        showToast('正在发布...', 'info');
        apiPost('/api/ros2/topic/pub', {
            container_id: containerId,
            topic: name,
            msg_type: msgType,
            data: msg
        }).then(function(d) {
            showToast(d.success ? '发布成功' : '发布失败: ' + (d.error || ''), d.success ? 'success' : 'error');
        });
    });
}

/**
 * 处理 killTopic 相关前端逻辑。
 */
function killTopic(name) {
    var containerId = getRos2PanelContainerId('topics');
    if (!containerId) {
        showToast('请先选择容器', 'warning');
        return;
    }
    customConfirm('确定要停止话题 ' + name + ' 吗？（将尝试杀死发布该话题的节点）', function() {
    });
    showToast('正在停止...', 'info');
    apiPost('/api/ros2/topic/kill', {
        container_id: containerId,
        topic: name
    }).then(function(d) {
        showToast(d.success ? '停止成功' : '停止失败: ' + (d.error || ''), d.success ? 'success' : 'error');
        if (d.success) setTimeout(loadTopics, 1000);
    });
}

/**
 * 处理 viewTopic 相关前端逻辑。
 */
function viewTopic(name) {
    var containerId = getRos2PanelContainerId('topics');
    document.getElementById('topicDetailCard').style.display = 'block';
    document.getElementById('topicDetailName').textContent = name;
    document.getElementById('topicDetailContent').innerHTML = '<span class="loading"></span> 加载中...';
    var url = '/api/ros2/topic/' + name + '/info';
    if (containerId) url += '?container_id=' + encodeURIComponent(containerId);
    apiGet(url).then(function(data) {
        if (data.success) {
            document.getElementById('topicDetailContent').innerHTML = '<pre style="white-space:pre-wrap;font-size:12px">' + escapeHtml(data.info || '无数据') + '</pre>';
        } else {
            document.getElementById('topicDetailContent').innerHTML = '<pre style="white-space:pre-wrap;font-size:12px;color:var(--error)">❌ ' + escapeHtml(data.error || '获取失败') + '</pre>';
            showToast('获取话题信息失败: ' + (data.error || ''), 'error');
        }
    });
}

/**
 * 处理 echoTopic 相关前端逻辑。
 */
function echoTopic(name) {
    var containerId = getRos2PanelContainerId('topics');
    showToast('正在获取...', 'info');
    var url = '/api/ros2/topic/' + name + '/echo?once=true';
    if (containerId) url += '&container_id=' + encodeURIComponent(containerId);
    apiGet(url).then(function(data) {
        document.getElementById('topicDetailCard').style.display = 'block';
        document.getElementById('topicDetailName').textContent = name + ' (Echo)';
        if (data.success) {
            document.getElementById('topicDetailContent').innerHTML = '<pre style="white-space:pre-wrap;font-size:12px">' + escapeHtml(data.data || '✅ 执行成功（无数据输出）') + '</pre>';
            showToast('获取成功', 'success');
        } else {
            document.getElementById('topicDetailContent').innerHTML = '<pre style="white-space:pre-wrap;font-size:12px;color:var(--error)">❌ ' + escapeHtml(data.error || '获取失败') + '</pre>';
            showToast('获取失败: ' + (data.error || ''), 'error');
        }
    });
}

// ========== 预留扩展区域（第401-450行） ==========
// 预留用于未来扩展，如话题监控、告警等
// ===========================================

// ============================================================
// 10. 节点管理
// ============================================================

/**
 * 处理 filterNodes 相关前端逻辑。
 */
function filterNodes() {
    var keyword = document.getElementById('nodeFilter').value.toLowerCase();
    var rows = document.querySelectorAll('#nodesTableBody tr');
    rows.forEach(function(row) {
        var name = row.getAttribute('data-node-name') || '';
        row.style.display = name.toLowerCase().includes(keyword) ? '' : 'none';
    });
}

/**
 * 加载节点列表（含权限控制）
 */
function loadNodes() {
    var containerId = getRos2PanelContainerId('nodes');
    var tbody = document.getElementById('nodesTableBody');
    if (!containerId) {
        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">请先在上方选择目标容器</td></tr>';
        return;
    }
    tbody.innerHTML = '<tr><td colspan="2" style="text-align:center">⏳ 加载中...</td></tr>';
    apiGet('/api/ros2/nodes?container_id=' + encodeURIComponent(containerId)).then(function(data) {
        if (!data.success) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--error)">❌ ' +
                escapeHtml(data.error || '执行失败，请确认容器内 ROS2 环境已加载') + '</td></tr>';
            return;
        }
        if (!data.nodes || !data.nodes.length) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">没有运行中的节点</td></tr>';
            return;
        }

        // ★★★ 判断是否为管理员 ★★★
        var isAdmin = (window.userRole === 'admin');

        var html = '';
        for (var i = 0; i < data.nodes.length; i++) {
            var n = data.nodes[i];
            html += '<tr data-node-name="' + escapeHtml(n) + '">' +
                '<td><code>' + escapeHtml(n) + '</code></td>' +
                '<td>' +
                '<button class="btn btn-sm" onclick="viewNode(\'' + escapeHtml(n) + '\')">📋 详情</button> ';
            if (isAdmin) {
                html += '<button class="btn btn-sm btn-error" onclick="killNode(\'' + escapeHtml(n) + '\')">⏹ 停止</button>';
            } else {
                html += '<span style="color:var(--text-muted);font-size:11px;">只读</span>';
            }
            html += '</td></tr>';
        }
        tbody.innerHTML = html;
    }).catch(function(err) {
        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--error)">❌ 请求失败: ' + escapeHtml(err.message) + '</td></tr>';
    });
}

/**
 * 处理 killNode 相关前端逻辑。
 */
function killNode(name) {
    var containerId = getRos2PanelContainerId('nodes');
    if (!containerId) {
        showToast('请先选择容器', 'warning');
        return;
    }
    customConfirm('确定要停止节点 ' + name + ' 吗？', function() {
    });
    showToast('正在停止...', 'info');
    apiPost('/api/ros2/node/kill', {
        container_id: containerId,
        node: name
    }).then(function(d) {
        showToast(d.success ? '停止成功' : '停止失败: ' + (d.error || ''), d.success ? 'success' : 'error');
        if (d.success) setTimeout(loadNodes, 1000);
    });
}

/**
 * 处理 viewNode 相关前端逻辑。
 */
function viewNode(name) {
    var containerId = getRos2PanelContainerId('nodes');
    document.getElementById('nodeDetailCard').style.display = 'block';
    document.getElementById('nodeDetailName').textContent = name;
    document.getElementById('nodeDetailContent').textContent = '加载中...';
    var url = '/api/ros2/node/' + name + '/info';
    if (containerId) url += '?container_id=' + encodeURIComponent(containerId);
    apiGet(url).then(function(data) {
        if (data.success) {
            document.getElementById('nodeDetailContent').textContent = data.info || '无信息';
        } else {
            document.getElementById('nodeDetailContent').textContent = '❌ 获取失败: ' + (data.error || '请确认节点是否存在');
            showToast('获取节点信息失败', 'warning');
        }
    });
}

// ========== 预留扩展区域（第451-500行） ==========
// 预留用于未来扩展，如节点监控、自动重启等
// ===========================================

// ============================================================
// 11. 服务管理
// ============================================================

/**
 * 处理 filterServices 相关前端逻辑。
 */
function filterServices() {
    var keyword = document.getElementById('serviceFilter').value.toLowerCase();
    var rows = document.querySelectorAll('#servicesTableBody tr');
    rows.forEach(function(row) {
        var name = row.getAttribute('data-service-name') || '';
        row.style.display = name.toLowerCase().includes(keyword) ? '' : 'none';
    });
}

/**
 * 加载服务列表（含权限控制）
 */
function loadServices() {
    var containerId = getRos2PanelContainerId('services');
    var tbody = document.getElementById('servicesTableBody');
    if (!containerId) {
        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">请先在上方选择目标容器</td></tr>';
        return;
    }
    tbody.innerHTML = '<tr><td colspan="2" style="text-align:center"><span class="loading"></span> 加载中...</td></tr>';
    apiGet('/api/ros2/services?container_id=' + encodeURIComponent(containerId)).then(function(data) {
        if (!data.success) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--error)">失败: ' +
                escapeHtml(data.error || '') + '</td></tr>';
            return;
        }
        if (!data.services || !data.services.length) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">没有可用服务</td></tr>';
            return;
        }

        // ★★★ 判断是否为管理员 ★★★
        var isAdmin = (window.userRole === 'admin');

        var html = '';
        for (var i = 0; i < data.services.length; i++) {
            var s = data.services[i];
            html += '<tr data-service-name="' + escapeHtml(s) + '">' +
                '<td><code>' + escapeHtml(s) + '</code></td>' +
                '<td>' +
                '<button class="btn btn-sm" onclick="prepareServiceCall(\'' + escapeHtml(s) + '\')">📞 调用</button> ';
            if (isAdmin) {
                html += '<button class="btn btn-sm btn-error" onclick="killService(\'' + escapeHtml(s) + '\')">⏹ 停止</button>';
            } else {
                html += '<span style="color:var(--text-muted);font-size:11px;">只读</span>';
            }
            html += '</td></tr>';
        }
        tbody.innerHTML = html;
    });
}

/**
 * 处理 killService 相关前端逻辑。
 */
function killService(name) {
    var containerId = getRos2PanelContainerId('services');
    if (!containerId) {
        showToast('请先选择容器', 'warning');
        return;
    }
    customConfirm('确定要停止服务 ' + name + ' 吗？', function() {
    });
    showToast('正在停止...', 'info');
    apiPost('/api/ros2/service/kill', {
        container_id: containerId,
        service: name
    }).then(function(d) {
        showToast(d.success ? '停止成功' : '停止失败: ' + (d.error || ''), d.success ? 'success' : 'error');
        if (d.success) setTimeout(loadServices, 1000);
    });
}

/**
 * 处理 prepareServiceCall 相关前端逻辑。
 */
function prepareServiceCall(name) {
    var containerId = getRos2PanelContainerId('services');
    document.getElementById('serviceCallCard').style.display = 'block';
    document.getElementById('serviceCallName').textContent = name;
    document.getElementById('serviceCallType').textContent = '查询中...';
    document.getElementById('serviceCallData').value = '';
    document.getElementById('serviceCallResult').textContent = '';
    window._currentServiceName = name;
    var url = '/api/ros2/service/' + name + '/type';
    if (containerId) url += '?container_id=' + encodeURIComponent(containerId);
    apiGet(url).then(function(data) {
        document.getElementById('serviceCallType').textContent = data.type || '未知';
        window._currentServiceType = data.type || '';
    });
}

/**
 * 处理 callServiceAction 相关前端逻辑。
 */
function callServiceAction() {
    var name = window._currentServiceName;
    var srvType = window._currentServiceType;
    var reqData = document.getElementById('serviceCallData').value.trim() || '{}';
    var containerId = getRos2PanelContainerId('services');
    if (!name) { showToast('请先选择服务', 'warning'); return; }
    showToast('正在调用...', 'info');
    apiPost('/api/ros2/service/' + name + '/call', { srv_type: srvType, data: reqData, container_id: containerId })
        .then(function(data) {
            document.getElementById('serviceCallResult').textContent = data.stdout || data.error || '无返回';
            showToast(data.success ? '调用成功' : '失败: ' + (data.error || ''), data.success ? 'success' : 'error');
        });
}

// ========== 预留扩展区域（第501-550行） ==========
// 预留用于未来扩展，如服务发现、负载均衡等
// ===========================================

// ============================================================
// 12. Action 管理
// ============================================================

/**
 * 加载 Action 列表（含权限控制）
 */
function loadActions() {
    var containerId = getRos2PanelContainerId('actions');
    var tbody = document.getElementById('actionsTableBody');
    if (!containerId) {
        tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">请先在上方选择目标容器</td></tr>';
        return;
    }
    tbody.innerHTML = '<tr><td colspan="2" style="text-align:center"><span class="loading"></span> 加载中...</td></tr>';
    apiGet('/api/ros2/actions?container_id=' + encodeURIComponent(containerId)).then(function(data) {
        if (!data.success) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;color:var(--error)">失败: ' +
                escapeHtml(data.error || '') + '</td></tr>';
            return;
        }
        if (!data.actions || !data.actions.length) {
            tbody.innerHTML = '<tr><td colspan="2" style="text-align:center;opacity:0.5">没有可用 Action</td></tr>';
            return;
        }

        // ★★★ 判断是否为管理员 ★★★
        var isAdmin = (window.userRole === 'admin');

        var html = '';
        for (var i = 0; i < data.actions.length; i++) {
            var a = data.actions[i];
            html += '<tr><td><code>' + escapeHtml(a) + '</code></td><td>';
            if (isAdmin) {
                html += '<button class="btn btn-sm" onclick="prepareActionGoal(\'' + escapeHtml(a) + '\')">🎯 发送</button> ';
            } else {
                html += '<span style="color:var(--text-muted);font-size:11px;">只读</span> ';
            }
            html += '<button class="btn btn-sm btn-outline" onclick="viewActionInfo(\'' + escapeHtml(a) + '\')">📋 详情</button>';
            html += '</td></tr>';
        }
        tbody.innerHTML = html;
    });
}

/**
 * 处理 viewActionInfo 相关前端逻辑。
 */
function viewActionInfo(name) {
    var containerId = getRos2PanelContainerId('actions');
    var url = '/api/ros2/action/' + name + '/info';
    if (containerId) url += '?container_id=' + encodeURIComponent(containerId);
    apiGet(url).then(function(data) {
        showToast(data.info || '无信息', 'info');
    });
}

/**
 * 处理 prepareActionGoal 相关前端逻辑。
 */
function prepareActionGoal(name) {
    document.getElementById('actionGoalCard').style.display = 'block';
    document.getElementById('actionGoalName').textContent = name;
    document.getElementById('actionGoalType').value = '';
    document.getElementById('actionGoalData').value = '';
    document.getElementById('actionGoalResult').textContent = '';
    window._currentActionName = name;
}

/**
 * 处理 sendActionGoal 相关前端逻辑。
 */
function sendActionGoal() {
    var name = window._currentActionName;
    var actionType = document.getElementById('actionGoalType').value.trim();
    var goalData = document.getElementById('actionGoalData').value.trim() || '{}';
    var containerId = getRos2PanelContainerId('actions');
    if (!name) { showToast('请先选择 Action', 'warning'); return; }
    showToast('正在发送...', 'info');
    apiPost('/api/ros2/action/' + name + '/send_goal', { action_type: actionType, data: goalData, container_id: containerId })
        .then(function(data) {
            document.getElementById('actionGoalResult').textContent = data.stdout || data.error || '无返回';
            showToast(data.success ? '发送成功' : '失败: ' + (data.error || ''), data.success ? 'success' : 'error');
        });
}

// ========== 预留扩展区域（第551-600行） ==========
// 预留用于未来扩展，如Action状态监控等
// ===========================================

// ============================================================
// 13. Docker 管理
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
        html += '<table class="data-table" style="font-size:12px;">';
        html += '<thead><tr><th style="width:140px;">时间</th><th style="width:100px;">用户</th><th style="width:120px;">操作</th><th>详情</th></tr></thead><tbody>';
        logs.reverse().forEach(function(log) {
            var time = log.timestamp ? formatTimestamp(log.timestamp) : '-';
            html += '<tr>';
            html += '<td style="color:var(--text-secondary);">' + time + '</td>';
            html += '<td><span class="tag tag-info">' + escapeHtml(log.username || '-') + '</span></td>';
            html += '<td><span class="tag tag-running">' + escapeHtml(log.action || '-') + '</span></td>';
            html += '<td style="max-width:300px;word-break:break-all;">' + escapeHtml(log.details || '-') + '</td>';
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
    var menu = btn.parentElement.querySelector('.dropdown-menu');
    if (menu) {
        if (menu.style.display === 'none' || menu.style.display === '') {
            // 计算按钮位置并设置菜单位置（fixed定位）
            var rect = btn.getBoundingClientRect();
            menu.style.position = 'fixed';
            menu.style.zIndex = '99999';
            menu.style.left = rect.left + 'px';
            menu.style.top = (rect.bottom + 4) + 'px';
            menu.style.display = 'block';
        } else {
            menu.style.display = 'none';
        }
    }
    // 点击其他地方时关闭菜单
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
    var tbody = document.getElementById('containersTableBody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:20px;"><div class="skeleton skeleton-block" style="height:40px;"></div></td></tr>';
    var url = '/api/docker/containers?all=' + all;
    if (filter) url += '&filter_image=' + encodeURIComponent(filter);

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

            var isRos2Container = c.image && (c.image.includes('ros2') || c.image.includes('humble') || c.image.includes('foxy'));
            
            var baseActions = '';
            var moreActions = '';
            
            // 启动/停止/重启按钮：拥有 Docker 管理页面权限即可使用。（基础按钮）
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

            // 删除按钮：拥有 Docker 管理页面权限即可使用。（展开按钮）
            if (hasDockerPerm) {
                moreActions += '<button class="btn btn-sm btn-error action-btn" onclick="removeContainer(\'' + c.id + '\',\'' + escapeHtml(c.name) + '\')" title="删除容器"><span class="btn-icon">🗑</span><span class="btn-text">删除</span></button>';
            }
            
            // 构建最终的操作按钮HTML
            var actions = '<div class="action-buttons">';
            actions += baseActions;
            if (moreActions) {
                actions += '<div class="more-actions-container">';
                actions += '<button class="btn btn-sm btn-outline action-btn more-btn" onclick="toggleMoreActions(this)" title="更多操作"><span class="btn-icon">⬇</span><span class="btn-text">更多</span></button>';
                actions += '<div class="more-actions" style="display:none;">' + moreActions + '</div>';
                actions += '</div>';
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
                '<td>' + escapeHtml(c.image) + '</td>' +
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

// v3.6: 当前日志查看模式（docker / ros2），默认 docker
var containerLogMode = 'docker';

/**
 * 处理 loadContainerLogs 相关前端逻辑。
 * v3.6: type 参数支持 'docker'（容器 stdout/stderr）或 'ros2'（ROS2 节点日志）。
 */
function loadContainerLogs(type) {
    if (!currentContainerId) return;
    if (type) containerLogMode = type;
    var mode = containerLogMode || 'docker';
    var container = document.getElementById('containerLogContent');
    container.innerHTML = '<span class="loading"></span> 加载' + (mode === 'ros2' ? ' ROS2 ' : ' Docker ') + '日志中...';

    var url;
    if (mode === 'ros2') {
        // bug3 修复：读取容器对应 ROS2 日志文件
        url = '/api/docker/container/' + currentContainerId + '/roslogs?tail=200';
    } else {
        url = '/api/docker/container/' + currentContainerId + '/logs?tail=200';
    }
    apiGet(url).then(function(d) {
        var text = d.logs || d.error || '无日志';
        if (mode === 'ros2' && d.log_file) {
            text = '📄 日志文件: ' + d.log_file + '\n' + '='.repeat(60) + '\n' + text;
        }
        container.textContent = text;
        container.scrollTop = container.scrollHeight;
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
        showToast('您没有 Docker 管理的操作权限', 'warning');
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
        showToast('您没有 Docker 管理的操作权限', 'warning');
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
// 14. 脚本管理
// ============================================================

/**
 * 处理 loadDefaultPaths 相关前端逻辑。
 */
function loadDefaultPaths(force) {
    if (defaultPathsLoaded && !force) return;
    defaultPathsLoaded = false;
    
    var defaultLaunchDir = '~/robotruck_ros2/install/simulation_launches/share/simulation_launches/launch';
    var defaultScriptsDir = '~/robotruck_ros2/Docker/scripts';
    var defaultLogsDir = '~/robotruck_ros2/Docker/logs';
    var defaultHostInstall = '/home/fox/robotruck_ros2/install';
    var defaultContainerInstall = '/root/robotruck_ros2/install';
    var defaultBagStorage = '/home/fox/robotruck_ros2/Docker/bags';
    var defaultContainerBagPath = '/root/robotruck_ros2/bags';
    
    Promise.all([
        apiGet(appendTargetUser('/api/scripts/launch-files')),
        apiGet(appendTargetUser('/api/scripts/list')),
        apiGet(appendTargetUser('/api/scripts/default-paths'))
    ]).then(function(results) {
        var launch = results[0];
        var list = results[1];
        var paths = results[2];
        
        // 优先使用 default-paths 返回的用户工作空间路径
        if (paths.success) {
            document.getElementById('genLaunchDir').value = paths.launch_dir || (launch.success && launch.launch_dir) || defaultLaunchDir;
            document.getElementById('genScriptsDir').value = paths.scripts_dir || (list.success && list.scripts_dir) || defaultScriptsDir;
            document.getElementById('genLogsDir').value = paths.logs_dir || defaultLogsDir;
            document.getElementById('genHostInstall').value = paths.host_install || defaultHostInstall;
            document.getElementById('genContainerInstall').value = paths.container_install || defaultContainerInstall;
            document.getElementById('genBagStorage').value = paths.bag_storage || defaultBagStorage;
            document.getElementById('genContainerBagPath').value = paths.container_bag_path || defaultContainerBagPath;
        } else {
            document.getElementById('genLaunchDir').value = (launch.success && launch.launch_dir) || defaultLaunchDir;
            document.getElementById('genScriptsDir').value = (list.success && list.scripts_dir) || defaultScriptsDir;
            document.getElementById('genLogsDir').value = (list.success && list.scripts_dir) ? list.scripts_dir.replace('/scripts', '/logs') : defaultLogsDir;
            document.getElementById('genHostInstall').value = defaultHostInstall;
            document.getElementById('genContainerInstall').value = defaultContainerInstall;
            document.getElementById('genBagStorage').value = defaultBagStorage;
            document.getElementById('genContainerBagPath').value = defaultContainerBagPath;
        }
        defaultPathsLoaded = true;
    }).catch(function() {
        document.getElementById('genLaunchDir').value = defaultLaunchDir;
        document.getElementById('genScriptsDir').value = defaultScriptsDir;
        document.getElementById('genLogsDir').value = defaultLogsDir;
        document.getElementById('genHostInstall').value = defaultHostInstall;
        document.getElementById('genContainerInstall').value = defaultContainerInstall;
        document.getElementById('genBagStorage').value = defaultBagStorage;
        document.getElementById('genContainerBagPath').value = defaultContainerBagPath;
        defaultPathsLoaded = true;
    });

    // 加载 Docker 镜像下拉框（仿真车分组）
    loadGenDockerImageOptions();
}

/**
 * 加载生成脚本面板的 Docker 镜像下拉框选项（仅 🚗 仿真车镜像分组）
 */
function loadGenDockerImageOptions() {
    var select = document.getElementById('genDockerImage');
    if (!select) return;
    var current = select.value || 'ros2_humble_image:v1';
    apiGet('/api/docker/images').then(function(d) {
        if (!d.success || !d.images) return;
        var simcarImages = [];
        for (var i = 0; i < d.images.length; i++) {
            var img = d.images[i];
            var tagName = (img.tags && img.tags.length) ? img.tags[0] : '';
            if (tagName && getImageGroup(tagName) === 'simcar') {
                simcarImages.push(tagName);
            }
        }
        if (!simcarImages.length) return; // 无镜像时保留默认 option
        var exists = simcarImages.indexOf(current) >= 0;
        var html = '';
        if (!exists) {
            html += '<option value="' + escapeHtml(current) + '">' + escapeHtml(current) + ' (当前)</option>';
        }
        for (var j = 0; j < simcarImages.length; j++) {
            html += '<option value="' + escapeHtml(simcarImages[j]) + '">' + escapeHtml(simcarImages[j]) + '</option>';
        }
        select.innerHTML = html;
        select.value = current;
    });
}

/**
 * 处理 loadLaunchFiles 相关前端逻辑。
 */
function loadLaunchFiles() {
    var div = document.getElementById('launchFilesList');
    apiGet(appendTargetUser('/api/scripts/launch-files')).then(function(d) {
        if (!d.success) { div.innerHTML = '<p style="color:var(--error)">' + escapeHtml(d.error) + '</p>'; return; }
        if (!d.files || !d.files.length) { div.innerHTML = '<p style="opacity:0.5">未找到 launch 文件</p>'; return; }
        var html = '<p style="margin-bottom:8px">找到 <strong>' + d.files.length + '</strong> 个 launch 文件:</p>';
        for (var i = 0; i < d.files.length; i++) {
            html += '<span class="tag" style="margin:2px">' + escapeHtml(d.files[i].name) + '</span>';
        }
        div.innerHTML = html;
    });
}

/**
 * 清空所有已生成的启动脚本
 */
function clearAllScripts() {
    customConfirm('确定要清空所有已生成的启动脚本吗？此操作不可撤销！', function() {
        apiDelete(appendTargetUser('/api/scripts/clear-all')).then(function(data) {
            if (data.success) {
                showToast(data.message || '已清空所有脚本', 'success');
                loadScripts();
                var div = document.getElementById('genResult');
                if (div) div.innerHTML = '<p style="color:var(--text-secondary)">脚本已清空，请重新生成。</p>';
            } else {
                showToast(data.error || '清空失败', 'error');
            }
        }).catch(function(err) {
            showToast('清空失败: ' + err, 'error');
        });
    });
}

/**
 * 处理 generateScripts 相关前端逻辑。
 */
function generateScripts() {
    var body = {
        launch_dir: document.getElementById('genLaunchDir').value,
        scripts_dir: document.getElementById('genScriptsDir').value,
        logs_dir: document.getElementById('genLogsDir').value,
        docker_image: document.getElementById('genDockerImage').value
    };
    // 添加target_user参数支持用户空间隔离
    if (currentTargetUser) {
        body.target_user = currentTargetUser;
    }
    showToast('正在生成脚本...', 'info');
    var div = document.getElementById('genResult');
    apiPost('/api/scripts/generate', body).then(function(d) {
        if (d.success) {
            var html = '<p style="color:var(--success)">✅ 已生成 <strong>' + d.generated.length + '</strong> 个脚本</p>';
            if (d.host_install) {
                html += '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:8px;">📦 挂载路径: ' + escapeHtml(d.host_install) + '</div>';
            }
            if (d.warnings && d.warnings.length > 0) {
                html += '<div class="port-warning">⚠️ 端口冲突已自动调整:<br>';
                for (var w = 0; w < d.warnings.length; w++) {
                    html += '• ' + escapeHtml(d.warnings[w]) + '<br>';
                }
                html += '</div>';
            }
            for (var i = 0; i < d.generated.length; i++) {
                var g = d.generated[i];
                html += '<div style="font-size:12px;margin:2px 0">📄 ' + escapeHtml(g.name) + ' → 容器: ' + escapeHtml(g.container) + ' (DOMAIN_ID=' + g.domain_id + ')</div>';
            }
            div.innerHTML = html;
            loadScripts();
            // 通知引导系统脚本生成完成
            if (typeof Onboarding !== 'undefined' && Onboarding.notifyScriptGenerated) {
                setTimeout(function() { Onboarding.notifyScriptGenerated(); }, 500);
            }
        } else {
            div.innerHTML = '<p style="color:var(--error)">❌ ' + escapeHtml(d.error) + '</p>';
            showToast('脚本生成失败，如遇到问题请联系飞书郭仕杰', 'error');
        }
    }).catch(function(err) {
        showToast('网络错误，脚本生成失败，如遇到问题请联系飞书郭仕杰', 'error');
    });
}

/**
 * 加载脚本列表（含权限控制）
 */
function loadScripts() {
    var tbody = document.getElementById('scriptsTableBody');
    tbody.innerHTML = '<tr><td colspan="3" style="text-align:center"><span class="loading"></span> 加载中...</td></tr>';
    apiGet(appendTargetUser('/api/scripts/list')).then(function(d) {
        if (!d.success) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;color:var(--error)">失败</td></tr>';
            return;
        }
        if (!d.scripts || !d.scripts.length) {
            tbody.innerHTML = '<tr><td colspan="3" style="text-align:center;opacity:0.5">没有脚本</td></tr>';
            return;
        }
        window._allScripts = d.scripts;

        // ★★★ 判断是否为管理员 ★★★
        // var isAdmin = (window.userRole === 'admin');
        var hasScriptsPerm = hasPermission('scripts');
        var html = '';
        for (var i = 0; i < d.scripts.length; i++) {
            var s = d.scripts[i];
            html += '<tr class="script-row" data-script="' + escapeHtml(s) + '">' +
                '<td style="width:30px;"><input type="checkbox" class="script-checkbox" value="' +
                escapeHtml(s) + '" style="width:16px;height:16px;"></td>' +
                '<td><code>' + escapeHtml(s) + '</code></td>' +
                '<td>';
            if (hasScriptsPerm) {
                html += '<button class="btn btn-sm btn-outline" onclick="editScript(\'' + escapeHtml(s) + '\')">✏️ 编辑</button> ';
                html += '<button class="btn btn-sm btn-success" onclick="executeSingleScript(\'' + escapeHtml(s) + '\')">▶ 执行</button> ';
                html += '<button class="btn btn-sm btn-error" onclick="deleteScript(\'' + escapeHtml(s) + '\')">🗑 删除</button>';
            } else {
                html += '<span style="color:var(--text-muted);font-size:11px;">📄 只读</span>';
            }
            html += '</td></tr>';
        }
        tbody.innerHTML = html;
    });
}

/**
 * 处理 toggleScriptsCollapse 相关前端逻辑。
 */
function toggleScriptsCollapse() {
    if (scriptsExpanded) collapseScripts();
    else expandScripts();
    localStorage.setItem('scriptsExpandDefault', scriptsExpanded ? 'true' : 'false');
}

/**
 * 处理 expandScripts 相关前端逻辑。
 */
function expandScripts() {
    var content = document.getElementById('scriptsCollapsible');
    content.classList.add('expanded');
    document.getElementById('scriptsToggleIcon').textContent = '▼';
    document.getElementById('scriptsCollapseToggle').innerHTML = '<span id="scriptsToggleIcon">▼</span> 收起';
    scriptsExpanded = true;
}

/**
 * 处理 collapseScripts 相关前端逻辑。
 */
function collapseScripts() {
    var content = document.getElementById('scriptsCollapsible');
    content.classList.remove('expanded');
    document.getElementById('scriptsToggleIcon').textContent = '▶';
    document.getElementById('scriptsCollapseToggle').innerHTML = '<span id="scriptsToggleIcon">▶</span> 展开';
    scriptsExpanded = false;
}

/**
 * 通用卡片收起/展开函数
 * @param {string} cardId - 卡片ID
 * @param {boolean} saveConfig - 是否保存配置到localStorage
 */
function toggleCard(cardId, saveConfig = true) {
    var content = document.getElementById(cardId + '-content');
    var icon = document.getElementById(cardId + '-icon');
    
    if (!content || !icon) return;
    
    var isExpanded = content.classList.contains('expanded');
    
    if (isExpanded) {
        content.classList.remove('expanded');
        icon.textContent = '▶';
    } else {
        content.classList.add('expanded');
        icon.textContent = '▼';
        
        // 展开帮助文档配置卡片时自动加载内容
        if (cardId === 'settings-help') {
            loadHelpContent();
        }
    }
    
    // 保存配置到 localStorage
    if (saveConfig) {
        var cardConfigs = getCardConfigs();
        cardConfigs[cardId] = !isExpanded;
        localStorage.setItem('cardConfigs', JSON.stringify(cardConfigs));
    }
}

/**
 * 获取卡片配置
 */
function getCardConfigs() {
    try {
        return JSON.parse(localStorage.getItem('cardConfigs') || '{}');
    } catch {
        return {};
    }
}

/**
 * 加载卡片配置并应用到所有卡片
 */
function loadCardConfigs() {
    var cardConfigs = getCardConfigs();
    var cards = document.querySelectorAll('[data-card-id]');
    
    cards.forEach(function(card) {
        var cardId = card.getAttribute('data-card-id');
        var content = document.getElementById(cardId + '-content');
        var icon = document.getElementById(cardId + '-icon');
        
        if (!content || !icon) return;
        
        var shouldExpand = cardConfigs[cardId] !== undefined ? cardConfigs[cardId] : false;
        
        if (shouldExpand) {
            content.classList.add('expanded');
            icon.textContent = '▼';
        } else {
            content.classList.remove('expanded');
            icon.textContent = '▶';
        }
    });
    
    // 更新界面偏好中的开关状态
    updateCardConfigSwitches();
}

/**
 * 更新界面偏好中的卡片配置开关状态
 */
function updateCardConfigSwitches() {
    var cardConfigs = getCardConfigs();
    var cardIds = ['nodes-main', 'services-main', 'actions-main', 'scripts-launch', 'scripts-gen', 
                   'monitor-gpu', 'settings-colors', 'check-result',
                   'settings-errorlog', 'settings-resource', 'settings-help', 'settings-sudo', 'settings-auth'];
    
    cardIds.forEach(function(cardId) {
        var checkbox = document.getElementById('card-' + cardId);
        if (checkbox) {
            checkbox.checked = cardConfigs[cardId] !== undefined ? cardConfigs[cardId] : false;
        }
    });
}

/**
 * 搜索过滤设置项
 */
function filterSettingsItems() {
    var searchInput = document.getElementById('settingsSearchInput');
    if (!searchInput) return;
    
    var searchText = searchInput.value.toLowerCase();
    var settingItems = document.querySelectorAll('#settings-pref-content .setting-item');
    
    settingItems.forEach(function(item) {
        var label = item.querySelector('.setting-label');
        var desc = item.querySelector('.setting-desc');
        
        var text = '';
        if (label) text += label.textContent.toLowerCase();
        if (desc) text += ' ' + desc.textContent.toLowerCase();
        
        if (searchText === '' || text.includes(searchText)) {
            item.style.display = 'flex';
        } else {
            item.style.display = 'none';
        }
    });
}

/**
 * 切换单个卡片的展开状态配置
 */
function toggleCardExpand(cardId, expand) {
    var cardConfigs = getCardConfigs();
    cardConfigs[cardId] = expand;
    localStorage.setItem('cardConfigs', JSON.stringify(cardConfigs));
    
    // 更新实际卡片的状态
    var card = document.querySelector('[data-card-id="' + cardId + '"]');
    if (card) {
        var content = document.getElementById(cardId + '-content');
        var icon = document.getElementById(cardId + '-icon');
        
        if (content && icon) {
            if (expand) {
                content.classList.add('expanded');
                icon.textContent = '▼';
            } else {
                content.classList.remove('expanded');
                icon.textContent = '▶';
            }
        }
    }
}

/**
 * 重置所有卡片配置为默认收起
 */
function resetCardConfigs() {
    localStorage.removeItem('cardConfigs');
    loadCardConfigs();
    showToast('已重置为默认配置', 'success');
}

/**
 * 展开所有卡片
 */
function expandAllCards() {
    var cards = document.querySelectorAll('[data-card-id]');
    cards.forEach(function(card) {
        var cardId = card.getAttribute('data-card-id');
        var content = document.getElementById(cardId + '-content');
        var icon = document.getElementById(cardId + '-icon');
        
        if (content && icon) {
            content.classList.add('expanded');
            icon.textContent = '▼';
        }
    });
    
    // 保存配置
    var cardConfigs = {};
    document.querySelectorAll('[data-card-id]').forEach(function(card) {
        cardConfigs[card.getAttribute('data-card-id')] = true;
    });
    localStorage.setItem('cardConfigs', JSON.stringify(cardConfigs));
    
    // 更新界面偏好中的开关状态
    updateCardConfigSwitches();
    showToast('已展开所有卡片', 'success');
}

/**
 * 收起所有卡片
 */
function collapseAllCards() {
    var cards = document.querySelectorAll('[data-card-id]');
    cards.forEach(function(card) {
        var cardId = card.getAttribute('data-card-id');
        var content = document.getElementById(cardId + '-content');
        var icon = document.getElementById(cardId + '-icon');
        
        if (content && icon) {
            content.classList.remove('expanded');
            icon.textContent = '▶';
        }
    });
    
    // 保存配置
    var cardConfigs = {};
    document.querySelectorAll('[data-card-id]').forEach(function(card) {
        cardConfigs[card.getAttribute('data-card-id')] = false;
    });
    localStorage.setItem('cardConfigs', JSON.stringify(cardConfigs));
    
    // 更新界面偏好中的开关状态
    updateCardConfigSwitches();
    showToast('已收起所有卡片', 'success');
}

/**
 * 卡片配置元数据
 */
var cardMetadata = {
    'nodes-main': { name: '运行中的节点', panel: 'nodes' },
    'services-main': { name: '可用服务', panel: 'services' },
    'actions-main': { name: '可用 Action', panel: 'actions' },
    'scripts-launch': { name: 'Launch 文件扫描', panel: 'scripts' },
    'scripts-gen': { name: '生成启动脚本', panel: 'scripts' },
    'monitor-gpu': { name: 'GPU 信息', panel: 'monitor' },
    
    'settings-colors': { name: '自定义颜色', panel: 'settings' },
    'settings-pref': { name: '界面偏好', panel: 'settings' },
    'check-result': { name: '检查结果', panel: 'check' },
    'nodes-help': { name: '节点帮助', panel: 'nodes' },
    'services-help': { name: '服务帮助', panel: 'services' },
    'actions-help': { name: 'Action 帮助', panel: 'actions' },
    'scripts-help': { name: '脚本帮助', panel: 'scripts' },
    'check-help': { name: '检查帮助', panel: 'check' },
    'settings-errorlog': { name: '全局错误日志', panel: 'settings' },
    'settings-resource': { name: '资源泄漏监控', panel: 'settings' },
    'settings-help': { name: '帮助文档', panel: 'settings' },
    'settings-sudo': { name: 'sudo 权限检查', panel: 'settings' },
    'settings-auth': { name: '敏感信息加密存储', panel: 'settings' }
};

/**
 * 加载卡片配置网格
 */
function loadCardConfigGrid() {
    var grid = document.getElementById('cardConfigGrid');
    if (!grid) return;
    
    var cardConfigs = getCardConfigs();
    var html = '';
    
    Object.keys(cardMetadata).forEach(function(cardId) {
        var meta = cardMetadata[cardId];
        var isExpanded = cardConfigs[cardId] !== undefined ? cardConfigs[cardId] : false;
        
        html += `
            <div class="card-config-item">
                <input type="checkbox" id="config-${cardId}" ${isExpanded ? 'checked' : ''} onchange="updateCardConfig('${cardId}', this.checked)">
                <label for="config-${cardId}">${meta.name}</label>
            </div>
        `;
    });
    
    grid.innerHTML = html;
}

/**
 * 设置卡片配置列数
 */
function setCardConfigColumns(columns) {
    // 获取设置项容器（界面偏好面板中的设置项区域，排除搜索框的div）
    var settingsContainer = document.querySelector('#settings-pref-content > div:last-child');
    if (!settingsContainer) return;
    
    // 移除所有列数类
    settingsContainer.classList.remove('columns-1', 'columns-2', 'columns-3', 'columns-4');
    
    // 添加当前列数类
    settingsContainer.classList.add('columns-' + columns);
    
    // 更新按钮状态
    document.querySelectorAll('.column-btn').forEach(function(btn) {
        btn.classList.remove('active');
    });
    document.querySelector('.column-btn[data-columns="' + columns + '"]').classList.add('active');
    
    // 保存到 localStorage
    localStorage.setItem('cardConfigColumns', columns);
}

/**
 * 加载卡片配置列数
 */
function loadCardConfigColumns() {
    var columns = parseInt(localStorage.getItem('cardConfigColumns')) || 4;
    setCardConfigColumns(columns);
}

/**
 * 更新单个卡片配置
 */
function updateCardConfig(cardId, isExpanded) {
    var cardConfigs = getCardConfigs();
    cardConfigs[cardId] = isExpanded;
    localStorage.setItem('cardConfigs', JSON.stringify(cardConfigs));
    
    // 同时更新实际的卡片状态
    var content = document.getElementById(cardId + '-content');
    var icon = document.getElementById(cardId + '-icon');
    
    if (content && icon) {
        if (isExpanded) {
            content.classList.add('expanded');
            icon.textContent = '▼';
        } else {
            content.classList.remove('expanded');
            icon.textContent = '▶';
        }
    }
}

/**
 * 当前帮助标签
 */
var currentHelpTab = 'nodes';
var helpPagesLoaded = false;
var helpPagesCache = [];

/**
 * 加载帮助页面列表
 */
function loadHelpPages() {
    var defaultPages = [
        {"id": "welcome", "name": "🏠 首页"},
        {"id": "scripts", "name": "📜 脚本生成"},
        {"id": "advanced-scripts", "name": "📜 脚本执行增强"},
        {"id": "vehicle", "name": "🚛 仿真车启动"},
        {"id": "docker", "name": "🐳 Docker 管理"},
        {"id": "advanced-docker", "name": "🐳 容器管理增强"},
        {"id": "images", "name": "💿 镜像管理"},
        {"id": "traffic", "name": "🚦 红绿灯模拟"},
        {"id": "advanced-fault", "name": "💥 故障注入"},
        {"id": "batch", "name": "📦 车辆配置生成"},
        {"id": "tools", "name": "🛠️ 其他工具"},
        {"id": "simulation", "name": "🎮 仿真控制"},
        {"id": "topics", "name": "📡 话题查看"},
        {"id": "nodes", "name": "🔷 节点管理"},
        {"id": "services", "name": "🔧 服务管理"},
        {"id": "actions", "name": "⚡ Action 管理"},
        {"id": "advanced-extend", "name": "🔌 拓展功能"},
        {"id": "monitor", "name": "📊 系统监控"},
        {"id": "api-manager", "name": "📡 REST API 管理"},
        {"id": "check", "name": "✅ 系统自检"},
        {"id": "theme", "name": "🎨 主题设置"},
        {"id": "settings", "name": "⚙️ 系统设置"}
    ];
    
    function fillHelpPages(pages) {
        helpPagesCache = pages;
        
        var select = document.getElementById('helpPageSelect');
        if (select) {
            var currentVal = select.value;
            select.innerHTML = '';
            pages.forEach(function(page) {
                var opt = document.createElement('option');
                opt.value = page.id;
                opt.textContent = page.name;
                select.appendChild(opt);
            });
            if (currentVal) {
                select.value = currentVal;
            } else if (pages.length > 0) {
                select.value = pages[0].id;
            }
        }
        
        var tabsContainer = document.getElementById('helpPanelTabs');
        if (tabsContainer) {
            tabsContainer.innerHTML = '';
            var tabNameMap = {
                'welcome': '首页', 'scripts': '脚本生成', 'advanced-scripts': '脚本增强',
                'vehicle': '仿真车启动', 'docker': 'Docker', 'advanced-docker': '容器增强',
                'images': '镜像管理', 'traffic': '红绿灯', 'advanced-fault': '故障注入',
                'tools': '其他工具', 'simulation': '仿真控制',
                'topics': '话题查看', 'nodes': '节点管理', 'services': '服务管理',
                'actions': 'Action', 'advanced-extend': '拓展功能',
                'monitor': '系统监控', 'api-manager': 'API管理',
                'theme': '主题设置', 'settings': '系统设置'
            };
            pages.forEach(function(page) {
                var tabName = tabNameMap[page.id] || page.name.replace(/^[^\s]+\s/, '');
                var btn = document.createElement('button');
                btn.className = 'help-tab';
                btn.setAttribute('data-tab', page.id);
                btn.textContent = tabName;
                btn.onclick = function() { switchHelpTab(page.id); };
                tabsContainer.appendChild(btn);
            });
        }
        
        helpPagesLoaded = true;
    }
    
    fillHelpPages(defaultPages);
    
    return apiGet('/api/system/help-pages').then(function(d) {
        if (d.success && d.pages && d.pages.length > 0) {
            fillHelpPages(d.pages);
            return d.pages;
        }
        return defaultPages;
    }).catch(function(err) {
        console.log('加载帮助页面列表失败，使用默认列表:', err);
        return defaultPages;
    });
}

/**
 * 切换帮助面板显示/隐藏
 */
function toggleHelpPanel() {
    var overlay = document.getElementById('helpPanelOverlay');
    var modal = document.getElementById('helpPanelModal');
    
    if (overlay.style.display === 'none' || overlay.style.display === '') {
        overlay.style.display = 'block';
        modal.classList.add('visible');
        
        var loadPromise = helpPagesLoaded ? Promise.resolve() : loadHelpPages();
        loadPromise.then(function() {
            syncHelpTabWithCurrentPanel();
            loadHelpPanelContent(currentHelpTab);
        });
    } else {
        closeHelpPanel();
    }
}

/**
 * 根据当前页面同步帮助标签
 */
function syncHelpTabWithCurrentPanel() {
    var panelToTabMap = {
        'panel-scripts': 'scripts',
        'panel-vehicle': 'vehicle',
        'panel-docker': 'docker',
        'panel-images': 'images',
        'panel-traffic': 'traffic',
        'panel-advanced-fault': 'advanced-fault',
        'panel-tools': 'tools',
        'panel-simulation': 'simulation',
        'panel-topics': 'topics',
        'panel-nodes': 'nodes',
        'panel-services': 'services',
        'panel-actions': 'actions',
        'panel-advanced-extend': 'advanced-extend',
        'panel-monitor': 'monitor',
        'panel-theme': 'theme',
        'panel-settings': 'settings',
        'panel-advanced-docker': 'advanced-docker',
        'panel-welcome': 'welcome',
        'panel-api-manager': 'api-manager',
        'panel-advanced-scripts': 'scripts',
        'panel-tickets': 'tickets'
    };
    
    var activePanel = document.querySelector('.panel.active');
    if (activePanel && panelToTabMap[activePanel.id]) {
        switchHelpTab(panelToTabMap[activePanel.id]);
    }
}

/**
 * 关闭帮助面板
 */
function closeHelpPanel() {
    var overlay = document.getElementById('helpPanelOverlay');
    var modal = document.getElementById('helpPanelModal');
    
    overlay.style.display = 'none';
    modal.classList.remove('visible');
}

/**
 * 切换帮助标签
 */
function switchHelpTab(tabId) {
    currentHelpTab = tabId;
    
    // 更新标签样式
    document.querySelectorAll('.help-tab').forEach(function(tab) {
        tab.classList.remove('active');
    });
    var targetTab = document.querySelector('.help-tab[data-tab="' + tabId + '"]');
    if (targetTab) {
        targetTab.classList.add('active');
    }
    
    // 加载对应内容
    loadHelpPanelContent(tabId);
}

/**
 * 加载帮助面板内容
 */
function loadHelpPanelContent(panelId) {
    var contentDiv = document.getElementById('helpPanelContent');
    if (!contentDiv) return;
    
    contentDiv.textContent = '⏳ 正在加载帮助内容...';
    
    apiGet('/api/system/help/' + panelId).then(function(d) {
        if (d.success && d.content !== undefined && d.content !== null && d.content.trim() !== '') {
            contentDiv.textContent = d.content;
        } else {
            contentDiv.textContent = getDefaultHelpContent(panelId);
        }
    }).catch(function() {
        contentDiv.textContent = getDefaultHelpContent(panelId);
    });
}

/**
 * 加载帮助文档内容
 */
function loadHelpContent(panelId) {
    var editor = document.getElementById('helpContentEditor');
    if (editor) {
        var page = panelId || document.getElementById('helpPageSelect').value;
        
        editor.placeholder = '⏳ 正在加载...';
        editor.value = '';
        
        apiGet('/api/system/help/' + page).then(function(d) {
            editor.placeholder = '在此输入帮助文档内容...';
            if (d.success && d.content !== undefined && d.content !== null) {
                editor.value = d.content;
            } else {
                editor.value = getDefaultHelpContent(page);
            }
        }).catch(function() {
            editor.placeholder = '在此输入帮助文档内容...';
            editor.value = getDefaultHelpContent(page);
        });
        return;
    }
    
    var textarea = document.getElementById(panelId + '-help-textarea');
    if (!textarea) return;
    
    apiGet('/api/system/help/' + panelId).then(function(d) {
        if (d.success && d.content !== undefined && d.content !== null) {
            textarea.value = d.content;
        } else {
            textarea.value = getDefaultHelpContent(panelId);
        }
    }).catch(function() {
        textarea.value = getDefaultHelpContent(panelId);
    });
}

/**
 * 获取默认帮助文档内容
 */
function getDefaultHelpContent(panelId) {
    var defaults = {
        'scripts': '## 脚本生成\n\n生成 ROS2 启动脚本，用于启动仿真车辆。\n\n### 操作流程\n\n1. **扫描 Launch 文件**\n   - 点击「扫描 Launch 文件」按钮\n   - 系统自动查找工作空间中的所有 .launch.py 文件\n   - 扫描完成后显示找到的文件列表\n\n2. **配置生成参数**\n   - 设置「脚本输出目录」: 生成的启动脚本存放位置\n   - 设置「日志目录」: 容器运行时日志输出位置\n   - 设置「宿主机 IP」: 可选，用于网络配置\n   - 设置「Docker 镜像」: 选择要使用的基础镜像\n\n3. **生成脚本**\n   - 点击「生成 ROS2 脚本」按钮\n   - 系统自动创建启动脚本\n   - 生成成功后显示脚本数量\n\n### 注意事项\n\n- 修改路径后需要重新生成脚本\n- 生成的脚本包含自动重启和日志管理功能\n- 建议在生成前确认路径存在且有写入权限',
        
        'vehicle': '## 仿真车启动\n\n管理已生成的启动脚本，支持批量启动仿真车辆。\n\n### 操作流程\n\n#### 一、脚本列表操作\n\n1. **筛选脚本**\n   - 在搜索框中输入关键词\n   - 实时过滤显示匹配的脚本\n\n2. **预览脚本内容**\n   - 点击脚本名称前的预览按钮\n   - 弹窗显示脚本完整内容\n\n3. **执行脚本**\n   - 点击「执行」按钮单独运行一个脚本\n   - 脚本执行后显示运行状态\n\n#### 二、批量操作\n\n1. **选择脚本**\n   - 勾选脚本前的复选框\n   - 使用「全选」按钮选中所有脚本\n\n2. **选择执行模式**\n   - **顺序执行**: 脚本按顺序依次启动，一个完成后启动下一个\n   - **并行执行**: 所有选中脚本同时启动\n\n3. **批量启动**\n   - 点击「批量启动」按钮\n   - 查看执行进度和结果\n\n#### 三、带重试执行（高级功能）\n\n1. **加载脚本列表**\n   - 点击「刷新」按钮加载当前脚本\n\n2. **批量执行（带重试）**\n   - 勾选需要执行的脚本\n   - 选择执行模式\n   - 点击「批量执行（带重试）」\n   - 系统会自动重试失败的脚本\n\n### 使用提示\n\n- 首次启动建议使用顺序执行，便于排查问题\n- 并行执行适用于已验证过的稳定脚本\n- 执行结果会显示每个脚本的启动状态\n- 红色表示启动失败，绿色表示成功',
        
        'docker': '## Docker 管理\n\n管理 Docker 容器的运行状态。\n\n### 操作流程\n\n1. **查看容器列表**\n   - 进入页面自动加载容器列表\n   - 显示容器名称、状态、镜像等信息\n\n2. **容器操作**\n   - **启动**: 启动已停止的容器\n   - **停止**: 停止运行中的容器\n   - **重启**: 重启容器\n   - **删除**: 删除不需要的容器\n\n3. **查看日志**\n   - 点击日志按钮查看容器日志\n   - 支持实时日志查看\n\n### 使用提示\n\n- 绿色指示灯表示容器运行中\n- 灰色指示灯表示容器已停止\n- 删除容器会永久移除容器及其数据',
        
        'images': '## 镜像管理\n\n管理 Docker 镜像。\n\n### 操作流程\n\n1. **查看镜像列表**\n   - 显示所有本地镜像\n   - 包含镜像名称、标签、大小等信息\n\n2. **镜像操作**\n   - **拉取**: 从远程仓库拉取镜像\n   - **删除**: 删除本地镜像\n   - **查看详情**: 显示镜像详细信息\n\n### 使用提示\n\n- 删除镜像前请确保没有容器使用该镜像\n- 建议定期清理不再使用的镜像以节省空间',
        
        'traffic': '## 红绿灯模拟\n\n模拟交通红绿灯信号。\n\n### 操作流程\n\n1. **设置状态**\n   - 选择红绿灯状态（红/黄/绿）\n   - 设置持续时间\n\n2. **启动模拟**\n   - 点击启动按钮开始模拟\n   - 自动循环切换灯色\n\n### 使用提示\n\n- 用于测试车辆的红绿灯识别功能\n- 可以自定义灯色持续时间',
        
        'advanced-fault': '## 故障注入\n\n模拟系统故障场景。\n\n### 操作流程\n\n1. **选择故障类型**\n   - 选择要模拟的故障类型\n   - 设置故障参数\n\n2. **注入故障**\n   - 点击注入按钮\n   - 系统模拟故障场景\n\n3. **恢复正常**\n   - 点击恢复按钮清除故障\n\n### 使用提示\n\n- 故障注入用于测试系统容错能力\n- 注入前请确保系统处于安全状态',
        
        'tools': '## 其他工具\n\n提供系统维护和配置工具。\n\n### 功能说明\n\n1. **一键换源**\n   - 快速切换系统软件源\n   - 支持阿里云、清华、中科大等源\n\n2. **软件安装**\n   - 一键安装常用工具软件\n   - 支持自定义软件包安装\n\n3. **文件夹同步**\n   - 同步配置文件和脚本\n   - 支持远程同步\n\n4. **数据清理**\n   - 清空 Bag 文件\n   - 清空日志文件\n\n### 使用提示\n\n- 换源后需要重启终端生效\n- 数据清理操作不可逆，请谨慎操作',
        
        'simulation': '## 仿真控制\n\n控制仿真环境的运行状态。\n\n### 操作流程\n\n1. **启动仿真**\n   - 配置仿真参数\n   - 点击启动按钮\n\n2. **控制仿真**\n   - 暂停/继续仿真\n   - 调整仿真速度\n   - 重置仿真状态\n\n3. **停止仿真**\n   - 点击停止按钮\n   - 保存仿真数据\n\n### 使用提示\n\n- 仿真启动需要一定时间，请耐心等待\n- 建议在停止前保存重要数据',
        
        'topics': '## 话题查看\n\n查看和管理 ROS2 话题。\n\n### 操作流程\n\n1. **筛选话题**\n   - 使用搜索框过滤话题\n   - 支持模糊搜索\n\n2. **查看话题**\n   - 点击查看按钮查看话题详情\n   - 显示消息内容和频率\n\n3. **话题操作**\n   - **查看**: 实时显示话题消息\n   - **Echo**: 持续打印话题消息\n   - **Publish**: 发布自定义消息\n   - **停止**: 停止查看或发布\n\n### 使用提示\n\n- 高频话题可能产生大量数据\n- 建议在必要时才开启 Echo 功能',
        
        'nodes': '## 节点管理\n\n管理当前运行的 ROS2 节点。\n\n### 操作流程\n\n1. **筛选节点**\n   - 使用搜索框实时筛选节点名称\n   - 支持按命名空间过滤\n\n2. **查看节点信息**\n   - 点击节点名称查看详情\n   - 显示节点发布/订阅的话题\n   - 显示节点提供的服务\n\n3. **节点操作**\n   - **查看日志**: 查看节点输出日志\n   - **关闭节点**: 停止指定节点\n\n### 使用提示\n\n- 节点名称格式通常为 `/namespace/node_name`\n- 灰色节点表示已停止或不可用\n- 关闭节点需要谨慎操作',
        
        'services': '## 服务管理\n\n管理 ROS2 服务。\n\n### 操作流程\n\n1. **筛选服务**\n   - 使用搜索框实时筛选服务名称\n   - 支持按命名空间过滤\n\n2. **调用服务**\n   - 点击调用按钮\n   - 填写服务请求数据\n   - 发送请求并查看响应\n\n### 使用提示\n\n- 服务请求数据需要符合服务消息格式\n- 服务调用是同步操作，可能需要等待响应\n- 可以查看服务类型定义了解数据格式',
        
        'actions': '## Action 管理\n\n管理 ROS2 Action。\n\n### 操作流程\n\n1. **发送目标**\n   - 选择 Action\n   - 设置目标数据\n   - 发送目标请求\n\n2. **监控执行**\n   - 实时显示 Action 状态\n   - 显示反馈信息\n   - 显示执行进度\n\n3. **取消任务**\n   - 在执行过程中点击取消\n   - 发送取消请求\n\n### 使用提示\n\n- Action 是异步操作，支持反馈和结果\n- 目标数据格式需要匹配 Action 类型定义\n- 取消操作可能不会立即生效',
        
        'monitor': '## 系统监控\n\n监控系统资源使用情况。\n\n### 功能说明\n\n1. **CPU 监控**\n   - 实时显示 CPU 使用率\n   - 显示进程 CPU 占用排行\n\n2. **内存监控**\n   - 显示内存使用情况\n   - 显示内存占用排行\n\n3. **磁盘监控**\n   - 显示磁盘使用情况\n   - 显示各分区占用\n\n4. **网络监控**\n   - 显示网络流量\n   - 显示网络连接状态\n\n### 使用提示\n\n- 监控数据每秒钟更新一次\n- 可以通过监控面板查看资源瓶颈',
        
        'settings': '## 系统设置\n\n配置系统参数和用户偏好。\n\n### 功能说明\n\n1. **界面偏好**\n   - 配置各页面默认展开状态\n   - 设置显示列数\n   - 搜索配置项\n\n2. **用户管理**\n   - 查看当前用户信息\n   - 修改用户角色\n\n3. **系统状态**\n   - 查看系统运行状态\n   - 查看 ROS2 环境信息\n\n4. **帮助文档配置**\n   - 编辑各页面帮助文档\n   - 自定义帮助内容\n\n5. **系统自检**\n   - 执行系统检查\n   - 查看检查结果\n   - 获取修复建议\n\n### 使用提示\n\n- 设置修改后立即生效\n- 建议定期执行系统自检',
        
        'advanced-docker': '## 容器管理增强\n\n高级容器管理功能。\n\n### 功能说明\n\n1. **容器日志实时跟踪**\n   - 选择容器\n   - 开始实时日志跟踪\n   - 查看容器输出日志\n\n2. **容器提交为镜像**\n   - 选择要提交的容器\n   - 设置镜像名称和标签\n   - 提交为新镜像\n\n3. **白名单管理**\n   - 管理容器白名单\n   - 控制允许运行的容器\n\n### 使用提示\n\n- 实时日志需要 WebSocket 连接\n- 提交镜像会保存容器当前状态',
        
        'advanced-extend': '## 拓展功能\n\n管理系统拓展功能。\n\n### 功能说明\n\n1. **功能开关**\n   - 启用或禁用拓展功能\n   - 配置功能参数\n\n### 使用提示\n\n- 部分功能需要管理员权限\n- 启用功能后需要刷新页面',
        
        'check': '## 系统自检\n\n检查系统环境和配置。\n\n### 功能说明\n\n1. **开始检查**: 点击按钮执行系统检查\n2. **查看结果**: 检查完成后显示各项状态\n3. **修复建议**: 根据检查结果提供修复建议\n\n### 检查项\n\n- ROS2 环境配置\n- Docker 服务状态\n- 网络连接\n- 目录权限',
        
        'welcome': '## 欢迎页面\n\n欢迎使用 ROS2 Web 管理工具。\n\n### 功能概览\n\n- 📜 **脚本生成**: 生成 ROS2 启动脚本\n- 🚛 **仿真车启动**: 管理和启动仿真车辆\n- 🐳 **Docker 管理**: 管理 Docker 容器\n- 💿 **镜像管理**: 管理 Docker 镜像\n- 🚦 **红绿灯模拟**: 模拟交通信号灯\n- 💥 **故障注入**: 模拟系统故障\n- 🛠️ **其他工具**: 系统维护工具\n- 🎮 **仿真控制**: 控制仿真环境\n- 📡 **话题查看**: 查看 ROS2 话题\n- 🔷 **节点管理**: 管理 ROS2 节点\n- 🔧 **服务管理**: 管理 ROS2 服务\n- ⚡ **Action 管理**: 管理 ROS2 Action\n- 📊 **系统监控**: 监控系统资源\n- ⚙️ **系统设置**: 配置系统参数\n\n### 使用提示\n\n- 使用左侧导航菜单切换功能模块\n- 点击右下角帮助按钮查看当前页面帮助\n- 系统设置中可配置界面偏好和帮助文档',
        
        'advanced-scripts': '## 脚本执行增强\n\n高级脚本执行功能。\n\n### 功能说明\n\n1. **脚本执行增强**\n   - 支持脚本执行状态跟踪\n   - 显示执行进度和结果\n   - 支持执行日志查看\n\n### 使用提示\n\n- 需要先在脚本生成页面生成脚本\n- 执行增强功能需要管理员权限',
        
        'api-manager': '## REST API 管理\n\n管理系统 REST API 服务，配置端口、认证，并提供 API 文档入口。\n\n### 功能说明\n\n1. **API 配置**\n   - API 端口: 设置 API 服务监听端口（默认 8875）\n   - 认证 Token: 设置访问令牌，留空表示无需认证\n   - 启用/禁用: 控制 API 服务开关\n   - 需要认证: 开启后所有 API 请求需携带 Token\n\n2. **API 文档入口**\n   - 📖 **Swagger UI**: 交互式 API 文档，支持在线测试\n   - 📄 **ReDoc**: 美观的文档展示界面\n   - 点击按钮即可在新窗口打开文档\n\n3. **认证方式**\n   如果启用了 Token 认证，调用 API 时需在请求头中添加：\n   ```\n   Authorization: Bearer YOUR_TOKEN\n   ```\n\n4. **连接测试**\n   点击「🔍 测试连接」可检测 API 服务是否正常响应，显示响应时间、接口数量等信息。',
        
        'theme': '## 主题设置\n\n自定义界面外观和显示效果。\n\n### 功能说明\n\n1. **主题模式**\n   - 亮色模式: 明亮清爽的界面\n   - 暗色模式: 护眼深色主题\n   - 跟随系统: 根据系统设置自动切换\n\n2. **主题色**\n   - 选择界面强调色\n   - 支持多种预设颜色\n\n3. **字体大小**\n   - 调整界面字体大小\n   - 适应不同显示需求\n\n### 使用提示\n\n- 主题设置立即生效\n- 偏好设置会自动保存'
    };
    return defaults[panelId] || '暂无帮助文档';
}

/**
 * 保存帮助文档内容
 */
function saveHelpContent(panelId) {
    var editor = document.getElementById('helpContentEditor');
    var page = panelId;
    
    if (editor) {
        page = page || document.getElementById('helpPageSelect').value;
        var content = editor.value;
        
        apiPost('/api/system/help', {
            page: page,
            content: content
        }).then(function(d) {
            if (d.success) {
                showToast(d.message || '帮助文档保存成功', 'success');
                if (currentHelpTab === page) {
                    loadHelpPanelContent(page);
                }
            } else {
                showToast(d.message || '保存失败', 'error');
            }
        }).catch(function() {
            showToast('保存失败，请检查网络连接', 'error');
        });
        return;
    }
    
    var textarea = document.getElementById(panelId + '-help-textarea');
    if (!textarea) return;
    
    var content = textarea.value;
    apiPost('/api/system/help', {
        page: panelId,
        content: content
    }).then(function(d) {
        showToast(d.message || (d.success ? '帮助文档保存成功' : '保存失败'), d.success ? 'success' : 'error');
        if (d.success && currentHelpTab === panelId) {
            loadHelpPanelContent(panelId);
        }
    }).catch(function() {
        showToast('保存失败，请检查网络连接', 'error');
    });
}

/**
 * 重置帮助文档内容（恢复到上次保存的内容）
 */
function resetHelpContent() {
    var editor = document.getElementById('helpContentEditor');
    if (editor) {
        var page = document.getElementById('helpPageSelect').value;
        loadHelpContent(page);
        showToast('已重置为当前保存的内容', 'info');
    }
}

/**
 * 删除帮助文档内容（恢复为默认值）
 */
function deleteHelpContent(panelId) {
    var page = panelId;
    var editor = document.getElementById('helpContentEditor');
    if (editor) {
        page = page || document.getElementById('helpPageSelect').value;
    }
    
    var pageName = page;
    if (helpPagesCache) {
        var found = helpPagesCache.find(function(p) { return p.id === page; });
        if (found) pageName = found.name;
    }
    
    customConfirm('确定要删除 "' + pageName + '" 的帮助文档吗？删除后将恢复为系统默认内容。', function() {
        return;
    });
    
    apiDelete('/api/system/help/' + page).then(function(d) {
        if (d.success) {
            showToast(d.message || '帮助文档已恢复默认', 'success');
            if (editor) {
                editor.value = d.content || getDefaultHelpContent(page);
            }
            loadHelpPanelContent(page);
        } else {
            showToast(d.message || '删除失败', 'error');
        }
    }).catch(function() {
        showToast('删除失败，请检查网络连接', 'error');
    });
}

/**
 * 保存当前卡片配置为默认配置（管理员功能）
 */
function saveCardConfigsAsDefault() {
    if (!hasPermission('admin')) {
        showToast('您没有管理员权限', 'warning');
        return;
    }
    
    var cardConfigs = getCardConfigs();
    apiPost('/api/system/settings', {
        key: 'default_card_configs',
        value: JSON.stringify(cardConfigs)
    }).then(function(d) {
        showToast(d.message || (d.success ? '配置保存成功' : '保存失败'), d.success ? 'success' : 'error');
    });
}

/**
 * 处理 filterScripts 相关前端逻辑。
 */
function filterScripts() {
    var keyword = document.getElementById('scriptFilter').value.toLowerCase();
    var rows = document.querySelectorAll('#scriptsTableBody .script-row');
    var hasVisible = false;
    for (var i = 0; i < rows.length; i++) {
        var name = rows[i].getAttribute('data-script').toLowerCase();
        var match = name.includes(keyword);
        rows[i].style.display = match ? '' : 'none';
        if (match) hasVisible = true;
    }
    if (hasVisible && !scriptsExpanded) expandScripts();
}

/**
 * 处理 toggleAllScripts 相关前端逻辑。
 */
function toggleAllScripts() {
    var checked = document.getElementById('selectAllScripts').checked;
    var rows = document.querySelectorAll('#scriptsTableBody .script-row');
    for (var i = 0; i < rows.length; i++) {
        if (rows[i].style.display !== 'none') {
            var cb = rows[i].querySelector('.script-checkbox');
            if (cb) cb.checked = checked;
        }
    }
}

/**
 * 处理 selectAllScripts 相关前端逻辑。
 */
function selectAllScripts() {
    var rows = document.querySelectorAll('#scriptsTableBody .script-row');
    for (var i = 0; i < rows.length; i++) {
        if (rows[i].style.display !== 'none') {
            var cb = rows[i].querySelector('.script-checkbox');
            if (cb) cb.checked = true;
        }
    }
    updateSelectAllState();
}

/**
 * 处理 invertSelectScripts 相关前端逻辑。
 */
function invertSelectScripts() {
    var rows = document.querySelectorAll('#scriptsTableBody .script-row');
    for (var i = 0; i < rows.length; i++) {
        if (rows[i].style.display !== 'none') {
            var cb = rows[i].querySelector('.script-checkbox');
            if (cb) cb.checked = !cb.checked;
        }
    }
    updateSelectAllState();
}

/**
 * 处理 updateSelectAllState 相关前端逻辑。
 */
function updateSelectAllState() {
    var rows = document.querySelectorAll('#scriptsTableBody .script-row:not([style*="display: none"])');
    var all = 0, checked = 0;
    for (var i = 0; i < rows.length; i++) {
        var cb = rows[i].querySelector('.script-checkbox');
        if (cb) { all++; if (cb.checked) checked++; }
    }
    document.getElementById('selectAllScripts').checked = all > 0 && all === checked;
}

/**
 * 处理 clearSelectScripts 相关前端逻辑。
 */
function clearSelectScripts() {
    var cbs = document.querySelectorAll('.script-checkbox');
    for (var i = 0; i < cbs.length; i++) cbs[i].checked = false;
    document.getElementById('selectAllScripts').checked = false;
}

/**
 * 处理 batchExecuteScripts 相关前端逻辑。
 */
function batchExecuteScripts() {
    var selected = [];
    var cbs = document.querySelectorAll('.script-checkbox:checked');
    for (var i = 0; i < cbs.length; i++) selected.push(cbs[i].value);
    if (!selected.length) { showToast('请至少选择一个脚本', 'warning'); return; }
    var mode = document.getElementById('batchExecMode').value;
    showToast('⏳ 正在 ' + mode + ' 执行 ' + selected.length + ' 个脚本...', 'info');
    var body = { scripts: selected, mode: mode };
    if (currentTargetUser) body.target_user = currentTargetUser;
    apiPost('/api/scripts/batch-execute', body).then(function(result) {
        if (result.success) {
            var successCount = 0;
            var failCount = 0;
            for (var i = 0; i < result.results.length; i++) {
                var r = result.results[i];
                if (r.success) successCount++;
                else failCount++;
            }
            var msg = '✅ 执行完成: ' + successCount + '成功, ' + failCount + '失败';
            showToast(msg, successCount > 0 && failCount === 0 ? 'success' : 'warning');
            setTimeout(function() { loadContainers(false, 'ros2_'); }, 2000);
            // 通知引导系统车辆已启动
            if (successCount > 0 && typeof Onboarding !== 'undefined' && Onboarding.notifyExecuteStarted) {
                setTimeout(function() { Onboarding.notifyExecuteStarted(); }, 2500);
            }
        } else {
            showToast('❌ 批量执行失败: ' + (result.error || ''), 'error');
        }
    });
}

/**
 * 处理 executeSingleScript 相关前端逻辑。
 */
function executeSingleScript(name) {
    showToast('⏳ 正在执行脚本 ' + name + '...', 'info');
    var body = { script: name };
    if (currentTargetUser) body.target_user = currentTargetUser;
    apiPost('/api/scripts/execute', body).then(function(d) {
        if (d.success) {
            showToast('✅ 脚本 ' + name + ' 执行完成', 'success');
            setTimeout(function() { loadContainers(false, 'ros2_'); }, 2000);
            // 通知引导系统车辆已启动
            if (typeof Onboarding !== 'undefined' && Onboarding.notifyExecuteStarted) {
                setTimeout(function() { Onboarding.notifyExecuteStarted(); }, 2500);
            }
        } else {
            showToast('❌ 脚本 ' + name + ' 执行失败: ' + (d.error || ''), 'error');
        }
    });
}

/**
 * 处理 editScript 相关前端逻辑。
 */
function editScript(name) {
    apiGet(appendTargetUser('/api/scripts/' + encodeURIComponent(name) + '/content')).then(function(d) {
        if (!d.success) { showToast('获取脚本内容失败: ' + (d.error || ''), 'error'); return; }
        var overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = '<div class="modal">' +
            '<h3 style="color:var(--text-primary)">✏️ 编辑脚本: ' + escapeHtml(name) + '</h3>' +
            '<textarea id="scriptEditor" rows="20" style="width:100%;font-family:monospace;font-size:13px;background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-color);border-radius:var(--radius);padding:8px;margin-top:8px;">' + escapeHtml(d.content) + '</textarea>' +
            '<div style="margin-top:12px;display:flex;gap:8px;">' +
            '<button class="btn" onclick="saveScript(\'' + name + '\')">💾 保存</button>' +
            '<button class="btn btn-outline" onclick="this.closest(\'.modal-overlay\').remove()">取消</button>' +
            '</div></div>';
        document.body.appendChild(overlay);
        overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });
    });
}

/**
 * 处理 saveScript 相关前端逻辑。
 */
function saveScript(name) {
    var content = document.getElementById('scriptEditor').value;
    var body = { content: content };
    if (currentTargetUser) body.target_user = currentTargetUser;
    apiPut('/api/scripts/' + encodeURIComponent(name), body).then(function(d) {
        if (d.success) {
            showToast('保存成功', 'success');
            var overlay = document.querySelector('.modal-overlay');
            if (overlay) overlay.remove();
            loadScripts();
        } else {
            showToast('保存失败: ' + (d.error || ''), 'error');
        }
    });
}

/**
 * 处理 deleteScript 相关前端逻辑。
 */
function deleteScript(name) {
    customConfirm('确定要删除脚本 ' + name + ' 吗？', function() {
    });
    apiDelete(appendTargetUser('/api/scripts/' + encodeURIComponent(name))).then(function(d) {
        showToast(d.success ? '已删除' : '删除失败: ' + (d.error || ''), d.success ? 'success' : 'error');
        if (d.success) loadScripts();
    });
}

/**
 * 处理 removeGpuFromScripts 相关前端逻辑。
 */
function removeGpuFromScripts() {
    if (!hasPermission('scripts')) {
        showToast('您没有脚本生成的操作权限', 'warning');
        return;
    }
    customConfirm('确定移除所有脚本中的 GPU 参数？', function() {
    });
    var body = {};
    if (currentTargetUser) body.target_user = currentTargetUser;
    apiPost('/api/scripts/remove-gpu', body).then(function(d) {
        showToast(d.success ? '已修改 ' + d.modified + ' 个脚本' : '失败', d.success ? 'success' : 'error');
    });
}

// ========== 预留扩展区域（第651-700行） ==========
// 预留用于未来扩展，如脚本模板管理、版本控制等
// ===========================================

// ============================================================
// 15. 镜像管理
// ============================================================

/**
 * 获取镜像分组配置
 */
function getImageGroupsConfig() {
    var config = localStorage.getItem('imageGroupsConfig');
    if (config) {
        return JSON.parse(config);
    }
    return {
        showSimCar: true,
        showMap: true,
        showPerformance: true,
        showOther: true,
        sortOrder: ['simcar', 'map', 'performance', 'other']
    };
}

/**
 * 判断镜像属于哪个分组
 */
function getImageGroup(tag) {
    var lowerTag = tag.toLowerCase();
    if (lowerTag.includes('ros2_humble') || lowerTag.includes('robotruck')) {
        return 'simcar';
    }
    if (lowerTag.includes('map_test') || lowerTag.includes('boonraymap') || lowerTag.includes('map-frontend')) {
        return 'map';
    }
    if (lowerTag.includes('grafana') || lowerTag.includes('prometheus') || 
        lowerTag.includes('node-exporter') || lowerTag.includes('influxdb')) {
        return 'performance';
    }
    return 'other';
}

/**
 * 获取分组信息
 */
function getGroupInfo(groupKey) {
    var groups = {
        'simcar': { name: '🚗 仿真车镜像', color: 'var(--accent)' },
        'map': { name: '🗺️ 地图服务镜像', color: '#3b82f6' },
        'performance': { name: '📊 性能服务镜像', color: '#10b981' },
        'other': { name: '🔧 其他镜像', color: '#6b7280' }
    };
    return groups[groupKey] || { name: '未知', color: '#6b7280' };
}

/**
 * 打开镜像分组配置弹窗
 */
function openImageGroupsConfig() {
    var config = getImageGroupsConfig();
    document.getElementById('groupSimCar').checked = config.showSimCar;
    document.getElementById('groupMap').checked = config.showMap;
    document.getElementById('groupPerformance').checked = config.showPerformance;
    document.getElementById('groupOther').checked = config.showOther;
    
    var sortOrder = config.sortOrder;
    document.getElementById('sort1').value = sortOrder[0];
    document.getElementById('sort2').value = sortOrder[1];
    document.getElementById('sort3').value = sortOrder[2];
    document.getElementById('sort4').value = sortOrder[3];
    
    document.getElementById('imageGroupsConfigModal').style.display = 'flex';
}

/**
 * 关闭镜像分组配置弹窗
 */
function closeImageGroupsConfig() {
    document.getElementById('imageGroupsConfigModal').style.display = 'none';
}

/**
 * 保存镜像分组配置
 */
function saveImageGroupsConfig() {
    var config = {
        showSimCar: document.getElementById('groupSimCar').checked,
        showMap: document.getElementById('groupMap').checked,
        showPerformance: document.getElementById('groupPerformance').checked,
        showOther: document.getElementById('groupOther').checked,
        sortOrder: [
            document.getElementById('sort1').value,
            document.getElementById('sort2').value,
            document.getElementById('sort3').value,
            document.getElementById('sort4').value
        ]
    };
    localStorage.setItem('imageGroupsConfig', JSON.stringify(config));
    closeImageGroupsConfig();
    loadImages();
    showToast('配置已保存', 'success');
}

/**
 * 切换镜像分组的展开/收起状态
 */
function toggleImageGroup(headerRow, groupKey) {
    var toggleIcon = headerRow.querySelector('.group-toggle');
    var contentRows = document.querySelectorAll('.group-content.group-' + groupKey);
    
    var isExpanded = toggleIcon.textContent === '▼';
    
    if (isExpanded) {
        // 收起
        toggleIcon.textContent = '▶';
        contentRows.forEach(function(row) {
            row.style.display = 'none';
        });
    } else {
        // 展开
        toggleIcon.textContent = '▼';
        contentRows.forEach(function(row) {
            row.style.display = 'table-row';
        });
    }
}

/**
 * 加载镜像列表（含权限控制和分组显示）
 */
function loadImages() {
    var tbody = document.getElementById('imagesTableBody');
    tbody.innerHTML = '<tr><td colspan="4" style="text-align:center"><span class="loading"></span> 加载中...</td></tr>';
    apiGet('/api/docker/images').then(function(d) {
        if (!d.success) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;color:var(--error)">失败: ' +
                escapeHtml(d.error || '') + '</td></tr>';
            return;
        }
        if (!d.images || !d.images.length) {
            tbody.innerHTML = '<tr><td colspan="4" style="text-align:center;opacity:0.5">没有镜像</td></tr>';
            return;
        }

        var config = getImageGroupsConfig();
        var hasImagesPerm = hasPermission('images');
        
        // 按分组分类镜像
        var groupedImages = {
            'simcar': [],
            'map': [],
            'performance': [],
            'other': []
        };
        
        for (var i = 0; i < d.images.length; i++) {
            var img = d.images[i];
            var tagName = (img.tags && img.tags.length) ? img.tags[0] : img.id;
            var group = getImageGroup(tagName);
            groupedImages[group].push(img);
        }

        // 按配置的排序顺序生成HTML
        var html = '';
        for (var i = 0; i < config.sortOrder.length; i++) {
            var groupKey = config.sortOrder[i];
            var images = groupedImages[groupKey];
            var groupInfo = getGroupInfo(groupKey);
            
            // 检查是否显示该分组
            var shouldShow = false;
            if (groupKey === 'simcar' && config.showSimCar) shouldShow = true;
            if (groupKey === 'map' && config.showMap) shouldShow = true;
            if (groupKey === 'performance' && config.showPerformance) shouldShow = true;
            if (groupKey === 'other' && config.showOther) shouldShow = true;
            
            if (!shouldShow || !images.length) continue;
            
            // 添加分组标题（可点击展开/收起）
            html += '<tr class="group-header" style="background:' + groupInfo.color + '20;cursor:pointer;" onclick="toggleImageGroup(this, \'' + groupKey + '\');">';
            html += '<td colspan="4" style="padding:8px 14px;font-weight:600;color:' + groupInfo.color + ';">';
            html += '<span class="group-toggle" style="margin-right:8px;display:inline-block;width:16px;">▼</span>' + groupInfo.name + ' (' + images.length + ')';
            html += '</td></tr>';
            
            // 添加分组内的镜像（默认展开）
            for (var j = 0; j < images.length; j++) {
                var img = images[j];
                var tags = img.tags && img.tags.length ? img.tags.join(', ') : '<none>';
                var size = (img.size / 1024 / 1024).toFixed(1) + ' MB';
                var tagName = (img.tags && img.tags.length) ? img.tags[0] : img.id;
                html += '<tr class="group-content group-' + groupKey + '" style="display:table-row;">';
                html += '<td>' + escapeHtml(tags) + '</td><td>' + img.id + '</td><td>' + size + '</td><td>';
                if (hasImagesPerm) {
                    html += '<button class="btn btn-sm btn-error" onclick="removeImage(\'' + escapeHtml(tagName) + '\');event.stopPropagation();">🗑 删除</button>';
                } else {
                    html += '<span style="color:var(--text-muted);font-size:11px;">只读</span>';
                }
                html += '</td></tr>';
            }
        }
        
        tbody.innerHTML = html;
    });
}

/**
 * 处理镜像文件选择
 */
var selectedImageFile = null;
function onImageFileSelect(input) {
    if (input.files && input.files.length > 0) {
        selectedImageFile = input.files[0];
        document.getElementById('imageTarPath').value = selectedImageFile.name;
    }
}

/**
 * 处理 loadImage 相关前端逻辑。
 */
function loadImage() {
    var path = document.getElementById('imageTarPath').value.trim();
    if (!path) { showToast('请输入文件路径', 'warning'); return; }
    showToast('正在导入...', 'info');

    // 如果有选择的文件，通过 FormData 上传
    // 注意：FormData 上传时不能手动设置 Content-Type，浏览器需自动生成 multipart boundary
    if (selectedImageFile) {
        var formData = new FormData();
        formData.append('file', selectedImageFile);
        var uploadHeaders = {};
        if (AUTH_TOKEN) {
            uploadHeaders['Authorization'] = 'Bearer ' + AUTH_TOKEN;
        }
        fetch(API_BASE + '/api/docker/images/load', {
            method: 'POST',
            headers: uploadHeaders,
            body: formData
        })
        .then(function(res) {
            if (res.status === 401) {
                handleLogout();
                return { success: false, error: '未授权，请重新登录' };
            }
            return res.json().catch(function() { return { success: false, error: '解析响应失败' }; });
        })
        .then(function(d) {
            showToast(d.success ? '导入成功' : '失败: ' + (d.error || d.message || ''), d.success ? 'success' : 'error');
            if (d.success) loadImages();
            selectedImageFile = null;
            document.getElementById('imageTarPath').value = '';
        })
        .catch(function(err) {
            showToast('请求失败: ' + err.message, 'error');
        });
        return;
    }

    // 兼容本地路径方式
    apiPost('/api/docker/images/load', { path: path }).then(function(d) {
        showToast(d.success ? '导入成功' : '失败: ' + (d.error || ''), d.success ? 'success' : 'error');
        if (d.success) loadImages();
    });
}

/**
 * 处理 removeImage 相关前端逻辑。
 */
function removeImage(name) {
    customConfirm('确定删除镜像 ' + name + '？', function() {
    });
    apiDelete('/api/docker/images/' + encodeURIComponent(name)).then(function(d) {
        showToast(d.message || d.error, d.success ? 'success' : 'error');
        if (d.success) loadImages();
    });
}

// ========== 预留扩展区域（第701-750行） ==========
// 预留用于未来扩展，如镜像构建、推送等
// ===========================================

// ============================================================
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

// ========== 预留扩展区域（第751-800行） ==========
// 预留用于未来扩展，如监控图表、告警规则等
// ===========================================

// ============================================================
// 17. 其他工具
// ============================================================

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
}

function startTrafficPanelMonitor() {
    setInterval(checkTrafficPanelStatus, 2000);
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
// 20. 主题设置
// ============================================================

/**
 * 处理 setTheme 相关前端逻辑。
 */
function setTheme(theme) {
    document.body.dataset.theme = theme;
    localStorage.setItem('ros2_web_theme', theme);
    var presets = document.querySelectorAll('.theme-preset');
    for (var i = 0; i < presets.length; i++) presets[i].classList.remove('active');
    var preset = document.querySelector('.theme-preset[data-theme="' + theme + '"]');
    if (preset) preset.classList.add('active');
    buildColorSliders();
}

/**
 * 处理 loadTheme 相关前端逻辑。
 */
function loadTheme() {
    var theme = localStorage.getItem('ros2_web_theme') || 'light';
    setTheme(theme);
}

/**
 * 处理 buildColorSliders 相关前端逻辑。
 */
function buildColorSliders() {
    var container = document.getElementById('colorSliders');
    var theme = document.body.dataset.theme || 'light';
    var colors = defaultColors[theme] || defaultColors['light'];
    var labels = {
        '--bg-primary': '主背景', '--bg-secondary': '次背景', '--bg-card': '卡片背景',
        '--bg-input': '输入框', '--text-primary': '主文字', '--text-secondary': '次文字',
        '--text-muted': '弱文字', '--border-color': '边框', '--accent': '强调色',
        '--accent-hover': '强调悬停', '--accent-light': '强调浅色', '--success': '成功',
        '--warning': '警告', '--error': '错误', '--info': '信息',
        '--sidebar-bg': '侧栏背景', '--sidebar-text': '侧栏文字',
        '--sidebar-hover': '侧栏悬停', '--sidebar-active': '侧栏激活',
        '--sidebar-border': '侧栏边框', '--header-bg': '顶栏背景',
        '--header-text': '顶栏文字', '--log-bg': '日志背景', '--log-text': '日志文字'
    };
    var html = '';
    for (var key in colors) {
        if (colors.hasOwnProperty(key)) {
            html += '<div class="color-slider-item"><label>' + (labels[key] || key) + '</label><input type="color" value="' + colors[key] + '" data-var="' + key + '" onchange="updateColorFromPicker(this)"></div>';
        }
    }
    container.innerHTML = html;
    var saved = localStorage.getItem('ros2_web_custom_colors');
    if (saved) {
        try {
            var custom = JSON.parse(saved);
            var inputs = container.querySelectorAll('input[type="color"]');
            for (var i = 0; i < inputs.length; i++) {
                var key = inputs[i].dataset.var;
                if (custom[key]) {
                    inputs[i].value = custom[key];
                    document.documentElement.style.setProperty(key, custom[key]);
                }
            }
        } catch (e) { /* ignore */ }
    }
}

/**
 * 根据颜色选择器更新 CSS 变量并保存自定义主题。
 */
function updateColorFromPicker(el) {
    document.documentElement.style.setProperty(el.dataset.var, el.value);
    saveCustomColors();
}

/**
 * 处理 applyCustomColors 相关前端逻辑。
 */
function applyCustomColors() { saveCustomColors(); showToast('已应用', 'success'); }

/**
 * 保存当前自定义主题颜色到本地存储。
 */
function saveCustomColors() {
    var custom = {};
    var inputs = document.querySelectorAll('#colorSliders input[type="color"]');
    for (var i = 0; i < inputs.length; i++) {
        custom[inputs[i].dataset.var] = inputs[i].value;
    }
    localStorage.setItem('ros2_web_custom_colors', JSON.stringify(custom));
}

/**
 * 处理 resetCustomColors 相关前端逻辑。
 */
function resetCustomColors() {
    localStorage.removeItem('ros2_web_custom_colors');
    setTheme(document.body.dataset.theme || 'light');
    showToast('已恢复默认', 'info');
}

// ========== 预留扩展区域（第951-1000行） ==========
// 预留用于未来扩展，如更多主题预设等
// ===========================================

// ============================================================
// 21. 终端模拟（xterm） —— 已拆分为按需加载模块 js/panels/terminal.js
//    首次调用 openTerminal 时动态加载 xterm CDN + terminal.js，
//    避免首屏被迫下载并解析 xterm.js（gzipped ~130KB）。
// ============================================================

var _terminalReady = false;
var _terminalLoading = null;

/** 动态注入脚本并返回 Promise */
function injectScript(src) {
    return new Promise(function(resolve, reject){
        var s = document.createElement('script');
        s.src = src;
        s.onload = function(){ resolve(); };
        s.onerror = function(){ reject(new Error('脚本加载失败: ' + src)); };
        document.head.appendChild(s);
    });
}

/** 加载终端模块（xterm CSS + xterm.js + addon-fit + terminal.js） */
function loadTerminalModule() {
    var tasks = [];
    if (!document.querySelector('link[data-xterm-css]')) {
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = 'https://cdn.jsdelivr.net/npm/xterm@5.3.0/css/xterm.css';
        link.setAttribute('data-xterm-css', '1');
        document.head.appendChild(link);
    }
    if (!window.Terminal) {
        tasks.push(injectScript('https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.js'));
    }
    if (!window.FitAddon) {
        tasks.push(injectScript('https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.js'));
    }
    if (typeof _openTerminalImpl === 'undefined') {
        tasks.push(injectScript('js/panels/terminal.js'));
    }
    return Promise.all(tasks);
}

/** 打开终端（首次调用时按需加载 xterm 模块，加载完成后调用真实实现） */
function openTerminal(containerId, mode, sourceRos2) {
    if (_terminalReady) {
        return _openTerminalImpl(containerId, mode, sourceRos2);
    }
    if (!_terminalLoading) {
        _terminalLoading = loadTerminalModule().then(function(){ _terminalReady = true; });
    }
    _terminalLoading.then(function(){
        _openTerminalImpl(containerId, mode, sourceRos2);
    }).catch(function(err){
        console.error('终端模块加载失败:', err);
        if (typeof showToast === 'function') showToast('❌ 终端模块加载失败，请检查网络', 'error');
    });
}

// ========== 预留扩展区域（第1001-1050行） ==========
// 预留用于未来扩展，如终端主题、快捷键等
// ===========================================

// ============================================================
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
// 31. 子菜单控制
// ============================================================

/**
 * 处理 getSubMenuItems 相关前端逻辑。
 */
function getSubMenuItems() {
    subMenuItems['scripts'] = document.querySelector('.nav-item[data-panel="advanced-scripts"]');
    subMenuItems['docker'] = document.querySelector('.nav-item[data-panel="advanced-docker"]');
}

/**
 * 处理 toggleSubMenu 相关前端逻辑。
 */
function toggleSubMenu(parentPanel) {
    var showSubMenus = localStorage.getItem('showSubMenus') !== 'false';
    if (!showSubMenus) return;
    getSubMenuItems();
    var subItem = subMenuItems[parentPanel];
    if (!subItem) return;
    if (subItem.style.display === 'none') {
        subItem.style.display = 'flex';
    } else {
        subItem.style.display = 'none';
    }
}

/**
 * 处理 updateSubMenuVisibility 相关前端逻辑。
 */
function updateSubMenuVisibility(panel) {
    var showSubMenus = localStorage.getItem('showSubMenus') !== 'false';
    
    getSubMenuItems();
    
    // 检查当前面板是否是父级菜单或子菜单
    var isParentOrSubMenu = false;
    var matchedParentKey = null;
    for (var key in subMenuItems) {
        if (key === panel) {
            isParentOrSubMenu = true;
            matchedParentKey = key;
            break;
        }
    }
    if (!isParentOrSubMenu) {
        for (var parentKey in subMenuMap) {
            if (subMenuMap[parentKey] === panel || parentKey === panel) {
                isParentOrSubMenu = true;
                matchedParentKey = parentKey;
                break;
            }
        }
    }
    
    if (!showSubMenus || !isParentOrSubMenu) {
        // 设置隐藏时，或点击的不是父级/子菜单页面时，所有子菜单都隐藏
        for (var key in subMenuItems) {
            if (subMenuItems[key]) {
                subMenuItems[key].style.display = 'none';
            }
        }
        return;
    }
    
    // 设置展开且点击的是父级或子菜单时，只显示当前点击的父级子菜单（需要有权限），其他隐藏
    for (var key in subMenuItems) {
        if (subMenuItems[key]) {
            // 检查当前子菜单是否与面板匹配
            var isCurrentParent = (key === panel || subMenuMap[key] === panel);
            
            // 检查用户是否有该增强页面的权限
            var hasPanelPermission = hasPermission(subMenuMap[key]);
            
            // 只有同时满足：是当前父级 且 用户有权限，才显示
            var displayStyle = (isCurrentParent && hasPanelPermission) ? 'flex' : 'none';
            subMenuItems[key].style.display = displayStyle;
        }
    }
}

/**
 * 初始化子菜单显示状态
 */
function initSubMenuVisibility() {
    var showSubMenus = localStorage.getItem('showSubMenus') !== 'false';
    getSubMenuItems();
    if (!showSubMenus) {
        // 设置隐藏时，所有子菜单都隐藏
        for (var key in subMenuItems) {
            if (subMenuItems[key]) {
                subMenuItems[key].style.display = 'none';
            }
        }
    } else {
        // 设置展开时，所有子菜单都隐藏（等待点击父级时显示）
        for (var key in subMenuItems) {
            if (subMenuItems[key]) {
                subMenuItems[key].style.display = 'none';
            }
        }
    }
}

/**
 * 处理 loadSubMenuSettings 相关前端逻辑。
 */
function loadSubMenuSettings() {
    var showSubMenus = localStorage.getItem('showSubMenus');
    if (showSubMenus === null) {
        localStorage.setItem('showSubMenus', 'true');
    }
    var checkbox = document.getElementById('settingShowSubMenus');
    if (checkbox) {
        checkbox.checked = localStorage.getItem('showSubMenus') !== 'false';
    }
}

/**
 * 处理 toggleSubMenuSetting 相关前端逻辑。
 */
function toggleSubMenuSetting() {
    var checkbox = document.getElementById('settingShowSubMenus');
    if (checkbox) {
        localStorage.setItem('showSubMenus', checkbox.checked ? 'true' : 'false');
        updateSubMenuVisibility(currentPanel);
        if (currentPanel !== 'settings') {
            switchPanel(currentPanel);
        }
        showToast(checkbox.checked ? '已显示增强面板' : '已隐藏增强面板', 'info');
    }
}

// ============================================================
// 32. 工具函数
// ============================================================

/**
 * 处理 toggleScriptsDefaultExpand 相关前端逻辑。
 */
function toggleScriptsDefaultExpand() {
    var checked = document.getElementById('settingScriptsExpand').checked;
    localStorage.setItem('scriptsExpandDefault', checked ? 'true' : 'false');
    if (checked) expandScripts();
    else collapseScripts();
}

/**
 * 处理 toggleContainersCollapse 相关前端逻辑。
 */
function toggleContainersCollapse() {
    var content = document.getElementById('containersCollapsible');
    var icon = document.getElementById('containersToggleIcon');
    var toggle = document.getElementById('containersCollapseToggle');
    var isExpanded = content.classList.contains('expanded');
    
    if (isExpanded) {
        content.classList.remove('expanded');
        icon.textContent = '▶';
        toggle.innerHTML = '<span id="containersToggleIcon">▶</span> 展开';
    } else {
        content.classList.add('expanded');
        icon.textContent = '▼';
        toggle.innerHTML = '<span id="containersToggleIcon">▼</span> 收起';
    }
    localStorage.setItem('containersExpandDefault', !isExpanded ? 'true' : 'false');
}

/**
 * 处理 toggleContainersDefaultExpand 相关前端逻辑。
 */
function toggleContainersDefaultExpand() {
    var checked = document.getElementById('settingContainersExpand').checked;
    localStorage.setItem('containersExpandDefault', checked ? 'true' : 'false');
    var content = document.getElementById('containersCollapsible');
    var icon = document.getElementById('containersToggleIcon');
    var toggle = document.getElementById('containersCollapseToggle');
    
    if (checked) {
        content.classList.add('expanded');
        icon.textContent = '▼';
        toggle.innerHTML = '<span id="containersToggleIcon">▼</span> 收起';
    } else {
        content.classList.remove('expanded');
        icon.textContent = '▶';
        toggle.innerHTML = '<span id="containersToggleIcon">▶</span> 展开';
    }
}

/**
 * 处理 loadSettings 相关前端逻辑。
 */
function loadSettings() {
    var expand = localStorage.getItem('scriptsExpandDefault') === 'true';
    var checkbox = document.getElementById('settingScriptsExpand');
    if (checkbox) checkbox.checked = expand;
    if (expand) expandScripts();
    else collapseScripts();
    
    var containersExpand = localStorage.getItem('containersExpandDefault') === 'true';
    var containersCheckbox = document.getElementById('settingContainersExpand');
    if (containersCheckbox) containersCheckbox.checked = containersExpand;
    var containersContent = document.getElementById('containersCollapsible');
    var containersIcon = document.getElementById('containersToggleIcon');
    var containersToggle = document.getElementById('containersCollapseToggle');
    if (containersContent && containersIcon && containersToggle) {
        if (containersExpand) {
            containersContent.classList.add('expanded');
            containersIcon.textContent = '▼';
            containersToggle.innerHTML = '<span id="containersToggleIcon">▼</span> 收起';
        } else {
            containersContent.classList.remove('expanded');
            containersIcon.textContent = '▶';
            containersToggle.innerHTML = '<span id="containersToggleIcon">▶</span> 展开';
        }
    }
    
    // 加载子菜单显示设置
    var showSub = localStorage.getItem('showSubMenus') !== 'false';
    var subCheckbox = document.getElementById('settingShowSubMenus');
    if (subCheckbox) subCheckbox.checked = showSub;
}

/**
 * 处理 refreshImages 相关前端逻辑。
 */
function refreshImages() {
    loadImages();
    showToast('镜像列表已刷新', 'success');
}

// ============================================================
// 用户管理功能（仅管理员）
// ============================================================

/**
 * 加载用户列表
 */
function loadUserList() {
    var container = document.getElementById('userListContainer');
    if (!container) return;
    container.innerHTML = '<div style="opacity:0.5; text-align:center; padding:20px;">加载中...</div>';
    apiGet('/api/admin/users').then(function(data) {
        if (!data.success) {
            container.innerHTML = '<div style="color:var(--error);">加载失败: ' + escapeHtml(data.error || '') + '</div>';
            return;
        }
        var users = data.users || {};
        var html = '<table class="data-table">';
        html += '<thead><tr><th>用户名(Email)</th><th>角色</th><th>权限数</th><th>操作</th></tr></thead><tbody>';
        for (var email in users) {
            var info = users[email];
            var permsCount = (info.permissions || []).length;
            var isCurrent = (email === CURRENT_USER || email === localStorage.getItem('ros2_web_user'));
            html += '<tr>';
            html += '<td><strong>' + escapeHtml(email) + '</strong>' + (info.username ? ' <span style="color:var(--text-muted);font-size:11px;">(' + escapeHtml(info.username) + ')</span>' : '') + (isCurrent ? ' <span class="tag tag-info">当前</span>' : '') + '</td>';
            html += '<td><span class="tag ' + (info.role === 'admin' ? 'tag-running' : 'tag-info') + '">' + escapeHtml(info.role || 'user') + '</span></td>';
            html += '<td>' + permsCount + '</td>';
            html += '<td>';
            if (window.userRole === 'admin' && !isCurrent) {
                html += '<button class="btn btn-sm btn-outline" onclick="editUser(\'' + escapeHtml(email) + '\', \'' + escapeHtml(info.id) + '\')">✏️ 编辑</button> ';
                html += '<button class="btn btn-sm btn-error" onclick="deleteUser(\'' + escapeHtml(email) + '\', \'' + escapeHtml(info.id) + '\')">🗑 删除</button>';
            } else if (window.userRole === 'admin' && isCurrent) {
                html += '<button class="btn btn-sm btn-outline" onclick="editUser(\'' + escapeHtml(email) + '\', \'' + escapeHtml(info.id) + '\')">✏️ 编辑</button> ';
                html += '<span style="color:var(--text-muted);font-size:11px;">不能删除自己</span>';
            }
            html += '</td></tr>';
        }
        html += '</tbody></table>';
        container.innerHTML = html;
    });
}

/**
 * 显示添加用户模态框
 */
function showAddUserModal() {
    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML = '<div class="modal">' +
        '<h3 style="color:var(--text-primary);">➕ 添加用户</h3>' +
        '<div style="display:flex;flex-direction:column;gap:12px;margin-top:16px;">' +
        '<div><label style="font-size:13px;color:var(--text-secondary);">邮箱账号</label><input type="text" id="addUsername" style="width:100%;" placeholder="格式：名.姓@boonray.com"><small style="color:var(--text-muted);font-size:11px;display:block;margin-top:2px;">格式：名.姓@boonray.com</small></div>' +
        '<div><label style="font-size:13px;color:var(--text-secondary);">密码</label><input type="password" id="addPassword" style="width:100%;" placeholder="至少6位，首字母大写+特殊符号"></div>' +
        '<div><label style="font-size:13px;color:var(--text-secondary);">角色</label><select id="addRole" style="width:100%;"><option value="user">普通用户</option><option value="admin">管理员</option></select></div>' +
        '<div><label style="font-size:13px;color:var(--text-secondary);">权限分配</label>' +
        '<div id="addPermissionsContainer" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;padding:8px;border:1px solid var(--border-color);border-radius:var(--radius-sm);max-height:200px;overflow-y:auto;"></div>' +
        '</div>' +
        '</div>' +
        '<div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end;">' +
        '<button class="btn btn-success" onclick="saveUser()">💾 保存</button>' +
        '<button class="btn btn-outline" onclick="this.closest(\'.modal-overlay\').remove()">取消</button>' +
        '</div>' +
        '</div>';
    document.body.appendChild(overlay);
    overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

    // 填充权限复选框
    var container = document.getElementById('addPermissionsContainer');
    var allPanels = [
        {id: 'welcome', label: '🏠 首页', default: true},
        {id: 'scripts', label: '📜 脚本生成', default: true},
        {id: 'advanced-scripts', label: '📜 脚本执行增强', default: false},
        {id: 'vehicle', label: '🚛 仿真车启动', default: true},
        {id: 'docker', label: '🐳 Docker 管理', default: true},
        {id: 'advanced-docker', label: '🐳 容器管理增强', default: false},
        {id: 'images', label: '💿 镜像管理', default: true},
        {id: 'traffic', label: '🚦 红绿灯模拟', default: true},
        {id: 'advanced-fault', label: '💥 故障注入', default: false},
        {id: 'tools', label: '⚙️ install 配置', default: true},
        {id: 'simulation', label: '🎮 仿真控制', default: false},
        {id: 'topics', label: '📡 话题查看', default: true},
        {id: 'nodes', label: '🔷 节点管理', default: true},
        {id: 'services', label: '🔧 服务管理', default: false},
        {id: 'actions', label: '⚡ Action 管理', default: false},
        {id: 'advanced-extend', label: '🔌 拓展功能', default: false},
        {id: 'monitor', label: '📊 系统监控', default: true},
        {id: 'api-manager', label: '📡 REST API 管理', default: false},
        {id: 'theme', label: '🎨 主题设置', default: true},
        {id: 'settings', label: '⚙️ 系统设置', default: false},
        {id: 'tickets', label: '🎫 工单管理', default: true}
    ];
    var html = '';
    allPanels.forEach(function(p) {
        // 默认勾选常用权限
        var checked = p.default ? 'checked' : '';
        html += '<label style="font-size:12px;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="perm-checkbox" value="' + p.id + '" ' + checked + '>' + p.label + '</label>';
    });
    container.innerHTML = html;
}

/**
 * 保存用户
 */
function saveUser() {
    var email = document.getElementById('addUsername').value.trim();
    var password = document.getElementById('addPassword').value.trim();
    var role = document.getElementById('addRole').value;
    var perms = [];
    document.querySelectorAll('#addPermissionsContainer .perm-checkbox:checked').forEach(function(cb) {
        perms.push(cb.value);
    });
    if (!email || email.length < 3) {
        showToast('请输入邮箱账号', 'warning');
        return;
    }
    if (!email.includes('@')) {
        showToast('请输入正确的邮箱格式（名.姓@boonray.com）', 'warning');
        return;
    }
    if (!password || password.length < 6) {
        showToast('密码至少6位', 'warning');
        return;
    }
    apiPost('/api/admin/users', { email: email, password: password, role: role, permissions: perms }).then(function(data) {
        if (data.success) {
            showToast('用户创建成功', 'success');
            document.querySelector('.modal-overlay').remove();
            loadUserList();
        } else {
            showToast('创建失败: ' + (data.detail || data.error || ''), 'error');
        }
    });
}

/**
 * 编辑用户
 */
function editUser(email, userId) {
    // 获取用户信息
    apiGet('/api/admin/users').then(function(data) {
        var user = data.users ? data.users[email] : null;
        if (!user) { showToast('用户不存在', 'error'); return; }
        var overlay = document.createElement('div');
        overlay.className = 'modal-overlay';
        overlay.innerHTML = '<div class="modal">' +
            '<h3 style="color:var(--text-primary);">✏️ 编辑用户: ' + escapeHtml(email) + '</h3>' +
            '<div style="display:flex;flex-direction:column;gap:12px;margin-top:16px;">' +
            '<div><label style="font-size:13px;color:var(--text-secondary);">新密码（留空不修改）</label><input type="password" id="editPassword" style="width:100%;" placeholder="至少6位"></div>' +
            '<div><label style="font-size:13px;color:var(--text-secondary);">角色</label><select id="editRole" style="width:100%;"><option value="user"' + (user.role === 'user' ? ' selected' : '') + '>普通用户</option><option value="admin"' + (user.role === 'admin' ? ' selected' : '') + '>管理员</option></select></div>' +
            '<div><label style="font-size:13px;color:var(--text-secondary);">权限分配</label>' +
            '<div id="editPermissionsContainer" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;padding:8px;border:1px solid var(--border-color);border-radius:var(--radius-sm);max-height:200px;overflow-y:auto;"></div>' +
            '</div>' +
            '</div>' +
            '<div style="display:flex;gap:8px;margin-top:16px;justify-content:flex-end;">' +
            '<button class="btn btn-success" onclick="updateUser(\'' + escapeHtml(email) + '\', \'' + escapeHtml(userId) + '\')">💾 保存</button>' +
            '<button class="btn btn-outline" onclick="this.closest(\'.modal-overlay\').remove()">取消</button>' +
            '</div>' +
            '</div>';
        document.body.appendChild(overlay);
        overlay.addEventListener('click', function(e) { if (e.target === overlay) overlay.remove(); });

        // 填充权限复选框
        var container = document.getElementById('editPermissionsContainer');
        var allPanels = [
            {id: 'welcome', label: '🏠 首页'},
            {id: 'scripts', label: '📜 脚本生成'},
            {id: 'advanced-scripts', label: '📜 脚本执行增强'},
            {id: 'vehicle', label: '🚛 仿真车启动'},
            {id: 'docker', label: '🐳 Docker 管理'},
            {id: 'advanced-docker', label: '🐳 容器管理增强'},
            {id: 'images', label: '💿 镜像管理'},
            {id: 'traffic', label: '🚦 红绿灯模拟'},
            {id: 'advanced-fault', label: '💥 故障注入'},
            {id: 'tools', label: '⚙️ install 配置'},
            {id: 'simulation', label: '🎮 仿真控制'},
            {id: 'topics', label: '📡 话题查看'},
            {id: 'nodes', label: '🔷 节点管理'},
            {id: 'services', label: '🔧 服务管理'},
            {id: 'actions', label: '⚡ Action 管理'},
            {id: 'advanced-extend', label: '🔌 拓展功能'},
            {id: 'monitor', label: '📊 系统监控'},
            {id: 'api-manager', label: '📡 REST API 管理'},
            {id: 'theme', label: '🎨 主题设置'},
            {id: 'settings', label: '⚙️ 系统设置'},
            {id: 'tickets', label: '🎫 工单管理'}
        ];
        var userPerms = user.permissions || [];
        var html = '';
        allPanels.forEach(function(p) {
            var checked = userPerms.includes(p.id) ? 'checked' : '';
            html += '<label style="font-size:12px;display:flex;align-items:center;gap:4px;"><input type="checkbox" class="edit-perm-checkbox" value="' + p.id + '" ' + checked + '>' + p.label + '</label>';
        });
        container.innerHTML = html;
    });
}

/**
 * 更新用户
 */
function updateUser(email, userId) {
    var password = document.getElementById('editPassword').value.trim();
    var role = document.getElementById('editRole').value;
    var perms = [];
    document.querySelectorAll('#editPermissionsContainer .edit-perm-checkbox:checked').forEach(function(cb) {
        perms.push(cb.value);
    });
    var data = { role: role, permissions: perms };
    if (password) data.password = password;
    apiPut('/api/admin/users/' + encodeURIComponent(userId), data).then(function(d) {
        if (d.success) {
            showToast('用户更新成功', 'success');
            document.querySelector('.modal-overlay').remove();
            loadUserList();
        } else {
            showToast('更新失败: ' + (d.detail || d.error || ''), 'error');
        }
    });
}

/**
 * 删除用户
 */
function deleteUser(email, userId) {
    customConfirm('确定要删除用户 ' + email + ' 吗？此操作不可撤销！', function() {
        apiDelete('/api/admin/users/' + encodeURIComponent(userId)).then(function(d) {
            if (d.success) {
                showToast('用户已删除', 'success');
                loadUserList();
            } else {
                showToast('删除失败: ' + (d.detail || d.error || ''), 'error');
            }
        });
    });
}

// ============================================================
// 快速开始配置
// ============================================================

/**
 * 获取所有可用面板列表（用于快速开始配置）
 */
function getQuickStartPanels() {
    return [
        { id: 'scripts', label: '脚本生成', icon: '📜', fixed: true },
        { id: 'vehicle', label: '仿真车启动', icon: '🚛', fixed: true },
        { id: 'docker', label: 'Docker 管理', icon: '🐳', fixed: true },
        { id: 'images', label: '镜像管理', icon: '💿', fixed: false },
        { id: 'traffic', label: '红绿灯模拟', icon: '🚦', fixed: false },
        { id: 'tools', label: '其他工具', icon: '🛠', fixed: false },
        { id: 'monitor', label: '系统监控', icon: '📊', fixed: false },
        { id: 'simulation', label: '仿真控制', icon: '🎮', fixed: false },
        { id: 'topics', label: '话题查看', icon: '📡', fixed: false },
        { id: 'nodes', label: '节点管理', icon: '🔷', fixed: false },
        { id: 'services', label: '服务管理', icon: '🔧', fixed: false },
        { id: 'actions', label: 'Action 管理', icon: '⚡', fixed: false },
        { id: 'api-manager', label: 'REST API 管理', icon: '📡', fixed: false },
        { id: 'theme', label: '主题设置', icon: '🎨', fixed: false },
        { id: 'settings', label: '系统设置', icon: '⚙️', fixed: false },
        { id: 'advanced-docker', label: '容器管理增强', icon: '🐙', fixed: false },
        { id: 'advanced-scripts', label: '脚本执行增强', icon: '📜', fixed: false },
        { id: 'advanced-extend', label: '拓展功能', icon: '🔌', fixed: false },
        { id: 'advanced-fault', label: '故障注入', icon: '💥', fixed: false },
        { id: 'tickets', label: '工单管理', icon: '🎫', fixed: false }
    ];
}

/**
 * 获取用户的快速开始配置（从localStorage）
 */
function getUserQuickStartConfig() {
    try {
        var config = localStorage.getItem('quickStartConfig');
        return config ? JSON.parse(config) : null;
    } catch (e) {
        return null;
    }
}

/**
 * 保存用户的快速开始配置
 */
function saveUserQuickStartConfig(panels) {
    try {
        localStorage.setItem('quickStartConfig', JSON.stringify(panels));
        return true;
    } catch (e) {
        return false;
    }
}

/**
 * 渲染快速开始区域
 */
function renderQuickStart() {
    var grid = document.getElementById('quickStartGrid');
    if (!grid) return;

    var allPanels = getQuickStartPanels();
    var userConfig = getUserQuickStartConfig();
    var perms = window.userPermissions || [];
    var isAdmin = window.userRole === 'admin';

    // 获取所有固定面板
    var fixedPanels = allPanels.filter(function(p) { return p.fixed; });

    // 获取用户配置的非固定面板（需要有权限）
    // 只显示用户配置的，不配置则不显示（固定面板除外）
    var userSelectedPanels = [];
    if (userConfig && userConfig.length > 0) {
        userSelectedPanels = allPanels.filter(function(p) {
            if (p.fixed) return false;
            return userConfig.includes(p.id) && (isAdmin || perms.includes(p.id));
        });
        // 按配置顺序排序
        userSelectedPanels.sort(function(a, b) {
            var idxA = userConfig.indexOf(a.id);
            var idxB = userConfig.indexOf(b.id);
            return idxA - idxB;
        });
    }

    // 合并固定面板和用户选择的面板
    var displayPanels = fixedPanels.concat(userSelectedPanels);

    var html = '';
    displayPanels.forEach(function(p) {
        var hasPerm = isAdmin || perms.includes(p.id);
        var disabledClass = p.fixed || hasPerm ? '' : 'disabled';
        html += '<div class="welcome-card ' + disabledClass + '" data-panel="' + p.id + '" onclick="handleQuickStartClick(\'' + p.id + '\')">' +
                '<span class="icon">' + p.icon + '</span>' +
                '<div class="label">' + p.label + '</div>' +
                (p.fixed ? '<div class="fixed-badge">固定</div>' : '') +
                '</div>';
    });

    grid.innerHTML = html;
}

/**
 * 处理快速开始卡片点击
 */
function handleQuickStartClick(panelId) {
    var perms = window.userPermissions || [];
    var isAdmin = window.userRole === 'admin';
    var panel = getQuickStartPanels().find(function(p) { return p.id === panelId; });
    
    // 固定面板直接跳转
    if (panel && panel.fixed) {
        switchPanel(panelId);
        return;
    }
    
    // 非固定面板检查权限
    if (isAdmin || perms.includes(panelId)) {
        switchPanel(panelId);
    } else {
        showToast('您没有访问此页面的权限', 'warning');
    }
}

/**
 * 关闭快速开始配置弹窗
 */
function closeQuickStartConfig() {
    var overlay = document.getElementById('quickStartConfigModal');
    if (overlay) {
        overlay.remove();
    }
    document.removeEventListener('keydown', quickStartEscHandler);
}

/**
 * ESC键关闭弹窗处理
 */
var quickStartEscHandler = function(e) {
    if (e.key === 'Escape') {
        closeQuickStartConfig();
    }
};

/**
 * 显示快速开始配置弹窗
 */
function showQuickStartConfig() {
    // 先关闭已存在的弹窗
    closeQuickStartConfig();
    
    var overlay = document.createElement('div');
    overlay.id = 'quickStartConfigModal';
    overlay.className = 'modal-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);display:flex;align-items:center;justify-content:center;z-index:9999;';
    
    // 点击遮罩关闭
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) {
            closeQuickStartConfig();
        }
    });
    
    var modal = document.createElement('div');
    modal.style.cssText = 'background:var(--bg-card);border-radius:12px;padding:20px;width:500px;max-height:80vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.5);';
    modal.innerHTML = '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">' +
                      '<h3 style="margin:0;color:var(--text-primary);">⚙ 配置快速开始</h3>' +
                      '<button class="btn btn-sm btn-outline" onclick="closeQuickStartConfig()">✕</button>' +
                      '</div>' +
                      '<div style="font-size:12px;color:var(--text-secondary);margin-bottom:12px;">' +
                      '勾选要显示在快速开始区域的页面。<strong style="color:#d97706">脚本生成、仿真车启动、Docker 管理</strong>为固定页面，不可取消。' +
                      '</div>' +
                      '<div id="quickStartConfigContainer" style="max-height:300px;overflow-y:auto;"></div>' +
                      '<div style="display:flex;justify-content:flex-end;gap:8px;margin-top:20px;">' +
                      '<button class="btn btn-outline" onclick="closeQuickStartConfig()">取消</button>' +
                      '<button class="btn btn-primary" onclick="saveQuickStartConfig()">保存配置</button>' +
                      '</div>';
    
    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // ESC键关闭
    document.addEventListener('keydown', quickStartEscHandler);

    // 加载配置项
    loadQuickStartConfigItems();
}

/**
 * 加载快速开始配置项
 */
function loadQuickStartConfigItems() {
    var container = document.getElementById('quickStartConfigContainer');
    if (!container) return;

    var allPanels = getQuickStartPanels();
    var userConfig = getUserQuickStartConfig() || [];
    var perms = window.userPermissions || [];
    var isAdmin = window.userRole === 'admin';

    var html = '';
    allPanels.forEach(function(p) {
        // 过滤：只显示用户有权限的非固定面板，加上所有固定面板
        if (!p.fixed && !isAdmin && !perms.includes(p.id)) return;

        var checked = p.fixed || userConfig.includes(p.id);
        var disabled = p.fixed ? 'disabled' : '';
        var fixedLabel = p.fixed ? ' <span style="color:#d97706;font-size:11px;">(固定)</span>' : '';
        
        html += '<label style="display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--border-color);">' +
                '<input type="checkbox" ' + (disabled ? 'disabled ' : '') + (checked ? 'checked ' : '') + 
                'value="' + p.id + '" class="quick-start-checkbox"' + (disabled ? ' style="opacity:0.5;"' : '') + '>' +
                '<span style="font-size:14px;">' + p.icon + ' ' + p.label + fixedLabel + '</span>' +
                '</label>';
    });

    container.innerHTML = html;
}

/**
 * 保存快速开始配置
 */
function saveQuickStartConfig() {
    var selected = [];
    document.querySelectorAll('.quick-start-checkbox:checked').forEach(function(cb) {
        selected.push(cb.value);
    });

    if (saveUserQuickStartConfig(selected)) {
        showToast('配置保存成功', 'success');
        closeQuickStartConfig();
        renderQuickStart();
    } else {
        showToast('保存失败', 'error');
    }
}

/**
 * 初始化快速开始
 */
function initQuickStart() {
    // 延迟初始化，确保权限已加载
    setTimeout(function() {
        renderQuickStart();
    }, 500);
}

// ============================================================
// 内嵌 API 文档查看器（解决 /docs 和 /redoc 因 CSP 无法加载的问题）
// 使用 iframe 方案，独立渲染上下文，避免下拉框被父容器裁剪
// ============================================================
var apiDocsCurrentView = null;
var apiDocsIframeLoaded = { swagger: false, redoc: false };

function getOpenApiUrl() {
    var portInput = document.getElementById('apiMgrPort');
    var port = parseInt(portInput ? portInput.value : '8875') || 8875;
    var protocol = window.location.protocol;
    var hostname = window.location.hostname;
    return protocol + '//' + hostname + ':' + port + '/openapi.json';
}

function generateSwaggerIframeHtml(openApiUrl) {
    var safeUrl = openApiUrl.replace(/"/g, '');
    return '<!DOCTYPE html><html><head><meta charset="UTF-8">' +
        '<title>Swagger UI</title>' +
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">' +
        '<style>body{margin:0;padding:0;background:#fafafa;} #swagger-ui{margin-top:0;}</style>' +
        '</head><body>' +
        '<div id="swagger-ui"></div>' +
        '<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"><\/script>' +
        '<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-standalone-preset.js"><\/script>' +
        '<script>' +
        'window.onload = function() {' +
        '  SwaggerUIBundle({' +
        '    url: "' + safeUrl + '",' +
        '    dom_id: "#swagger-ui",' +
        '    deepLinking: true,' +
        '    presets: [SwaggerUIBundle.presets.apis, SwaggerUIStandalonePreset.slice(1)],' +
        '    layout: "BaseLayout",' +
        '    withCredentials: true,' +
        '    filter: true' +
        '  });' +
        '};<\/script>' +
        '</body></html>';
}

function generateRedocIframeHtml(openApiUrl) {
    var safeUrl = openApiUrl.replace(/"/g, '');
    return '<!DOCTYPE html><html><head><meta charset="UTF-8">' +
        '<title>ReDoc</title>' +
        '<style>body{margin:0;padding:0;background:white;}</style>' +
        '</head><body>' +
        '<redoc spec-url="' + safeUrl + '" expand-responses="all" required-props-first="true"></redoc>' +
        '<script src="https://cdn.jsdelivr.net/npm/redoc@2.0.0/bundles/redoc.standalone.js"><\/script>' +
        '</body></html>';
}

function showApiDocsModal(viewType) {
    var modal = document.getElementById('apiDocsModal');
    modal.style.display = 'flex';
    document.getElementById('apiDocsLoading').style.display = 'block';
    
    // 隐藏所有容器
    document.getElementById('swaggerIframe').style.display = 'none';
    document.getElementById('redocIframe').style.display = 'none';
    document.getElementById('swaggerUIContainer').style.display = 'none';
    document.getElementById('redocContainer').style.display = 'none';
    
    // 重置模态框容器样式
    var container = document.getElementById('apiDocsContainer');
    container.style.overflow = '';
    container.style.height = '';

    switchApiDocsView(viewType || 'swagger');
}

function getApiDocsBaseUrl() {
    var portInput = document.getElementById('apiMgrPort');
    var port = parseInt(portInput ? portInput.value : '8875') || 8875;
    var protocol = window.location.protocol;
    var hostname = window.location.hostname;
    return protocol + '//' + hostname + ':' + port;
}

function switchApiDocsView(viewType) {
    if (viewType === apiDocsCurrentView) return;
    apiDocsCurrentView = viewType;

    document.getElementById('apiDocsLoading').style.display = 'block';
    
    // 隐藏所有iframe
    document.getElementById('swaggerIframe').style.display = 'none';
    document.getElementById('redocIframe').style.display = 'none';

    var baseUrl = getApiDocsBaseUrl();
    var title = viewType === 'swagger' ? '📖 Swagger UI - API 文档' : '📄 ReDoc - API 文档';
    document.getElementById('apiDocsTitle').textContent = title;

    setTimeout(function() {
        if (viewType === 'swagger') {
            var iframe = document.getElementById('swaggerIframe');
            iframe.style.display = 'block';
            var swaggerUrl = baseUrl + '/api/docs';
            if (iframe.src !== swaggerUrl) {
                iframe.src = swaggerUrl;
                iframe.onload = function() {
                    document.getElementById('apiDocsLoading').style.display = 'none';
                };
                setTimeout(function() {
                    document.getElementById('apiDocsLoading').style.display = 'none';
                }, 3000);
            } else {
                document.getElementById('apiDocsLoading').style.display = 'none';
            }
        } else {
            var iframe = document.getElementById('redocIframe');
            iframe.style.display = 'block';
            var redocUrl = baseUrl + '/api/redoc';
            if (iframe.src !== redocUrl) {
                iframe.src = redocUrl;
                iframe.onload = function() {
                    document.getElementById('apiDocsLoading').style.display = 'none';
                };
                setTimeout(function() {
                    document.getElementById('apiDocsLoading').style.display = 'none';
                }, 3000);
            } else {
                document.getElementById('apiDocsLoading').style.display = 'none';
            }
        }
    }, 100);
}

function closeApiDocsModal() {
    document.getElementById('apiDocsModal').style.display = 'none';
    apiDocsCurrentView = null;
}

// 点击模态框遮罩关闭
document.addEventListener('click', function(e) {
    if (e.target.id === 'apiDocsModal') {
        closeApiDocsModal();
    }
});

// ESC 键关闭
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        var modal = document.getElementById('apiDocsModal');
        if (modal && modal.style.display !== 'none') {
            closeApiDocsModal();
        }
    }
});

// ============================================================
// 工单系统模块 (Tickets)
// ============================================================

var ticketsCurrentPage = 1;
var ticketsPageSize = 20;
var ticketsMetaCache = { categories: [], statuses: [], priorities: [], transitions: {}, is_admin: false };
var ticketsEditingId = null;       // 当前编辑的工单 ID（null=新建）
var ticketsPendingAttachments = []; // 表单中已上传的附件

function _ticketStatusBadge(status) {
    var map = {
        pending:    { text: '待处理',  cls: 'ticket-status-pending' },
        processing: { text: '处理中',  cls: 'ticket-status-processing' },
        resolved:   { text: '已解决',  cls: 'ticket-status-resolved' },
        closed:     { text: '已关闭',  cls: 'ticket-status-closed' }
    };
    var s = map[status] || { text: status, cls: '' };
    return '<span class="ticket-status-badge ' + s.cls + '">' + s.text + '</span>';
}

function _ticketPriorityBadge(p) {
    var p = parseInt(p, 10) || 3;
    var cls = '';
    if (p >= 5) cls = 'ticket-pri-urgent';
    else if (p === 4) cls = 'ticket-pri-high';
    else if (p === 3) cls = 'ticket-pri-mid';
    else cls = 'ticket-pri-low';
    return '<span class="ticket-pri-badge ' + cls + '">P' + p + '</span>';
}

function _ticketFormatTime(t) {
    if (!t) return '-';
    try {
        var d = new Date(t);
        if (isNaN(d.getTime())) return t;
        var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
        return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate())
             + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    } catch (e) { return t; }
}

function _ticketEscape(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/[&<>"']/g, function(c) {
        return { '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c];
    });
}

function _ticketFormatSize(bytes) {
    if (!bytes) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB'];
    var i = 0;
    while (bytes >= 1024 && i < units.length - 1) { bytes /= 1024; i++; }
    return bytes.toFixed(1) + ' ' + units[i];
}

// ---------- 元信息加载 ----------

function loadTicketsMeta() {
    apiGet('/api/tickets/meta').then(function(res) {
        if (!res.success) return;
        ticketsMetaCache = {
            categories: res.categories || [],
            statuses: res.statuses || [],
            priorities: res.priorities || [],
            transitions: res.transitions || {},
            is_admin: !!res.is_admin,
            current_user_id: res.current_user_id,
            current_username: res.current_username
        };
        // 填充分类下拉框
        var filterCat = document.getElementById('ticketFilterCategory');
        var formCat = document.getElementById('ticketFormCategory');
        if (filterCat) {
            var cur = filterCat.value;
            var html = '<option value="">全部</option>';
            for (var i = 0; i < ticketsMetaCache.categories.length; i++) {
                html += '<option value="' + _ticketEscape(ticketsMetaCache.categories[i]) + '">' + _ticketEscape(ticketsMetaCache.categories[i]) + '</option>';
            }
            filterCat.innerHTML = html;
            filterCat.value = cur;
        }
        if (formCat) {
            var html2 = '';
            for (var i = 0; i < ticketsMetaCache.categories.length; i++) {
                html2 += '<option value="' + _ticketEscape(ticketsMetaCache.categories[i]) + '">' + _ticketEscape(ticketsMetaCache.categories[i]) + '</option>';
            }
            formCat.innerHTML = html2;
        }
        // 角色提示
        var hint = document.getElementById('ticketsRoleHint');
        if (hint) {
            hint.textContent = ticketsMetaCache.is_admin
                ? '👤 管理员模式：可查看与处理全部工单'
                : '👤 普通用户：仅可查看与处理自己提交的工单';
        }
    });
}

// ---------- 列表加载 ----------

function loadTickets(page) {
    if (page) ticketsCurrentPage = parseInt(page, 10) || 1;
    var params = '?page=' + ticketsCurrentPage + '&limit=' + ticketsPageSize;
    var status = (document.getElementById('ticketFilterStatus') || {}).value || '';
    var category = (document.getElementById('ticketFilterCategory') || {}).value || '';
    var priority = (document.getElementById('ticketFilterPriority') || {}).value || '';
    var keyword = (document.getElementById('ticketFilterKeyword') || {}).value || '';
    if (status) params += '&status=' + encodeURIComponent(status);
    if (category) params += '&category=' + encodeURIComponent(category);
    if (priority) params += '&priority=' + encodeURIComponent(priority);
    if (keyword) params += '&keyword=' + encodeURIComponent(keyword);

    var tbody = document.getElementById('ticketsTableBody');
    if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;opacity:0.5;">加载中...</td></tr>';

    apiGet('/api/tickets' + params).then(function(res) {
        if (!res.success) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:#e74c3c;">' + _ticketEscape(res.error || '加载失败') + '</td></tr>';
            return;
        }
        var items = res.items || [];
        var total = res.total || 0;
        var isAdmin = !!res.is_admin;

        // 更新分页信息
        var pageInfo = document.getElementById('ticketsPageInfo');
        var totalPages = Math.max(1, Math.ceil(total / ticketsPageSize));
        if (pageInfo) pageInfo.textContent = '第 ' + ticketsCurrentPage + ' / ' + totalPages + ' 页，共 ' + total + ' 条';
        var prevBtn = document.getElementById('ticketsPrevBtn');
        var nextBtn = document.getElementById('ticketsNextBtn');
        if (prevBtn) prevBtn.disabled = ticketsCurrentPage <= 1;
        if (nextBtn) nextBtn.disabled = ticketsCurrentPage >= totalPages;
        var hint = document.getElementById('ticketsTotalHint');
        if (hint) hint.textContent = '(' + total + ' 条)';

        if (!items.length) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;opacity:0.5;">暂无工单</td></tr>';
            return;
        }

        var html = '';
        for (var i = 0; i < items.length; i++) {
            var t = items[i];
            html += '<tr data-ticket-id="' + _ticketEscape(t.id) + '" style="cursor:pointer;" onclick="showTicketDetail(\'' + _ticketEscape(t.id) + '\')">'
                + '<td><strong>' + _ticketEscape(t.ticket_no) + '</strong></td>'
                + '<td>' + _ticketEscape(t.title) + '</td>'
                + '<td>' + _ticketEscape(t.category || '-') + '</td>'
                + '<td style="text-align:center;">' + _ticketPriorityBadge(t.priority) + '</td>'
                + '<td style="text-align:center;">' + _ticketStatusBadge(t.status) + '</td>'
                + '<td>' + _ticketEscape(t.customer_name || '-') + '</td>'
                + '<td>' + _ticketEscape(t.assignee_name || '-') + '</td>'
                + '<td style="font-size:12px;">' + _ticketFormatTime(t.created_at) + '</td>'
                + '<td onclick="event.stopPropagation();">'
                  + '<button class="btn btn-sm" onclick="showTicketDetail(\'' + _ticketEscape(t.id) + '\')">查看</button>'
                + '</td>'
                + '</tr>';
        }
        if (tbody) tbody.innerHTML = html;
    });
}

function changeTicketPage(delta) {
    var newPage = ticketsCurrentPage + delta;
    if (newPage < 1) newPage = 1;
    loadTickets(newPage);
}

// ---------- 创建/编辑 ----------

function showTicketCreateModal() {
    ticketsEditingId = null;
    ticketsPendingAttachments = [];
    document.getElementById('ticketFormTitle').textContent = '提交工单';
    document.getElementById('ticketFormSubmitBtn').textContent = '提交';
    document.getElementById('ticketFormTitleInput').value = '';
    document.getElementById('ticketFormContent').value = '';
    document.getElementById('ticketFormPriority').value = '3';
    if (ticketsMetaCache.categories.length) {
        document.getElementById('ticketFormCategory').value = ticketsMetaCache.categories[ticketsMetaCache.categories.length - 1];
    }
    document.getElementById('ticketFormFiles').value = '';
    document.getElementById('ticketFormAttachments').innerHTML = '';
    var modal = document.getElementById('ticketFormModal');
    modal.style.display = 'flex';
}

function hideTicketFormModal() {
    document.getElementById('ticketFormModal').style.display = 'none';
    ticketsPendingAttachments = [];
}

function submitTicketForm() {
    var title = (document.getElementById('ticketFormTitleInput').value || '').trim();
    var content = (document.getElementById('ticketFormContent').value || '').trim();
    var category = document.getElementById('ticketFormCategory').value;
    var priority = parseInt(document.getElementById('ticketFormPriority').value, 10) || 3;
    if (!title) { showToast('请填写标题', 'error'); return; }
    if (!content) { showToast('请填写问题描述', 'error'); return; }

    var btn = document.getElementById('ticketFormSubmitBtn');
    btn.disabled = true;
    btn.textContent = '提交中...';

    function finalize(payload) {
        if (ticketsEditingId) {
            apiPut('/api/tickets/' + ticketsEditingId, payload).then(function(res) {
                btn.disabled = false;
                btn.textContent = '提交';
                if (res.success) {
                    showToast('工单已更新', 'success');
                    hideTicketFormModal();
                    loadTickets();
                } else {
                    showToast(res.error || '更新失败', 'error');
                }
            }).catch(function() {
                btn.disabled = false;
                btn.textContent = '提交';
            });
        } else {
            apiPost('/api/tickets', payload).then(function(res) {
                btn.disabled = false;
                btn.textContent = '提交';
                if (res.success) {
                    showToast('工单已提交：' + (res.ticket && res.ticket.ticket_no || ''), 'success');
                    hideTicketFormModal();
                    loadTickets(1);
                } else {
                    showToast(res.error || '提交失败', 'error');
                }
            }).catch(function() {
                btn.disabled = false;
                btn.textContent = '提交';
            });
        }
    }

    // 上传附件（如有）
    var filesInput = document.getElementById('ticketFormFiles');
    var files = filesInput && filesInput.files ? Array.from(filesInput.files) : [];
    if (!files.length) {
        finalize({ title: title, content: content, category: category, priority: priority, attachments: ticketsPendingAttachments });
        return;
    }
    // 顺序上传（使用 XHR 以正确处理 FormData）
    var uploaded = ticketsPendingAttachments.slice();
    var idx = 0;
    function uploadNext() {
        if (idx >= files.length) {
            ticketsPendingAttachments = uploaded;
            finalize({ title: title, content: content, category: category, priority: priority, attachments: uploaded });
            return;
        }
        var f = files[idx++];
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API_BASE + '/api/tickets/attachments');
        xhr.setRequestHeader('Authorization', 'Bearer ' + (localStorage.getItem('token') || ''));
        xhr.onload = function() {
            try {
                var r = JSON.parse(xhr.responseText);
                if (r.success && r.attachment) uploaded.push(r.attachment);
            } catch (e) {}
            uploadNext();
        };
        xhr.onerror = function() { uploadNext(); };
        var fd = new FormData();
        fd.append('file', f);
        xhr.send(fd);
    }
    uploadNext();
}

// ---------- 详情 ----------

var ticketDetailCurrentId = null;

function showTicketDetail(ticketId) {
    ticketDetailCurrentId = ticketId;
    apiGet('/api/tickets/' + encodeURIComponent(ticketId)).then(function(res) {
        if (!res.success) {
            showToast(res.error || '加载工单失败', 'error');
            return;
        }
        renderTicketDetail(res.ticket, res.replies || [], res.is_admin, res.current_user_id);
        var modal = document.getElementById('ticketDetailModal');
        modal.style.display = 'flex';
    });
}

function hideTicketDetailModal() {
    document.getElementById('ticketDetailModal').style.display = 'none';
    ticketDetailCurrentId = null;
}

function renderTicketDetail(ticket, replies, isAdmin, currentUserId) {
    var body = document.getElementById('ticketDetailBody');
    if (!ticket) { body.innerHTML = '<p>工单不存在</p>'; return; }
    var isOwner = ticket.customer_id === currentUserId;
    var canEdit = isAdmin || isOwner;
    var transitions = ticketsMetaCache.transitions || {};
    var allowedNext = transitions[ticket.status] || [];

    // 头部信息卡
    var html = '<div class="card" style="margin-bottom:12px;">'
        + '<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:8px;">'
        +   '<div>'
        +     '<div style="font-size:12px;opacity:0.6;">' + _ticketEscape(ticket.ticket_no) + '</div>'
        +     '<h2 style="margin:4px 0;font-size:18px;">' + _ticketEscape(ticket.title) + '</h2>'
        +     '<div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">'
        +       _ticketStatusBadge(ticket.status)
        +       _ticketPriorityBadge(ticket.priority)
        +       '<span style="font-size:12px;opacity:0.7;">分类: ' + _ticketEscape(ticket.category || '-') + '</span>'
        +     '</div>'
        +   '</div>'
        +   '<div style="text-align:right;font-size:12px;opacity:0.7;">'
        +     '<div>提交人: ' + _ticketEscape(ticket.customer_name || '-') + '</div>'
        +     '<div>处理人: ' + _ticketEscape(ticket.assignee_name || '-') + '</div>'
        +     '<div>创建: ' + _ticketFormatTime(ticket.created_at) + '</div>'
        +     '<div>更新: ' + _ticketFormatTime(ticket.updated_at) + '</div>'
        +     (ticket.resolved_at ? '<div>解决: ' + _ticketFormatTime(ticket.resolved_at) + '</div>' : '')
        +     (ticket.closed_at ? '<div>关闭: ' + _ticketFormatTime(ticket.closed_at) + '</div>' : '')
        +   '</div>'
        + '</div>';

    // 问题描述
    html += '<div style="margin-top:12px;padding:12px;background:var(--bg-input);border-radius:var(--radius);">'
        + '<div style="font-size:12px;opacity:0.6;margin-bottom:4px;">问题描述</div>'
        + '<div style="white-space:pre-wrap;word-break:break-word;">' + _ticketEscape(ticket.content) + '</div>'
        + '</div>';

    // 附件列表
    var atts = ticket.attachments || [];
    if (atts.length) {
        html += '<div style="margin-top:8px;font-size:12px;">附件：';
        for (var i = 0; i < atts.length; i++) {
            var a = atts[i];
            html += '<a href="' + (a.url || '#') + '" target="_blank" style="margin-right:8px;color:var(--accent);">'
                + '📎 ' + _ticketEscape(a.filename) + ' (' + _ticketFormatSize(a.size) + ')</a>';
        }
        html += '</div>';
    }

    // 操作按钮
    html += '<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">';
    if (canEdit) {
        html += '<button class="btn btn-sm" onclick="editTicketFromDetail(\'' + _ticketEscape(ticket.id) + '\')">✏️ 编辑</button>';
    }
    if (isAdmin) {
        // 状态流转按钮
        for (var i = 0; i < allowedNext.length; i++) {
            var ns = allowedNext[i];
            var label = { processing: '处理中', resolved: '标记已解决', closed: '关闭工单', pending: '重置为待处理' }[ns] || ns;
            html += '<button class="btn btn-sm btn-primary" onclick="changeTicketStatus(\'' + _ticketEscape(ticket.id) + '\',\'' + ns + '\')">' + label + '</button>';
        }
        if (ticket.status !== 'closed') {
            html += '<button class="btn btn-sm btn-danger" onclick="deleteTicket(\'' + _ticketEscape(ticket.id) + '\')">🗑 删除</button>';
        }
    }
    html += '</div>';
    html += '</div>';

    // 回复列表
    html += '<div class="card" style="margin-bottom:12px;">'
        + '<div class="card-title">💬 沟通记录 (' + (replies ? replies.length : 0) + ')</div>'
        + '<div id="ticketRepliesList" style="max-height:300px;overflow-y:auto;">';
    if (replies && replies.length) {
        for (var i = 0; i < replies.length; i++) {
            var r = replies[i];
            var isMine = r.reply_user_id === currentUserId;
            var isAdminReply = r.reply_user_type === 'admin';
            var bubbleClass = isAdminReply ? 'ticket-reply-admin' : (isMine ? 'ticket-reply-mine' : 'ticket-reply-other');
            html += '<div class="ticket-reply ' + bubbleClass + '">'
                + '<div class="ticket-reply-head">'
                +   '<span style="font-weight:600;">' + _ticketEscape(r.reply_user_name || '-') + '</span>'
                +   (isAdminReply ? '<span class="ticket-tag-admin">管理员</span>' : '<span class="ticket-tag-customer">用户</span>')
                +   '<span style="font-size:11px;opacity:0.6;margin-left:8px;">' + _ticketFormatTime(r.created_at) + '</span>'
                + '</div>'
                + '<div style="white-space:pre-wrap;word-break:break-word;margin-top:4px;">' + _ticketEscape(r.content) + '</div>';
            var rAtts = r.attachments || [];
            if (rAtts.length) {
                html += '<div style="margin-top:4px;font-size:12px;">';
                for (var j = 0; j < rAtts.length; j++) {
                    html += '<a href="' + (rAtts[j].url || '#') + '" target="_blank" style="margin-right:6px;">📎 ' + _ticketEscape(rAtts[j].filename) + '</a>';
                }
                html += '</div>';
            }
            html += '</div>';
        }
    } else {
        html += '<div style="text-align:center;opacity:0.5;padding:16px;">暂无回复</div>';
    }
    html += '</div>';

    // 回复输入框
    if (canEdit) {
        html += '<div style="margin-top:12px;border-top:1px solid var(--border-color);padding-top:12px;">'
            + '<textarea id="ticketReplyContent" rows="3" placeholder="输入回复内容..." style="width:100%;padding:8px;border-radius:var(--radius);border:1px solid var(--border-color);background:var(--bg-input);resize:vertical;font-family:inherit;"></textarea>'
            + '<div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;gap:8px;flex-wrap:wrap;">'
            +   '<input type="file" id="ticketReplyFiles" multiple style="font-size:12px;flex:1;min-width:200px;">'
            +   '<button class="btn btn-primary" onclick="submitTicketReply(\'' + _ticketEscape(ticket.id) + '\')">发送回复</button>'
            + '</div>'
            + '</div>';
    } else {
        html += '<div style="margin-top:12px;font-size:12px;opacity:0.6;text-align:center;">无权回复</div>';
    }
    html += '</div>';

    body.innerHTML = html;
}

function editTicketFromDetail(ticketId) {
    // 复用创建表单，载入工单数据
    apiGet('/api/tickets/' + encodeURIComponent(ticketId)).then(function(res) {
        if (!res.success || !res.ticket) {
            showToast(res.error || '加载工单失败', 'error');
            return;
        }
        var t = res.ticket;
        ticketsEditingId = ticketId;
        ticketsPendingAttachments = (t.attachments || []).slice();
        document.getElementById('ticketFormTitle').textContent = '编辑工单 ' + (t.ticket_no || '');
        document.getElementById('ticketFormSubmitBtn').textContent = '保存';
        document.getElementById('ticketFormTitleInput').value = t.title || '';
        document.getElementById('ticketFormContent').value = t.content || '';
        document.getElementById('ticketFormPriority').value = String(t.priority || 3);
        document.getElementById('ticketFormCategory').value = t.category || '';
        document.getElementById('ticketFormFiles').value = '';
        var attDiv = document.getElementById('ticketFormAttachments');
        if (attDiv) {
            var html = '';
            for (var i = 0; i < ticketsPendingAttachments.length; i++) {
                html += '<div>📎 ' + _ticketEscape(ticketsPendingAttachments[i].filename) + ' (' + _ticketFormatSize(ticketsPendingAttachments[i].size) + ')</div>';
            }
            attDiv.innerHTML = html;
        }
        hideTicketDetailModal();
        document.getElementById('ticketFormModal').style.display = 'flex';
    });
}

function changeTicketStatus(ticketId, newStatus) {
    customConfirm('确认将工单状态改为 "' + newStatus + '" 吗？', function() {
        apiPut('/api/tickets/' + encodeURIComponent(ticketId), { status: newStatus }).then(function(res) {
            if (res.success) {
                showToast('状态已更新', 'success');
                showTicketDetail(ticketId);
                loadTickets();
            } else {
                showToast(res.error || '更新失败', 'error');
            }
        });
    });
}

function deleteTicket(ticketId) {
    customConfirm('确认删除该工单吗？删除后无法恢复。', function() {
        apiDelete('/api/tickets/' + encodeURIComponent(ticketId)).then(function(res) {
            if (res.success) {
                showToast('工单已删除', 'success');
                hideTicketDetailModal();
                loadTickets();
            } else {
                showToast(res.error || '删除失败', 'error');
            }
        });
    });
}

function submitTicketReply(ticketId) {
    var content = (document.getElementById('ticketReplyContent').value || '').trim();
    if (!content) { showToast('请输入回复内容', 'error'); return; }

    var filesInput = document.getElementById('ticketReplyFiles');
    var files = filesInput && filesInput.files ? Array.from(filesInput.files) : [];

    function send(attachments) {
        apiPost('/api/tickets/' + encodeURIComponent(ticketId) + '/replies', {
            content: content,
            attachments: attachments || []
        }).then(function(res) {
            if (res.success) {
                showToast('回复已发送', 'success');
                showTicketDetail(ticketId);
                loadTickets();
            } else {
                showToast(res.error || '回复失败', 'error');
            }
        });
    }

    if (!files.length) { send([]); return; }
    // 顺序上传
    var uploaded = [];
    var idx = 0;
    function uploadNext() {
        if (idx >= files.length) { send(uploaded); return; }
        var f = files[idx++];
        var xhr = new XMLHttpRequest();
        xhr.open('POST', API_BASE + '/api/tickets/attachments');
        xhr.setRequestHeader('Authorization', 'Bearer ' + (localStorage.getItem('token') || ''));
        xhr.onload = function() {
            try { var r = JSON.parse(xhr.responseText); if (r.success && r.attachment) uploaded.push(r.attachment); } catch (e) {}
            uploadNext();
        };
        xhr.onerror = function() { uploadNext(); };
        var fd = new FormData();
        fd.append('file', f);
        xhr.send(fd);
    }
    uploadNext();
}

// ---------- WebSocket 实时通知 ----------
// 主 WebSocket 的 onmessage 已直接处理 type='ticket_event' 事件并调用 handleTicketEvent
// 此函数保留为初始化钩子，便于未来扩展
function initTicketsWebSocketListener() {
    // no-op：事件处理已集成在 connectWebSocket 的 onmessage 中
}

function handleTicketEvent(msg) {
    var event = msg.event;
    var data = msg.data || {};
    var ticketId = msg.ticket_id;
    var title = data.title || data.ticket_no || '';
    var text = '';
    switch (event) {
        case 'create':    text = '🆕 新工单创建: ' + title; break;
        case 'update':    text = '✏️ 工单已更新: ' + title; break;
        case 'reply':     text = '💬 工单有新回复: ' + title + ' (' + (data.reply_user_name || '') + ')'; break;
        case 'status_change':
            text = '🔄 工单状态变更: ' + title + ' (' + (data.old_status || '') + ' -> ' + (data.new_status || '') + ')';
            break;
        case 'delete':    text = '🗑 工单已删除: ' + title; break;
        default:          text = '🎫 工单事件: ' + (title || event);
    }
    showToast(text, 'info');

    // 如果当前正在工单面板，自动刷新列表
    var active = document.querySelector('.panel.active');
    if (active && active.id === 'panel-tickets') {
        clearTimeout(window._ticketsRefreshTimer);
        window._ticketsRefreshTimer = setTimeout(function() { loadTickets(); }, 800);
    }
    // 如果工单详情模态框打开且事件来自当前工单，刷新详情
    var detailModal = document.getElementById('ticketDetailModal');
    if (detailModal && detailModal.style.display !== 'none' && ticketDetailCurrentId === ticketId
        && (event === 'update' || event === 'reply' || event === 'status_change')) {
        clearTimeout(window._ticketDetailRefreshTimer);
        window._ticketDetailRefreshTimer = setTimeout(function() { showTicketDetail(ticketId); }, 500);
    }
}

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initTicketsWebSocketListener();
});

// ============================================================
// v3.6 安装目录管理 / 文件夹同步 / 备份回滚 / 操作历史
// ============================================================

/**
 * 加载管理员专属下拉切换器的用户列表。
 */
function loadWorkspaceUsers() {
    var sel = document.getElementById('workspaceUserSelect');
    if (!sel) return;
    apiGet('/api/install/workspace-users').then(function(data) {
        if (!data.success || !data.users || data.users.length <= 1) {
            sel.style.display = 'none';
            return;
        }
        // 仅管理员可见
        if (window.userRole !== 'admin') {
            sel.style.display = 'none';
            return;
        }
        sel.style.display = 'inline-block';
        var html = '<option value="">📌 我的工作空间（admin）</option>';
        for (var i = 0; i < data.users.length; i++) {
            var u = data.users[i];
            if (u.username === 'admin') continue;
            html += '<option value="' + escapeHtml(u.username) + '">👤 ' + escapeHtml(u.username) + '</option>';
        }
        sel.innerHTML = html;
        // 还原之前的选择
        if (currentTargetUser) sel.value = currentTargetUser;
    }).catch(function() { sel.style.display = 'none'; });
}

/**
 * 切换目标用户工作空间。
 */
function onWorkspaceUserChange(username) {
    currentTargetUser = username || null;
    showToast(currentTargetUser ? '已切换到用户: ' + currentTargetUser : '已切换回管理员空间', 'info');
    // 切换用户时强制刷新（绕过缓存），确保立即显示新用户空间的真实状态
    checkInstallStatus(true);
}

/**
 * 部署 install 到 bk（仅覆盖同名文件，不清空，带备份）。
 * v3.8：默认 clean=false，符合"不要清空 bk，要替换"的要求。
 */
function deployInstallToBk() {
    var tip = '确定部署？\n\n将把 install 中的配置覆盖到 bk（不清空，仅替换同名文件，.pem 证书不动）。';
    if (currentTargetUser) tip += '\n\n目标用户: ' + currentTargetUser;
    customConfirm(tip, function() {
        showToast('正在部署...', 'info');
        apiPost('/api/install/deploy', {
            target_user: currentTargetUser || null,
            clean: false,
            backup: true
        }).then(function(d) {
            if (d.success) {
                var msg = '✅ 部署完成\n复制 ' + (d.copied || []).length + ' 个文件';
                if (d.skipped && d.skipped.length) msg += '\n跳过 ' + d.skipped.length + ' 项';
                if (d.backup) msg += '\n备份: ' + d.backup.split('/').pop();
                showToast(msg, 'success');
                // 通知引导系统部署完成
                if (typeof Onboarding !== 'undefined' && Onboarding.notifyDeploySuccess) {
                    setTimeout(function() { Onboarding.notifyDeploySuccess(); }, 1000);
                }
            } else {
                showToast('部署失败: ' + (d.error || ''), 'error');
            }
        });
    });
}

/**
 * 清空 bk 子目录。
 */
function bkCleanSelected() {
    var sel = document.getElementById('bkCleanSubSelect');
    if (!sel) return;
    var sub = sel.value;
    var tip = '确定清空 bk/' + sub + '？\n\n将先备份 bk 目录，再清空选中子目录。';
    if (currentTargetUser) tip += '\n\n目标用户: ' + currentTargetUser;
    customConfirm(tip, function() {
        showToast('正在清空...', 'info');
        apiPost('/api/system/bk/clean', {
            target_user: currentTargetUser || null,
            sub: sub,
            backup: true
        }).then(function(d) {
            if (d.success) {
                var msg = '✅ 清空完成\n' + (d.cleaned || []).join('\n');
                if (d.backup) msg += '\n备份: ' + d.backup.split('/').pop();
                showToast(msg, 'success');
            } else {
                showToast('清空失败: ' + (d.error || ''), 'error');
            }
        });
    });
}

/**
 * 从 install 复制配置到 bk（不清空，仅覆盖）。
 */
function bkCopyFromInstall() {
    var tip = '确定从 install 复制配置到 bk？\n\n仅覆盖同名文件，不影响其他文件。';
    if (currentTargetUser) tip += '\n\n目标用户: ' + currentTargetUser;
    customConfirm(tip, function() {
        showToast('正在复制...', 'info');
        apiPost('/api/system/bk/copy-from-install', {
            target_user: currentTargetUser || null,
            backup: true
        }).then(function(d) {
            if (d.success) {
                var msg = '✅ 复制完成\n复制 ' + (d.copied || []).length + ' 个文件';
                if (d.skipped && d.skipped.length) msg += '\n跳过 ' + d.skipped.length + ' 项';
                if (d.backup) msg += '\n备份: ' + d.backup.split('/').pop();
                showToast(msg, 'success');
            } else {
                showToast('复制失败: ' + (d.error || ''), 'error');
            }
        });
    });
}

/**
 * 显示操作历史 / 回滚模态框。
 */
function showBkHistoryModal() {
    var modal = document.getElementById('bkHistoryModal');
    if (!modal) return;
    modal.style.display = 'flex';
    loadBkHistory();
}

function closeBkHistoryModal() {
    var modal = document.getElementById('bkHistoryModal');
    if (modal) modal.style.display = 'none';
}

/**
 * 加载操作历史和备份包列表。
 */
function loadBkHistory() {
    var backupsList = document.getElementById('bkBackupsList');
    var historyList = document.getElementById('bkHistoryList');
    if (backupsList) backupsList.innerHTML = '<div style="text-align:center;padding:8px;color:var(--text-muted);">加载中...</div>';
    if (historyList) historyList.innerHTML = '<div style="text-align:center;padding:8px;color:var(--text-muted);">加载中...</div>';

    var url = '/api/system/bk/history';
    if (currentTargetUser) url += '?target_user=' + encodeURIComponent(currentTargetUser);

    apiGet(url).then(function(data) {
        if (!data.success) {
            if (backupsList) backupsList.innerHTML = '<div style="color:#dc3545;">加载失败</div>';
            if (historyList) historyList.innerHTML = '<div style="color:#dc3545;">加载失败</div>';
            return;
        }

        // 备份包列表
        var html = '';
        if (!data.backups || data.backups.length === 0) {
            html = '<div style="color:var(--text-muted);text-align:center;padding:8px;">暂无备份包</div>';
        } else {
            html = '<table class="data-table"><thead><tr><th>备份包</th><th>大小</th><th>时间</th><th>操作</th></tr></thead><tbody>';
            for (var i = 0; i < data.backups.length; i++) {
                var b = data.backups[i];
                html += '<tr>';
                html += '<td style="font-family:monospace;font-size:12px;">' + escapeHtml(b.name) + '</td>';
                html += '<td>' + formatSize(b.size) + '</td>';
                html += '<td style="font-size:12px;">' + (b.mtime || '').replace('T', ' ').slice(0, 19) + '</td>';
                html += '<td><button class="btn btn-sm btn-warning" onclick="bkRollback(\'' + escapeHtml(b.name) + '\')">⏪ 回滚</button></td>';
                html += '</tr>';
            }
            html += '</tbody></table>';
        }
        if (backupsList) backupsList.innerHTML = html;

        // 审计日志
        var html2 = '';
        if (!data.history || data.history.length === 0) {
            html2 = '<div style="color:var(--text-muted);text-align:center;padding:8px;">暂无操作记录</div>';
        } else {
            html2 = '<table class="data-table"><thead><tr><th>时间</th><th>用户</th><th>操作</th><th>详情</th><th>备份</th></tr></thead><tbody>';
            for (var j = 0; j < data.history.length; j++) {
                var h = data.history[j];
                html2 += '<tr>';
                html2 += '<td style="font-size:12px;">' + ((h.timestamp || '').replace('T', ' ').slice(0, 19)) + '</td>';
                html2 += '<td>' + escapeHtml(h.user || '') + '</td>';
                html2 += '<td><code>' + escapeHtml(h.action || '') + '</code></td>';
                html2 += '<td style="font-size:12px;">' + escapeHtml(h.details || '') + '</td>';
                html2 += '<td style="font-size:12px;">' + (h.backup ? escapeHtml(h.backup) : '-') + '</td>';
                html2 += '</tr>';
            }
            html2 += '</tbody></table>';
        }
        if (historyList) historyList.innerHTML = html2;
    }).catch(function(e) {
        if (backupsList) backupsList.innerHTML = '<div style="color:#dc3545;">加载失败: ' + e.message + '</div>';
        if (historyList) historyList.innerHTML = '<div style="color:#dc3545;">加载失败: ' + e.message + '</div>';
    });
}

/**
 * 回滚到指定备份包。
 */
function bkRollback(backupName) {
    customConfirm('确定回滚到备份: ' + backupName + '？\n\n⚠️ 警告：当前 bk 目录内容将被替换！', function() {
        showToast('正在回滚...', 'info');
        apiPost('/api/system/bk/rollback', {
            target_user: currentTargetUser || null,
            backup: backupName
        }).then(function(d) {
            if (d.success) {
                showToast('✅ ' + d.message, 'success');
            } else {
                showToast('回滚失败: ' + (d.error || ''), 'error');
            }
        });
    });
}

