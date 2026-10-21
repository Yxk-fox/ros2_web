#!/bin/bash
# 自动提交并推送到 GitHub（ros2_web.git）
# 用法：bash 迭代记录/push_to_git.sh
# 说明：
#   - 每次执行自动 add + commit（时间戳消息）+ push
#   - 迭代记录/推送到git.md 含账号令牌，通过 .gitignore 排除，不会上传
#   - 认证使用系统密钥环（libsecret），脚本内不保存任何令牌

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRET_FILE="$PROJECT_DIR/迭代记录/推送到git.md"
BRANCH="main"

cd "$PROJECT_DIR"

if [ ! -d .git ]; then
    echo "❌ 未找到 .git（$PROJECT_DIR 不是 git 仓库），请先初始化"
    exit 1
fi

# 1) 确保秘密文件被 .gitignore 排除（幂等，只加一次）
touch .gitignore
if ! grep -qxF "迭代记录/推送到git.md" .gitignore; then
    echo "迭代记录/推送到git.md" >> .gitignore
    echo "ℹ️ 已将 推送到git.md 加入 .gitignore（不会上传）"
fi

# 2) 若秘密文件曾被误暂存，先移出（防止历史遗留跟踪）
git reset -q -- "$SECRET_FILE" 2>/dev/null || true

# 3) 提交全部变更
git add -A
if git diff --cached --quiet; then
    echo "ℹ️ 没有任何变更，无需提交"
else
    git commit -m "$(date '+%Y-%m-%d %H:%M:%S') auto commit"
    echo "✅ 已提交: $(git log -1 --format='%h %s')"
fi

# 4) 推送（被拒时先 rebase 远端变更再重试一次）
if ! git push -u origin "$BRANCH"; then
    echo "ℹ️ 直接推送失败，尝试拉取远端后重试..."
    git pull --rebase origin "$BRANCH"
    git push -u origin "$BRANCH"
fi

echo "✅ 推送完成: $(git remote get-url origin) @ $BRANCH"
