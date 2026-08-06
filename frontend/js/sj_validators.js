/* ============================================================
版权所有：上海伯镭科技有限公司
@File    :  sj_validators.js
@Time    :  2026/06/26 10:26:00
@Author  :  Fox
@Version :  3.5
@Desc    :  ROS2 Web 管理工具 - 前端表单验证工具
            包含：邮箱格式校验、密码强度校验等

            代码结构：
            1.注册表单格式校验
============================================================ */


/**
 * 校验用户名是否符合 Boonray 邮箱格式
 * 要求：名.姓@boonray.com（如 john.doe@boonray.com）
 */
function isValidBoonrayEmail(username) {
    return /^[a-zA-Z]+\.[a-zA-Z]+@boonray\.com$/.test(username);
}

/**
 * 校验密码强度
 * 规则：
 *   - 首字母大写
 *   - 至少包含一个字母（小写或大写）
 *   - 至少包含一个特殊符号（!@#$%^&*()_+...等）
 *   - 不能包含连续三个递增或递减的数字（如 123、456、321、987 等）
 *   - 长度至少 6 位（由调用方额外检查）
 */
function isValidPassword(password) {
    // 首字母大写
    if (!/^[A-Z]/.test(password)) return false;
    // 包含字母
    if (!/[a-zA-Z]/.test(password)) return false;
    // 包含特殊符号（常见符号）
    if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>/?]/.test(password)) return false;
    // 检查连续数字（三个连续递增或递减）
    for (var i = 0; i < password.length - 2; i++) {
        var a = parseInt(password[i]);
        var b = parseInt(password[i+1]);
        var c = parseInt(password[i+2]);
        if (!isNaN(a) && !isNaN(b) && !isNaN(c)) {
            if ((b === a + 1 && c === b + 1) || (b === a - 1 && c === b - 1)) {
                return false;
            }
        }
    }
    return true;
}
// ========== 预留扩展区域（第1501-1550行） ==========
// 预留用于未来扩展，如更多工具函数等
// ===========================================