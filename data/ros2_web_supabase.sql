-- ============================================================
-- Mock Truck - Supabase 数据库初始化脚本（整合版）
-- ============================================================
-- 说明：
--   1. 幂等执行（CREATE IF NOT EXISTS / OR REPLACE / DROP IF EXISTS）
--   2. 包含 5 张表：users / audit_logs / containers / tickets / ticket_replies
--   3. 默认管理员 admin/123456（bcrypt 哈希）
--   4. 其他 5 个测试用户密码均为 Boonray2020!（bcrypt 哈希）
--   5. 启用 RLS、索引、updated_at 触发器
--   6. 由 ros2_web_supabase.sql + tickets_supabase.sql 整合而成
-- ============================================================


-- ============================================================
-- 1. 用户表 (public.users)
-- ============================================================

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'users'
    ) THEN
        CREATE TABLE public.users (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email            TEXT NOT NULL UNIQUE,
            username         TEXT NOT NULL,
            home_folder_path TEXT DEFAULT '',
            role             TEXT NOT NULL DEFAULT 'user',
            permissions      JSONB DEFAULT '[]'::jsonb,
            password         TEXT DEFAULT '',
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ DEFAULT now()
        );
    END IF;
END $$;

-- 字段平滑迁移（兼容旧表）
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS permissions JSONB DEFAULT '[]'::jsonb;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS password   TEXT DEFAULT '';
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS onboarding_completed BOOLEAN DEFAULT false;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS onboarding_skipped   BOOLEAN DEFAULT false;
-- v5.0：install 版本选择（空字符串 = 未选择，回退旧版 <home>/install 目录）
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS current_version TEXT DEFAULT '';
-- v5.1：版本备注（{版本名: 备注文本} JSONB，前端"安装目录管理"卡片编辑）
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS version_notes JSONB DEFAULT '{}'::jsonb;
-- v5.1：回滚记录（{"version": ..., "switched_at": ...} JSONB，NULL = 暂无可回滚版本）
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS previous_version JSONB DEFAULT NULL;

-- 旧数据回填（幂等）：已存在 users 表但列为 NULL 时补默认值
UPDATE public.users SET version_notes = '{}'::jsonb WHERE version_notes IS NULL;
UPDATE public.users SET previous_version = NULL WHERE previous_version IS NULL;

-- 刷新 PostgREST schema cache（新列立即可见；Supabase 通常自动刷新，此处兜底）
NOTIFY pgrst, 'reload schema';

-- 索引
CREATE INDEX IF NOT EXISTS idx_users_email ON public.users (email);
CREATE INDEX IF NOT EXISTS idx_users_role  ON public.users (role);


-- ============================================================
-- 2. 审计日志表 (public.audit_logs)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.audit_logs (
    id         BIGSERIAL PRIMARY KEY,
    username   TEXT NOT NULL,
    action     TEXT NOT NULL,
    details    TEXT DEFAULT '',
    timestamp  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON public.audit_logs (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_username  ON public.audit_logs (username);


-- ============================================================
-- 3. 容器表 (public.containers) - 用于用户权限隔离
-- ============================================================

CREATE TABLE IF NOT EXISTS public.containers (
    id           BIGSERIAL PRIMARY KEY,
    container_id TEXT NOT NULL,                  -- Docker 容器短 ID
    name         TEXT NOT NULL,                  -- 容器名（如 ros2_simulation_launch）
    image        TEXT DEFAULT '',
    state        TEXT DEFAULT 'running',         -- running / exited
    created_by   UUID,                           -- 创建者 user.id（普通用户隔离用）
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(name)
);

ALTER TABLE public.containers ADD COLUMN IF NOT EXISTS created_by UUID;

-- 联合索引：加速普通用户的列表检索
CREATE INDEX IF NOT EXISTS idx_containers_user_state ON public.containers (created_by, state);
CREATE INDEX IF NOT EXISTS idx_containers_name       ON public.containers (name);


-- ============================================================
-- 4. 工单表 (public.tickets)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.tickets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_no       VARCHAR(32) NOT NULL UNIQUE,        -- 工单编号 TK20260717001
    title           VARCHAR(200) NOT NULL,             -- 标题
    content         TEXT NOT NULL DEFAULT '',           -- 问题描述
    customer_id     UUID NOT NULL,                     -- 提交者 user.id
    customer_name   TEXT DEFAULT '',                    -- 提交者用户名（冗余便于查询）
    category        VARCHAR(50) DEFAULT '其他',         -- 分类
    priority        SMALLINT DEFAULT 3,                 -- 优先级 1~5
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/processing/resolved/closed
    assignee_id     UUID,                              -- 处理人 user.id
    assignee_name   TEXT DEFAULT '',                    -- 处理人用户名（冗余）
    resolved_at     TIMESTAMPTZ,                       -- 解决时间
    closed_at       TIMESTAMPTZ,                       -- 关闭时间
    attachments     JSONB DEFAULT '[]'::jsonb,          -- 附件数组
    deleted_at      TIMESTAMPTZ,                       -- 软删除时间（NULL=未删除）
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 字段平滑迁移（兼容已存在的表）
-- v3.6：补充 assignee_id / assignee_name，并新增 resolved_at / closed_at / deleted_at 等字段
ALTER TABLE public.tickets ADD COLUMN IF NOT EXISTS customer_name   TEXT DEFAULT '';
ALTER TABLE public.tickets ADD COLUMN IF NOT EXISTS assignee_id     UUID;             -- v3.6 新增：处理人 ID
ALTER TABLE public.tickets ADD COLUMN IF NOT EXISTS assignee_name    TEXT DEFAULT '';  -- v3.6 新增：处理人用户名
ALTER TABLE public.tickets ADD COLUMN IF NOT EXISTS resolved_at     TIMESTAMPTZ;      -- v3.6 新增：解决时间
ALTER TABLE public.tickets ADD COLUMN IF NOT EXISTS closed_at       TIMESTAMPTZ;
ALTER TABLE public.tickets ADD COLUMN IF NOT EXISTS deleted_at      TIMESTAMPTZ;

-- v3.6 数据回填：将历史遗留未分配处理人的工单，默认处理人置为提交人
-- 仅回填 assignee_id IS NULL 的记录，幂等可重复执行
UPDATE public.tickets
SET assignee_id = customer_id,
    assignee_name = customer_name,
    updated_at = now()
WHERE assignee_id IS NULL
  AND customer_id IS NOT NULL
  AND deleted_at IS NULL;

-- 索引
CREATE INDEX IF NOT EXISTS idx_tickets_status       ON public.tickets (status);
CREATE INDEX IF NOT EXISTS idx_tickets_customer    ON public.tickets (customer_id);
CREATE INDEX IF NOT EXISTS idx_tickets_assignee   ON public.tickets (assignee_id);
CREATE INDEX IF NOT EXISTS idx_tickets_created    ON public.tickets (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_status_created ON public.tickets (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tickets_deleted_at ON public.tickets (deleted_at);


-- ============================================================
-- 5. 工单回复表 (public.ticket_replies)
-- ============================================================

CREATE TABLE IF NOT EXISTS public.ticket_replies (
    id              BIGSERIAL PRIMARY KEY,
    ticket_id       UUID NOT NULL,                     -- 工单 ID
    reply_user_id   UUID NOT NULL,                     -- 回复人 user.id
    reply_user_name TEXT DEFAULT '',                   -- 回复人用户名（冗余）
    reply_user_type VARCHAR(10) NOT NULL,             -- customer / admin
    content         TEXT NOT NULL DEFAULT '',          -- 回复内容
    attachments     JSONB DEFAULT '[]'::jsonb,         -- 附件数组
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.ticket_replies ADD COLUMN IF NOT EXISTS reply_user_name TEXT DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_replies_ticket    ON public.ticket_replies (ticket_id);
CREATE INDEX IF NOT EXISTS idx_replies_created   ON public.ticket_replies (created_at);


-- ============================================================
-- 6. 行级安全 (RLS) 与策略
-- ============================================================

ALTER TABLE public.users          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_logs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.containers     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tickets        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ticket_replies ENABLE ROW LEVEL SECURITY;

-- users
DROP POLICY IF EXISTS "Users can view own profile" ON public.users;
DROP POLICY IF EXISTS "Users can update own profile" ON public.users;
CREATE POLICY "Users can view own profile"
    ON public.users FOR SELECT
    USING (auth.uid()::text = id);
CREATE POLICY "Users can update own profile"
    ON public.users FOR UPDATE
    USING (auth.uid()::text = id);

-- audit_logs
DROP POLICY IF EXISTS "Authenticated users can read audit logs" ON public.audit_logs;
CREATE POLICY "Authenticated users can read audit logs"
    ON public.audit_logs FOR SELECT
    USING (auth.role() = 'authenticated');

-- containers：普通用户只能看自己创建的，管理员可看全部
DROP POLICY IF EXISTS "Users can view own containers" ON public.containers;
CREATE POLICY "Users can view own containers"
    ON public.containers FOR SELECT
    USING (created_by = auth.uid());

-- tickets：用户能查询（应用层会用 service_role_key 全部查询，因此 RLS 主要做兜底）
DROP POLICY IF EXISTS "Users can view own tickets" ON public.tickets;
CREATE POLICY "Users can view own tickets"
    ON public.tickets FOR SELECT
    USING (customer_id = auth.uid() OR assignee_id = auth.uid());

-- ticket_replies：所有相关方均可查看
DROP POLICY IF EXISTS "Users can view ticket replies" ON public.ticket_replies;
CREATE POLICY "Users can view ticket replies"
    ON public.ticket_replies FOR SELECT
    USING (true);


-- ============================================================
-- 7. updated_at 自动维护触发器
-- ============================================================

CREATE OR REPLACE FUNCTION public.update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_users_updated_at ON public.users;
CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON public.users
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_containers_updated_at ON public.containers;
CREATE TRIGGER trg_containers_updated_at
    BEFORE UPDATE ON public.containers
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();

DROP TRIGGER IF EXISTS trg_tickets_updated_at ON public.tickets;
CREATE TRIGGER trg_tickets_updated_at
    BEFORE UPDATE ON public.tickets
    FOR EACH ROW
    EXECUTE FUNCTION public.update_updated_at_column();


-- ============================================================
-- 8. 初始化用户数据（含密码 bcrypt 哈希）
-- ============================================================

-- admin / 123456
INSERT INTO public.users (id, email, username, home_folder_path, role, permissions, password, created_at, updated_at)
VALUES (
    '13f53708-62b9-407d-a4eb-1c1c3bc43f2b',
    'admin', 'admin', '~/robotruck_ros2', 'admin',
    '["welcome","scripts","advanced-scripts","docker","advanced-docker","images","traffic","advanced-fault","batch","tools","simulation","topics","nodes","services","actions","advanced-env","advanced-extend","advanced-global","monitor","advanced-monitor","theme","settings"]'::jsonb,
    '$2b$12$JCHjdliHgg9kN84WzR7RHewl.LYBUEAHT8OEsVMGuW8XSMooIaKXa',
    '2026-06-21 10:04:27.975851+00', '2026-07-16 08:37:59.873076+00'
)
ON CONFLICT (email) DO UPDATE SET
    username         = EXCLUDED.username,
    home_folder_path = EXCLUDED.home_folder_path,
    role             = EXCLUDED.role,
    permissions      = EXCLUDED.permissions,
    password         = COALESCE(NULLIF(public.users.password, ''), EXCLUDED.password),
    updated_at       = now();

-- 其他用户密码均为 Boonray2020!
-- v3.6 修复：home_folder_path 与代码 generate_username_from_email 逻辑保持一致
--           邮箱 @ 前的 . 替换为 _（与服务器实际目录、Web 注册创建路径一致）
INSERT INTO public.users (id, email, username, home_folder_path, role, permissions, password, created_at, updated_at)
VALUES
    ('608056f4-b196-4d1f-9a93-498de70e546d', 'shijie.guo@boonray.com',  'shijie_guo',  '~/robotruck_ros2/shijie_guo',  'user', '["welcome","scripts","docker","traffic","advanced-fault","batch","tools","simulation","topics","nodes","theme"]'::jsonb, '$2b$12$KrTpSJ3/QBse56f0HH0T3uFsGfSOf45nwoUxxJrgRJAHCAR3NYhkC', '2026-06-21 11:12:07.256708+00', '2026-07-16 08:39:54.286196+00'),
    ('717de141-1362-4f40-8a1c-b86ec3468a65', 'ning.jiao@boonray.com',   'ning_jiao',   '~/robotruck_ros2/ning_jiao',   'user', '["welcome","scripts","docker","traffic","advanced-fault","batch","tools","simulation","topics","nodes","theme"]'::jsonb, '$2b$12$KrTpSJ3/QBse56f0HH0T3uFsGfSOf45nwoUxxJrgRJAHCAR3NYhkC', '2026-06-22 13:17:57.899983+00', '2026-07-16 08:16:43.018728+00'),
    ('fd94eb73-c5cc-45d1-8e97-86cb89ce3403', 'honglan.wang@boonray.com','honglan_wang','~/robotruck_ros2/honglan_wang','user', '["welcome","scripts","docker","traffic","advanced-fault","batch","tools","simulation","topics","nodes","theme"]'::jsonb, '$2b$12$KrTpSJ3/QBse56f0HH0T3uFsGfSOf45nwoUxxJrgRJAHCAR3NYhkC', '2026-06-22 13:15:53.547720+00', '2026-07-16 08:16:43.018728+00'),
    ('a1b2c3d4-e5f6-7890-abcd-ef1234567890', 'wenrui.cao@boonray.com',  'wenrui_cao',  '~/robotruck_ros2/wenrui_cao',  'user', '["welcome","scripts","docker","traffic","advanced-fault","batch","tools","simulation","topics","nodes","theme"]'::jsonb, '$2b$12$KrTpSJ3/QBse56f0HH0T3uFsGfSOf45nwoUxxJrgRJAHCAR3NYhkC', '2026-06-22 13:17:35.213183+00', '2026-07-16 08:16:43.018728+00'),
    ('b2c3d4e5-f6a7-8901-bcde-f12345678901', 'yuyong.cao@boonray.com', 'yuyong_cao',  '~/robotruck_ros2/yuyong_cao',  'user', '["welcome","scripts","docker","traffic","advanced-fault","batch","tools","simulation","topics","nodes","theme"]'::jsonb, '$2b$12$KrTpSJ3/QBse56f0HH0T3uFsGfSOf45nwoUxxJrgRJAHCAR3NYhkC', '2026-06-23 08:10:30.654037+00', '2026-07-16 08:16:43.018728+00')
ON CONFLICT (email) DO UPDATE SET
    username         = EXCLUDED.username,
    home_folder_path = EXCLUDED.home_folder_path,
    role             = EXCLUDED.role,
    permissions      = EXCLUDED.permissions,
    password         = COALESCE(NULLIF(public.users.password, ''), EXCLUDED.password),
    updated_at       = now();


-- ============================================================
-- 9. 校验查询
-- ============================================================

-- v3.6 数据回填：修复历史遗留的带点号 home_folder_path
-- 将 ~/robotruck_ros2/xxx.yyy 修正为 ~/robotruck_ros2/xxx_yyy
-- 幂等可重复执行：仅修改用户名段（最后一段）包含 . 的记录
-- admin 的 home_folder_path 为 ~/robotruck_ros2（无 /），不会被匹配
UPDATE public.users
SET home_folder_path = '~/robotruck_ros2/' || REPLACE(
    substring(home_folder_path from '^~/robotruck_ros2/(.+)$'),
    '.', '_'
),
    updated_at = now()
WHERE home_folder_path LIKE '~/robotruck_ros2/%'
  AND substring(home_folder_path from '^~/robotruck_ros2/(.+)$') LIKE '%.%';

SELECT id, email, username, role,
       CASE WHEN password IS NULL OR password = '' THEN '❌ 未设置' ELSE '✅ 已设置' END AS password_status,
       home_folder_path,
       created_at
FROM public.users
ORDER BY created_at;

SELECT 'tickets' AS table_name, count(*) AS cnt FROM public.tickets
UNION ALL
SELECT 'ticket_replies', count(*) FROM public.ticket_replies;
