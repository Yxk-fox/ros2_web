/* ============================================================
   新手引导（Onboarding）系统
   包含：遮罩高亮、气泡提示、8步引导流程、首次登录弹窗
   ============================================================ */

var Onboarding = (function() {
    'use strict';

    var TOTAL_STEPS = 8;
    var currentStep = 0;
    var isActive = false;
    var isReviewMode = false;
    var stateCompleted = false;
    var stateSkipped = false;
    var waitingForUpload = false;
    var waitingForDeploy = false;
    var waitingForScript = false;
    var waitingForExecute = false;
    var highlightTimer = null;
    var deployCompleted = false;
    var uploadCompleted = false;
    var scriptGenerated = false;
    // 记录引导开始时的初始状态，用于判断是否是本次引导中新发生的操作
    var initialScriptCount = 0;
    var initialInstallReady = false;
    var initialDeployDone = false;

    // DOM 元素引用（延迟创建）
    var overlayTop = null;
    var overlayRight = null;
    var overlayBottom = null;
    var overlayLeft = null;
    var highlightEl = null;
    var bubbleEl = null;

    // 用于高亮定位的刷新计时器（用于在面板渲染后重新定位）
    var repositionTimer = null;
    var repositionCount = 0;

    // ============================================================
    // 步骤定义
    // ============================================================
    var steps = [
        {
            // Step 1: 上传 install
            title: '安装目录管理',
            desc: '请点击上传区域，选择您的 install 压缩包（支持 .zip / .tar.gz / .tgz / .tar.bz2）。上传完成后将自动进入下一步。',
            targetPanel: 'welcome',
            highlightSelector: '#uploadZone',
            fallbackSelector: '#installStatusContent .upload-zone',
            waitForUpload: true,
            condition: function() {
                return checkInstallReady();
            },
            conditionMsg: '检测到您已上传 install 包，自动跳过此步骤。',
            onEnter: function() {
                if (typeof switchPanel === 'function') switchPanel('welcome');
                // 不自动刷新，避免引导定位错误
                // 检查是否需要显示上传区域
                var installContent = document.getElementById('installStatusContent');
                if (installContent && installContent.children.length === 0) {
                    if (typeof checkInstallStatus === 'function') {
                        checkInstallStatus();
                    }
                }
            }
        },
        {
            // Step 2: 创建该版本对应模板
            title: '创建该版本对应模板',
            desc: '点击【🚀 创建该版本对应模板】按钮，将创建该版本对应模板。创建成功后将自动进入下一步。\n💡 若无需创建，可直接点击下一步跳过。',
            targetPanel: 'welcome',
            highlightSelector: '#deployBkBtn',
            fallbackSelector: 'button[onclick*="deployInstallToBk"]',
            waitForDeploy: true,
            allowManualNext: true,
            condition: function() {
                return checkDeploySuccess();
            },
            conditionMsg: '检测到部署已完成，自动跳过此步骤。',
            onEnter: function() {
                if (typeof switchPanel === 'function') switchPanel('welcome');
                deployCompleted = false;
            }
        },
        {
            // Step 3: Install 配置 - 点击侧边栏菜单项进入面板
            title: 'Install 配置',
            desc: '点击左侧菜单中的【⚙️ install配置】，进入安装参数配置界面。',
            targetPanel: 'tools',
            highlightSelector: '.nav-item[data-panel="tools"]',
            fallbackSelector: '.nav-item[data-tip*="install配置"]',
            waitForPanelSwitch: true,
            onEnter: function() {
                var navItem = document.querySelector('.nav-item[data-panel="tools"]');
                if (navItem) {
                    navItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        },
        {
            // Step 4: 云配置IP及证书切换 - 进入面板后高亮云配置区域
            title: '🌐 云配置IP及证书切换',
            desc: '在 install 配置页面中找到【🌐 云配置IP及证书切换】区域。\n💡 当前默认已配置139环境，若无需切换环境可直接点击下一步跳过。',
            targetPanel: 'tools',
            highlightSelector: '#cloudConfigSection',
            fallbackSelector: '#cloudConfigSection',
            onEnter: function() {
                if (typeof switchPanel === 'function') switchPanel('tools');
                var section = document.getElementById('cloudConfigSection');
                if (section) {
                    section.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
        },
        {
            // Step 5: 脚本与启动 - 生成脚本
            title: '脚本与启动',
            desc: '点击【⚡ 生成 ROS2 脚本】按钮，基于当前配置生成启动脚本。生成成功后将自动进入下一步。\n⚠️ 必须点击生成脚本后才能继续，如遇到问题请联系飞书郭仕杰。',
            targetPanel: 'scripts',
            highlightSelector: '#generateScriptsBtn',
            fallbackSelector: 'button[onclick*="generateScripts"]',
            waitForScript: true,
            onEnter: function() {
                if (typeof switchPanel === 'function') switchPanel('scripts');
            }
        },
        {
            // Step 6: 启动车辆
            title: '启动车辆',
            desc: '点击单个脚本的【▶ 执行】按钮，启动仿真车辆节点。\n⏳ 启动加载中，请等待自动检测启动成功后跳转下一步。\n💡 若需跳过，可直接点击下一步。',
            targetPanel: 'scripts',
            highlightSelector: '#scriptsTableBody button[onclick*="executeSingleScript"]',
            fallbackSelector: '#scriptsTableBody .btn-success',
            waitForExecute: true,
            allowManualNext: true,
            onEnter: function() {
                if (typeof switchPanel === 'function') switchPanel('scripts');
                if (typeof loadScripts === 'function') loadScripts();
                if (typeof expandScripts === 'function') expandScripts();
            }
        },
        {
            // Step 7: 可视化连接
            title: '可视化连接',
            desc: '请依次操作：1. 点击目标容器的【更多】按钮；2. 点击下拉菜单中的【可视化】；3. 点击【打开 RVIZ】。如弹出RVIZ窗口，即代表成功。',
            targetPanel: 'docker',
            highlightSelector: '.nav-item[data-panel="docker"]',
            fallbackSelector: '.nav-item[data-tip*="仿真车管理"]',
            onEnter: function() {
                if (typeof switchPanel === 'function') switchPanel('docker');
                if (typeof loadContainers === 'function') loadContainers(false, 'ros2_');
            }
        },
        {
            title: '恭喜完成！',
            desc: '',
            isFinal: true,
            onEnter: function() {
                showCompleteDialog();
            }
        }
    ];

    // ============================================================
    // 条件检测函数
    // ============================================================
    function countScriptItems() {
        var scriptList = document.getElementById('scriptList');
        if (scriptList) return scriptList.children.length;
        var items = document.querySelectorAll('#panel-scripts .script-item, #panel-scripts .launch-file-item');
        return items.length;
    }

    // 静态DOM检测：install包是否已就绪（不区分引导前后）
    function isInstallReadyDOM() {
        try {
            var treeContainer = document.getElementById('installTreeContainer');
            if (treeContainer) return true;
            var readyIcons = document.querySelectorAll('#installStatusContent .install-tree');
            if (readyIcons.length > 0) return true;
            var readyText = document.querySelector('#installStatusContent');
            if (readyText && readyText.textContent && readyText.textContent.indexOf('安装包已就绪') >= 0) return true;
            var deployBar = document.getElementById('installDeployBar');
            if (deployBar && deployBar.style.display !== 'none' && deployBar.offsetParent !== null) return true;
        } catch(e) {}
        return false;
    }

    // 静态DOM检测：部署是否成功（不区分引导前后）
    function isDeploySuccessDOM() {
        try {
            var successEls = document.querySelectorAll('[id*="deploy"][id*="success"], [class*="deploy-success"]');
            for (var i = 0; i < successEls.length; i++) {
                if (successEls[i].offsetParent !== null) return true;
            }
            var deployBar = document.getElementById('installDeployBar');
            if (deployBar && deployBar.offsetParent !== null) {
                var btns = deployBar.querySelectorAll('button');
                var hasDeployBtn = false;
                for (var j = 0; j < btns.length; j++) {
                    if (btns[j].textContent && btns[j].textContent.indexOf('部署到bk') >= 0) hasDeployBtn = true;
                }
                if (!hasDeployBtn && btns.length > 0) return true;
            }
        } catch(e) {}
        return false;
    }

    // 用于condition前置检查（自动跳过）：只要DOM显示已就绪就跳过
    function checkInstallReady() {
        return isInstallReadyDOM();
    }

    // 用于轮询等待（等待本次操作完成）：要么收到notify回调，要么DOM从"未就绪"变为"已就绪"
    function checkInstallReadyForWait() {
        if (uploadCompleted) return true;
        if (!initialInstallReady && isInstallReadyDOM()) return true;
        return false;
    }

    function checkDeploySuccess() {
        return isDeploySuccessDOM();
    }

    function checkDeploySuccessForWait() {
        if (deployCompleted) return true;
        if (!initialDeployDone && isDeploySuccessDOM()) return true;
        return false;
    }

    function checkScriptsReady() {
        return scriptGenerated;
    }

    // 检查是否已启动车辆（检测 ros2_ 开头的容器是否在运行）
    function checkExecuteStarted() {
        try {
            var rows = document.querySelectorAll('#scriptsTableBody tr, #scriptsTableBody .script-row');
            for (var i = 0; i < rows.length; i++) {
                var row = rows[i];
                // 检查是否有"运行中"状态标识（绿色badge/按钮/图标）
                var statusEl = row.querySelector('.badge-success, .status-running, .badge-running');
                if (statusEl) return true;
                // 检查是否有"停止"按钮（说明容器正在运行）
                var stopBtn = row.querySelector('button[onclick*="stopContainer"], button[onclick*="stopScript"]');
                if (stopBtn) return true;
            }
            // 备用：检查容器列表中是否有 ros2_ 开头的运行中容器
            if (typeof window.lastContainerList === 'object' && window.lastContainerList) {
                for (var j = 0; j < window.lastContainerList.length; j++) {
                    var c = window.lastContainerList[j];
                    if (c && c.name && c.name.indexOf('ros2_') === 0 && c.state === 'running') {
                        return true;
                    }
                }
            }
        } catch(e) {}
        return false;
    }

    // ============================================================
    // 权限检查
    // ============================================================
    function hasPermission(panel) {
        if (window.userRole === 'admin') return true;
        if (!window.userPermissions) return true;
        return window.userPermissions.indexOf(panel) >= 0;
    }

    // ============================================================
    // DOM 创建 - 使用4块遮罩包围高亮区域，实现点击穿透
    // ============================================================
    function createOverlay() {
        if (overlayTop) return;
        var overlayStyle = 'position:fixed;background:rgba(0,0,0,0.6);z-index:10000;pointer-events:auto;';
        overlayTop = document.createElement('div');
        overlayTop.style.cssText = overlayStyle + 'top:0;left:0;right:0;height:0;';
        overlayRight = document.createElement('div');
        overlayRight.style.cssText = overlayStyle + 'top:0;right:0;bottom:0;width:0;';
        overlayBottom = document.createElement('div');
        overlayBottom.style.cssText = overlayStyle + 'left:0;right:0;bottom:0;height:0;';
        overlayLeft = document.createElement('div');
        overlayLeft.style.cssText = overlayStyle + 'top:0;left:0;bottom:0;width:0;';
        
        document.body.appendChild(overlayTop);
        document.body.appendChild(overlayRight);
        document.body.appendChild(overlayBottom);
        document.body.appendChild(overlayLeft);
    }

    function createHighlight() {
        if (highlightEl) return;
        highlightEl = document.createElement('div');
        highlightEl.className = 'onboarding-highlight';
        highlightEl.style.display = 'none';
        document.body.appendChild(highlightEl);
    }

    function removeOverlay() {
        [overlayTop, overlayRight, overlayBottom, overlayLeft, highlightEl, bubbleEl].forEach(function(el) {
            if (el) { el.remove(); }
        });
        overlayTop = overlayRight = overlayBottom = overlayLeft = highlightEl = bubbleEl = null;
        if (highlightTimer) { clearTimeout(highlightTimer); highlightTimer = null; }
        if (repositionTimer) { clearInterval(repositionTimer); repositionTimer = null; }
        waitingForUpload = false;
        waitingForDeploy = false;
        waitingForScript = false;
    }

    // ============================================================
    // 查找目标元素 - 必须真正可见才算找到
    // ============================================================
    function isElementVisible(el) {
        if (!el) return false;
        if (el.offsetParent === null) {
            var style = getComputedStyle(el);
            if (style.position === 'fixed' || style.position === 'sticky') {
                if (style.display === 'none' || style.visibility === 'hidden') return false;
            } else {
                return false;
            }
        }
        var rect = el.getBoundingClientRect();
        if (rect.width < 5 || rect.height < 5) return false;
        return true;
    }

    function findTarget(selector, fallbackSelector) {
        var target = null;
        if (selector) {
            var el = document.querySelector(selector);
            if (isElementVisible(el)) {
                target = el;
            }
        }
        if (!target && fallbackSelector) {
            if (fallbackSelector.indexOf(':contains(') >= 0) {
                var text = fallbackSelector.match(/:contains\("(.+)"\)/);
                if (text) {
                    var allEls = document.querySelectorAll('button, .btn, .nav-item, .tab-btn, a, [role="button"]');
                    for (var i = 0; i < allEls.length; i++) {
                        if (allEls[i].textContent && allEls[i].textContent.replace(/\s+/g, ' ').trim().indexOf(text[1]) >= 0) {
                            if (isElementVisible(allEls[i])) {
                                target = allEls[i];
                                break;
                            }
                        }
                    }
                }
            } else {
                var fb = document.querySelector(fallbackSelector);
                if (isElementVisible(fb)) {
                    target = fb;
                }
            }
        }
        return target;
    }

    // ============================================================
    // 高亮元素 - 同时调整遮罩块位置，留出高亮区域可点击
    // ============================================================
    function highlightTarget(selector, fallbackSelector) {
        var target = findTarget(selector, fallbackSelector);
        if (!target) {
            if (highlightEl) highlightEl.style.display = 'none';
            return false;
        }

        if (target && highlightEl) {
            var rect = target.getBoundingClientRect();
            if (rect.width < 5 || rect.height < 5) {
                highlightEl.style.display = 'none';
                return false;
            }
            var pad = 6;
            var left = rect.left - pad;
            var top = rect.top - pad;
            var width = rect.width + pad * 2;
            var height = rect.height + pad * 2;
            var right = left + width;
            var bottom = top + height;
            var viewW = window.innerWidth;
            var viewH = window.innerHeight;
            
            highlightEl.style.display = 'block';
            highlightEl.style.left = left + 'px';
            highlightEl.style.top = top + 'px';
            highlightEl.style.width = width + 'px';
            highlightEl.style.height = height + 'px';
            
            if (overlayTop) overlayTop.style.height = Math.max(0, top) + 'px';
            if (overlayLeft) {
                overlayLeft.style.top = Math.max(0, top) + 'px';
                overlayLeft.style.width = Math.max(0, left) + 'px';
                overlayLeft.style.height = Math.max(0, height) + 'px';
            }
            if (overlayRight) {
                overlayRight.style.top = Math.max(0, top) + 'px';
                overlayRight.style.width = Math.max(0, viewW - right) + 'px';
                overlayRight.style.height = Math.max(0, height) + 'px';
            }
            if (overlayBottom) overlayBottom.style.height = Math.max(0, viewH - bottom) + 'px';
            
            return true;
        }
        if (highlightEl) highlightEl.style.display = 'none';
        return false;
    }

    // ============================================================
    // 气泡提示
    // ============================================================
    function showBubble(stepIndex, extraText) {
        if (bubbleEl) bubbleEl.remove();

        var step = steps[stepIndex];
        if (!step || step.isFinal) return;

        bubbleEl = document.createElement('div');
        bubbleEl.className = 'onboarding-bubble';

        var progressPct = Math.round(((stepIndex + 1) / TOTAL_STEPS) * 100);

        var nextBtnText = (stepIndex < TOTAL_STEPS - 1) ? '下一步' : '完成';
        var isWaiting = step.waitForUpload || step.waitForDeploy || step.waitForScript || step.waitForExecute;

        var waitText = '';
        if (step.waitForUpload) waitText = '⏳ 等待上传完成...';
        else if (step.waitForDeploy) waitText = '⏳ 等待部署完成...';
        else if (step.waitForScript) waitText = '⏳ 等待脚本生成...';
        else if (step.waitForExecute) waitText = '⏳ 等待车辆启动...';

        // T-6.0-03：工作流标签（与手册 5.1-5.3 三条工作流对应）
        var workflowNames = ['准备工作 · 环境配置', '准备工作 · 环境配置', '准备工作 · 环境配置', '准备工作 · 环境配置', '工作流二 · 生成并批量执行脚本', '工作流二 · 生成并批量执行脚本', '工作流一 · 启动仿真车', ''];
        var workflow = step.workflow || workflowNames[stepIndex] || '';

        var html = '';
        html += '<div class="onboarding-progress">';
        html += '<div class="onboarding-progress-bar"><div class="onboarding-progress-fill" style="width:' + progressPct + '%"></div></div>';
        html += '<span class="onboarding-progress-text">步骤 ' + (stepIndex + 1) + ' / ' + TOTAL_STEPS + '</span>';
        html += '</div>';
        if (workflow) {
            html += '<div class="onboarding-workflow-tag">' + escapeHtml(workflow) + '</div>';
        }
        html += '<div class="onboarding-bubble-title">' + escapeHtml(step.title) + '</div>';
        html += '<div class="onboarding-bubble-desc">' + (extraText || step.desc) + '</div>';
        html += '<div class="onboarding-bubble-actions">';
        if (isWaiting) {
            html += '<span style="color:#1890FF;font-size:12px;padding:7px 10px;">' + waitText + '</span>';
        }
        html += '<button class="onboarding-btn onboarding-btn-primary" onclick="Onboarding.next()">' + nextBtnText + '</button>';
        html += '<button class="onboarding-btn onboarding-btn-skip" onclick="Onboarding.skip()">退出引导</button>';
        html += '</div>';

        bubbleEl.innerHTML = html;
        document.body.appendChild(bubbleEl);

        positionBubble();
    }

    function positionBubble() {
        if (!highlightEl || !bubbleEl) return;
        var hRect = highlightEl.getBoundingClientRect();
        var bWidth = bubbleEl.offsetWidth;
        var bHeight = bubbleEl.offsetHeight;
        var viewW = window.innerWidth;
        var viewH = window.innerHeight;

        var left, top, arrowClass;

        // 优先显示在上方，避免遮挡操作区域（上传进度条、按钮下方的反馈信息等）
        if (hRect.top - bHeight - 20 >= 20) {
            // 上方有足够空间，显示在上方
            top = hRect.top - bHeight - 12;
            left = Math.max(20, Math.min(viewW - bWidth - 20, hRect.left + hRect.width / 2 - bWidth / 2));
            arrowClass = 'arrow-bottom';
        }
        else if (hRect.right + bWidth + 20 <= viewW - 20) {
            // 右侧有空间，显示在右侧
            left = hRect.right + 12;
            top = Math.max(20, Math.min(viewH - bHeight - 20, hRect.top + hRect.height / 2 - bHeight / 2));
            arrowClass = 'arrow-left';
        }
        else if (hRect.bottom + bHeight + 20 <= viewH - 20) {
            // 下方有空间，显示在下方
            top = hRect.bottom + 12;
            left = Math.max(20, Math.min(viewW - bWidth - 20, hRect.left + hRect.width / 2 - bWidth / 2));
            arrowClass = 'arrow-top';
        }
        else {
            // 空间不足，贴右显示
            left = Math.max(20, viewW - bWidth - 20);
            top = Math.max(20, Math.min(viewH - bHeight - 20, hRect.top));
            arrowClass = 'arrow-left';
        }

        bubbleEl.style.left = left + 'px';
        bubbleEl.style.top = top + 'px';
        bubbleEl.className = 'onboarding-bubble ' + arrowClass;
    }

    // ============================================================
    // 轮询检查等待状态
    // ============================================================
    function startWaiting() {
        if (repositionTimer) clearInterval(repositionTimer);
        repositionCount = 0;

        repositionTimer = setInterval(function() {
            var step = steps[currentStep];
            if (!step || !isActive) {
                clearInterval(repositionTimer);
                repositionTimer = null;
                return;
            }

            // 定期重新高亮，以适应DOM变化
            var ok = highlightTarget(step.highlightSelector, step.fallbackSelector);
            if (ok) {
                if (bubbleEl) {
                    positionBubble();
                } else {
                    showBubble(currentStep);
                }
            } else {
                setFullOverlay();
                hideBubble();
            }

            repositionCount++;

            // 检查是否完成等待条件
            if (step.waitForUpload && checkInstallReadyForWait()) {
                clearInterval(repositionTimer);
                repositionTimer = null;
                waitingForUpload = false;
                showToast('安装包上传完成！', 'success');
                setTimeout(function() { next(); }, 800);
                return;
            }
            if (step.waitForDeploy && checkDeploySuccessForWait()) {
                clearInterval(repositionTimer);
                repositionTimer = null;
                waitingForDeploy = false;
                showToast('部署成功！', 'success');
                setTimeout(function() { next(); }, 800);
                return;
            }
            if (step.waitForScript && checkScriptsReady()) {
                clearInterval(repositionTimer);
                repositionTimer = null;
                waitingForScript = false;
                showToast('脚本生成成功！', 'success');
                setTimeout(function() { next(); }, 800);
                return;
            }
            if (step.waitForExecute && checkExecuteStarted()) {
                clearInterval(repositionTimer);
                repositionTimer = null;
                waitingForExecute = false;
                showToast('车辆启动成功！', 'success');
                setTimeout(function() { next(); }, 800);
                return;
            }

            // 最长等待 5 分钟（300 次 * 1秒）
            if (repositionCount > 300) {
                clearInterval(repositionTimer);
                repositionTimer = null;
                if (step.allowManualNext) {
                    showToast('等待超时，可点击"下一步"继续', 'warning');
                } else if (step.waitForScript) {
                    showToast('等待超时，如遇到问题请联系飞书郭仕杰', 'warning');
                } else {
                    showToast('等待超时，可点击"下一步"跳过', 'warning');
                }
                // 超时后刷新气泡（显示下一步按钮）
                showBubble(currentStep, step.desc);
            }
        }, 1000);
    }

    function stopWaiting() {
        if (repositionTimer) {
            clearInterval(repositionTimer);
            repositionTimer = null;
        }
        waitingForUpload = false;
        waitingForDeploy = false;
        waitingForScript = false;
        waitingForExecute = false;
    }

    // 设置全屏遮罩（目标元素未就绪时使用，此时不能穿透点击）
    function setFullOverlay() {
        if (!overlayTop) return;
        var viewW = window.innerWidth;
        var viewH = window.innerHeight;
        overlayTop.style.height = viewH + 'px';
        overlayRight.style.width = '0px';
        overlayBottom.style.height = '0px';
        overlayLeft.style.width = '0px';
        overlayLeft.style.height = '0px';
        if (highlightEl) highlightEl.style.display = 'none';
    }

    // 隐藏气泡
    function hideBubble() {
        if (bubbleEl) { bubbleEl.remove(); bubbleEl = null; }
    }

    // ============================================================
    // 步骤导航
    // ============================================================
    function goToStep(stepIndex, skipConditionCheck) {
        if (stepIndex >= TOTAL_STEPS) {
            finish();
            return;
        }

        // 停止之前的等待
        stopWaiting();

        currentStep = stepIndex;
        var step = steps[stepIndex];
        // T-6.0-03 验收③：持久化当前步骤，中途刷新可恢复
        if (!isReviewMode) saveStepProgress(stepIndex);

        if (overlayTop) setFullOverlay();
        hideBubble();

        // 权限检查
        if (step.permissionRequired && !hasPermission(step.permissionRequired)) {
            showSkipNotice('当前步骤因权限限制已跳过，请联系管理员开通。');
            goToStep(stepIndex + 1, true);
            return;
        }

        // 前置条件检查（自动跳过已完成的步骤）
        if (!skipConditionCheck && step.condition && typeof step.condition === 'function') {
            try {
                var result = step.condition();
                if (result) {
                    showSkipNotice(step.conditionMsg || '此步骤已完成，自动跳过。');
                    goToStep(stepIndex + 1, true);
                    return;
                }
            } catch(e) {}
        }

        if (step.isFinal) {
            if (step.onEnter) step.onEnter();
            return;
        }

        // 切换到目标面板
        if (step.onEnter) step.onEnter();

        hideBubble();

        var bubbleShown = false;
        var waitingStarted = false;

        // 延迟高亮（等待面板渲染）
        function doHighlight() {
            var ok = highlightTarget(step.highlightSelector, step.fallbackSelector);
            if (ok) {
                if (!bubbleShown) {
                    showBubble(stepIndex);
                    bubbleShown = true;
                } else {
                    positionBubble();
                }
                if (!waitingStarted && (step.waitForUpload || step.waitForDeploy || step.waitForScript || step.waitForExecute)) {
                    waitingForUpload = step.waitForUpload;
                    waitingForDeploy = step.waitForDeploy;
                    waitingForScript = step.waitForScript;
                    waitingForExecute = step.waitForExecute;
                    startWaiting();
                    waitingStarted = true;
                }
            } else {
                setFullOverlay();
                hideBubble();
                if (highlightTimer) clearTimeout(highlightTimer);
                highlightTimer = setTimeout(doHighlight, 300);
            }
        }

        if (highlightTimer) clearTimeout(highlightTimer);
        highlightTimer = setTimeout(doHighlight, 500);
    }

    function next() {
        stopWaiting();
        panelSwitchHandled = false;
        goToStep(currentStep + 1);
    }

    function skip() {
        stopWaiting();
        if (isReviewMode) {
            removeOverlay();
            isActive = false;
            return;
        }
        saveState(false, true);
        clearStepProgress();
        removeOverlay();
        isActive = false;
    }

    function finish() {
        stopWaiting();
        removeOverlay();
        isActive = false;
        if (!isReviewMode) {
            saveState(true, stateSkipped);
            clearStepProgress();
        }
    }

    // ============================================================
    // 完成弹窗
    // ============================================================
    function showCompleteDialog() {
        removeOverlay();
        var overlay = document.createElement('div');
        overlay.className = 'onboarding-complete-overlay';
        overlay.innerHTML = '<div class="onboarding-complete-dialog">' +
            '<div class="complete-icon">🎉</div>' +
            '<h2>恭喜完成新手引导！</h2>' +
            '<p>您已掌握平台核心操作流程。更多功能（如红绿灯模拟、故障注入、工单管理等）待您自行探索。</p>' +
            '<p class="contact-email">💡 如需开通额外权限，请联系：shijie.guo@boonray.com</p>' +
            '<button class="onboarding-btn onboarding-btn-primary" style="padding:10px 32px;font-size:14px;">开始使用</button>' +
            '</div>';
        document.body.appendChild(overlay);

        overlay.querySelector('button').addEventListener('click', function() {
            overlay.remove();
            finish();
        });
    }

    // ============================================================
    // 首次登录弹窗
    // ============================================================
    function showWelcomeDialog() {
        var overlay = document.createElement('div');
        overlay.className = 'onboarding-welcome-overlay';
        overlay.innerHTML = '<div class="onboarding-welcome-dialog">' +
            '<h2>欢迎使用 Boonray 仿真平台！</h2>' +
            '<p>是否立即开始新手操作指引？<br>（约需2分钟，覆盖三条工作流核心操作）</p>' +
            '<ul style="text-align:left;margin:12px 0;padding-left:20px;color:#4b5563;font-size:13px;line-height:1.8">' +
            '<li><strong>工作流一：</strong>启动一辆仿真车（Docker 面板 → 启动容器 → 可视化）</li>' +
            '<li><strong>工作流二：</strong>生成并批量执行脚本（脚本管理 → 生成 → 执行）</li>' +
            '<li><strong>工作流三：</strong>监控与排障（系统监控 → 日志 → 工单）</li>' +
            '</ul>' +
            '<div class="onboarding-welcome-actions">' +
            '<button class="onboarding-btn onboarding-btn-primary" id="onboardingStartBtn">开始指引</button>' +
            '<button class="onboarding-btn onboarding-btn-secondary" id="onboardingExploreBtn">自行探索</button>' +
            '</div>' +
            '<label class="onboarding-remember">' +
            '<input type="checkbox" id="onboardingDontShowAgain">' +
            '下次登录不再提示' +
            '</label>' +
            '</div>';
        document.body.appendChild(overlay);

        document.getElementById('onboardingStartBtn').addEventListener('click', function() {
            var dontShow = document.getElementById('onboardingDontShowAgain').checked;
            overlay.remove();
            if (dontShow) {
                saveState(false, true);
            }
            startGuidedTour(false);
        });

        document.getElementById('onboardingExploreBtn').addEventListener('click', function() {
            var dontShow = document.getElementById('onboardingDontShowAgain').checked;
            overlay.remove();
            saveState(false, dontShow);
        });
    }

    // ============================================================
    // 跳过提示
    // ============================================================
    function showSkipNotice(msg) {
        var notice = document.createElement('div');
        notice.className = 'onboarding-skip-notice';
        notice.textContent = msg;
        document.body.appendChild(notice);
        setTimeout(function() {
            notice.style.opacity = '0';
            notice.style.transition = 'opacity 0.3s';
            setTimeout(function() { notice.remove(); }, 300);
        }, 2000);
    }

    // ============================================================
    // 状态管理
    // ============================================================
    function saveState(completed, skipped) {
        stateCompleted = completed;
        if (skipped !== undefined) stateSkipped = skipped;
        fetch('/api/auth/onboarding', {
            method: 'PUT',
            headers: getAuthHeaders(),
            body: JSON.stringify({
                completed: completed,
                skipped: skipped
            })
        }).catch(function() {});
    }

    function loadState(callback) {
        fetch('/api/auth/onboarding', {
            method: 'GET',
            headers: getAuthHeaders()
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            stateCompleted = data.completed || false;
            stateSkipped = data.skipped || false;
            if (callback) callback(stateCompleted, stateSkipped);
        })
        .catch(function() {
            if (callback) callback(false, false);
        });
    }

    // ============================================================
    // 公共 API
    // ============================================================
    function startGuidedTour(reviewMode) {
        if (isActive) return;
        isActive = true;
        isReviewMode = reviewMode || false;
        currentStep = 0;
        deployCompleted = false;
        uploadCompleted = false;
        scriptGenerated = false;
        // 记录初始状态，避免误判引导开始前已存在的内容
        initialInstallReady = checkInstallReady();
        initialDeployDone = checkDeploySuccess();
        initialScriptCount = countScriptItems();
        createOverlay();
        createHighlight();
        // T-6.0-03 验收③：中途刷新不丢进度——非复习模式且本地有未完成进度时恢复
        var resumeStep = 0;
        if (!isReviewMode) {
            var saved = parseInt(localStorage.getItem('ros2_web_onboarding_step'), 10);
            if (!isNaN(saved) && saved > 0 && saved < TOTAL_STEPS) {
                resumeStep = saved;
            }
        }
        goToStep(resumeStep);
    }

    // T-6.0-03 验收③：步骤进度持久化（localStorage，避免动后端 schema）
    function saveStepProgress(stepIndex) {
        try {
            if (stepIndex >= 0 && stepIndex < TOTAL_STEPS) {
                localStorage.setItem('ros2_web_onboarding_step', String(stepIndex));
            }
        } catch(e) {}
    }

    function clearStepProgress() {
        try {
            localStorage.removeItem('ros2_web_onboarding_step');
        } catch(e) {}
    }

    function checkFirstLogin() {
        if (!isLoggedIn()) return;
        loadState(function(completed, skipped) {
            if (!completed && !skipped) {
                showWelcomeDialog();
            }
        });
    }

    function startReview() {
        if (isActive) {
            removeOverlay();
            isActive = false;
        }
        startGuidedTour(true);
    }

    function isOnboardingActive() {
        return isActive;
    }

    // 通知上传/部署/脚本生成完成（供外部调用）
    function notifyUploadComplete() {
        uploadCompleted = true;
        if (!isActive) return;
        var step = steps[currentStep];
        if (step && step.waitForUpload) {
            // 稍等一下让 DOM 渲染完成
            setTimeout(function() {
                if (checkInstallReady()) {
                    stopWaiting();
                    showToast('安装包上传完成！', 'success');
                    setTimeout(function() { next(); }, 800);
                }
            }, 1500);
        }
    }

    function notifyDeploySuccess() {
        deployCompleted = true;
        if (!isActive) return;
        var step = steps[currentStep];
        if (step && step.waitForDeploy) {
            setTimeout(function() {
                if (repositionTimer) {
                    clearInterval(repositionTimer);
                    repositionTimer = null;
                }
                waitingForDeploy = false;
                showToast('部署成功！', 'success');
                setTimeout(function() { next(); }, 800);
            }, 500);
        }
    }

    function notifyScriptGenerated() {
        scriptGenerated = true;
        if (!isActive) return;
        var step = steps[currentStep];
        if (step && step.waitForScript) {
            setTimeout(function() {
                if (checkScriptsReady()) {
                    stopWaiting();
                    showToast('脚本生成成功！', 'success');
                    setTimeout(function() { next(); }, 800);
                }
            }, 1500);
        }
    }

    // 通知车辆已启动（由脚本执行函数调用）
    function notifyExecuteStarted() {
        if (!isActive) return;
        var step = steps[currentStep];
        if (step && step.waitForExecute) {
            // 延迟检测，等待容器状态更新
            setTimeout(function() {
                if (checkExecuteStarted()) {
                    stopWaiting();
                    showToast('车辆启动成功！', 'success');
                    setTimeout(function() { next(); }, 800);
                }
            }, 2000);
        }
    }

    // 面板切换通知 - 用于步骤3、4等需要用户点击菜单项的步骤
    var panelSwitchHandled = false;
    function notifyPanelSwitch(panel) {
        if (!isActive) return;
        // 防止onEnter中自动switchPanel触发误跳转
        if (panelSwitchHandled) return;
        var step = steps[currentStep];
        if (!step) return;
        // 只有标记了 waitForPanelSwitch 的步骤才会在面板切换时自动推进
        if (step.waitForPanelSwitch && step.targetPanel === panel) {
            panelSwitchHandled = true;
            // 用户成功点击了目标菜单项，稍等渲染后切换高亮目标到面板内元素
            setTimeout(function() {
                if (step.onPanelEnter) step.onPanelEnter();
                var highlightSelector = step.panelHighlightSelector || step.highlightSelector;
                var fallbackSelector = step.panelFallbackSelector || step.fallbackSelector;
                var ok = highlightTarget(highlightSelector, fallbackSelector);
                if (ok) {
                    showBubble(currentStep);
                }
                showToast('已进入' + step.title + '！', 'success');
                // 不自动下一步，让用户确认后点击下一步
                panelSwitchHandled = false;
            }, 500);
        }
    }

    // ============================================================
    // 辅助函数
    // ============================================================
    function escapeHtml(text) {
        if (!text) return '';
        var div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    window.addEventListener('resize', function() {
        if (isActive && bubbleEl && highlightEl) {
            positionBubble();
        }
    });

    return {
        start: startGuidedTour,
        checkFirstLogin: checkFirstLogin,
        startReview: startReview,
        next: next,
        skip: skip,
        isActive: isOnboardingActive,
        notifyUploadComplete: notifyUploadComplete,
        notifyDeploySuccess: notifyDeploySuccess,
        notifyScriptGenerated: notifyScriptGenerated,
        notifyExecuteStarted: notifyExecuteStarted,
        notifyPanelSwitch: notifyPanelSwitch,
        getState: function() { return { completed: stateCompleted, skipped: stateSkipped }; }
    };

})();
