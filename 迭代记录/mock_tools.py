      
#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import struct
import threading
import socket
import time
import math
import gzip
import base64
import random
import queue
import tkinter as tk
from tkinter import ttk
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Chair 参数
# ---------------------------------------------------------------------------
CHAIR_TARGET_SN = "fz_c01"
CHAIR_DEVICE_SN = "seat_control_01"
CHAIR_UDP_PORT = 19696
CHAIR_SEND_ADDR = ("0.0.0.0", 8801)
CHAIR_SHOVEL_ADDR = ("106.14.223.60", 1234)

CHAIR_MODE_NAMES = ["UDP直连JSON", "铲运转发JSON", "UDP直连PB"]
CHAIR_DRIVE_MODE_NAMES = ["人工", "遥控", "自动"]
CHAIR_GEAR_NAMES = ["P", "R", "N", "D"]
CHAIR_GEAR_VALUES = [0, 1, 2, 3]
CHAIR_PTO_NAMES = ["保持", "上升", "下降"]
CHAIR_PTO_VALUES = [0, 1, 2]
CHAIR_DRIVE_STATUS_NAMES = {0: "人工驾驶", 1: "遥控驾驶", 2: "自动驾驶",
                            3: "方向盘介入", 4: "刹车介入", 5: "油门介入",
                            6: "刹车失效", 11: "手柄遥控模式"}

CHAIR_DEFAULT_THROTTLE = 0.0
CHAIR_DEFAULT_BRAKE = 0.0
CHAIR_DEFAULT_STEERING = 0.0

# ---------------------------------------------------------------------------
# V2E 参数
# ---------------------------------------------------------------------------
V2E_DEVICE_SN = "brook_sc_m001"
V2E_TARGET_SN = "fz_c01"
V2E_UDP_PORT = 16969
V2E_SEND_ADDR = ("0.0.0.0", 8801)
V2E_SHOVEL_ADDR = ("106.14.223.60", 1234)

# ---------------------------------------------------------------------------
# 交通灯 (Light) 参数
# ---------------------------------------------------------------------------
LIGHT_DEFAULT_TARGET_IP = "106.14.223.60"
LIGHT_DEFAULT_TARGET_PORT = 1234
LIGHT_DEFAULT_DEVICE_LIST = "hz_test_light01\nhz_test_light02\nhz_test_light04"
LIGHT_DEFAULT_RED = 10
LIGHT_DEFAULT_GREEN = 30
LIGHT_DEFAULT_YELLOW = 3
LIGHT_DEFAULT_INTERVAL = "0.3"

LIGHT_GREEN = 1
LIGHT_RED = 2
LIGHT_OFF = 3
LIGHT_YELLOW = 4

LIGHT_STATE_NAME = {
    LIGHT_GREEN: "绿灯",
    LIGHT_RED: "红灯",
    LIGHT_OFF: "关灯",
    LIGHT_YELLOW: "黄灯",
}
LIGHT_STATE_COLOR = {
    LIGHT_GREEN: "#2ecc71",
    LIGHT_RED: "#e74c3c",
    LIGHT_OFF: "#7f8c8d",
    LIGHT_YELLOW: "#f1c40f",
}

# ---------------------------------------------------------------------------
# 附件控制 键值表 (ChairCmd)
# ---------------------------------------------------------------------------
ACCESSORY_KEYS = {
    "turn_left": ("turn_signal", "转向灯:左"),
    "turn_right": ("turn_signal", "转向灯:右"),
    "turn_close": ("turn_signal", "转向灯:关"),
    "headlight": ("headlight", "前照灯"),
    "ac_mode": ("ac_mode", "空调"),
    "wiper": ("wiper", "雨刮"),
    "wiper_clean": ("wiper_clean", "雨刮喷水"),
    "retarder": ("retarder", "缓行器"),
    "lsd": ("lsd", "差速锁"),
    "pos_light": ("pos_light", "示廓灯"),
    "inside_light": ("inside_light", "室内灯"),
    "front_fog_light": ("front_fog_light", "前雾灯"),
    "front_working_light": ("front_working_light", "前工作灯"),
    "side_light": ("side_light", "侧照灯"),
    "emer_steering": ("emer_steering_ctrl", "应急转向"),
    "canopy": ("canopy", "雨棚"),
}

ACCESSORY_OFF_KEYS = {
    "turn_signal": 0,
    "headlight": 0,
    "ac_mode": 0,
    "wiper": 0,
    "wiper_clean": 0,
    "retarder": 0,
    "lsd": 0,
    "pos_light": 0,
    "inside_light": 0,
    "front_fog_light": 0,
    "front_working_light": 0,
    "side_light": 0,
    "emer_steering_ctrl": 0,
    "canopy": 0,
}

# ---------------------------------------------------------------------------
# 车况回显字段 -> (显示名称, 格式化)
# ---------------------------------------------------------------------------
FEEDBACK_FIELDS = [
    ("drive_mode", "驾驶模式", "enum"),
    ("gear", "挡位", "gear"),
    ("pdc_speed", "车速", "raw"),
    ("soc", "电量SOC", "raw"),
    ("battery_voltage", "电池电压", "raw"),
    ("battery_current", "电流", "raw"),
    ("motor1_motspeed", "电机1转速", "raw"),
    ("throttle", "油门开度", "raw"),
    ("brake_pos", "刹车开度", "raw"),
    ("steering", "前轮转角", "raw"),
    ("lift_angle", "举升角度", "raw"),
    ("pto_state", "取力器", "pto"),
    ("epb", "手刹", "epb"),
    ("emergency_stop_src_desc", "急停来源", "raw"),
    ("network_latency", "网络延时", "raw"),
    ("chair_latency", "座椅延时", "raw"),
    ("vehicle_error_level", "整车故障等级", "raw"),
    ("veh_errLevel", "VCU故障等级", "raw"),
]


def _tb_json(text):
    """去掉 UDP 前缀(1@/6@/7@/111@)后的 json"""
    for prefix in ["111@", "1@", "6@", "7@"]:
        if text.startswith(prefix):
            return text[len(prefix):]
    return text


class MockToolsApp:

    def __init__(self, root):
        self.root = root
        self.root.title("辅助测试工具")

        # ★ 全局默认字体与样式（仅影响 UI，不动逻辑）
        try:
            default_font = ("Microsoft YaHei UI", 9)
            self.root.option_add("*Font", default_font)
            style = ttk.Style()
            style.configure(".", font=default_font)
            style.configure("TButton", padding=(8, 4))
            style.configure("TLabel", padding=(0, 1))
            style.configure("TLabelframe", padding=(8, 6))
            style.configure("TLabelframe.Label",
                            font=("Microsoft YaHei UI", 9, "bold"))
            style.configure("TRadiobutton", padding=(2, 2))
            style.configure("TCheckbutton", padding=(2, 2))
        except Exception:
            pass

        self._set_icon()
        self.root.resizable(True, True)
        self._center_window(920, 1000)
        self._show_home()

    def _center_window(self, width, height):
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = (screen_h - height) // 2
        self.root.geometry("{}x{}+{}+{}".format(width, height, x, y))

    def _set_icon(self):
        """ 程序化生成蓝色 Mock 图标 """
        icon = tk.PhotoImage(width=32, height=32)
        for x in range(32):
            for y in range(32):
                cx, cy = 15.5, 15.5
                dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if dist <= 15.5:
                    icon.put("#4A90D9", (x, y))
                elif dist <= 16:
                    icon.put("#3A7BC8", (x, y))
        for x in range(9, 12):
            for y in range(7, 26):
                icon.put("#FFFFFF", (x, y))
        for x in range(21, 24):
            for y in range(7, 26):
                icon.put("#FFFFFF", (x, y))
        for i in range(5):
            for j in range(2):
                icon.put("#FFFFFF", (12 + i + j, 7 + i + j))
        for i in range(5):
            for j in range(2):
                icon.put("#FFFFFF", (20 - i - j, 7 + i + j))
        self.root.iconphoto(True, icon)

    def _clear_page(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    def _show_home(self):
        self._clear_page()

        # 整体背景
        bg = "#f5f7fa"
        self.root.configure(bg=bg)

        outer = tk.Frame(self.root, bg=bg)
        outer.pack(fill=tk.BOTH, expand=True)

        # ---------- 顶部标题区 ----------
        header = tk.Frame(outer, bg="#2c3e50", height=120)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        tk.Label(header, text="Mock 辅助测试工具",
                 font=("Microsoft YaHei UI", 22, "bold"),
                 bg="#2c3e50", fg="white").pack(pady=(28, 2))
        tk.Label(header, text="Mock Auxiliary Test Toolbox",
                 font=("Microsoft YaHei UI", 10),
                 bg="#2c3e50", fg="#a9b7c6").pack()

        # ---------- 中部按钮区（grid 多行多列卡片） ----------
        body = tk.Frame(outer, bg=bg)
        body.pack(fill=tk.BOTH, expand=True)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)

        cards_wrap = tk.Frame(body, bg=bg)
        cards_wrap.grid(row=0, column=0)

        # 卡片定义：标题 / 副标题 / 图标色 / 回调
        cards = [
            ("Chair 座椅控制", "座椅控制 / 附件 / 车况回显",
             "#4A90D9", self._show_chair),
            ("V2E 控车", "行走 / 举升 / 位置调整",
             "#27ae60", self._show_v2e),
            ("故障模拟", "change_status / mock_status",
             "#e67e22", self._show_fault),
            ("交通灯控制", "手动 / 计时 · 多灯独立",
             "#8e44ad", self._show_light),
            ("地图工具", "bag 分析 / map 格式转换",
             "#16a085", self._show_map_tool),
            ("仿真测试", "单案例 / 批量 / 容器会话",
             "#c0392b", self._show_sim_test),
            ("Orin 烧录", "镜像扫描 / 整机烧录",
             "#7f8c8d", self._show_orin_flash),
            ("网络工具", "tc 延迟注入 / 清理",
             "#2980b9", self._show_network),
            ("云平台工具", "UDP灯态 / MQTT / TCP",
             "#d35400", self._show_cloud),
            ("目标点更新", "dump_goal 坐标平移",
             "#34495e", self._show_goal_update),
        ]

        # 每行 4 张卡片
        for i, (title, subtitle, color, cmd) in enumerate(cards):
            row, col = divmod(i, 4)
            self._make_home_card(cards_wrap, title, subtitle, color, cmd,
                                 row=row, col=col)

        # ---------- 底部退出 ----------
        footer = tk.Frame(outer, bg=bg)
        footer.pack(fill=tk.X, pady=(0, 30))

        exit_btn = tk.Button(
            footer, text="退出",
            font=("Microsoft YaHei UI", 10),
            bg="#e74c3c", fg="white",
            activebackground="#c0392b", activeforeground="white",
            relief="flat", bd=0, cursor="hand2",
            width=14, height=1,
            command=self.root.quit,
        )
        exit_btn.pack(pady=6, ipady=6)
        exit_btn.bind("<Enter>", lambda e: exit_btn.configure(bg="#c0392b"))
        exit_btn.bind("<Leave>", lambda e: exit_btn.configure(bg="#e74c3c"))

    def _make_home_card(self, parent, title, subtitle, color, command,
                        row=0, col=0):
        """创建一个 grid 排布的卡片式按钮"""
        card = tk.Frame(parent, bg="white", bd=0,
                        highlightthickness=1,
                        highlightbackground="#e1e4e8")
        card.grid(row=row, column=col, padx=12, pady=10, ipadx=6, ipady=6)

        inner = tk.Frame(card, bg="white", width=200, height=170)
        inner.pack_propagate(False)
        inner.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)

        # 顶部色条
        bar = tk.Frame(inner, bg=color, height=4)
        bar.pack(fill=tk.X, pady=(0, 14))

        # 图标圆点
        icon = tk.Label(inner, text="●", font=("", 22, "bold"),
                        bg="white", fg=color)
        icon.pack(pady=(4, 10))

        # 标题
        title_lbl = tk.Label(inner, text=title,
                             font=("Microsoft YaHei UI", 11, "bold"),
                             bg="white", fg="#2c3e50")
        title_lbl.pack()

        # 副标题
        sub_lbl = tk.Label(inner, text=subtitle,
                           font=("Microsoft YaHei UI", 8),
                           bg="white", fg="#95a5a6",
                           wraplength=170, justify=tk.CENTER)
        sub_lbl.pack(pady=(6, 0))

        widgets = [card, inner, bar, icon, title_lbl, sub_lbl]

        def on_enter(_):
            card.configure(highlightbackground=color)
            inner.configure(bg="#fafcff")
            for w in (icon, title_lbl, sub_lbl):
                w.configure(bg="#fafcff")

        def on_leave(_):
            card.configure(highlightbackground="#e1e4e8")
            inner.configure(bg="white")
            for w in (icon, title_lbl, sub_lbl):
                w.configure(bg="white")

        for w in widgets:
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)
            w.bind("<Button-1>", lambda e, c=command: c())
            try:
                w.configure(cursor="hand2")
            except Exception:
                pass

    def _show_chair(self):
        self._clear_page()
        self._chair = ChairPage(self.root, self._show_home)

    def _show_v2e(self):
        self._clear_page()
        self._v2e = V2ePage(self.root, self._show_home)

    def _show_fault(self):
        self._clear_page()
        self._fault = FaultPage(self.root, self._show_home)

    def _show_light(self):
        self._clear_page()
        self._light = LightPage(self.root, self._show_home)

    def _show_map_tool(self):
        self._clear_page()
        self._map_tool = MapToolPage(self.root, self._show_home)

    def _show_sim_test(self):
        self._clear_page()
        self._sim_test = SimTestPage(self.root, self._show_home)

    def _show_orin_flash(self):
        self._clear_page()
        self._orin_flash = OrinFlashPage(self.root, self._show_home)

    def _show_network(self):
        self._clear_page()
        self._network = NetworkPage(self.root, self._show_home)

    def _show_cloud(self):
        self._clear_page()
        self._cloud = CloudToolsPage(self.root, self._show_home)

    def _show_goal_update(self):
        self._clear_page()
        self._goal_update = GoalUpdatePage(self.root, self._show_home)


class ScrollFrame(ttk.Frame):
    """ 可滚动容器, 内容放入 self.body """

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.body = ttk.Frame(self.canvas, padding="4 4 4 4")
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.body.bind("<MouseWheel>", self._on_mousewheel)

    def _on_body_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)

    def _on_mousewheel(self, event):
        if self.canvas.winfo_viewable():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class ChairPage:

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back

        # 控制参数
        self._mode = 0
        self._controled = False
        self._drive_mode = 1
        self._brake = 50
        self._throttle = 20
        self._steering = 20
        self._gear = 1
        self._pto = 0
        self._delay = 0

        # SN (可配置)
        self.target_sn = CHAIR_TARGET_SN
        self.device_sn = CHAIR_DEVICE_SN

        # 急停
        self._emergency = False

        # 车况回显
        self.feedback = {}
        self.last_feedback_time = 0

        # UDP socket
        self._udp_client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_client.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp_client.bind(("0.0.0.0", CHAIR_UDP_PORT))
        self._running = True

        self._init_socket()

        # GUI 变量
        self._mode_var = tk.IntVar(value=0)
        self._drive_mode_var = tk.IntVar(value=1)
        self._gear_var = tk.IntVar(value=0)
        self._pto_var = tk.IntVar(value=0)
        self._throttle_var = tk.DoubleVar(value=CHAIR_DEFAULT_THROTTLE)
        self._brake_var = tk.DoubleVar(value=CHAIR_DEFAULT_BRAKE)
        self._steering_var = tk.DoubleVar(value=CHAIR_DEFAULT_STEERING)
        self._delay_var = tk.IntVar(value=0)
        self._ctrl_var = tk.BooleanVar(value=False)
        self._emg_var = tk.BooleanVar(value=False)
        self._obstacles_var = tk.BooleanVar(value=False)
        self._target_sn_var = tk.StringVar(value=self.target_sn)
        self._device_sn_var = tk.StringVar(value=self.device_sn)
        self._heartbeat_var = tk.StringVar(value="O 等待回传")
        self._raw_prefix_var = tk.IntVar(value=6)
        self._raw_shovel_var = tk.BooleanVar(value=False)
        self._raw_method_var = tk.StringVar(value="chair_control_cmd")

        self._create_gui()

        # 心跳 & 车况 刷新
        self.root.after(200, self._poll_feedback)

    # ------------------------------------------------------------------
    # UDP 通信
    # ------------------------------------------------------------------
    def _init_socket(self):
        self._threadpool = ThreadPoolExecutor(max_workers=5)

        recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        recv_thread.start()

        pub_thread = threading.Thread(target=self._publish_loop, daemon=True)
        pub_thread.start()

        ctrl_thread = threading.Thread(target=self._accessory_loop, daemon=True)
        ctrl_thread.start()

    def _recv_loop(self):
        while self._running:
            try:
                data, addr = self._udp_client.recvfrom(8192)
                self._msg_callback(data, addr)
            except OSError:
                break
            except Exception:
                time.sleep(0.5)

    def _msg_callback(self, data, addr):
        """ 收到消息回调 - 处理网络延时探测 / 车况回显 / 指令回复 """
        text = data.decode('utf-8', errors='ignore')
        try:
            recv_data = json.loads(_tb_json(text))
        except Exception:
            return
        method = recv_data.get("method", "")
        params = recv_data.get("params", {})

        # 1. 网络延时探测
        if method == "network_latency":
            time.sleep(0.05 + random.random() * 0.1)
            m_id = recv_data["id"]

            send_data = {
                'id': m_id,
                'method': 'network_latency_res',
                'params': {
                    't': params['t'],
                    'rc': time.time()
                }
            }

            if "source_sn" in params:
                s_data = {
                    "method": "notify_to_device",
                    "params": {
                        "target_device_sn": self.target_sn,
                    }
                }
                s_data["params"].update(**send_data)
                self._send_msg("1@{}".format(json.dumps(s_data)).encode(), to_shovel=True)
            else:
                def _send_delayed():
                    delay = self._delay
                    time.sleep(delay * 0.001)
                    self._send_msg("7@{}".format(json.dumps(send_data)).encode(), to_shovel=False)
                self._threadpool.submit(_send_delayed)

        # 2. 车况回显 (新版本协议, JSON gzip+base64)
        elif method == "chair_rt_msg_vtc":
            raw_json = self._decode_gz_b64(params)
            if raw_json is None:
                return
            self.feedback = raw_json
            self.last_feedback_time = time.time()

        # 3. 车况回显 (pb 版本, 待弃用)
        elif method == "rt_message_protobuf":
            data_dict = self._decode_pb(params)
            if data_dict is not None:
                self.feedback = data_dict
                self.last_feedback_time = time.time()

        # 4. 车端对控制指令的回复
        elif method == "chair_control_cmd_res":
            code = params.get("code", "")
            msg = params.get("msg", "")
            self._update_log("车端回复: code={} msg={}".format(code, msg), tag="info")

    def _decode_gz_b64(self, params):
        if isinstance(params, dict):
            raw_json = None
            for v in params.values():
                if isinstance(v, str):
                    raw_json = self._decode_gz_b64(v)
                    if raw_json is not None:
                        break
            return raw_json
        try:
            raw = gzip.decompress(base64.b64decode(params))
            return json.loads(raw)
        except Exception:
            try:
                return json.loads(params)
            except Exception:
                return None

    def _decode_pb(self, params):
        """ pb 车况回显, 解析 Tsl / seatControl """
        try:
            from guardian_common.utils.tsl_pb2 import Tsl
            msg = Tsl()
            msg.ParseFromString(base64.b64decode(params))
            return dict([(f.name, getattr(msg, f.name)) for f in msg.DESCRIPTOR.fields])
        except Exception:
            try:
                from guardian_common.utils.tsl_pb2 import seatControl
                msg = seatControl()
                msg.ParseFromString(base64.b64decode(params))
                return dict([(f.name, getattr(msg, f.name)) for f in msg.DESCRIPTOR.fields])
            except Exception:
                return None

    def _publish_loop(self):
        while self._running:
            if self._controled:
                try:
                    self._send_rt_msg()
                except Exception:
                    pass
            time.sleep(0.2)

    def _accessory_loop(self):
        """ 忽略障碍物 常开开关轮询(0.5s) """
        while self._running:
            try:
                if self._obstacles_var.get():
                    self._send_ignore_obstacles()
            except Exception:
                pass
            time.sleep(0.5)

    def _send_rt_msg(self):
        if self._mode == 0:
            self._send_udp_json()
        elif self._mode == 1:
            self._send_shovel_json()
        else:
            self._send_udp_pb()

    def _send_udp_json(self):
        params = self._build_control_cmd()
        data = base64.b64encode(
            gzip.compress(json.dumps(params).encode())
        ).decode("utf-8")
        send_data = {
            "method": "chair_rt_msg_ctv",
            "params": data
        }
        self._send_msg("6@{}".format(json.dumps(send_data)).encode(), to_shovel=False)

    def _send_shovel_json(self):
        params = self._build_control_cmd()
        params["source_sn"] = self.device_sn
        data = base64.b64encode(
            gzip.compress(json.dumps(params).encode())
        ).decode("utf-8")
        send_data = {
            "method": "notify_to_device",
            "params": {
                "target_device_sn": self.target_sn,
                "method": "chair_rt_msg_ctv",
                "params": data
            }
        }
        self._send_msg("1@{}".format(json.dumps(send_data)).encode(), to_shovel=True)

    def _send_udp_pb(self):
        from utils.tsl_pb2 import seatControl
        msg = seatControl()
        for k, v in self._build_control_cmd().items():
            setattr(msg, k, v)
        send_data = base64.b64encode(msg.SerializeToString()).decode('utf-8')
        data = {
            'method': 'rt_message_protobuf',
            'params': send_data
        }
        self._send_msg("1@{}".format(json.dumps(data)).encode(), to_shovel=False)

    def _build_control_cmd(self):
        cmd = {
            "target_drive_mode": self._drive_mode,
            "brake": self._brake,
            "throttle": self._throttle,
            "steering": self._steering,
            "gear": self._gear,
            "pto": self._pto,
            "emergency_stop": 1 if self._emergency else 0,
            "target_device_serial_number": self.target_sn
        }
        return cmd

    def _send_chair_cmd(self, key, value):
        """ 发送 chair_control_cmd 附件指令 """
        send_data = {
            "id": "#{:013d}".format(random.randint(0, 10**13)),
            "method": "chair_control_cmd",
            "params": {
                key: value
            }
        }
        self._send_msg("6@{}".format(json.dumps(send_data)).encode(), to_shovel=False)

    def _send_task_cmd(self, extra):
        """ 一次性任务指令 (chair_rt_msg_ctv) """
        params = self._build_control_cmd()
        params.update(extra)
        data = base64.b64encode(
            gzip.compress(json.dumps(params).encode())
        ).decode("utf-8")
        send_data = {
            "method": "chair_rt_msg_ctv",
            "params": data
        }
        self._send_msg("6@{}".format(json.dumps(send_data)).encode(), to_shovel=False)

    def _send_msg(self, data, to_shovel=False):
        addr = CHAIR_SHOVEL_ADDR if to_shovel else CHAIR_SEND_ADDR
        self._udp_client.sendto(data, addr)

    def _send_ignore_obstacles(self):
        """ 发送忽略障碍物指令 """
        send_data = {
            "id": "#{:013d}".format(random.randint(0, 10**13)),
            "method": "chair_control_cmd",
            "params": {
                "ignore_obstacles": {
                    "time": 123,
                    "interval": 5
                },
                "turn_signal": 1
            }
        }
        self._send_msg("6@{}".format(json.dumps(send_data)).encode(), to_shovel=False)
        self._update_log("已发送忽略障碍物指令")

    def _cleanup(self):
        self._controled = False
        self._running = False
        try:
            self._udp_client.close()
        except Exception:
            pass
        try:
            self._threadpool.shutdown(wait=False)
        except Exception:
            pass
        self._update_log("资源已清理")

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------
    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        # ---------- 顶部标题栏 ----------
        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        self._back_btn = ttk.Button(title_frame, text="← 返回首页", command=self._on_back)
        self._back_btn.pack(side=tk.LEFT)
        ttk.Label(title_frame, text="Chair 座椅控制",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        self._status_label = ttk.Label(title_frame, text="状态: 未控制",
                                       foreground="red", font=("", 10, "bold"))
        self._status_label.pack(side=tk.RIGHT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ============================================================
        # 设置
        # ============================================================
        settings_frame = ttk.LabelFrame(body, text="设置", padding="12 8 12 8")
        settings_frame.pack(fill=tk.X, padx=12, pady=6)

        # 控制模式
        mode_frame = ttk.Frame(settings_frame)
        mode_frame.pack(fill=tk.X, pady=6)
        ttk.Label(mode_frame, text="控制模式:", width=10).pack(side=tk.LEFT)
        for i, name in enumerate(CHAIR_MODE_NAMES):
            ttk.Radiobutton(mode_frame, text=name, variable=self._mode_var, value=i,
                            command=self._on_mode_change).pack(side=tk.LEFT, padx=10)

        # 控制开关
        ctrl_frame = ttk.Frame(settings_frame)
        ctrl_frame.pack(fill=tk.X, pady=6)
        ttk.Label(ctrl_frame, text="控制开关:", width=10).pack(side=tk.LEFT)
        ttk.Checkbutton(ctrl_frame, text="开始控制", variable=self._ctrl_var,
                        command=self._on_ctrl_change).pack(side=tk.LEFT, padx=10)

        # 延时
        delay_frame = ttk.Frame(settings_frame)
        delay_frame.pack(fill=tk.X, pady=6)
        ttk.Label(delay_frame, text="回复延时:", width=10).pack(side=tk.LEFT)
        ttk.Scale(delay_frame, from_=0, to=999, variable=self._delay_var,
                  command=self._on_delay_change, orient=tk.HORIZONTAL,
                  length=320).pack(side=tk.LEFT, padx=10)
        self._delay_label = ttk.Label(delay_frame, text="0 ms", width=8)
        self._delay_label.pack(side=tk.LEFT)

        # SN 配置
        sn_frame = ttk.Frame(settings_frame)
        sn_frame.pack(fill=tk.X, pady=6)
        ttk.Label(sn_frame, text="SN 配置:", width=10).pack(side=tk.LEFT)
        ttk.Label(sn_frame, text="目标车SN:").pack(side=tk.LEFT)
        ttk.Entry(sn_frame, textvariable=self._target_sn_var, width=18).pack(side=tk.LEFT, padx=3)
        ttk.Label(sn_frame, text="本设备SN:").pack(side=tk.LEFT, padx=(10, 0))
        ttk.Entry(sn_frame, textvariable=self._device_sn_var, width=18).pack(side=tk.LEFT, padx=3)
        ttk.Button(sn_frame, text="应用", width=6, command=self._apply_sn).pack(side=tk.LEFT, padx=8)

        # 急停
        emg_frame = ttk.Frame(settings_frame)
        emg_frame.pack(fill=tk.X, pady=6)
        ttk.Label(emg_frame, text="急停:", width=10).pack(side=tk.LEFT)
        ttk.Checkbutton(emg_frame, text="按下急停 (emergency_stop=1)", variable=self._emg_var,
                        command=self._on_emergency_change).pack(side=tk.LEFT, padx=10)
        ttk.Label(emg_frame, text="紧急急停会随控制指令每 0.2s 发送",
                  foreground="gray").pack(side=tk.LEFT)

        # 忽略障碍物
        ignore_frame = ttk.Frame(settings_frame)
        ignore_frame.pack(fill=tk.X, pady=6)
        ttk.Label(ignore_frame, text="忽略障碍物:", width=10).pack(side=tk.LEFT)
        ttk.Checkbutton(ignore_frame, text="常开", variable=self._obstacles_var).pack(side=tk.LEFT, padx=3)
        ttk.Button(ignore_frame, text="发送一次", width=10,
                   command=self._send_ignore_obstacles).pack(side=tk.LEFT, padx=5)
        ttk.Label(ignore_frame, text="常开时每 0.5s 自动发送",
                  foreground="gray").pack(side=tk.LEFT)

        # ============================================================
        # 控制指令
        # ============================================================
        cmd_frame = ttk.LabelFrame(body, text="控制指令 (随控制开关每 0.2s 发送)",
                                   padding="12 8 12 8")
        cmd_frame.pack(fill=tk.X, padx=12, pady=6)

        dm_frame = ttk.Frame(cmd_frame)
        dm_frame.pack(fill=tk.X, pady=8)
        ttk.Label(dm_frame, text="驾驶模式:", width=10).pack(side=tk.LEFT)
        for i, name in enumerate(CHAIR_DRIVE_MODE_NAMES):
            ttk.Radiobutton(dm_frame, text=name, variable=self._drive_mode_var, value=i,
                            command=self._on_drive_mode_change).pack(side=tk.LEFT, padx=10)

        gear_frame = ttk.Frame(cmd_frame)
        gear_frame.pack(fill=tk.X, pady=8)
        ttk.Label(gear_frame, text="挡位:", width=10).pack(side=tk.LEFT)
        for i, name in enumerate(CHAIR_GEAR_NAMES):
            ttk.Radiobutton(gear_frame, text=name, variable=self._gear_var,
                            value=CHAIR_GEAR_VALUES[i],
                            command=self._on_gear_change).pack(side=tk.LEFT, padx=10)

        pto_frame = ttk.Frame(cmd_frame)
        pto_frame.pack(fill=tk.X, pady=8)
        ttk.Label(pto_frame, text="PTO控制:", width=10).pack(side=tk.LEFT)
        for i, name in enumerate(CHAIR_PTO_NAMES):
            ttk.Radiobutton(pto_frame, text=name, variable=self._pto_var,
                            value=CHAIR_PTO_VALUES[i],
                            command=self._on_pto_change).pack(side=tk.LEFT, padx=10)

        thr_frame = ttk.Frame(cmd_frame)
        thr_frame.pack(fill=tk.X, pady=8)
        ttk.Label(thr_frame, text="油门:", width=10).pack(side=tk.LEFT)
        ttk.Scale(thr_frame, from_=0, to=100, variable=self._throttle_var,
                  command=self._on_throttle_change, orient=tk.HORIZONTAL,
                  length=320).pack(side=tk.LEFT, padx=10)
        self._throttle_label = ttk.Label(thr_frame, text="0.000", width=8)
        self._throttle_label.pack(side=tk.LEFT)

        brake_frame = ttk.Frame(cmd_frame)
        brake_frame.pack(fill=tk.X, pady=8)
        ttk.Label(brake_frame, text="刹车:", width=10).pack(side=tk.LEFT)
        ttk.Scale(brake_frame, from_=0, to=100, variable=self._brake_var,
                  command=self._on_brake_change, orient=tk.HORIZONTAL,
                  length=320).pack(side=tk.LEFT, padx=10)
        self._brake_label = ttk.Label(brake_frame, text="0.000", width=8)
        self._brake_label.pack(side=tk.LEFT)

        steer_frame = ttk.Frame(cmd_frame)
        steer_frame.pack(fill=tk.X, pady=8)
        ttk.Label(steer_frame, text="转向:", width=10).pack(side=tk.LEFT)
        ttk.Scale(steer_frame, from_=100, to=-100, variable=self._steering_var,
                  command=self._on_steering_change, orient=tk.HORIZONTAL,
                  length=320).pack(side=tk.LEFT, padx=10)
        self._steering_label = ttk.Label(steer_frame, text="0.000", width=8)
        self._steering_label.pack(side=tk.LEFT)
        ttk.Button(steer_frame, text="归0", width=4,
                   command=self._on_steering_zero).pack(side=tk.LEFT, padx=5)
        ttk.Label(steer_frame, text="左正 右负", foreground="gray").pack(side=tk.LEFT, padx=5)

        # ============================================================
        # 附件控制
        # ============================================================
        acc_frame = ttk.LabelFrame(body, text="附件控制 (通过 chair_control_cmd 6@ 发送)",
                                   padding="12 8 12 8")
        acc_frame.pack(fill=tk.X, padx=12, pady=6)
        row, col = 0, 0
        for key, (cmd, label) in ACCESSORY_KEYS.items():
            f = ttk.Frame(acc_frame)
            f.grid(row=row, column=col, sticky="w", padx=6, pady=3)
            ttk.Button(f, text=label, width=13,
                       command=lambda c=cmd: self._send_accessory(c, 1)).pack(side=tk.LEFT)
            ttk.Button(f, text="关", width=4,
                       command=lambda c=cmd: self._send_accessory(c, 0)).pack(side=tk.LEFT, padx=2)
            col += 1
            if col >= 3:
                col = 0
                row += 1

        # ============================================================
        # 任务指令
        # ============================================================
        task_frame = ttk.LabelFrame(body, text="任务指令 (一次性 chair_rt_msg_ctv)",
                                    padding="12 8 12 8")
        task_frame.pack(fill=tk.X, padx=12, pady=6)
        TASKS = [
            ("开始自动驾驶", {"target_drive_mode": 2}),
            ("停止任务", {"stop_task": 1}),
            ("暂停任务", {"pause_task": 1}),
            ("路径录制", {"record_path": 1}),
            ("复位自动", {"reset_auto": 1}),
            ("自动举升", {"target_drive_mode": 2, "dot_type": 1}),
        ]
        for name, extra in TASKS:
            ttk.Button(task_frame, text=name, width=14,
                       command=lambda e=extra, n=name: self._on_task_click(n, e)).pack(
                           side=tk.LEFT, padx=5, pady=4)

        # ============================================================
        # 自定义原始报文
        # ============================================================
        raw_frame = ttk.LabelFrame(body, text="自定义原始报文", padding="12 8 12 8")
        raw_frame.pack(fill=tk.X, padx=12, pady=6)

        raw_r1 = ttk.Frame(raw_frame)
        raw_r1.pack(fill=tk.X, pady=4)
        ttk.Label(raw_r1, text="前缀:", width=10).pack(side=tk.LEFT)
        ttk.Radiobutton(raw_r1, text="1@ UDP直连", variable=self._raw_prefix_var, value=1).pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(raw_r1, text="6@ Chair直连", variable=self._raw_prefix_var, value=6).pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(raw_r1, text="7@ UDP本地", variable=self._raw_prefix_var, value=7).pack(side=tk.LEFT, padx=6)
        ttk.Checkbutton(raw_r1, text="走铲运(notify_to_device)",
                        variable=self._raw_shovel_var).pack(side=tk.LEFT, padx=10)

        raw_r2 = ttk.Frame(raw_frame)
        raw_r2.pack(fill=tk.X, pady=4)
        ttk.Label(raw_r2, text="method:", width=10).pack(side=tk.LEFT)
        ttk.Entry(raw_r2, textvariable=self._raw_method_var, width=40).pack(side=tk.LEFT, padx=5)
        ttk.Button(raw_r2, text="发送报文", width=10,
                   command=self._send_raw_msg).pack(side=tk.RIGHT, padx=5)

        raw_r3 = ttk.Frame(raw_frame)
        raw_r3.pack(fill=tk.X, pady=4)
        ttk.Label(raw_r3, text="params:", width=10).pack(side=tk.LEFT, anchor=tk.N)
        self._raw_params_text = tk.Text(raw_r3, height=3, width=70, wrap=tk.WORD,
                                        font=("Consolas", 9))
        self._raw_params_text.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Label(raw_r3, text="JSON, 如 {\"target_drive_mode\": 1}",
                  foreground="gray").pack(side=tk.LEFT)

        # ============================================================
        # 车况回显
        # ============================================================
        fb_frame = ttk.LabelFrame(body, text="车况回显 (车端下发 chair_rt_msg_vtc)",
                                  padding="12 8 12 8")
        fb_frame.pack(fill=tk.X, padx=12, pady=6)

        self._heartbeat_label = ttk.Label(fb_frame, textvariable=self._heartbeat_var,
                                          foreground="gray", font=("", 10, "bold"))
        self._heartbeat_label.pack(anchor=tk.W, pady=(0, 6))

        self._feedback_labels = {}
        fb_grid_wrap = ttk.Frame(fb_frame)
        fb_grid_wrap.pack(fill=tk.X)
        for i, (field, name, fmt) in enumerate(FEEDBACK_FIELDS):
            lab = ttk.Label(fb_grid_wrap, text="{}: -".format(name),
                            width=26, anchor=tk.W)
            lab.grid(row=i // 3, column=i % 3, sticky="w", padx=6, pady=2)
            self._feedback_labels[field] = lab

        # ============================================================
        # 日志
        # ============================================================
        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.X, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=8, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("info", foreground="#1e6fd9")

        self._update_log("Chair 座椅控制页面已启动")

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _update_status(self, text, color):
        self._status_label.config(text="状态: {}".format(text), foreground=color)

    # ------------------------------------------------------------------
    # 事件回调
    # ------------------------------------------------------------------
    def _on_back(self):
        self._cleanup()
        self.on_back()

    def _on_ctrl_change(self):
        self._controled = self._ctrl_var.get()
        status = "控制中" if self._controled else "未控制"
        color = "green" if self._controled else "red"
        self._update_status(status, color)
        self._back_btn.config(state=tk.DISABLED if self._controled else tk.NORMAL)
        self._update_log("{}控制".format("开始" if self._controled else "结束"))

    def _on_mode_change(self):
        self._mode = self._mode_var.get()
        self._update_log("控制模式切换至: {}".format(CHAIR_MODE_NAMES[self._mode]))

    def _on_drive_mode_change(self):
        self._drive_mode = self._drive_mode_var.get()
        self._update_log("驾驶模式切换至: {}".format(CHAIR_DRIVE_MODE_NAMES[self._drive_mode]))

    def _on_gear_change(self):
        gear_val = self._gear_var.get()
        self._gear = gear_val
        self._update_log("挡位切换至: {}".format(CHAIR_GEAR_NAMES[CHAIR_GEAR_VALUES.index(gear_val)]))

    def _on_pto_change(self):
        pto_val = self._pto_var.get()
        self._pto = pto_val
        self._update_log("PTO控制切换至: {}".format(CHAIR_PTO_NAMES[CHAIR_PTO_VALUES.index(pto_val)]))

    def _on_throttle_change(self, value):
        val = round(float(value), 3)
        self._throttle = val
        self._throttle_label.config(text="{:.3f}".format(val))

    def _on_brake_change(self, value):
        val = round(float(value), 3)
        self._brake = val
        self._brake_label.config(text="{:.3f}".format(val))

    def _on_steering_change(self, value):
        val = round(float(value), 3)
        self._steering = val
        self._steering_label.config(text="{:.3f}".format(val))

    def _on_steering_zero(self):
        self._steering_var.set(0.0)
        self._steering = 0.0
        self._steering_label.config(text="0.000")

    def _on_delay_change(self, value):
        val = int(float(value))
        self._delay = val
        self._delay_label.config(text="{} ms".format(val))

    def _on_emergency_change(self):
        self._emergency = self._emg_var.get()
        self._update_log("{}急停 (emergency_stop={})".format(
            "按下" if self._emergency else "解除", 1 if self._emergency else 0),
            tag="error" if self._emergency else "info")
        self._update_status("急停中" if self._emergency else
                            ("控制中" if self._controled else "未控制"),
                            "red" if self._emergency else ("green" if self._controled else "red"))

    def _apply_sn(self):
        self.target_sn = self._target_sn_var.get().strip()
        self.device_sn = self._device_sn_var.get().strip()
        self._update_log("SN 已更新: 目标车SN={} 本设备SN={}".format(
            self.target_sn, self.device_sn))

    def _send_accessory(self, cmd, value):
        self._send_chair_cmd(cmd, value)
        self._update_log("附件指令: {} = {}".format(cmd, value))

    def _on_task_click(self, name, extra):
        self._send_task_cmd(extra)
        self._update_log("任务指令: {}  extra={}".format(
            name, json.dumps(extra, ensure_ascii=False)))

    def _send_raw_msg(self):
        method = self._raw_method_var.get().strip()
        if not method:
            self._update_log("method 不能为空", tag="error")
            return
        param_text = self._raw_params_text.get("1.0", tk.END).strip()
        try:
            params = json.loads(param_text) if param_text else {}
        except Exception:
            self._update_log("params 不是合法 JSON: {}".format(param_text), tag="error")
            return
        payload = {
            "id": "#{:013d}".format(random.randint(0, 10**13)),
            "method": method,
            "params": params
        }
        to_shovel = self._raw_shovel_var.get()
        if to_shovel:
            wrapped = {
                "method": "notify_to_device",
                "params": {"target_device_sn": self.target_sn}
            }
            wrapped["params"].update(payload)
            payload = wrapped
        prefix = "{}@".format(self._raw_prefix_var.get())
        self._send_msg(prefix + json.dumps(payload).encode(), to_shovel=to_shovel)
        self._update_log("发送报文: {}{} ≤{}".format(
            prefix, json.dumps(payload, ensure_ascii=False),
            CHAIR_SHOVEL_ADDR if to_shovel else CHAIR_SEND_ADDR))

    # ------------------------------------------------------------------
    # 车况回显
    # ------------------------------------------------------------------
    def _format_feedback(self, field, value):
        try:
            if field == "drive_mode":
                v = int(value)
                return CHAIR_DRIVE_STATUS_NAMES.get(v, "未知({})".format(v))
            if field == "gear":
                v = int(value)
                return CHAIR_GEAR_NAMES[v] if 0 <= v <= 3 else str(value)
            if field == "pto":
                v = int(value)
                return CHAIR_PTO_NAMES[v] if 0 <= v <= 2 else str(value)
            if field == "epb":
                v = int(value)
                return "ON(拉起)" if v == 1 else ("OFF(松开)" if v == 0 else str(value))
            if isinstance(value, bool):
                return str(value)
            if isinstance(value, (int, float)):
                return str(round(float(value), 2))
            return str(value)
        except Exception:
            return str(value)

    def _poll_feedback(self):
        try:
            now = time.time()
            if self.last_feedback_time == 0:
                self._heartbeat_var.set("○ 等待车况回传")
                hb_color = "gray"
            else:
                age = now - self.last_feedback_time
                if age < 3:
                    self._heartbeat_var.set("● 车况正常 (回传 {:.1f}s 前)".format(age))
                    hb_color = "green"
                elif age < 10:
                    self._heartbeat_var.set("● 车况延迟 (回传 {:.1f}s 前)".format(age))
                    hb_color = "orange"
                else:
                    self._heartbeat_var.set("● 车况超时 ({:.0f}s 无回传)".format(age))
                    hb_color = "red"
            if hasattr(self, "_heartbeat_label"):
                self._heartbeat_label.config(foreground=hb_color)

            for field, name, fmt in FEEDBACK_FIELDS:
                lab = self._feedback_labels.get(field)
                if lab is None:
                    continue
                if field in self.feedback:
                    lab.config(text="{}: {}".format(name, self._format_feedback(field, self.feedback[field])))
                else:
                    lab.config(text="{}: -".format(name))
        except Exception:
            pass
        if self._running:
            self.root.after(200, self._poll_feedback)


class V2ePage:

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back

        # 控制参数
        self._target = False
        self._controled = False
        self._control_rejected = False
        self._action = 1          # 1=行走, 2=举升
        self._gear = 1            # 1=R, 3=D
        self._move = 0
        self._steering = 0.0
        self._throttle = 0.0
        self._pto = 0
        self._network_latency = 999
        self._running = True

        # UDP socket
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp.bind(("0.0.0.0", V2E_UDP_PORT))

        self._init_socket()

        # GUI 变量
        self._action_var = tk.IntVar(value=1)
        self._gear_var = tk.IntVar(value=1)
        self._steering_var = tk.DoubleVar(value=0.0)
        self._throttle_var = tk.DoubleVar(value=0.0)
        self._pto_var = tk.IntVar(value=0)

        self._create_gui()

    # ------------------------------------------------------------------
    # UDP 通信
    # ------------------------------------------------------------------
    def _init_socket(self):
        recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        recv_thread.start()

        pub_thread = threading.Thread(target=self._pub_loop, daemon=True)
        pub_thread.start()

        cmd_thread = threading.Thread(target=self._publish_cmd_loop, daemon=True)
        cmd_thread.start()

    def _recv_loop(self):
        while self._running:
            try:
                data, addr = self._udp.recvfrom(1024)
                self._msg_callback(data, addr)
            except OSError:
                break
            except Exception:
                time.sleep(0.5)

    def _pub_loop(self):
        while self._running:
            try:
                self._send_rt_message()
            except Exception:
                pass
            time.sleep(0.5)

    def _publish_cmd_loop(self):
        while self._running:
            if self._target != self._controled:
                if self._target:
                    self._control_rejected = False
                    self._controled = True
                    self._send_start_msg()
                else:
                    self._controled = False
                    self._send_stop_msg()

            if self._controled and not self._control_rejected:
                self._send_control_msg()

            time.sleep(0.2)

    def _send_rt_message(self):
        data = {
            "method": "rt_message",
            "params": {
                "sn": V2E_DEVICE_SN,
                "timestamp": time.time(),
                "longitude": 127.0,
                "altitude": 100.0,
                "latitude": 32.0,
                "work_status": 0,
                "localization_valid": 1,
                "roll": 0.0,
                "yaw": 0.0,
                "pitch": 0.0,
                "network_latency": self._network_latency
            }
        }
        self._udp.sendto("1@{}".format(json.dumps(data)).encode(), V2E_SHOVEL_ADDR)

    def _msg_callback(self, data, addr):
        text = data.decode("utf-8")
        for prefix in ["1@", "6@", "7@"]:
            if text.startswith(prefix):
                text = text[len(prefix):]
                break
        recv_data = json.loads(text)
        method = recv_data.get("method", "")
        params = recv_data.get("params", {})

        if method == "network_latency":
            res = {
                "id": recv_data.get("id", ""),
                "method": "network_latency_res",
                "params": {
                    "t": params["t"],
                    "r": time.time()
                }
            }
            if "source_sn" not in params:
                self._udp.sendto("7@{}".format(json.dumps(res)).encode(), addr)
            else:
                send_data = {
                    "method": "notify_to_device",
                    "params": {
                        "target_device_sn": V2E_TARGET_SN,
                    }
                }
                send_data["params"].update(res)
                send_data["params"]["params"].update({
                    "sn": V2E_TARGET_SN,
                    "source_sn": V2E_DEVICE_SN
                })
                self._udp.sendto("1@{}".format(json.dumps(send_data)).encode(), addr)

        elif method == "rt_message_ack":
            self._network_latency = (time.time() - params["timestamp"]) * 1000

        else:
            self._on_business_msg(recv_data, addr)

    def _on_business_msg(self, data, addr):
        method = data.get("method", "")
        params = data.get("params", {})

        self._update_log("收到消息: method={}, params={}".format(
            method, json.dumps(params, ensure_ascii=False) if params else "{}"))

        if method == "robotruck_alarm_infomation":
            code = params.get("code", 0)
            msg = params.get("msg", "")
            if code == 0:
                self._control_rejected = False
                self._reject_reason = ""
                self._reject_reason_var.set("")
                self._update_log("允许控制: {}".format(msg))
                if self._target:
                    self._controled = True
                    self._update_status("控制中", "green")
            elif code == 1:
                self._control_rejected = True
                self._controled = False
                self._target = False
                self._reject_reason = msg
                self._ctrl_var.set(False)
                self._update_status("不允许控制", "red")
                self._reject_reason_var.set("拒绝原因: {}".format(msg))
                self._update_log("不允许控制: {}".format(msg), "error")
            else:
                self._update_log("{}: {}".format(code, msg))

        elif method == "v2e_start_adjust_position_res":
            if params.get("result", 0) != 0:
                self._control_rejected = True
                self._controled = False
                self._target = False
                self._ctrl_var.set(False)
                self._update_status("被拒绝", "red")
                self._update_log("控制被拒绝: {}".format(
                    params.get("msg", "车辆状态不符")), "error")

    def _use_shovel_forward(self, data):
        send_data = {
            "method": "notify_to_device",
            "params": {
                "target_device_sn": V2E_TARGET_SN
            }
        }
        send_data["params"].update(data)
        send_data["params"]["params"].update({
            "sn": V2E_TARGET_SN,
            "source_sn": V2E_DEVICE_SN
        })
        return send_data

    def _send_start_msg(self):
        data = {
            "method": "v2e_start_adjust_position",
            "params": {
                "timestamp": time.time(),
                "sn": V2E_TARGET_SN
            }
        }
        data = self._use_shovel_forward(data)
        self._udp.sendto("1@{}".format(json.dumps(data)).encode(), V2E_SHOVEL_ADDR)

    def _send_stop_msg(self):
        data = {
            "method": "v2e_stop_adjust_position",
            "params": {}
        }
        data = self._use_shovel_forward(data)
        self._udp.sendto("1@{}".format(json.dumps(data)).encode(), V2E_SHOVEL_ADDR)

    def _send_control_msg(self):
        data = {"method": "v2e_adjusting_position"}

        if self._action == 1:
            data["params"] = {
                "timestamp": time.time(),
                "move": self._move,
                "gear": self._gear,
                "throttle": self._throttle,
                "steering": self._steering,
                "action": 1,
            }
        elif self._action == 2:
            data["params"] = {
                "timestamp": time.time(),
                "pto": self._pto,
                "throttle": self._throttle,
                "action": 2,
            }
        data = self._use_shovel_forward(data)
        self._udp.sendto("1@{}".format(json.dumps(data)).encode(), V2E_SHOVEL_ADDR)

    def _cleanup(self):
        self._target = False
        self._controled = False
        self._running = False
        try:
            self._udp.close()
        except Exception:
            pass
        self._update_log("资源已清理")

    # ------------------------------------------------------------------
    # GUI
    # ------------------------------------------------------------------
    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        # ---------- 标题栏 ----------
        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        self._back_btn = ttk.Button(title_frame, text="← 返回首页", command=self._on_back)
        self._back_btn.pack(side=tk.LEFT)
        ttk.Label(title_frame, text="V2E 控车",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        self._status_label = ttk.Label(title_frame, text="状态: 未控制",
                                       foreground="red", font=("", 10, "bold"))
        self._status_label.pack(side=tk.RIGHT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ============================================================
        # 设置
        # ============================================================
        settings_frame = ttk.LabelFrame(body, text="设置", padding="12 8 12 8")
        settings_frame.pack(fill=tk.X, padx=12, pady=6)

        ctrl_frame = ttk.Frame(settings_frame)
        ctrl_frame.pack(fill=tk.X, pady=6)
        ttk.Label(ctrl_frame, text="控制模式:", width=10).pack(side=tk.LEFT)
        self._ctrl_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl_frame, text="开始控制", variable=self._ctrl_var,
                        command=self._on_ctrl_change).pack(side=tk.LEFT, padx=10)

        self._reject_reason_var = tk.StringVar(value="")
        ttk.Label(settings_frame, textvariable=self._reject_reason_var,
                  foreground="red", wraplength=760).pack(fill=tk.X, pady=2)

        action_frame = ttk.Frame(settings_frame)
        action_frame.pack(fill=tk.X, pady=6)
        ttk.Label(action_frame, text="动作模式:", width=10).pack(side=tk.LEFT)
        ttk.Radiobutton(action_frame, text="行走", variable=self._action_var, value=1,
                        command=self._on_action_change).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(action_frame, text="举升", variable=self._action_var, value=2,
                        command=self._on_action_change).pack(side=tk.LEFT, padx=10)

        # ============================================================
        # 控制指令 - 行走
        # ============================================================
        self._move_frame = ttk.LabelFrame(body, text="控制指令 - 行走", padding="12 8 12 8")
        self._move_frame.pack(fill=tk.X, padx=12, pady=6)

        gear_frame = ttk.Frame(self._move_frame)
        gear_frame.pack(fill=tk.X, pady=8)
        ttk.Label(gear_frame, text="挡位:", width=10).pack(side=tk.LEFT)
        ttk.Radiobutton(gear_frame, text="R", variable=self._gear_var, value=1,
                        command=self._on_gear_change).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(gear_frame, text="D", variable=self._gear_var, value=3,
                        command=self._on_gear_change).pack(side=tk.LEFT, padx=10)

        move_btn_frame = ttk.Frame(self._move_frame)
        move_btn_frame.pack(fill=tk.X, pady=8)
        ttk.Label(move_btn_frame, text="移动:", width=10).pack(side=tk.LEFT)
        self._move_btn = ttk.Button(move_btn_frame, text="启动移动",
                                    command=self._on_move_toggle)
        self._move_btn.pack(side=tk.LEFT, padx=10)

        steer_frame = ttk.Frame(self._move_frame)
        steer_frame.pack(fill=tk.X, pady=8)
        ttk.Label(steer_frame, text="转向:", width=10).pack(side=tk.LEFT)
        ttk.Scale(steer_frame, from_=100, to=-100, variable=self._steering_var,
                  command=self._on_steering_change, orient=tk.HORIZONTAL,
                  length=320).pack(side=tk.LEFT, padx=10)
        self._steering_label = ttk.Label(steer_frame, text="0.000", width=8)
        self._steering_label.pack(side=tk.LEFT)
        ttk.Button(steer_frame, text="归0", width=4,
                   command=self._on_steering_zero).pack(side=tk.LEFT, padx=5)
        ttk.Label(steer_frame, text="左正 右负", foreground="gray").pack(side=tk.LEFT, padx=5)

        thr_frame = ttk.Frame(self._move_frame)
        thr_frame.pack(fill=tk.X, pady=8)
        ttk.Label(thr_frame, text="油门:", width=10).pack(side=tk.LEFT)
        ttk.Scale(thr_frame, from_=0, to=100, variable=self._throttle_var,
                  command=self._on_throttle_change, orient=tk.HORIZONTAL,
                  length=320).pack(side=tk.LEFT, padx=10)
        self._throttle_label = ttk.Label(thr_frame, text="0.000", width=8)
        self._throttle_label.pack(side=tk.LEFT)

        # ============================================================
        # 控制指令 - 举升
        # ============================================================
        self._lift_frame = ttk.LabelFrame(body, text="控制指令 - 举升", padding="12 8 12 8")

        pto_frame = ttk.Frame(self._lift_frame)
        pto_frame.pack(fill=tk.X, pady=8)
        ttk.Label(pto_frame, text="货厢控制:", width=10).pack(side=tk.LEFT)
        ttk.Radiobutton(pto_frame, text="保持", variable=self._pto_var, value=0,
                        command=self._on_pto_change).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(pto_frame, text="上升", variable=self._pto_var, value=1,
                        command=self._on_pto_change).pack(side=tk.LEFT, padx=10)
        ttk.Radiobutton(pto_frame, text="下降", variable=self._pto_var, value=2,
                        command=self._on_pto_change).pack(side=tk.LEFT, padx=10)

        thr2_frame = ttk.Frame(self._lift_frame)
        thr2_frame.pack(fill=tk.X, pady=8)
        ttk.Label(thr2_frame, text="油门:", width=10).pack(side=tk.LEFT)
        ttk.Scale(thr2_frame, from_=0, to=100, variable=self._throttle_var,
                  command=self._on_throttle_change, orient=tk.HORIZONTAL,
                  length=320).pack(side=tk.LEFT, padx=10)
        self._throttle_label2 = ttk.Label(thr2_frame, text="0.000", width=8)
        self._throttle_label2.pack(side=tk.LEFT)

        # ============================================================
        # 日志
        # ============================================================
        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_frame = log_frame
        self._log_text = tk.Text(log_frame, height=8, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("info", foreground="#1e6fd9")

        self._update_log("V2E 控车页面已启动")

    # ------------------------------------------------------------------
    # 日志
    # ------------------------------------------------------------------
    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _update_status(self, text, color):
        self._status_label.config(text="状态: {}".format(text), foreground=color)

    # ------------------------------------------------------------------
    # 事件回调
    # ------------------------------------------------------------------
    def _on_back(self):
        self._cleanup()
        self.on_back()

    def _on_ctrl_change(self):
        self._target = self._ctrl_var.get()
        if self._target:
            self._control_rejected = False
            self._update_status("控制中", "green")
        else:
            self._update_status("未控制", "red")
        self._back_btn.config(state=tk.DISABLED if self._target else tk.NORMAL)
        self._update_log("{}控制".format("开始" if self._target else "结束"))

    def _on_action_change(self):
        self._action = self._action_var.get()
        if self._action == 1:
            self._move_frame.pack(fill=tk.X, padx=12, pady=6, before=self._log_frame)
            self._lift_frame.pack_forget()
            self._update_log("动作模式切换至: 行走")
        else:
            self._lift_frame.pack(fill=tk.X, padx=12, pady=6, before=self._log_frame)
            self._move_frame.pack_forget()
            self._update_log("动作模式切换至: 举升")

    def _on_gear_change(self):
        self._gear = self._gear_var.get()
        self._update_log("挡位切换至: {}".format("R" if self._gear == 1 else "D"))

    def _on_move_toggle(self):
        self._move = 1 - self._move
        btn_text = "停止移动" if self._move else "启动移动"
        self._move_btn.config(text=btn_text)
        self._update_log("{}移动".format("开始" if self._move else "停止"))

    def _on_steering_change(self, value):
        val = round(float(value), 3)
        self._steering = val
        self._steering_label.config(text="{:.3f}".format(val))

    def _on_steering_zero(self):
        self._steering_var.set(0.0)
        self._steering = 0.0
        self._steering_label.config(text="0.000")

    def _on_throttle_change(self, value):
        val = round(float(value), 3)
        self._throttle = val
        self._throttle_label.config(text="{:.3f}".format(val))
        self._throttle_label2.config(text="{:.3f}".format(val))

    def _on_pto_change(self):
        self._pto = self._pto_var.get()
        pto_names = ["保持", "上升", "下降"]
        self._update_log("货厢动作: {}".format(pto_names[self._pto]))


class FaultPage:

    """ 故障模拟页 - 汇总 mock_vehicle 的全部模拟方法:
    1) change_status  (k:v;k:v 设置车辆反馈位)
    2) change_mock_status (JSON setattr, 可写任意私有属性 _MockVehicle__xxx)
    让车辆反馈命中 decision_center 判定后自然触发故障上报 """

    FAULTS = [
        ("303086", "排土位附近俯仰角过大", {
            "_MockVehicle__pitch": -8.0
        }, "TO_DUMP 且距排土点<5m 时, pitch<-5° 触发 (running_task.py:397)"),
        ("303024", "带斗行车", {
            "_MockVehicle__liftAngle": 16.0
        }, "行车中 lift_angle>=15° 触发 (running_task.py:409)"),
        ("301074", "货箱未达到下止点", {
            "_MockVehicle__liftAngle": 5.0
        }, "需 guardian.enable_lift_limiter=true, 且 lift_angle>=2° 持续3s (running_task.py:421)"),
        ("311001", "卸料完成后超时未收到新的任务", None,
         "纯云端时序: 卸料完成(send_finish_unload)后 30s 未下发新任务 (running_task.py:749)"),
    ]

    STATUS_SIM = [
        ("驾驶模式", "d", "int", 2),
        ("油量 fl", "fl", "float", 50.0),
        ("举升故障 l", "l", "bit", 0),
        ("刹车故障 b", "b", "bit", 0),
        ("转向故障 s", "s", "bit", 0),
        ("手刹故障 e", "e", "bit", 0),
        ("变速箱故障", "t", "bit", 0),
        ("发动机故障", "en", "bit", 0),
        ("PDC等级 pd", "pd", "int", 0),
        ("整车等级 ve", "ve", "int", 0),
        ("雨棚展开", "cu", "bit", 0),
        ("雨棚折叠", "cf", "bit", 0),
        ("油门 throttle", "throttle_pos", "frac", 0.0),
        ("速度 speed", "speed", "frac", 0.0),
        ("转速 es", "es", "frac", 600.0),
        ("定位 lv", "lv", "int", 1),
        ("相机心跳", "cv", "bit", 1),
        ("DTU心跳 sv", "sv", "bit", 1),
        ("胎压 tpms", "tpms", "tpms", 780.0),
        ("液温 en_cool_temp", "en_cool_temp", "temp", 50.0),
        ("主正1温度", "main_pos_relay1_temp", "temp", 50.0),
        ("主正2温度", "main_pos_relay2_temp", "temp", 50.0),
        ("主负1温度", "main_neg_relay1_temp", "temp", 50.0),
        ("主负2温度", "main_neg_relay2_temp", "temp", 50.0),
        ("SOC soc", "soc", "frac", 100.0),
    ]

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self._ros_node = None
        self._status_pub = None
        self._mock_pub = None
        self._ros_ok = False
        self._running = True
        self._status_vars = {}
        self._status_defaults = {}

        self._status_var = tk.StringVar(value="ROS 未初始化")
        self._log_text = None

        self._init_ros()
        self._create_gui()

    def _init_ros(self):
        try:
            import rclpy
            from std_msgs.msg import String
            if not rclpy.ok():
                rclpy.init()
            self._ros_node = rclpy.create_node("mock_tools_fault")
            self._status_pub = self._ros_node.create_publisher(
                String, "/mock_truck/change_status", 10
            )
            self._mock_pub = self._ros_node.create_publisher(
                String, "/mock_truck/change_mock_status", 10
            )
            self._String = String
            self._ros_ok = True
            self._status_var.set("ROS 已连接 /mock_truck/change_status")
        except Exception as e:
            self._status_var.set("ROS 不可用: {}".format(e))

    def _publish(self, topic, data_str):
        if not self._ros_ok or self._ros_node is None:
            self._update_log("ROS 未连接, 无法发布", tag="error")
            return
        try:
            msg = self._String()
            msg.data = data_str
            pub = self._status_pub if topic == "status" else self._mock_pub
            pub.publish(msg)
            self._update_log("发布 {}: {}".format(topic, data_str))
        except Exception as e:
            self._update_log("发布失败: {}".format(e), tag="error")

    def _publish_status(self, kv_str):
        self._publish("status", kv_str)

    def _publish_mock(self, kv):
        import json as _json
        self._publish("mock", _json.dumps(kv))

    def _trigger(self, idx):
        self._update_log("触发故障: {}".format(self.FAULTS[idx][0]), tag="info")
        kv = self.FAULTS[idx][2]
        if kv is not None:
            self._publish_mock(kv)
        else:
            self._update_log("311001 无法直接触发, 需跑完整 dump 任务且不回复新任务",
                             tag="error")

    def _restore(self):
        self._update_log("恢复 pitch / lift_angle 为 0", tag="info")
        self._publish_mock({
            "_MockVehicle__pitch": 0.0,
            "_MockVehicle__liftAngle": 0.0,
        })

    def _send_status_item(self, key, override=None):
        var = self._status_vars.get(key)
        if var is None:
            self._update_log("未找到控件: {}".format(key), tag="error")
            return
        value = str(override) if override is not None else var.get().strip()
        item = next((i for i in self.STATUS_SIM if i[1] == key), None)
        if item is None:
            return
        kind = item[2]
        if kind == "tpms" and value in ("0", "780"):
            self._publish_status("{}:{}".format(key, value))
            return
        try:
            if kind in ("int", "bit", "temp"):
                float(value)
            self._publish_status("{}:{}".format(key, value))
        except Exception:
            self._update_log("数值无效: {}={}".format(key, value), tag="error")

    def _reset_status_item(self, key):
        var = self._status_vars.get(key)
        default = self._status_defaults.get(key)
        if var is not None and default is not None:
            var.set(str(default))
            self._update_log("复位(仅改输入框): {}".format(key))

    def _reset_all_status(self):
        for key, default in self._status_defaults.items():
            var = self._status_vars.get(key)
            if var is not None:
                var.set(str(default))
        self._update_log("全部输入框复位为默认值(未发送)")

    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        # ---------- 标题栏 ----------
        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        self._back_btn = ttk.Button(title_frame, text="← 返回首页", command=self._on_back)
        self._back_btn.pack(side=tk.LEFT)
        ttk.Label(title_frame, text="故障模拟",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        self._status_label = ttk.Label(title_frame, textvariable=self._status_var,
                                       foreground="green", font=("", 10, "bold"))
        self._status_label.pack(side=tk.RIGHT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ============================================================
        # 说明
        # ============================================================
        tip_frame = ttk.LabelFrame(body, text="说明", padding="12 8 12 8")
        tip_frame.pack(fill=tk.X, padx=12, pady=6)
        tip_text = (
            "原理: 故障由 decision_center 检测并上报, 直接发故障码无效。\n"
            "本页汇总 mock_vehicle 全部模拟方法: ①车辆反馈模拟(change_status) ②通用属性改写(change_mock_status)。\n"
            "改写 pitch / lift_angle 等反馈让 DC 命中判定后自然触发; 触发需在对应任务状态下生效。\n"
            "mock_vehicle 私有属性经名称修饰, JSON 键需用 _MockVehicle__pitch / _MockVehicle__liftAngle。"
        )
        ttk.Label(tip_frame, text=tip_text, foreground="#555",
                  justify=tk.LEFT, wraplength=820).pack(anchor=tk.W)

        # ============================================================
        # 一键触发故障
        # ============================================================
        fault_frame = ttk.LabelFrame(body, text="一键触发故障 (组合场景)",
                                     padding="12 8 12 8")
        fault_frame.pack(fill=tk.X, padx=12, pady=6)
        for idx, (code, name, kv, desc) in enumerate(self.FAULTS):
            f = ttk.Frame(fault_frame)
            f.pack(fill=tk.X, pady=4)
            ttk.Button(f, text=name, width=26,
                       command=lambda i=idx: self._trigger(i)).pack(side=tk.LEFT)
            ttk.Label(f, text="[{}] {}".format(code, desc),
                      foreground="gray").pack(side=tk.LEFT, padx=8)

        restore_frame = ttk.Frame(fault_frame)
        restore_frame.pack(fill=tk.X, pady=4)
        ttk.Button(restore_frame, text="恢复正常 (pitch=0, lift_angle=0)",
                   command=self._restore).pack(side=tk.LEFT, padx=4)

        # ============================================================
        # 车辆反馈模拟
        # ============================================================
        sim_frame = ttk.LabelFrame(
            body, text="车辆反馈模拟 (/mock_truck/change_status 全部方法)",
            padding="12 8 12 8")
        sim_frame.pack(fill=tk.X, padx=12, pady=6)

        top = ttk.Frame(sim_frame)
        top.pack(fill=tk.X, pady=(0, 6))
        ttk.Button(top, text="全部复位", width=10,
                   command=self._reset_all_status).pack(side=tk.LEFT)
        ttk.Label(top, text="bit 项直接点 1/0 即发送; 其他项填值后点【发送】",
                  foreground="gray").pack(side=tk.LEFT, padx=8)

        COLS = 3
        grid_wrap = ttk.Frame(sim_frame)
        grid_wrap.pack(fill=tk.X)
        for idx, (name, key, kind, default) in enumerate(self.STATUS_SIM):
            r, c = idx // COLS, idx % COLS
            cell = ttk.Frame(grid_wrap)
            cell.grid(row=r, column=c, sticky="we", padx=8, pady=3)

            ttk.Label(cell, text=name, anchor="w").grid(row=0, column=0, sticky="w")
            var = tk.StringVar(value=str(default))
            self._status_vars[key] = var
            self._status_defaults[key] = str(default)
            ttk.Entry(cell, textvariable=var, width=8).grid(
                row=0, column=1, sticky="w", padx=3)

            col = 2
            if kind == "bit":
                ttk.Button(cell, text="1", width=3,
                           command=lambda k=key: self._send_status_item(k, "1")
                           ).grid(row=0, column=col, padx=1); col += 1
                ttk.Button(cell, text="0", width=3,
                           command=lambda k=key: self._send_status_item(k, "0")
                           ).grid(row=0, column=col, padx=1); col += 1
            ttk.Button(cell, text="发送", width=5,
                       command=lambda k=key: self._send_status_item(k)
                       ).grid(row=0, column=col, padx=1); col += 1
            ttk.Button(cell, text="复位", width=5,
                       command=lambda k=key: self._reset_status_item(k)
                       ).grid(row=0, column=col, padx=1); col += 1
            if kind == "tpms":
                ttk.Label(cell, text="0低/780常", foreground="gray").grid(
                    row=0, column=col, padx=3)

        for c in range(COLS):
            grid_wrap.columnconfigure(c, weight=1, uniform="status")

        # ============================================================
        # 通用属性改写
        # ============================================================
        gen_frame = ttk.LabelFrame(
            body, text="通用属性改写 (/mock_truck/change_mock_status JSON setattr)",
            padding="12 8 12 8")
        gen_frame.pack(fill=tk.X, padx=12, pady=6)

        gen_r1 = ttk.Frame(gen_frame)
        gen_r1.pack(fill=tk.X, pady=4)
        ttk.Label(gen_r1, text="属性名(可写 _MockVehicle__xxx 私有属性):",
                  width=36).pack(side=tk.LEFT)
        self._gen_key_var = tk.StringVar(value="_MockVehicle__pitch")
        ttk.Entry(gen_r1, textvariable=self._gen_key_var, width=30).pack(side=tk.LEFT, padx=5)

        gen_r2 = ttk.Frame(gen_frame)
        gen_r2.pack(fill=tk.X, pady=4)
        ttk.Label(gen_r2, text="新值:", width=36).pack(side=tk.LEFT)
        self._gen_val_var = tk.StringVar(value="-8.0")
        ttk.Entry(gen_r2, textvariable=self._gen_val_var, width=30).pack(side=tk.LEFT, padx=5)
        ttk.Button(gen_r2, text="发送", width=8,
                   command=self._send_generic).pack(side=tk.LEFT, padx=6)

        quick_label = ttk.Label(gen_frame, text="常用属性:  ", foreground="gray")
        quick_label.pack(anchor=tk.W, pady=(6, 2))
        QUICK_KEYS = [
            ("pitch", "_MockVehicle__pitch", "-8.0"),
            ("liftAngle", "_MockVehicle__liftAngle", "16.0"),
            ("roll", "_MockVehicle__roll", "-8.0"),
            ("speed", "_MockVehicle__speed", "3.5"),
            ("fuelLevel", "_MockVehicle__fuelLevel", "10.0"),
            ("soc", "_MockVehicle__soc", "15.0"),
            ("tpms_pressure", "_MockVehicle__tpms_pressure", "0.0"),
            ("engineCoolWaterTemperature", "_MockVehicle__engineCoolWaterTemperature", "130.0"),
            ("localizationState", "_MockVehicle__localizationState", "2"),
            ("vcuState", "_MockVehicle__vcuState", "0"),
            ("cameraState", "_MockVehicle__cameraState", "0"),
            ("softDtuState", "_MockVehicle__softDtuState", "0"),
            ("epb", "_MockVehicle__epb", "1"),
            ("gear", "_MockVehicle__gear", "1"),
        ]
        qf = ttk.Frame(gen_frame)
        qf.pack(fill=tk.X, pady=2)
        for idx, (label, key, val) in enumerate(QUICK_KEYS):
            ttk.Button(qf, text=label, width=10,
                       command=lambda k=key, v=val: self._gen_quick(k, v)).grid(
                           row=idx // 4, column=idx % 4, sticky="w", padx=3, pady=2)

        # ============================================================
        # 发布日志
        # ============================================================
        log_frame = ttk.LabelFrame(body, text="发布日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=8, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("info", foreground="#1e6fd9")

        self._update_log("故障模拟页面已启动")

    # ------------------------------------------------------------------
    # 通用属性改写
    # ------------------------------------------------------------------
    def _send_generic(self):
        key = self._gen_key_var.get().strip()
        value = self._gen_val_var.get().strip()
        if not key:
            self._update_log("属性名不能为空", tag="error")
            return
        try:
            num = float(value)
            v = num if (num.is_integer() and key.endswith("State")) else num
        except Exception:
            try:
                v = int(value)
            except Exception:
                v = value
        self._publish_mock({key: v})

    def _gen_quick(self, key, value):
        self._gen_key_var.set(key)
        self._gen_val_var.set(value)
        self._send_generic()

    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
        self._log_text.see(tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _on_back(self):
        self._running = False
        self._cleanup()
        self.on_back()

    def _cleanup(self):
        try:
            if self._ros_node is not None:
                self._ros_node.destroy_node()
        except Exception:
            pass
        try:
            import rclpy
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


class LightSender:

    """ 交通灯 UDP 发送器 (1@ rt_message) """

    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.target_ip = LIGHT_DEFAULT_TARGET_IP
        self.target_port = LIGHT_DEFAULT_TARGET_PORT
        self.device_list = []
        self.device_state = {}

    def configure(self, ip, port, devices):
        self.target_ip = ip
        self.target_port = port
        self.device_list = list(devices)
        new_state = {}
        for sn in self.device_list:
            new_state[sn] = self.device_state.get(sn, LIGHT_OFF)
        self.device_state = new_state

    def build_msg(self, sn, light_state):
        ts = math.floor(time.time())
        content = (
            '1@{"method": "rt_message", "params": '
            '{"sn": "%s", "light_state": %d, "timestamp": %d}}' % (sn, light_state, ts)
        )
        return content.encode("utf-8")

    def send_one(self, sn, light_state):
        data = self.build_msg(sn, light_state)
        try:
            self.sock.sendto(data, (self.target_ip, self.target_port))
        except Exception as e:
            print("发送失败:", e)

    def send_all(self):
        for sn, st in self.device_state.items():
            self.send_one(sn, st)

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


class LightPage:

    """ 交通灯控制页 - 手动 / 计时，多灯独立 """

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self.sender = LightSender()

        self._running = True
        self.sending = False
        self.timer_mode = False
        self.lock = threading.Lock()

        self.red_dur = LIGHT_DEFAULT_RED
        self.green_dur = LIGHT_DEFAULT_GREEN
        self.yellow_dur = LIGHT_DEFAULT_YELLOW

        self.timer_phase_index = 0
        self.timer_phase_start = 0.0
        self.timer_phase_applied = False

        self.device_timer_enabled = {}
        self.device_timer_flags = {}
        self.device_widgets = {}
        self._ui_q = queue.Queue()
        self._log_text = None
        self._status_var = tk.StringVar(value="就绪")

        self._create_gui()
        self._apply_config(first_time=True)
        self._start_send_thread()
        self._start_timer_thread()
        self._ui_poller()

    # ================================ UI ================================
    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        # ---------- 标题栏 ----------
        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        self._back_btn = ttk.Button(title_frame, text="← 返回首页", command=self._on_back)
        self._back_btn.pack(side=tk.LEFT)
        ttk.Label(title_frame, text="交通灯控制",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        ttk.Label(title_frame, text="手动 / 计时 · 多灯独立",
                  foreground="#888").pack(side=tk.LEFT)
        self._status_label = ttk.Label(title_frame, textvariable=self._status_var,
                                       foreground="gray", font=("", 10, "bold"))
        self._status_label.pack(side=tk.RIGHT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ---------- 配置 ----------
        cfg = ttk.LabelFrame(body, text="配置", padding="12 8 12 8")
        cfg.pack(fill=tk.X, padx=12, pady=6)

        row1 = ttk.Frame(cfg); row1.pack(fill=tk.X, pady=4)
        ttk.Label(row1, text="目标IP:").pack(side="left")
        self.ip_var = tk.StringVar(value=LIGHT_DEFAULT_TARGET_IP)
        ttk.Entry(row1, textvariable=self.ip_var, width=20).pack(side="left", padx=5)
        ttk.Label(row1, text="端口:").pack(side="left", padx=(15, 0))
        self.port_var = tk.StringVar(value=str(LIGHT_DEFAULT_TARGET_PORT))
        ttk.Entry(row1, textvariable=self.port_var, width=8).pack(side="left", padx=5)
        ttk.Label(row1, text="发送间隔(秒):").pack(side="left", padx=(15, 0))
        self.interval_var = tk.StringVar(value=LIGHT_DEFAULT_INTERVAL)
        ttk.Entry(row1, textvariable=self.interval_var, width=5).pack(side="left", padx=5)

        row2 = ttk.Frame(cfg); row2.pack(fill=tk.X, pady=4)
        ttk.Label(row2, text="设备SN列表(每行一个):").pack(side="left", anchor="n")
        self.devices_text = tk.Text(row2, height=4, width=40,
                                    font=("Consolas", 9))
        self.devices_text.pack(side="left", padx=5)
        self.devices_text.insert("1.0", LIGHT_DEFAULT_DEVICE_LIST)

        row3 = ttk.Frame(cfg); row3.pack(fill=tk.X, pady=4)
        ttk.Label(row3, text="红灯(秒):").pack(side="left")
        self.red_var = tk.StringVar(value=str(LIGHT_DEFAULT_RED))
        ttk.Entry(row3, textvariable=self.red_var, width=6).pack(side="left", padx=5)
        ttk.Label(row3, text="绿灯(秒):").pack(side="left", padx=(15, 0))
        self.green_var = tk.StringVar(value=str(LIGHT_DEFAULT_GREEN))
        ttk.Entry(row3, textvariable=self.green_var, width=6).pack(side="left", padx=5)
        ttk.Label(row3, text="黄灯(秒):").pack(side="left", padx=(15, 0))
        self.yellow_var = tk.StringVar(value=str(LIGHT_DEFAULT_YELLOW))
        ttk.Entry(row3, textvariable=self.yellow_var, width=6).pack(side="left", padx=5)
        ttk.Button(row3, text="应用配置", command=self._apply_config).pack(side="left", padx=15)

        # ---------- 全局控制 ----------
        top = ttk.LabelFrame(body, text="全局控制 (所有设备)", padding="12 8 12 8")
        top.pack(fill=tk.X, padx=12, pady=6)
        ttk.Button(top, text="全部绿灯", command=lambda: self._set_all(LIGHT_GREEN)).pack(side="left", padx=5, pady=5)
        ttk.Button(top, text="全部红灯", command=lambda: self._set_all(LIGHT_RED)).pack(side="left", padx=5, pady=5)
        ttk.Button(top, text="全部黄灯", command=lambda: self._set_all(LIGHT_YELLOW)).pack(side="left", padx=5, pady=5)
        ttk.Button(top, text="全部关灯", command=lambda: self._set_all(LIGHT_OFF)).pack(side="left", padx=5, pady=5)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)
        self._btn_send = ttk.Button(top, text="开始发送", command=self._toggle_send)
        self._btn_send.pack(side="left", padx=5)

        # ---------- 计时模式 ----------
        mode = ttk.LabelFrame(body, text="计时模式", padding="12 8 12 8")
        mode.pack(fill=tk.X, padx=12, pady=6)
        self._btn_timer = ttk.Button(mode, text="开始计时", command=self._toggle_timer)
        self._btn_timer.pack(side="left", padx=10, pady=5)
        self._timer_info_var = tk.StringVar(value="计时未启动")
        ttk.Label(mode, textvariable=self._timer_info_var).pack(side="left", padx=10)
        ttk.Label(mode, text="(勾选下方设备右侧「参与计时」即可加入循环)",
                  foreground="#888").pack(side="left", padx=15)

        # ---------- 设备列表 ----------
        dev_frame = ttk.LabelFrame(body, text="设备列表 (每个灯独立控制)",
                                   padding="12 8 12 8")
        dev_frame.pack(fill=tk.X, padx=12, pady=6)
        self.device_container = ttk.Frame(dev_frame)
        self.device_container.pack(fill=tk.X, padx=5, pady=5)

        # ---------- 日志 ----------
        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=8, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")

        self._update_log("交通灯控制页已启动")

        self.devices_text.bind("<<Modified>>", self._on_devices_edited)

    # ============================== 实时同步 ==============================
    def _on_devices_edited(self, event=None):
        try:
            if not self.devices_text.edit_modified():
                return
            self.devices_text.edit_modified(False)
            self._sync_devices_from_text()
        except Exception:
            pass

    def _sync_devices_from_text(self):
        devices = [line.strip() for line in
                   self.devices_text.get("1.0", "end").splitlines() if line.strip()]
        with self.lock:
            old_state = self.sender.device_state
            new_state = {}
            for sn in devices:
                new_state[sn] = old_state.get(sn, LIGHT_OFF)
            self.sender.device_state = new_state
            self.sender.device_list = list(devices)

        new_enabled = {}
        new_flags = {}
        for sn in devices:
            if sn in self.device_timer_enabled:
                new_enabled[sn] = self.device_timer_enabled[sn]
            else:
                new_enabled[sn] = tk.BooleanVar(value=True)
            new_flags[sn] = bool(self.device_timer_flags.get(sn, True))
        self.device_timer_enabled = new_enabled
        self.device_timer_flags = new_flags

        self._rebuild_device_rows()

    # ============================== 配置 ==============================
    def _apply_config(self, first_time=False):
        ip = self.ip_var.get().strip()
        if not ip:
            self._update_log("配置错误: 目标IP不能为空", tag="error")
            return
        try:
            port = int(self.port_var.get().strip())
        except ValueError:
            self._update_log("配置错误: 端口必须是整数", tag="error")
            return
        devices = [line.strip() for line in self.devices_text.get("1.0", "end").splitlines() if line.strip()]
        if not devices:
            self._update_log("配置错误: 设备列表不能为空", tag="error")
            return
        try:
            red = int(self.red_var.get().strip())
            green = int(self.green_var.get().strip())
            yellow = int(self.yellow_var.get().strip())
        except ValueError:
            self._update_log("配置错误: 红/绿/黄持续时间必须是整数", tag="error")
            return

        self.red_dur = red
        self.green_dur = green
        self.yellow_dur = yellow
        self._send_interval = self._parse_interval()

        with self.lock:
            self.sender.configure(ip, port, devices)

        new_enabled = {}
        new_flags = {}
        for sn in devices:
            if sn in self.device_timer_enabled:
                new_enabled[sn] = self.device_timer_enabled[sn]
            else:
                new_enabled[sn] = tk.BooleanVar(value=True)
            new_flags[sn] = bool(self.device_timer_flags.get(sn, True))
        self.device_timer_enabled = new_enabled
        self.device_timer_flags = new_flags

        self._rebuild_device_rows()
        self._update_log("配置已应用: IP={} 端口={} 设备数={} 红={}s 绿={}s 黄={}s".format(
            ip, port, len(devices), red, green, yellow))
        if first_time:
            self._status_var.set("配置已加载，请点「开始发送」再点「开始计时」")

    def _rebuild_device_rows(self):
        for w in self.device_container.winfo_children():
            w.destroy()
        self.device_widgets.clear()

        # 表头
        header = ttk.Frame(self.device_container)
        header.pack(fill=tk.X, padx=5, pady=(0, 6))
        tk.Label(header, text="设备SN", width=22, anchor="w",
                 font=("", 9, "bold")).pack(side="left")
        tk.Label(header, text="当前", width=6,
                 font=("", 9, "bold")).pack(side="left", padx=8)
        tk.Label(header, text="手动切换",
                 font=("", 9, "bold")).pack(side="left", padx=4)
        tk.Label(header, text="参与计时", width=8,
                 font=("", 9, "bold")).pack(side="right", padx=10)

        for sn in self.sender.device_list:
            row = ttk.Frame(self.device_container, padding="4 4 4 4")
            row.pack(fill=tk.X, padx=2, pady=2)

            tk.Label(row, text=sn, width=22, anchor="w").pack(side="left")

            st0 = self.sender.device_state.get(sn, LIGHT_OFF)
            state_lbl = tk.Label(row, text=LIGHT_STATE_NAME[st0], width=6,
                                 bg=LIGHT_STATE_COLOR[st0], fg="white",
                                 relief="flat", bd=0)
            state_lbl.pack(side="left", padx=8, ipady=2)

            for st in (LIGHT_GREEN, LIGHT_RED, LIGHT_YELLOW, LIGHT_OFF):
                tk.Button(row, text=LIGHT_STATE_NAME[st], width=6,
                          bg=LIGHT_STATE_COLOR[st],
                          fg="white" if st != LIGHT_YELLOW else "black",
                          relief="flat", bd=0,
                          activebackground=LIGHT_STATE_COLOR[st],
                          cursor="hand2",
                          command=lambda s=sn, st=st: self._set_device(s, st)
                          ).pack(side="left", padx=3, ipady=2)

            cb = ttk.Checkbutton(row, variable=self.device_timer_enabled[sn],
                                 command=lambda s=sn: self._on_timer_check(s))
            cb.pack(side="right", padx=10)

            self.device_widgets[sn] = {"state_label": state_lbl}

    def _on_timer_check(self, sn):
        v = self.device_timer_enabled[sn].get()
        self.device_timer_flags[sn] = v
        self._update_log("{} {}计时循环".format(sn, "加入" if v else "退出"))

    # ============================== 状态操作 ==============================
    def _burst_send(self, sn, state, times=3, gap=0.05):
        for _ in range(times):
            self.sender.send_one(sn, state)
            if gap > 0:
                time.sleep(gap)

    def _set_device(self, sn, state):
        with self.lock:
            self.sender.device_state[sn] = state
        self._refresh_label(sn)
        self._update_log("{} -> {}".format(sn, LIGHT_STATE_NAME[state]))
        self._burst_send(sn, state)

    def _set_all(self, state):
        with self.lock:
            for sn in self.sender.device_list:
                self.sender.device_state[sn] = state
        for sn in self.sender.device_list:
            self._refresh_label(sn)
            self._burst_send(sn, state)
        self._update_log("全部 -> {}".format(LIGHT_STATE_NAME[state]))

    def _refresh_label(self, sn):
        if sn not in self.device_widgets:
            return
        st = self.sender.device_state.get(sn, LIGHT_OFF)
        w = self.device_widgets[sn]["state_label"]
        try:
            w.configure(text=LIGHT_STATE_NAME[st], bg=LIGHT_STATE_COLOR[st])
        except Exception:
            pass

    # ============================== 发送线程 ==============================
    def _start_send_thread(self):
        threading.Thread(target=self._send_loop, daemon=True).start()

    def _gui(self, fn):
        try:
            self._ui_q.put(fn)
        except Exception:
            pass

    def _ui_poller(self):
        try:
            while True:
                fn = self._ui_q.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        try:
            self.root.after(100, self._ui_poller)
        except Exception:
            pass

    def _send_loop(self):
        while self._running:
            try:
                if self.sending:
                    with self.lock:
                        self.sender.send_all()
                    self._gui(lambda: self._status_var.set(
                        "发送中... 间隔 {}s  设备数 {}".format(
                            self._current_interval(), len(self.sender.device_list))))
                else:
                    self._gui(lambda: self._status_var.set("未开启持续发送 (接收端可能超时变灰)"))
            except Exception:
                pass
            time.sleep(self._current_interval())

    def _current_interval(self):
        try:
            return self._send_interval
        except AttributeError:
            return 0.3

    def _parse_interval(self):
        try:
            return max(0.1, float(self.interval_var.get().strip()))
        except Exception:
            return 0.3

    def _toggle_send(self):
        self.sending = not self.sending
        self._btn_send.configure(text="停止发送" if self.sending else "开始发送")
        self._update_log("开始持续发送" if self.sending else "停止持续发送")

    # ============================== 计时模式 ==============================
    def _start_timer_thread(self):
        threading.Thread(target=self._timer_loop, daemon=True).start()

    def _toggle_timer(self):
        if self.timer_mode:
            self.timer_mode = False
            self._btn_timer.configure(text="开始计时")
            self._timer_info_var.set("计时未启动")
            self._update_log("计时模式停止")
        else:
            self.timer_mode = True
            self.timer_phase_index = 0
            self.timer_phase_start = time.time()
            self.timer_phase_applied = False
            self._btn_timer.configure(text="停止计时")
            if not self.sending:
                self.sending = True
                self._btn_send.configure(text="停止发送")
                self._update_log("已自动开启持续发送 (防止接收端超时变灰)")
            self._update_log("计时模式启动: 红 → 绿 → 黄 循环 (仅对勾选「参与计时」的设备生效)")

    def _timer_loop(self):
        phases = [
            (LIGHT_RED, lambda: self.red_dur),
            (LIGHT_GREEN, lambda: self.green_dur),
            (LIGHT_YELLOW, lambda: self.yellow_dur),
        ]
        while self._running:
            try:
                if self.timer_mode:
                    idx = self.timer_phase_index
                    st, dur_getter = phases[idx]
                    dur = dur_getter()
                    elapsed = time.time() - self.timer_phase_start
                    if not self.timer_phase_applied:
                        with self.lock:
                            for sn in self.sender.device_list:
                                if self.device_timer_flags.get(sn, False):
                                    self.sender.device_state[sn] = st
                        for sn in self.sender.device_list:
                            if self.device_timer_flags.get(sn, False):
                                self._gui(lambda s=sn: self._refresh_label(s))
                                self._burst_send(sn, st)
                        self._gui(lambda s=st, d=dur: self._update_log(
                            "[计时] {} 持续 {}s".format(LIGHT_STATE_NAME[s], d)))
                        self.timer_phase_applied = True
                    remain = max(0, dur - elapsed)
                    self._gui(lambda s=st, r=remain: self._timer_info_var.set(
                        "当前: {}  剩余 {:.0f}s".format(LIGHT_STATE_NAME[s], r)))
                    if elapsed >= dur:
                        self.timer_phase_index = (idx + 1) % len(phases)
                        self.timer_phase_start = time.time()
                        self.timer_phase_applied = False
                else:
                    self.timer_phase_applied = False
            except Exception:
                pass
            time.sleep(0.3)

    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _on_back(self):
        self._running = False
        self.sending = False
        self.timer_mode = False
        self._cleanup()
        self.on_back()

    def _cleanup(self):
        try:
            self.sender.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 通用宿主命令工具 (from auto_test.py / auto_51sim.py)
# ---------------------------------------------------------------------------

def _host_sh(cmd):
    import subprocess
    r = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    return r.returncode, r.stdout.strip()


def _host_sh_check(cmd):
    rc, out = _host_sh(cmd)
    if rc != 0:
        raise RuntimeError("命令失败: {}\n{}".format(cmd, out))
    return out


def _format_size(size):
    if size < 1000:
        return "{:7d}B".format(size)
    if size >= 1000000000000:
        return "{:7.2f}T".format(size / 1000000000000)
    if size >= 1000000000:
        return "{:7.2f}G".format(size / 1000000000)
    if size >= 1000000:
        return "{:7.2f}M".format(size / 1000000)
    return "{:7.2f}K".format(size / 1000)


# ---------------------------------------------------------------------------
# MapToolPage (from 转换地图.py / pb2json/pb2txt.py)
# ---------------------------------------------------------------------------

class MapToolPage:

    """ 地图工具: bag 大小分析 / map bin->txt->json 转换 """

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self._running = True
        self._log_text = None
        self._busy = False

        self.bag_initial_dir = os.path.expanduser("~/data/bagfiles")
        self.maps_initial_dir = os.path.expanduser("~/data/maps")
        default_pb_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "pb2json")
        self.planning_msgs_dir = default_pb_dir

        self._create_gui()
        self._update_log("地图工具页已启动 (bag 分析 / 地图格式转换)")

    # ================================ UI ================================
    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Button(title_frame, text="← 返回首页",
                   command=self._on_back).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="地图工具",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        ttk.Label(title_frame, text="bag 大小分析 / map 格式转换",
                  foreground="#888").pack(side=tk.LEFT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ---------- 配置 ----------
        cfg = ttk.LabelFrame(body, text="配置", padding="12 8 12 8")
        cfg.pack(fill=tk.X, padx=12, pady=6)
        row = ttk.Frame(cfg); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="planning_msgs 路径:").pack(side="left")
        self.pb_dir_var = tk.StringVar(value=self.planning_msgs_dir)
        ttk.Entry(row, textvariable=self.pb_dir_var, width=52).pack(side="left", padx=5)
        ttk.Button(row, text="浏览", command=self._browse_pb_dir).pack(side="left")

        # ---------- Bag 分析 ----------
        bag = ttk.LabelFrame(body, text="Bag 大小分析 (ROS1 .bag)",
                             padding="12 8 12 8")
        bag.pack(fill=tk.X, padx=12, pady=6)
        ttk.Label(bag,
                  text="选择 .bag 文件，统计每个 topic 的累计序列化字节数。\n"
                       "优先使用 rosbag; 未安装时用内置解析器 (仅支持未压缩 bag)。",
                  foreground="#555").pack(anchor="w", pady=(0, 6))
        ttk.Button(bag, text="选择 Bag 文件并分析",
                   command=self._pick_bag).pack(anchor="w")

        # ---------- 地图转换 ----------
        conv = ttk.LabelFrame(body, text="地图格式转换 (map_pb2)", padding="12 8 12 8")
        conv.pack(fill=tk.X, padx=12, pady=6)
        row2 = ttk.Frame(conv); row2.pack(fill=tk.X, pady=4)
        ttk.Label(row2, text="输出格式:").pack(side="left")
        self.conv_target = tk.StringVar(value="both")
        for val, name in (("txt", "txt (.txt)"), ("json", "json (.json)"), ("both", "txt + json")):
            ttk.Radiobutton(row2, text=name, value=val,
                            variable=self.conv_target).pack(side="left", padx=4)
        ttk.Button(conv, text="选择 Map 文件并转换",
                   command=self._pick_map).pack(anchor="w", pady=(6, 0))

        # ---------- 日志 ----------
        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=12, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("ok", foreground="#0a0")

    # ============================== 逻辑 ==============================
    def _browse_pb_dir(self):
        from tkinter import filedialog
        d = filedialog.askdirectory(initialdir=self.planning_msgs_dir,
                                    title="选择包含 planning_msgs 的目录")
        if d:
            self.pb_dir_var.set(d)
            self.planning_msgs_dir = d
            self._update_log("planning_msgs 路径已更新: {}".format(d))

    def _pick_bag(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            initialdir=self.bag_initial_dir, title="Select bag file",
            filetypes=(("bag files", "*.bag"), ("All files", "*.*")))
        if not path:
            return
        self._run_worker(lambda: self._analyze_bag(path))

    def _pick_map(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            initialdir=self.maps_initial_dir, title="Select map file",
            filetypes=(("map files", "*.bin"), ("All files", "*.*")))
        if not path:
            return
        self._run_worker(lambda: self._convert_map(path))

    def _run_worker(self, fn):
        if self._busy:
            self._update_log("已有任务在进行中，请稍候", tag="error")
            return
        self._busy = True
        threading.Thread(target=self._wrap, args=(fn,), daemon=True).start()

    def _wrap(self, fn):
        try:
            self._log_safe("[开始] " + (fn.__doc__ or ""))
            fn()
        except Exception as e:
            self._log_safe("出错: {}".format(e), tag="error")
        finally:
            self._busy = False

    # ---------- bag 分析 ----------
    def _analyze_bag(self, path):
        size_map = None
        try:
            import rosbag
        except Exception:
            rosbag = None
        if rosbag is not None:
            size_map = {}
            with rosbag.Bag(path, "r") as bag:
                for topic, msg, t in bag.read_messages(raw=True):
                    size_map[topic] = size_map.get(topic, 0) + len(msg[1])
        else:
            size_map = _analyze_bag_pure(path)
            if size_map is None:
                raise RuntimeError(
                    "内置解析器不支持压缩 bag; 请在装有 ROS1 rosbag 的环境使用 rosbag 分析")
        items = sorted(size_map.items(), key=lambda x: x[1], reverse=True)
        lines = ["=== Bag 大小分析: {} ===".format(os.path.basename(path))]
        for topic, size in items:
            lines.append("{}  {}".format(_format_size(size), topic))
        lines.append("=== 共 {} 个 topic ===".format(len(items)))
        self._log_safe("\n".join(lines), tag="ok")

    # ---------- map 转换 ----------
    def _convert_map(self, src):
        import sys
        pb_dir = self.pb_dir_var.get().strip() or self.planning_msgs_dir
        sys.path.insert(0, pb_dir)
        try:
            from planning_msgs.map import map_pb2
        except Exception as e:
            raise RuntimeError("无法导入 planning_msgs (检查路径 {}): {}".format(pb_dir, e))
        import google.protobuf.text_format as text_format
        from google.protobuf.json_format import MessageToJson

        with open(src, "rb") as f:
            data = f.read()
        pb_map = map_pb2.Map()
        pb_map.ParseFromString(data)

        base = src[:-4] if src.lower().endswith(".bin") else src
        target = self.conv_target.get()
        if target in ("txt", "both"):
            out = base + ".txt"
            with open(out, "w") as f:
                text_format.PrintMessage(pb_map, f)
            self._log_safe("已生成: {}".format(out), tag="ok")
        if target in ("json", "both"):
            out = src + ".json"
            with open(out, "w") as f:
                f.write(MessageToJson(pb_map, indent=2))
            self._log_safe("已生成: {}".format(out), tag="ok")

    # ============================== 日志 ==============================
    def _log_safe(self, message, tag="info"):
        try:
            self.root.after(0, lambda: self._update_log(message, tag))
        except Exception:
            pass

    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END,
                                  time.strftime("[%H:%M:%S] ") + message + "\n", tag)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _on_back(self):
        self._running = False
        self.on_back()


def _parse_bag_fields(header):
    fields = {}
    off = 0
    while off < len(header):
        length = struct.unpack("<I", header[off:off + 4])[0]
        off += 4
        raw = header[off:off + length]
        off += length
        if b"=" in raw:
            k, v = raw.split(b"=", 1)
            fields[k] = v
    return fields


def _field_int(v):
    if not v:
        return 0
    return int.from_bytes(v, "little")


def _analyze_bag_pure(path):
    """ 不依赖 rosbag 的轻量解析 (仅支持未压缩 bag v2.0)
        遇到压缩 chunk 返回 None 表示需要 rosbag
    """
    topic_size = {}
    with open(path, "rb") as fp:
        magic = fp.read(4)
        if magic not in (b"#ROS", b"#ros"):
            fp.seek(0)
            head = fp.read(32)
            if b"bag" not in head.lower() and b"ROSBAG" not in head:
                raise RuntimeError("不是 ROS1 bag 文件: {}".format(path))
            fp.seek(0)
        else:
            fp.seek(0)
        while True:
            hlen_b = fp.read(4)
            if len(hlen_b) < 4:
                break
            hlen = struct.unpack("<I", hlen_b)[0]
            hdr = fp.read(hlen)
            if len(hdr) < hlen:
                break
            dlen_b = fp.read(4)
            if len(dlen_b) < 4:
                break
            dlen = struct.unpack("<I", dlen_b)[0]
            data = fp.read(dlen)
            if len(data) < dlen:
                break
            fields = _parse_bag_fields(hdr)
            op = _field_int(fields.get(b"op"))
            if op == 2:  # MSG_DATA
                topic = fields.get(b"topic", b"?").decode(errors="ignore")
                topic_size[topic] = topic_size.get(topic, 0) + dlen
            elif op == 5:  # CHUNK -> 压缩
                return None
    return topic_size


# ---------------------------------------------------------------------------
# SimTestPage (from auto_test.py / auto_51sim.py / cars_ros2)
# ---------------------------------------------------------------------------

SIM_API_BASE = "https://mineapiprod.boonray.com/dispatch"
SIM_API_ARRANGE_TASK = SIM_API_BASE + "/arrange_task"
SIM_API_BREAK_TASK = SIM_API_BASE + "/break_task"
SIM_API_CONTINUE_TASK = SIM_API_BASE + "/continue_task"
SIM_API_PROJECT_ID = "56955550355457"
SIM_API_USER_ID = "56524522090689"
SIM_API_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJib29ucmF5IiwiZXhwIjoxNzg4NjY0MjAyLCJ1c2VyX2lkIjo1NjUyNDUyMjA5MDY4OSwicm9sZV9sZXZlbCI6MywicHJvamVjdF9pZCI6NTY5NTU1NTAzNTU0NTcsInByb2plY3Rfcm9sZV9sZXZlbCI6MX0.9auI2W2oajhCeXL_NQkcRjg6lglXc0nHf2aUDldljns"
SIM_BATCH_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJib29ucmF5IiwiZXhwIjoxNzkwMTQyNTI1LCJ1c2VyX2lkIjo1NjUyNDUyMjA5MDY4OSwicm9sZV9sZXZlbCI6MywicHJvamVjdF9pZCI6NTY5NTU1NTAzNTU0NTcsInByb2plY3Rfcm9sZV9sZXZlbCI6MX0.ON0f_ButKVnpACkrpzMM3wA3vnss628cNLBvmYqhc3k"

SIM_AD_READY_NODE_MIN = 5
SIM_AD_READY_TIMEOUT = 300
SIM_WAIT_CONTAINER_TIMEOUT = 90
SIM_BREAK_DELAY = 20
SIM_CONTINUE_DELAY = 5

SIM_GUARDIAN_INNER = "/tmp/auto_51sim_guardian_inner.sh"
SIM_GUARDIAN_TRIGGER = "/tmp/auto_51sim_guardian.trigger"
SIM_GUARDIAN_DONE = "/tmp/auto_51sim_guardian.done"
SIM_GUARDIAN_TIMEOUT = 30


class SimTestPage:

    """ 仿真测试: 容器会话(cars_ros2) + 单案例(auto_test) + 批量(auto_51sim) """

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self._running = True
        self._log_text = None
        self._flow_lock = threading.Lock()
        self._ask_event = threading.Event()
        self._ask_pending = False
        self._worker = None
        self.batch_results = []

        self._create_gui()
        self._update_log("仿真测试页已启动 (容器会话 / 单案例 / 批量)")

    # ================================ UI ================================
    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Button(title_frame, text="← 返回首页", command=self._on_back).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="仿真测试",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        ttk.Label(title_frame, text="单案例 / 批量 / 容器会话",
                  foreground="#888").pack(side=tk.LEFT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ---------- 容器会话 (cars_ros2) ----------
        cs = ttk.LabelFrame(body, text="Docker 容器会话 (T01~T10)", padding="12 8 12 8")
        cs.pack(fill=tk.X, padx=12, pady=6)
        r0 = ttk.Frame(cs); r0.pack(fill=tk.X, pady=4)
        ttk.Label(r0, text="容器列表(空格分隔):").pack(side="left")
        self.cs_containers_var = tk.StringVar(value="T01 T02 T03 T04 T05 T06 T07 T08 T09 T10")
        ttk.Entry(r0, textvariable=self.cs_containers_var, width=44).pack(side="left", padx=5)
        ttk.Label(r0, text="镜像:").pack(side="left", padx=(10, 0))
        self.cs_image_var = tk.StringVar(value="ros2_humble_image:v1")
        ttk.Entry(r0, textvariable=self.cs_image_var, width=18).pack(side="left", padx=5)
        r1 = ttk.Frame(cs); r1.pack(fill=tk.X, pady=4)
        ttk.Label(r1, text="镜像根目录:").pack(side="left")
        self.cs_base_var = tk.StringVar(value="/home/boonray/robotruck/ros2")
        ttk.Entry(r1, textvariable=self.cs_base_var, width=44).pack(side="left", padx=5)
        ttk.Button(r1, text="启动全部容器会话", command=self._cs_start).pack(side="left", padx=5)
        ttk.Button(r1, text="停止全部容器会话", command=self._cs_stop).pack(side="left", padx=5)

        # ---------- 单案例 (auto_test) ----------
        one = ttk.LabelFrame(body, text="单案例仿真测试 (auto_test.py)", padding="12 8 12 8")
        one.pack(fill=tk.X, padx=12, pady=6)
        r2 = ttk.Frame(one); r2.pack(fill=tk.X, pady=4)
        ttk.Label(r2, text="案例:").pack(side="left")
        self.one_case_var = tk.StringVar(value="T01")
        ttk.Entry(r2, textvariable=self.one_case_var, width=8).pack(side="left", padx=5)
        ttk.Label(r2, text="设备SN:").pack(side="left", padx=(10, 0))
        self.one_device_var = tk.StringVar(value="fz_c01")
        ttk.Entry(r2, textvariable=self.one_device_var, width=14).pack(side="left", padx=5)
        ttk.Label(r2, text="容器:").pack(side="left", padx=(10, 0))
        self.one_cont_var = tk.StringVar(value="fz1")
        ttk.Entry(r2, textvariable=self.one_cont_var, width=8).pack(side="left", padx=5)
        r3 = ttk.Frame(one); r3.pack(fill=tk.X, pady=4)
        ttk.Label(r3, text="API Token(单案例):").pack(side="left")
        self.one_token_var = tk.StringVar(value=SIM_API_TOKEN)
        ttk.Entry(r3, textvariable=self.one_token_var, width=80).pack(side="left", padx=5)
        r4 = ttk.Frame(one); r4.pack(fill=tk.X, pady=4)
        ttk.Button(r4, text="完成全流程", command=self._one_full).pack(side="left", padx=4)
        ttk.Button(r4, text="打开窗口并启动容器", command=self._one_open).pack(side="left", padx=4)
        ttk.Button(r4, text="等待容器就绪", command=self._one_wait_container).pack(side="left", padx=4)
        ttk.Button(r4, text="等待AD就绪", command=self._one_wait_ad).pack(side="left", padx=4)
        ttk.Button(r4, text="发送任务", command=self._one_send).pack(side="left", padx=4)
        ttk.Button(r4, text="中断任务", command=self._one_break).pack(side="left", padx=4)
        ttk.Button(r4, text="继续任务", command=self._one_continue).pack(side="left", padx=4)
        ttk.Button(r4, text="清理容器", command=self._one_stop).pack(side="left", padx=4)

        # ---------- 批量 (auto_51sim) ----------
        batch = ttk.LabelFrame(body, text="批量仿真测试 (auto_51sim.py)", padding="12 8 12 8")
        batch.pack(fill=tk.X, padx=12, pady=6)
        r5 = ttk.Frame(batch); r5.pack(fill=tk.X, pady=4)
        ttk.Label(r5, text="案例目录:").pack(side="left")
        self.batch_case_dir_var = tk.StringVar(value="/home/boonray/robotruck/ros2/auto_51sim")
        ttk.Entry(r5, textvariable=self.batch_case_dir_var, width=40).pack(side="left", padx=5)
        ttk.Button(r5, text="刷新案例数", command=self._batch_refresh).pack(side="left", padx=5)
        self.batch_case_count_var = tk.StringVar(value="未扫描")
        ttk.Label(r5, textvariable=self.batch_case_count_var,
                  foreground="#555").pack(side="left", padx=6)
        r6 = ttk.Frame(batch); r6.pack(fill=tk.X, pady=4)
        ttk.Label(r6, text="设备SN:").pack(side="left")
        self.batch_device_var = tk.StringVar(value="fz_c01")
        ttk.Entry(r6, textvariable=self.batch_device_var, width=14).pack(side="left", padx=5)
        ttk.Label(r6, text="Token:").pack(side="left", padx=(10, 0))
        self.batch_token_var = tk.StringVar(value=SIM_BATCH_TOKEN)
        ttk.Entry(r6, textvariable=self.batch_token_var, width=80).pack(side="left", padx=5)
        r7 = ttk.Frame(batch); r7.pack(fill=tk.X, pady=4)
        self.auto_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(r7, text="自动确认(跳过手动回车)", variable=self.auto_var).pack(side="left")
        self._confirm_btn = ttk.Button(r7, text="确认继续 →", command=self._approve,
                                       state=tk.DISABLED)
        self._confirm_btn.pack(side="left", padx=8)
        ttk.Button(r7, text="启动批量测试", command=self._batch_start).pack(side="left", padx=4)
        ttk.Button(r7, text="停止批量", command=self._batch_stop).pack(side="left", padx=4)
        ttk.Button(r7, text="生成报告", command=self._batch_report).pack(side="left", padx=4)
        ttk.Button(r7, text="清理容器", command=self._batch_clean).pack(side="left", padx=4)

        # ---------- 日志 ----------
        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=14, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("ok", foreground="#0a0")
        self._log_text.tag_configure("warn", foreground="#a60")

    # ============================== 通用 ==============================
    def _log_safe(self, message, tag="info"):
        try:
            self.root.after(0, lambda: self._update_log(message, tag))
        except Exception:
            pass

    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _run_worker(self, fn):
        if self._worker is not None and self._worker.is_alive():
            self._update_log("已有任务在运行: 请等待或点「停止批量」", tag="warn")
            return
        if not self._flow_lock.acquire(blocking=False):
            self._update_log("已有任务在运行", tag="warn")
            return
        threading.Thread(target=self._worker_wrap, args=(fn,), daemon=True).start()

    def _worker_wrap(self, fn):
        try:
            fn()
        except Exception as e:
            self._log_safe("出错: {}".format(e), tag="error")
        finally:
            try:
                self.root.after(0, self._approve_button, False)
            except Exception:
                pass
            self._flow_lock.release()

    def _approve(self):
        if self._ask_pending:
            self._ask_event.set()

    def _approve_button(self, enabled):
        try:
            self._confirm_btn.config(state=tk.NORMAL if enabled else tk.DISABLED)
        except Exception:
            pass

    def _ask_wait(self, message, timeout=1800):
        """工作线程内调用: 需要人工确认时阻塞等待; 勾选自动则直接返回"""
        if self.auto_var.get():
            self._log_safe("[自动确认] " + message)
            return True
        self._ask_pending = True
        self._ask_event.clear()
        self._log_safe("[等待人工确认] " + message, tag="warn")
        self._log_safe("确认仿真就绪后，点击上方「确认继续」...", tag="warn")
        try:
            self.root.after(0, self._approve_button, True)
        except Exception:
            pass
        self._ask_event.wait(timeout)
        self._ask_pending = False
        return True

    # ============================== 容器会话 ==============================
    def _cs_names(self):
        names = []
        for n in self.cs_containers_var.get().split():
            n = n.strip()
            if n:
                names.append(n)
        return names or ["T01"]

    def _gen_container(self, name, base_dir):
        import subprocess
        from pathlib import Path
        rc, out = _host_sh("docker ps --format '{{.Names}}'")
        if name in out.split():
            self._log_safe("容器 {} 已在运行".format(name))
            return
        base_dir = self.cs_base_var.get().strip() or base_dir
        os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/runtime-boonray")
        os.makedirs("/tmp/runtime-boonray", exist_ok=True)
        Path("/home/boonray/.boonray").mkdir(exist_ok=True)
        install_folder = base_dir + "/"
        launch_folder = base_dir + "/launches"
        docker_img_name = self.cs_image_var.get().strip() or "ros2_humble_image"
        try:
            docker_num = int(name[1:])
        except Exception:
            docker_num = 1
        if "/" not in docker_img_name:
            docker_img_name += ":v1"
        cmd0 = (
            "/usr/bin/docker run -it --privileged=true --rm --gpus all "
            "--env=NVIDIA_VISIBLE_DEVICES=all --env=NVIDIA_DRIVER_CAPABILITIES=all "
            "--env=DISPLAY --env=QT_X11_NO_MITSHM=1 --env=ROS_DOMAIN_ID={} "
            "-v /tmp/.X11-unix:/tmp/.X11-unix:rw "
            "-v {}install:/home/boonray/install "
            "-v {}:/home/boonray/simulation_launches/ "
            "-v /dev/input/js0:/dev/input/js0 "
            "-v /etc/localtime:/etc/localtime:ro -v /etc/timezone:/etc/timezone:ro "
            "--hostname {} --name {} {} bash").format(
                docker_num, install_folder, launch_folder,
                name, name, docker_img_name)
        self._log_safe("启动容器 {} (gnome-terminal)".format(name))
        subprocess.Popen(
            ["/usr/bin/gnome-terminal", "-v", "-t", name,
             "--working-directory=$HOME", "--tab", "--",
             "bash", "-c", cmd0],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        rc, out = _host_sh("docker ps --format '{{.Names}}'")
        if name in out.split():
            self._log_safe("容器 {} 运行中".format(name), tag="ok")
        else:
            self._log_safe("容器 {} 尚未检测到 (等待创建...)".format(name))

    def _cs_start(self):
        def flow():
            base_dir = self.cs_base_var.get().strip() or "/home/boonray/robotruck/ros2"
            for name in self._cs_names():
                self._gen_container(name, base_dir)
        self._run_worker(flow)

    def _cs_stop(self):
        def flow():
            for name in self._cs_names():
                _host_sh("docker stop {}".format(name))
                self._log_safe("已停止 {}".format(name))
        self._run_worker(flow)

    # ============================== API 通用 ==============================
    def _api_request(self, url, desc, extra=None):
        import requests
        token = self.one_token_var.get().strip()
        params = {"project_id": SIM_API_PROJECT_ID, "user_id": SIM_API_USER_ID}
        headers = {
            "Authorization": "token {}".format(token),
            "Content-Type": "application/json;charset=utf-8",
            "ProjectID": SIM_API_PROJECT_ID,
        }
        data = {
            "target_device_sn": self.one_device_var.get().strip(),
            "project_id": int(SIM_API_PROJECT_ID),
        }
        if extra:
            data.update(extra)
        self._log_safe("{} -> 设备 {}".format(desc, data["target_device_sn"]))
        resp = requests.post(url, params=params, headers=headers, json=data, timeout=30)
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        self._log_safe("状态码: {}  响应: {}".format(resp.status_code, body))
        return resp

    def _one_send(self):
        self._run_worker(lambda: self._api_request(
            SIM_API_ARRANGE_TASK, "发送调度任务", extra={"task_type": 102}))

    def _one_break(self):
        self._run_worker(lambda: self._api_request(SIM_API_BREAK_TASK, "发送中断任务"))

    def _one_continue(self):
        self._run_worker(lambda: self._api_request(SIM_API_CONTINUE_TASK, "发送继续任务"))

    # ============================== 单案例流程 ==============================
    def _print_window_hint(self):
        self._log_safe("gnome-terminal 三个标签页: 1=容器主终端, 2=AD程序, 3=trans_node",
                       tag="ok")

    def _one_full(self):
        def flow():
            import tempfile
            cont = self.one_cont_var.get().strip() or "fz1"
            case_dir = self.one_case_var.get().strip() or "T01"
            # 1. 预检
            rc, out = _host_sh("docker ps -a --format '{{.Names}}'")
            if cont in out.split():
                _host_sh("docker rm -f {}".format(cont))
                self._log_safe("已删除残留容器 {}".format(cont))
            # 2. 打开窗口
            os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/runtime-boonray")
            os.makedirs("/tmp/runtime-boonray", exist_ok=True)
            tmp = tempfile.mkdtemp(prefix="mock_tools_sim_")
            panes = {
                "pane0.sh": "wenrui_ros2_launch {} install\n".format(cont),
                "pane1.sh": (
                    "echo 'waiting for container {}...'\n"
                    "until docker exec {} true 2>/dev/null; do sleep 1; done\n"
                    "docker exec -it {} bash -ic "
                    "'source install/setup.bash && wenrui_launch simulation_launches/{}/'\n"
                ).format(cont, cont, cont, case_dir),
                "pane2.sh": (
                    "echo 'waiting for container {}...'\n"
                    "until docker exec {} true 2>/dev/null; do sleep 1; done\n"
                    "docker exec -it {} bash -ic "
                    "'cd install/wordsimtest/run && bash run.sh'\n"
                ).format(cont, cont, cont),
            }
            paths = {}
            for name, content in panes.items():
                p = os.path.join(tmp, name)
                with open(p, "w") as f:
                    f.write(content)
                paths[name] = p

            def pane_cmd(title, sp, is_first):
                inner = "bash -ic 'source {}; exec bash'".format(sp)
                parts = []
                if is_first:
                    parts += ["--window", "--title", title]
                else:
                    parts += ["--tab", "--title", title]
                parts += ["-e", inner]
                return parts

            import subprocess
            cmd = ["/usr/bin/gnome-terminal", "-v"]
            cmd += pane_cmd("容器主终端", paths["pane0.sh"], True)
            cmd += pane_cmd("AD程序", paths["pane1.sh"], False)
            cmd += pane_cmd("trans_node", paths["pane2.sh"], False)
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._log_safe("已打开 gnome-terminal 3 标签页", tag="ok")
            # 3. 等待容器
            self._wait_container(cont)
            # 4. 等待 AD
            self._wait_ad(cont)
            # 5. 人工确认
            self._ask_wait("请在 SimOne 中运行案例 {} / {} 并确认连接".format(case_dir, self.one_device_var.get()))
            # 6. 任务序列
            self._api_request(SIM_API_ARRANGE_TASK, "发送调度任务", extra={"task_type": 102})
            self._log_safe("等待 {}s 后中断...".format(SIM_BREAK_DELAY))
            time.sleep(SIM_BREAK_DELAY)
            self._api_request(SIM_API_BREAK_TASK, "发送中断任务")
            self._log_safe("等待 {}s 后继续...".format(SIM_CONTINUE_DELAY))
            time.sleep(SIM_CONTINUE_DELAY)
            self._api_request(SIM_API_CONTINUE_TASK, "发送继续任务")
            self._log_safe("单案例任务序列完成", tag="ok")
        self._run_worker(flow)

    def _one_open(self):
        def flow():
            cont = self.one_cont_var.get().strip() or "fz1"
            rc, out = _host_sh("docker ps -a --format '{{.Names}}'")
            if cont in out.split():
                _host_sh("docker rm -f {}".format(cont))
                self._log_safe("已删除残留容器 {}".format(cont))
            case_dir = self.one_case_var.get().strip() or "T01"
            os.environ.setdefault("XDG_RUNTIME_DIR", "/tmp/runtime-boonray")
            os.makedirs("/tmp/runtime-boonray", exist_ok=True)
            pane0 = "wenrui_ros2_launch {} install\n".format(cont)
            pane1 = ("until docker exec {} true 2>/dev/null; do sleep 1; done\n"
                     "docker exec -it {} bash -ic 'source install/setup.bash && "
                     "wenrui_launch simulation_launches/{}/'\n").format(cont, cont, case_dir)
            pane2 = ("until docker exec {} true 2>/dev/null; do sleep 1; done\n"
                     "docker exec -it {} bash -ic 'cd install/wordsimtest/run && bash run.sh'\n"
                     ).format(cont, cont)
            self._open_three_panes(pane0, pane1, pane2)
        self._run_worker(flow)

    def _open_three_panes(self, pane0, pane1, pane2):
        import subprocess
        import tempfile
        tmp = tempfile.mkdtemp(prefix="mock_tools_sim_")
        paths = {}
        for i, content in enumerate((pane0, pane1, pane2)):
            p = os.path.join(tmp, "pane{}.sh".format(i))
            with open(p, "w") as f:
                f.write(content)
            paths[i] = p
        titles = ("容器主终端", "AD程序", "trans_node")

        def pane_cmd(title, sp, is_first):
            inner = "bash -ic 'source {}; exec bash'".format(sp)
            parts = []
            if is_first:
                parts += ["--window", "--title", title]
            else:
                parts += ["--tab", "--title", title]
            parts += ["-e", inner]
            return parts

        cmd = ["/usr/bin/gnome-terminal", "-v"]
        cmd += pane_cmd(titles[0], paths[0], True)
        cmd += pane_cmd(titles[1], paths[1], False)
        cmd += pane_cmd(titles[2], paths[2], False)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._log_safe("已打开 gnome-terminal: 容器主终端 / AD程序 / trans_node", tag="ok")

    def _wait_container(self, cont):
        self._log_safe("等待容器 {} 启动...".format(cont))
        t0 = time.time()
        while time.time() - t0 < SIM_WAIT_CONTAINER_TIMEOUT:
            rc, out = _host_sh("docker ps --format '{{.Names}}'")
            if cont in out.split():
                self._log_safe("容器 {} 已启动 ({}s)".format(cont, int(time.time() - t0)), tag="ok")
                return True
            time.sleep(2)
        self._log_safe("容器启动超时", tag="error")
        return False

    def _wait_ad(self, cont):
        self._log_safe("等待 AD 程序就绪 (最多 {}s)...".format(SIM_AD_READY_TIMEOUT))
        t0 = time.time()
        while time.time() - t0 < SIM_AD_READY_TIMEOUT:
            rc, out = _host_sh(
                "docker exec {} bash -c 'source /opt/ros/humble/setup.bash >/dev/null 2>&1; "
                "{{ ros2 node list 2>/dev/null; ROS_DOMAIN_ID=93 ros2 node list 2>/dev/null; }} "
                "| sort -u | wc -l'".format(cont))
            try:
                n = int(out or "0")
            except ValueError:
                n = 0
            if n >= SIM_AD_READY_NODE_MIN:
                self._log_safe("AD 程序就绪 ({} 节点)".format(n), tag="ok")
                return True
            rc, alive = _host_sh(
                "docker exec {} bash -c \"pgrep -f '[s]imulation_launch' >/dev/null && echo OK || echo DEAD\"".format(cont))
            if "DEAD" in alive:
                self._log_safe("AD 程序进程已退出, 请查看终端标签2日志", tag="error")
                return False
            time.sleep(5)
        self._log_safe("AD 等待超时, 继续", tag="warn")
        return False

    def _one_wait_container(self):
        self._run_worker(lambda: self._wait_container(self.one_cont_var.get().strip() or "fz1"))

    def _one_wait_ad(self):
        self._run_worker(lambda: self._wait_ad(self.one_cont_var.get().strip() or "fz1"))

    def _one_stop(self):
        def flow():
            cont = self.one_cont_var.get().strip() or "fz1"
            _host_sh("docker rm -f {}".format(cont))
            self._log_safe("已删除容器 {}".format(cont))
        self._run_worker(flow)

    # ============================== 批量流程 ==============================
    def _batch_case_dirs(self):
        d = self.batch_case_dir_var.get().strip()
        if not os.path.isdir(d):
            return []
        dirs = sorted([x for x in os.listdir(d)
                       if os.path.isdir(os.path.join(d, x))])
        case_dirs = [x for x in dirs if x.startswith("case")]
        return case_dirs or dirs

    def _batch_refresh(self):
        cases = self._batch_case_dirs()
        self.batch_case_count_var.set("共 {} 个案例".format(len(cases)))
        self._update_log("批量测试案例: {}".format(", ".join(cases[:12]) + ("..." if len(cases) > 12 else "")),
                         tag="ok")

    def _batch_start(self):
        def flow():
            cont = "fz1"
            # 记录并反馈案例列表
            cases = self._batch_case_dirs()
            if not cases:
                raise RuntimeError("未找到任何案例目录: " + self.batch_case_dir_var.get())
            self._log_safe("案例列表: {}".format(", ".join(cases)))
            self._check_batch_token()
            # 1. 清理残留容器
            _host_sh("docker rm -f {}".format(cont))
            self._log_safe("已清理残留容器 {}".format(cont))
            # 2. 生成 guardian 脚本
            self._write_guardian_script()
            # 3. 打开终端
            self._open_batch_window(cont)
            # 4. 等待容器
            if not self._wait_container(cont):
                return
            # 5. 启动 AD
            self._batch_start_ad(cont)
            # 6. 循环案例
            for i, case in enumerate(cases):
                self._log_safe(">>> 进度 {}/{}".format(i + 1, len(cases)))
                self._run_batch_case(cont, case)
            self._log_safe("所有案例执行完毕", tag="ok")
            self._batch_generate_report(cases)
        self._run_worker(flow)

    def _check_batch_token(self):
        import base64
        token = self.batch_token_var.get().strip()
        try:
            payload = token.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            exp = json.loads(base64.urlsafe_b64decode(payload))["exp"]
            if exp < time.time():
                self._log_safe("!!! API_TOKEN 已过期, 任务会被云端拒绝, 请更新 Token",
                               tag="error")
        except Exception:
            pass

    def _write_guardian_script(self):
        with open(SIM_GUARDIAN_INNER, "w") as f:
            f.write(
                "source /opt/ros/humble/setup.bash >/dev/null 2>&1\n"
                "source /home/boonray/install/setup.bash\n"
                'echo ""\n'
                'echo ">>> guardian 服务调用: /guardian/mix/service_interface ..."\n'
                "timeout 20 ros2 service call /guardian/mix/service_interface "
                "guardian_msgs/srv/GService \"{'type':10,'value':1,'params':''}\"\n"
                'echo ">>> guardian 服务调用结束"\n'
            )
        self._log_safe("guardian 调用脚本已生成: {}".format(SIM_GUARDIAN_INNER))

    def _open_batch_window(self, cont):
        import subprocess
        tmp = "/tmp"
        pane0 = os.path.join(tmp, "mock_tools_batch_pane0.sh")
        pane1 = os.path.join(tmp, "mock_tools_batch_pane1.sh")
        pane2 = os.path.join(tmp, "mock_tools_batch_pane2.sh")
        with open(pane0, "w") as f:
            f.write("rm -f {} {}\n".format(SIM_GUARDIAN_TRIGGER, SIM_GUARDIAN_DONE))
            f.write("(\n  while true; do\n")
            f.write("    if [ -f {} ]; then\n".format(SIM_GUARDIAN_TRIGGER))
            f.write("      rm -f {}\n".format(SIM_GUARDIAN_TRIGGER))
            f.write("      docker exec -i {} bash < {}\n".format(cont, SIM_GUARDIAN_INNER))
            f.write("      touch {}\n".format(SIM_GUARDIAN_DONE))
            f.write("    fi\n    sleep 1\n  done\n) &\n")
            f.write("wenrui_ros2_launch {} install 1\n".format(cont))
        with open(pane1, "w") as f:
            f.write(
                "echo '等待容器 {} 就绪...'\n"
                "until docker exec {} true 2>/dev/null; do sleep 1; done\n"
                "echo 'AD 程序日志监控中...'\n"
                "LOG_FILE=/tmp/ad_program.log\n"
                "while true; do\n"
                "  while ! docker exec {} test -s $LOG_FILE 2>/dev/null; do sleep 1; done\n"
                "  docker exec {} tail -f $LOG_FILE 2>&1\n"
                "  sleep 1\n"
                "done\n").format(cont, cont, cont, cont)
        with open(pane2, "w") as f:
            f.write(
                "echo '等待容器 {} 就绪...'\n"
                "until docker exec {} true 2>/dev/null; do sleep 1; done\n"
                "echo 'trans_node 日志监控中...'\n"
                "LOG_FILE=/tmp/trans_node.log\n"
                "while true; do\n"
                "  while ! docker exec {} pgrep -f trans_node >/dev/null 2>&1; do sleep 1; done\n"
                "  docker exec {} tail -f $LOG_FILE 2>&1\n"
                "  sleep 1\n"
                "done\n").format(cont, cont, cont, cont)

        def pane_cmd(title, sp, is_first):
            inner = "bash -ic 'source {}; exec bash'".format(sp)
            parts = []
            if is_first:
                parts += ["--window", "--title", title]
            else:
                parts += ["--tab", "--title", title]
            parts += ["-e", inner]
            return parts

        cmd = ["/usr/bin/gnome-terminal", "-v"]
        cmd += pane_cmd("容器主终端", pane0, True)
        cmd += pane_cmd("AD程序", pane1, False)
        cmd += pane_cmd("trans_node日志", pane2, False)
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._log_safe("批量测试窗口已打开 (guardian 触发器就绪)", tag="ok")

    def _batch_start_ad(self, cont):
        self._log_safe("启动 AD 程序 (后台)...")
        _host_sh("docker exec {} bash -c ' > /tmp/ad_program.log'".format(cont))
        _host_sh(
            "docker exec -d {} bash -c "
            "'source /home/boonray/install/setup.bash && "
            "ros2 launch rclpy wenrui_launch.py conf:=/home/boonray/simulation_launches/T01/ "
            "> /tmp/ad_program.log 2>&1'".format(cont))
        time.sleep(10)
        if self._wait_ad(cont):
            self._log_safe("AD 程序就绪", tag="ok")
        else:
            self._log_safe("AD 就绪检测超时, 继续执行", tag="warn")

    def _case_deadline(self, case):
        cfg = os.path.join(self.batch_case_dir_var.get().strip(), case, "config.ini")
        if not os.path.exists(cfg):
            return 10
        try:
            import configparser
            cp = configparser.ConfigParser()
            cp.read(cfg)
            return cp.getint("CaseConfig", "Case_Deadline")
        except Exception:
            return 10

    def _trans_running(self, cont):
        rc, out = _host_sh(
            "docker exec {} bash -c 'pgrep -f trans_node >/dev/null 2>&1 && echo alive || echo dead'".format(cont))
        return "alive" in out

    def _wait_trans_exit(self, cont, max_wait):
        self._log_safe("监控 trans_node 退出 (最多 {}s)...".format(max_wait))
        t0 = time.time()
        while time.time() - t0 < max_wait:
            if not self._trans_running(cont):
                self._log_safe("trans_node 已退出 ({}s)".format(int(time.time() - t0)), tag="ok")
                return True
            time.sleep(0.5)
        self._log_safe("trans_node 超时未退出, 强制停止", tag="warn")
        _host_sh("docker exec {} bash -c 'pkill -f trans_node || true'".format(cont))
        return False

    def _call_guardian(self, cont):
        self._log_safe("触发 guardian 服务调用 (窗口1容器内执行)...")
        _host_sh("rm -f {}".format(SIM_GUARDIAN_DONE))
        _host_sh("touch {}".format(SIM_GUARDIAN_TRIGGER))
        t0 = time.time()
        while time.time() - t0 < SIM_GUARDIAN_TIMEOUT:
            if os.path.exists(SIM_GUARDIAN_DONE):
                time.sleep(1)
                self._log_safe("guardian 服务调用完成", tag="ok")
                return True
            time.sleep(0.5)
        self._log_safe("guardian 调用等待超时, 继续", tag="warn")
        return False

    def _send_batch_task(self):
        import requests
        token = self.batch_token_var.get().strip()
        params = {"project_id": SIM_API_PROJECT_ID, "user_id": SIM_API_USER_ID}
        headers = {
            "Authorization": "token {}".format(token),
            "Content-Type": "application/json;charset=utf-8",
            "ProjectID": SIM_API_PROJECT_ID,
        }
        data = {
            "target_device_sn": self.batch_device_var.get().strip(),
            "project_id": int(SIM_API_PROJECT_ID),
            "task_type": 102,
        }
        try:
            resp = requests.post(SIM_API_ARRANGE_TASK, params=params,
                                 headers=headers, json=data, timeout=30)
            try:
                body = resp.json()
            except ValueError:
                body = resp.text
            self._log_safe("调度任务已发送 | {} | {}".format(resp.status_code, body))
        except Exception as e:
            self._log_safe("请求失败: {}".format(e), tag="error")

    def _run_batch_case(self, cont, case):
        import configparser
        deadline = self._case_deadline(case)
        self._log_safe("=" * 50)
        self._log_safe("[案例] {}  (Case_Deadline={}s)".format(case, deadline))
        # 1. 启动 trans_node
        case_config = "/home/boonray/auto_51sim/{}/config.ini".format(case)
        _host_sh("docker exec {} bash -c ' > /tmp/trans_node.log'".format(cont))
        _host_sh(
            "docker exec -d {} bash -c '"
            "cd /home/boonray/worldsimtest/run && "
            "bash run.sh --case_config_path {} "
            "> /tmp/trans_node.log 2>&1'".format(cont, case_config))
        time.sleep(5)
        if self._trans_running(cont):
            self._log_safe("trans_node 运行中", tag="ok")
        else:
            self._log_safe("trans_node 未检测到, 请查看日志", tag="warn")
        # 2. guardian
        self._call_guardian(cont)
        # 3. 确认
        self._ask_wait("请在 SimOne 确认仿真车辆已连接, 准备下发任务")
        # 4. 发任务
        self._send_batch_task()
        # 5. 等 trans_node 退出
        self._wait_trans_exit(cont, deadline + 30)
        # 6. 停 AD
        _host_sh("docker exec {} bash -c 'pkill -f simulation_launch || true; pkill -f ros2 || true'".format(cont))
        time.sleep(3)
        self._log_safe("AD 程序已停止")
        time.sleep(5)
        # 7. 重启 AD
        self._batch_start_ad(cont)
        # 8. 扫描异常
        faults = self._scan_faults(cont)
        deduped = self._dedup(faults)
        self._log_safe("[案例 {}] {}".format(
            case, "未发现异常" if not deduped else "发现 {} 种异常".format(len(deduped))))
        for f in deduped:
            prefix = "[" + f["code"] + "] " if f.get("code") else ""
            self._log_safe("  {}{} (x{})".format(prefix, f["message"][:100], f["count"]),
                           tag=("error" if f["type"] == "business_fault" else "warn"))
        self.batch_results.append({"case": case, "deadline": deadline, "faults": faults})

    def _scan_faults(self, cont):
        import re as _re
        faults = []
        noise = [
            "Socket Connect Error", "Socket Shutdown Error", "Initializing node failed",
            "仍然存在的故障码", "获取云端故障码成功", "导入GuardianJsonString失败",
            "创建socket失败", "Default logging verbosity", "感知消息时间与当前时间差值较大",
            "字段 .* 转换异常", "电车手刹释放时掉电", "dropping desired message",
            "init\\[15\\] cost", "vehicle_error_reason: 正常 ->",
            "broadcast/common/fault_code_update", "自动继续",
        ]

        def clean(s):
            return _re.sub(r'\x1b\[[0-9;]*m', '', s)

        rc, out = _host_sh("docker exec {} cat /tmp/ad_program.log 2>/dev/null".format(cont))
        if rc == 0 and out:
            for line in out.splitlines():
                c = clean(line)
                if "topic:" in c and "/fault" in c:
                    try:
                        payload_str = c[c.index("payload:") + len("payload:"):].strip()
                        payload = json.loads(payload_str)
                        for f in payload.get("faults", []):
                            faults.append({"type": "business_fault", "code": f.get("code", ""),
                                           "message": f.get("message", ""), "source": "ad_program"})
                    except (json.JSONDecodeError, ValueError):
                        pass
                    continue
                if ("ERROR" in c or "Case deadline" in c or "guardian_state is null" in c):
                    if not any(_re.search(p, c) for p in noise):
                        faults.append({"type": "runtime_error", "code": "",
                                       "message": c[:200], "source": "ad_program"})
        rc, out = _host_sh("docker exec {} cat /tmp/trans_node.log 2>/dev/null".format(cont))
        if rc == 0 and out:
            for line in out.splitlines():
                c = clean(line)
                if "ERROR" in c or "error" in c:
                    if not any(_re.search(p, c) for p in noise):
                        faults.append({"type": "runtime_error", "code": "",
                                       "message": c[:200], "source": "trans_node"})
        return faults

    def _dedup(self, faults):
        seen = {}
        for f in faults:
            key = "{}|{}".format(f["code"], f["message"][:80])
            if key not in seen:
                seen[key] = dict(f, **{"count": 1})
            else:
                seen[key]["count"] += 1
        return list(seen.values())

    def _batch_generate_report(self, cases):
        from datetime import datetime
        report_path = os.path.join(self.batch_case_dir_var.get().strip(), "..", "test_report.md")
        report_path = os.path.abspath(report_path)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        failures = [r for r in self.batch_results if r["faults"]]
        passes = [r for r in self.batch_results if not r["faults"]]
        lines = ["# 自动驾驶仿真测试报告", "", "| 项目 | 结果 |", "|------|------|",
                 "| 生成时间 | {} |".format(now),
                 "| 案例总数 | {} |".format(len(self.batch_results)),
                 "| 通过 | {} |".format(len(passes)),
                 "| 有异常 | {} |".format(len(failures)), "", "## 一、案例总览", "",
                 "| 案例 | 结果 | 业务异常 | 运行时错误 |", "|------|------|----------|------------|"]
        for r in self.batch_results:
            ded = self._dedup(r["faults"])
            biz = sum(1 for f in ded if f["type"] == "business_fault")
            rt = sum(1 for f in ded if f["type"] == "runtime_error")
            lines.append("| {} | {} | {} | {} |".format(r["case"], "FAIL" if r["faults"] else "PASS", biz, rt))
        lines += ["", "## 二、业务异常汇总 (跨案例去重)", ""]
        all_biz = [f for r in self.batch_results for f in r["faults"] if f["type"] == "business_fault"]
        dbiz = self._dedup(all_biz)
        if dbiz:
            lines += ["| 故障码 | 故障描述 | 出现次数 |", "|--------|----------|----------|"]
            for f in dbiz:
                lines.append("| {} | {} | {} |".format(f["code"], f["message"][:100], f["count"]))
        else:
            lines.append("无业务异常")
        lines += ["", "## 三、运行时错误汇总 (跨案例去重)", ""]
        all_rt = [f for r in self.batch_results for f in r["faults"] if f["type"] == "runtime_error"]
        drt = self._dedup(all_rt)
        if drt:
            lines += ["| 来源 | 错误信息 | 出现次数 |", "|------|----------|----------|"]
            for f in drt:
                lines.append("| {} | {} | {} |".format(f["source"], f["message"][:100], f["count"]))
        else:
            lines.append("无运行时错误")
        lines += ["", "## 四、各案例详情", ""]
        for r in self.batch_results:
            lines += ["### {}".format(r["case"]), "", "- 超时设置: {}秒".format(r["deadline"]), ""]
            ded = self._dedup(r["faults"])
            if not ded:
                lines += ["**结果: PASS** - 未检测到异常", ""]
            else:
                lines += ["**结果: FAIL**", ""]
                for f in ded:
                    lines.append("- [{}] {} (x{})".format(f["code"], f["message"][:120], f["count"]))
            lines += ["---", ""]
        with open(report_path, "w", encoding="utf-8") as fp:
            fp.write("\n".join(lines))
        self._log_safe("测试报告已生成: {}".format(report_path), tag="ok")

    def _batch_stop(self):
        def flow():
            cont = "fz1"
            self._log_safe("停止批量 (停 AD 并清理容器)...")
            _host_sh("docker exec {} bash -c 'pkill -f simulation_launch || true; pkill -f ros2 || true'".format(cont))
            _host_sh("docker rm -f {}".format(cont))
            self._log_safe("已清理容器 {}".format(cont))
        if self._flow_lock.acquire(blocking=False):
            threading.Thread(target=lambda: self._worker_wrap(flow), daemon=True).start()
        else:
            def flow2():
                self._log_safe("等待当前案例结束后停止...", tag="warn")
                _host_sh("docker rm -f fz1")
                self._log_safe("已强制删除 fz1")
            self._run_worker(flow2)

    def _batch_report(self):
        if getattr(self, "batch_results", None):
            self._batch_generate_report(self._batch_case_dirs())
        else:
            self._update_log("还没有批量测试结果, 先运行批量测试", tag="warn")

    def _batch_clean(self):
        def flow():
            _host_sh("docker rm -f fz1")
            self._log_safe("已删除容器 fz1")
        self._run_worker(flow)

    def _on_back(self):
        self._running = False
        self._ask_event.set()
        self.on_back()


# ---------------------------------------------------------------------------
# OrinFlashPage (from main.py / auto_flash_orin.sh)
# ---------------------------------------------------------------------------

ORIN_IMAGE_BASE_DIR = os.path.expanduser("~/robotruck")
ORIN_IMAGE_DOWNLOAD_URL = "https://ug.link/drivingcontrol"
ORIN_DOWNLOAD_USERNAME = "boonray"
ORIN_DOWNLOAD_PASSWORD = "Password1!"

ORIN_IMAGES_CONFIG = [
    ("ROS1_64_Before2026", "ROS1_64_Before2026", "before2026"),
    ("ROS1_64_After2026", "ROS1_64_After2026", "after2026"),
    ("ROS2_Ubuntu22.04", "ROS2_Ubuntu22.04", "ros2"),
]


class OrinFlashPage:

    """ NVIDIA Orin 工控机烧录工具 (main.py / auto_flash_orin.sh) """

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self._log_text = None
        self._running = True

        self.is_running = False
        self.selected_image_path = ""
        self.selected_flash_mode = ""
        self.process = None
        self.stop_flag = False

        self._create_gui()
        self.scan_images()

    # ================================ UI ================================
    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Button(title_frame, text="← 返回首页", command=self._on_back).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="NVIDIA Orin 烧录",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        ttk.Label(title_frame, text="镜像扫描 / 整机烧录",
                  foreground="#888").pack(side=tk.LEFT)
        self._status_var = tk.StringVar(value="就绪")
        ttk.Label(title_frame, textvariable=self._status_var,
                  foreground="gray", font=("", 10, "bold")).pack(side=tk.RIGHT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ---------- 镜像选择 ----------
        img = ttk.LabelFrame(body, text="镜像选择", padding="12 8 12 8")
        img.pack(fill=tk.X, padx=12, pady=6)
        row = ttk.Frame(img); row.pack(fill=tk.X, pady=4)
        self.image_listbox = tk.Listbox(row, height=4, font=("Consolas", 10))
        self.image_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(row, orient=tk.VERTICAL, command=self.image_listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.image_listbox.config(yscrollcommand=sb.set)
        self.image_listbox.bind('<<ListboxSelect>>', self.on_image_select)

        info = ttk.Frame(img); info.pack(fill=tk.X, pady=(6, 0))
        self.image_path_label = ttk.Label(info, text="镜像路径: 未选择", foreground="gray")
        self.image_path_label.pack(anchor=tk.W)
        self.flash_mode_label = ttk.Label(info, text="烧录模式: 未选择", foreground="gray")
        self.flash_mode_label.pack(anchor=tk.W)

        row2 = ttk.Frame(img); row2.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(row2, text="刷新镜像列表", command=self.scan_images).pack(side=tk.LEFT, padx=4)
        ttk.Button(row2, text="打开镜像目录", command=self.open_image_dir).pack(side=tk.LEFT, padx=4)
        self.flash_button = ttk.Button(row2, text="开始烧录", command=self.start_flash,
                                       state=tk.DISABLED)
        self.flash_button.pack(side=tk.LEFT, padx=4)
        self.stop_button = ttk.Button(row2, text="停止烧录", command=self.stop_flash,
                                      state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=4)

        tip = ttk.LabelFrame(body, text="下载提示", padding="12 8 12 8")
        tip.pack(fill=tk.X, padx=12, pady=6)
        ttk.Label(tip, justify=tk.LEFT, text=(
            "镜像下载地址: {}  用户名: {}  密码: {}\n"
            "下载后解压到: {}".format(ORIN_IMAGE_DOWNLOAD_URL,
                                     ORIN_DOWNLOAD_USERNAME,
                                     ORIN_DOWNLOAD_PASSWORD,
                                     ORIN_IMAGE_BASE_DIR))).pack(anchor=tk.W)

        # ---------- 日志 ----------
        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=14, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("INFO", foreground="#0a0")
        self._log_text.tag_configure("ERROR", foreground="red")
        self._log_text.tag_configure("WARN", foreground="#a60")
        self._log_text.tag_configure("STEP", foreground="#06c", font=("Consolas", 9, "bold"))
        self._log_text.tag_configure("SUCCESS", foreground="#0a0", font=("Consolas", 9, "bold"))
        ttk.Button(log_frame, text="清空日志", command=self.clear_log).pack(anchor=tk.E, pady=(5, 0))

        self._log("NVIDIA Orin 烧录页已启动")

    # ============================== 日志 ==============================
    def _log(self, message, tag="INFO"):
        try:
            self.root.after(0, lambda: self._log_now(message, tag))
        except Exception:
            pass

    def _log_now(self, message, tag="INFO"):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, "[{}] {}\n".format(
                time.strftime("%H:%M:%S"), message), tag)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def log_info(self, m):
        self._log(m, "INFO")

    def log_error(self, m):
        self._log(m, "ERROR")

    def log_warn(self, m):
        self._log(m, "WARN")

    def log_step(self, m):
        sep = "━" * 50
        self._log("\n{}\n[STEP] {}\n{}\n".format(sep, m, sep), "STEP")

    def log_success(self, m):
        self._log("✓ " + m, "SUCCESS")

    def clear_log(self):
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.delete(1.0, tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def set_status(self, m):
        try:
            self.root.after(0, lambda: self._status_var.set(m))
        except Exception:
            pass

    # ============================== 镜像 ==============================
    def scan_images(self):
        self.log_step("扫描镜像目录")
        try:
            os.makedirs(ORIN_IMAGE_BASE_DIR, exist_ok=True)
        except Exception:
            pass
        try:
            self.image_listbox.delete(0, tk.END)
        except Exception:
            pass
        self.image_paths = []
        self.image_modes = []
        self.image_names = []
        found = 0
        for dir_name, display_name, flash_mode in ORIN_IMAGES_CONFIG:
            image_path = os.path.join(ORIN_IMAGE_BASE_DIR, dir_name)
            if os.path.isdir(image_path):
                self.image_listbox.insert(tk.END, display_name)
                self.image_paths.append(image_path)
                self.image_modes.append(flash_mode)
                self.image_names.append(display_name)
                found += 1
                self.log_success("找到镜像: {}".format(display_name))
        if found == 0:
            try:
                self.flash_button.config(state=tk.DISABLED)
            except Exception:
                pass
            self.log_warn("未找到任何镜像文件夹")
        self.log_info("下载地址: {}  用户名: {}  密码: {}".format(
            ORIN_IMAGE_DOWNLOAD_URL, ORIN_DOWNLOAD_USERNAME, ORIN_DOWNLOAD_PASSWORD))
        self.log_info("下载后解压到: {}".format(ORIN_IMAGE_BASE_DIR))
        self.set_status("找到 {} 个镜像".format(found))

    def open_image_dir(self):
        subprocess = __import__("subprocess")
        try:
            os.makedirs(ORIN_IMAGE_BASE_DIR, exist_ok=True)
        except Exception:
            pass
        try:
            subprocess.Popen(["nautilus", ORIN_IMAGE_BASE_DIR])
        except Exception:
            try:
                subprocess.Popen(["xdg-open", ORIN_IMAGE_BASE_DIR])
            except Exception:
                self.log_error("无法打开文件管理器: " + ORIN_IMAGE_BASE_DIR)

    def on_image_select(self, event):
        try:
            selection = self.image_listbox.curselection()
        except Exception:
            return
        if not selection:
            return
        index = selection[0]
        self.selected_image_path = self.image_paths[index]
        self.selected_flash_mode = self.image_modes[index]
        self.image_path_label.config(text="镜像路径: {}".format(self.selected_image_path),
                                     foreground="black")
        self.flash_mode_label.config(text="烧录模式: {}".format(self.selected_flash_mode),
                                     foreground="black")
        self.flash_button.config(state=tk.NORMAL)
        self.log_success("已选择: {}".format(self.image_names[index]))
        self.log_info("烧录模式: {}".format(self.selected_flash_mode))

    # ============================== 设备/环境 ==============================
    def check_device(self):
        import subprocess
        import re
        self.log_step("检查工控机连接状态")
        for i in range(3):
            self.log_info("lsusb (尝试 {}/3)".format(i + 1))
            try:
                result = subprocess.run(["lsusb"], capture_output=True, text=True)
                self._log(result.stdout or "   (无输出)", "INFO")
                if re.search(r"NVIDIA Corp", result.stdout, re.I):
                    for line in result.stdout.split("\n"):
                        if "NVIDIA Corp" in line:
                            self._log("  " + line, "INFO")
                    self.log_success("已检测到 NVIDIA Corp 设备")
                    return True
            except Exception as e:
                self.log_error("lsusb 失败: {}".format(e))
            if i < 2:
                self.log_warn("未检测到设备, 2 秒后重试...")
                time.sleep(2)
        self.log_error("未检测到 NVIDIA Corp 设备")
        self.log_info("请确认: 1.工控机已进入烧录模式 2.USB线已连接 3.已通电 4.重新拔插USB")
        return False

    def setup_python(self):
        import subprocess
        self.log_step("配置电脑 Python 环境...")
        try:
            subprocess.run(["python2", "--version"], capture_output=True, check=True)
            self.log_success("python2 已安装")
        except Exception:
            self.log_warn("python2 未安装, 开始安装 (sudo apt install python2)...")
            try:
                subprocess.run(["sudo", "apt", "update"], check=True)
                subprocess.run(["sudo", "apt", "install", "-y", "python2"], check=True)
                self.log_success("python2 安装完成")
            except Exception as e:
                self.log_error("安装 python2 失败: {}".format(e))
                return False
        try:
            subprocess.run(["python", "--version"], capture_output=True, check=True)
            self.log_success("python 命令已存在")
        except Exception:
            self.log_warn("创建 python -> python2 软链接...")
            try:
                subprocess.run(["sudo", "rm", "-f", "/usr/bin/python"], check=True)
                subprocess.run(["sudo", "ln", "-sf", "/usr/bin/python2",
                                "/usr/bin/python"], check=True)
                self.log_success("软链接已创建")
            except Exception as e:
                self.log_error("创建软链接失败: {}".format(e))
                return False
        self.log_success("Python 环境配置正确")
        return True

    # ============================== 烧录 ==============================
    def extract_dram_and_emmc(self, work_dir):
        import subprocess
        import glob
        self.log_step("解压镜像包...")
        try:
            os.chdir(work_dir)
        except Exception as e:
            self.log_error(str(e))
        dram = glob.glob("t234-dram-package-*.tbz2")
        if dram:
            self.log_info("解压 dram 包: {}".format(dram[0]))
            try:
                subprocess.run(["sudo", "tar", "-xpf", dram[0]], check=True)
                self.log_success("dram 包解压完成")
            except Exception as e:
                self.log_error("解压 dram 包失败: {}".format(e))
                return False
        else:
            self.log_warn("未找到 dram 包")
        emmc = glob.glob("t234-pcn*-emmc-*.tbz2")
        if emmc:
            self.log_info("解压 emmc 包: {}".format(emmc[0]))
            try:
                subprocess.run(["sudo", "tar", "-xpf", emmc[0]], check=True)
                self.log_success("emmc 包解压完成")
            except Exception as e:
                self.log_error("解压 emmc 包失败: {}".format(e))
                return False
        else:
            self.log_warn("未找到 emmc 包")
        return True

    def run_expect_script(self, menu_key):
        import subprocess
        try:
            subprocess.run(["which", "expect"], capture_output=True, check=True)
        except Exception:
            self.log_error("expect 未安装, 请先安装: sudo apt install expect")
            return False
        script = (
            "set timeout 3600\n"
            "log_user 1\n"
            "spawn sudo ./tztek_flash.sh\n"
            "after 3000 { send \"%s\\r\" }\n"
            "after 6000 { send \"6\\r\" }\n"
            "after 8000 { send \"yes\\r\" }\n"
            "expect eof\n" % menu_key)
        self._log("烧录菜单选择: {} -> 6 -> yes".format(menu_key), "INFO")
        try:
            self.process = subprocess.Popen(
                ["sudo", "expect", "-c", script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            for line in self.process.stdout:
                self._log(line.rstrip(), "INFO")
                if self.stop_flag:
                    self.process.terminate()
                    break
            self.process.wait()
            if self.process.returncode == 0:
                self.log_success("烧录完成!")
                return True
            self.log_error("烧录失败, 退出码: {}".format(self.process.returncode))
            return False
        except Exception as e:
            self.log_error("执行烧录命令失败: {}".format(e))
            return False

    def flash_before2026(self):
        import subprocess
        linux_dir = os.path.join(self.selected_image_path, "Linux_for_Tegra")
        if not os.path.isdir(linux_dir):
            self.log_error("找不到 Linux_for_Tegra 目录: {}".format(linux_dir))
            return False
        self.log_step("执行烧录 (Before2026)")
        os.chdir(linux_dir)
        return self.run_expect_script("8")

    def flash_after2026(self):
        import subprocess
        self.log_step("After2026: 解压/挂载/依赖/initrd 后烧录")
        image_path = self.selected_image_path
        os.chdir(image_path)
        if not os.path.isfile("system.img.raw") or not os.path.isdir("Linux_for_Tegra"):
            self.log_error("缺少 system.img.raw 或 Linux_for_Tegra, 无法继续")
            return False
        if not self.extract_dram_and_emmc(image_path):
            return False
        try:
            os.makedirs("Linux_for_Tegra/rootfs", exist_ok=True)
            subprocess.run(["sudo", "mount", "system.img.raw",
                            "Linux_for_Tegra/rootfs/"], check=True)
            self.log_success("系统镜像已挂载")
        except Exception as e:
            self.log_error("挂载镜像失败: {}".format(e))
            return False
        subprocess.run(["sudo", "systemctl", "stop", "udisks2.service"], capture_output=True)
        self.log_success("USB 外部存储已禁用")
        if not os.path.isfile("Linux_for_Tegra/tools/l4t_flash_prerequisites.sh"):
            self.log_error("找不到 l4t_flash_prerequisites.sh")
            return False
        os.chdir("Linux_for_Tegra/tools")
        try:
            subprocess.run(["sudo", "./l4t_flash_prerequisites.sh"], check=True)
            self.log_success("依赖项安装完成")
        except Exception as e:
            self.log_error("依赖项安装失败: {}".format(e))
            return False
        os.chdir("../..")
        os.chdir("Linux_for_Tegra")
        try:
            subprocess.run(["sudo", "./tools/l4t_update_initrd.sh"], check=True)
            self.log_success("initrd 更新完成")
        except Exception as e:
            self.log_error("initrd 更新失败: {}".format(e))
            return False
        os.chdir("..")
        os.chdir("Linux_for_Tegra")
        return self.run_expect_script("8")

    def flash_ros2(self):
        import subprocess
        self.log_step("ROS2: 解压/挂载/依赖/initrd 后烧录")
        image_path = self.selected_image_path
        os.chdir(image_path)
        if not os.path.isfile("system.img.raw") or not os.path.isdir("Linux_for_Tegra"):
            self.log_error("缺少 system.img.raw 或 Linux_for_Tegra, 无法继续")
            return False
        if not self.extract_dram_and_emmc(image_path):
            return False
        try:
            os.makedirs("Linux_for_Tegra/rootfs", exist_ok=True)
            subprocess.run(["sudo", "mount", "system.img.raw",
                            "Linux_for_Tegra/rootfs/"], check=True)
            self.log_success("系统镜像已挂载")
        except Exception as e:
            self.log_error("挂载镜像失败: {}".format(e))
            return False
        subprocess.run(["sudo", "systemctl", "stop", "udisks2.service"], capture_output=True)
        self.log_success("USB 外部存储已禁用")
        if not os.path.isfile("Linux_for_Tegra/tools/l4t_flash_prerequisites.sh"):
            self.log_error("找不到 l4t_flash_prerequisites.sh")
            return False
        os.chdir("Linux_for_Tegra/tools")
        try:
            subprocess.run(["sudo", "./l4t_flash_prerequisites.sh"], check=True)
            self.log_success("依赖项安装完成")
        except Exception as e:
            self.log_error("依赖项安装失败: {}".format(e))
            return False
        os.chdir("../..")
        os.chdir("Linux_for_Tegra")
        try:
            subprocess.run(["sudo", "./tools/l4t_update_initrd.sh"], check=True)
            self.log_success("initrd 更新完成")
        except Exception as e:
            self.log_error("initrd 更新失败: {}".format(e))
            return False
        os.chdir("..")
        os.chdir("Linux_for_Tegra")
        return self.run_expect_script("7")

    # ============================== 流程 ==============================
    def start_flash(self):
        if self.is_running:
            return
        if not self.selected_image_path:
            self._log("请先选择一个镜像", "ERROR")
            return
        self.is_running = True
        self.stop_flag = False
        self.flash_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.image_listbox.config(state=tk.DISABLED)
        threading.Thread(target=self._flash_thread, daemon=True).start()

    def _flash_thread(self):
        self._log("", "INFO")
        self._log("━━━ NVIDIA Orin 工控机烧录工具 ━━━".center(40), "STEP")
        success = False
        try:
            self.set_status("配置 Python 环境...")
            if not self.setup_python():
                self.set_status("Python 环境配置失败")
                return
            self.set_status("检查设备连接...")
            if not self.check_device():
                self.set_status("设备检查失败")
                return
            self.set_status("烧录: {}".format(self.selected_flash_mode))
            funcs = {"before2026": self.flash_before2026,
                     "after2026": self.flash_after2026,
                     "ros2": self.flash_ros2}
            fn = funcs.get(self.selected_flash_mode)
            success = fn() if fn else False
            if success:
                self.set_status("烧录完成")
                self.log_success("烧录程序已完成所有步骤")
                self.log_info("后续: 1.等待工控机重启 2.升级内核 3.ROS2配置SN和设备名 4.检查网口IP 5.重启")
            else:
                self.set_status("烧录失败")
        except Exception as e:
            self.log_error("烧录过程异常: {}".format(e))
            self.set_status("烧录异常")
        finally:
            self.is_running = False
            self.flash_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.image_listbox.config(state=tk.NORMAL)
            if not success:
                self.flash_button.config(state=tk.DISABLED)

    def stop_flash(self):
        if self.process:
            self.stop_flag = True
            self.log_warn("正在停止烧录...")
            try:
                self.process.terminate()
            except Exception:
                pass
            self.set_status("已停止")

    def _on_back(self):
        self._running = False
        if self.is_running:
            self.stop_flag = True
            try:
                if self.process:
                    self.process.terminate()
            except Exception:
                pass
        self.on_back()


# ---------------------------------------------------------------------------
# NetworkPage (from network.sh / network1.sh)
# ---------------------------------------------------------------------------

class NetworkPage:

    """ tc 流量控制: 入口 UDP 延迟注入 / 清理 """

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self._running = True
        self._log_text = None
        self._create_gui()
        self._update_log("网络工具页已启动 (tc 延迟注入/清理)")

    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Button(title_frame, text="← 返回首页", command=self._on_back).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="网络工具",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        ttk.Label(title_frame, text="tc 入口 UDP 延迟注入",
                  foreground="#888").pack(side=tk.LEFT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        cfg = ttk.LabelFrame(body, text="配置", padding="12 8 12 8")
        cfg.pack(fill=tk.X, padx=12, pady=6)
        row = ttk.Frame(cfg); row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text="网卡:").pack(side="left")
        self.iface_var = tk.StringVar(value="eno2np1")
        ttk.Entry(row, textvariable=self.iface_var, width=16).pack(side="left", padx=5)
        ttk.Label(row, text="入口延迟(ms):").pack(side="left", padx=(12, 0))
        self.delay_var = tk.StringVar(value="5000")
        ttk.Entry(row, textvariable=self.delay_var, width=8).pack(side="left", padx=5)
        ttk.Button(row, text="注入延迟", command=self._inject).pack(side="left", padx=8)
        ttk.Button(row, text="清理恢复", command=self._clean).pack(side="left", padx=4)

        info = ttk.LabelFrame(body, text="说明", padding="12 8 12 8")
        info.pack(fill=tk.X, padx=12, pady=6)
        ttk.Label(info, justify=tk.LEFT, foreground="#555", text=(
            "原理 (network.sh):\n"
            "  modprobe ifb → eno2np1 上挂 ingress qdisc → u32 过滤入站 UDP(协议17) 重定向 ifb0\n"
            "  → ifb0 上 netem delay 注入入口延迟\n"
            "清理 (network1.sh): 删除 ingress / ifb0 的 qdisc 并 down 掉 ifb0\n"
            "注意: 需要 sudo 权限, 若当前不是 root, 命令会要求输入 sudo 密码。")).pack(anchor=tk.W)

        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=12, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("ok", foreground="#0a0")

    def _run(self, cmds):
        import subprocess
        for cmd in cmds:
            self._update_log(">>> {}".format(cmd))
            r = subprocess.run(cmd, shell=True, text=True,
                               capture_output=True)
            if r.stdout.strip():
                self._update_log(r.stdout.strip())
            if r.stderr.strip():
                self._update_log(r.stderr.strip(), "error")
            if r.returncode != 0:
                self._update_log("命令返回码: {} (如需权限请用 sudo 启动)".format(
                    r.returncode), "error")
            else:
                time.sleep(0.3)

    def _inject(self):
        iface = self.iface_var.get().strip() or "eno2np1"
        try:
            delay = int(self.delay_var.get().strip())
        except ValueError:
            self._update_log("延迟必须是整数(ms)", "error")
            return
        self._run([
            "sudo modprobe ifb numifbs=1",
            "sudo ip link set up dev ifb0",
            "sudo tc qdisc add dev {} ingress 2>/dev/null || true".format(iface),
            "sudo tc filter del dev {} ingress protocol ip prio 49152 2>/dev/null || true".format(iface),
            "sudo tc filter add dev {} ingress protocol ip prio 49152 u32 "
            "match ip protocol 17 0xff action mirred egress redirect dev ifb0".format(iface),
            "sudo tc qdisc del dev ifb0 root 2>/dev/null || true",
            "sudo tc qdisc add dev ifb0 root netem delay {}ms".format(delay),
        ])
        self._update_log("UDP 入口流量延迟 {}ms 已注入 (网卡 {})".format(delay, iface), "ok")

    def _clean(self):
        self._run([
            "sudo tc qdisc del dev {} ingress 2>/dev/null || true".format(self.iface_var.get().strip() or "eno2np1"),
            "sudo tc qdisc del dev ifb0 root 2>/dev/null || true",
            "sudo ip link set down dev ifb0",
        ])
        self._update_log("已清理所有流量控制规则, 网络恢复正常", "ok")

    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _on_back(self):
        self._running = False
        self.on_back()


# ---------------------------------------------------------------------------
# CloudToolsPage (from CloudPlantProject: UDP灯态 + MQTT + TCP)
# ---------------------------------------------------------------------------

CLOUD_DEFAULT_YAML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "CloudPlantProject", "yaml_data")
if not os.path.isdir(CLOUD_DEFAULT_YAML_DIR):
    CLOUD_DEFAULT_YAML_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "CloudPlantProject", "yaml_data")

CLOUD_MQTT_DEFAULTS = {
    "host": "106.14.223.60",
    "port": 1883,
    "client_id": "mock_tools_mqtt",
    "username": "ds",
    "password": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJib29ucmF5IiwiZXhwIjo0NzkzNjcwMDIxLCJ1c2VyX2lkIjozLCJyb2xlX2xldmVsIjoxLCJwcm9qZWN0X2lkcyI6W119.2X9l7TcTA-T9iYRon0lkCqfRCSDRTv7qbYXa1J6bLS4",
    "keepalive": 60,
}


class CloudToolsPage:

    """ 云平台工具: UDP灯态 / MQTT 发布与回放 / TCP 收发 """

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self._running = True
        self._log_text = None

        self._mqtt = None
        self._mqtt_connected = False
        self._tcp_sock = None
        self._tcp_thread = None
        self._tcp_connected = False
        self._udp_cycle = False

        self._create_gui()
        self._update_log("云平台工具页已启动 (UDP灯态 / MQTT / TCP)")

    # ================================ UI ================================
    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Button(title_frame, text="← 返回首页", command=self._on_back).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="云平台工具",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        ttk.Label(title_frame, text="UDP灯态 / MQTT / TCP",
                  foreground="#888").pack(side=tk.LEFT)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        # ---------- UDP 灯态 ----------
        udp = ttk.LabelFrame(body, text="UDP 灯态上报 (1@ rt_message)", padding="12 8 12 8")
        udp.pack(fill=tk.X, padx=12, pady=6)
        r0 = ttk.Frame(udp); r0.pack(fill=tk.X, pady=4)
        ttk.Label(r0, text="目标IP:").pack(side="left")
        self.udp_ip_var = tk.StringVar(value="106.14.223.60")
        ttk.Entry(r0, textvariable=self.udp_ip_var, width=16).pack(side="left", padx=5)
        ttk.Label(r0, text="端口:").pack(side="left", padx=(10, 0))
        self.udp_port_var = tk.StringVar(value="1234")
        ttk.Entry(r0, textvariable=self.udp_port_var, width=6).pack(side="left", padx=5)
        ttk.Label(r0, text="SN:").pack(side="left", padx=(10, 0))
        self.udp_sn_var = tk.StringVar(value="psz_light")
        ttk.Entry(r0, textvariable=self.udp_sn_var, width=16).pack(side="left", padx=5)
        ttk.Label(r0, text="灯态:").pack(side="left", padx=(10, 0))
        self.udp_state_var = tk.StringVar(value="1")
        ttk.Combobox(r0, textvariable=self.udp_state_var, width=4, state="readonly",
                     values=["1", "2", "3", "4"]).pack(side="left")
        r1 = ttk.Frame(udp); r1.pack(fill=tk.X, pady=4)
        ttk.Label(r1, text="持续(秒,0=一次):").pack(side="left")
        self.udp_dur_var = tk.StringVar(value="0")
        ttk.Entry(r1, textvariable=self.udp_dur_var, width=6).pack(side="left", padx=5)
        ttk.Label(r1, text="间隔(秒):").pack(side="left", padx=(10, 0))
        self.udp_interval_var = tk.StringVar(value="1")
        ttk.Entry(r1, textvariable=self.udp_interval_var, width=6).pack(side="left", padx=5)
        ttk.Button(r1, text="发送一次", command=self._udp_send_once).pack(side="left", padx=4)
        ttk.Button(r1, text="持续发送", command=self._udp_start).pack(side="left", padx=4)
        self._udp_stop_btn = ttk.Button(r1, text="停止", command=self._udp_stop,
                                        state=tk.DISABLED)
        self._udp_stop_btn.pack(side="left", padx=4)

        # ---------- MQTT ----------
        mq = ttk.LabelFrame(body, text="MQTT (paho-mqtt)", padding="12 8 12 8")
        mq.pack(fill=tk.X, padx=12, pady=6)
        r2 = ttk.Frame(mq); r2.pack(fill=tk.X, pady=4)
        ttk.Label(r2, text="Host:").pack(side="left")
        self.mq_host_var = tk.StringVar(value=CLOUD_MQTT_DEFAULTS["host"])
        ttk.Entry(r2, textvariable=self.mq_host_var, width=16).pack(side="left", padx=4)
        ttk.Label(r2, text="Port:").pack(side="left")
        self.mq_port_var = tk.StringVar(value=str(CLOUD_MQTT_DEFAULTS["port"]))
        ttk.Entry(r2, textvariable=self.mq_port_var, width=6).pack(side="left", padx=4)
        ttk.Label(r2, text="client_id:").pack(side="left")
        self.mq_cid_var = tk.StringVar(value=CLOUD_MQTT_DEFAULTS["client_id"])
        ttk.Entry(r2, textvariable=self.mq_cid_var, width=20).pack(side="left", padx=4)
        self._mq_status_var = tk.StringVar(value="未连接")
        ttk.Label(r2, textvariable=self._mq_status_var, foreground="#555"
                  ).pack(side="left", padx=10)
        self._mq_conn_btn = ttk.Button(r2, text="连接", command=self._mq_connect)
        self._mq_conn_btn.pack(side="left", padx=3)
        self._mq_disc_btn = ttk.Button(r2, text="断开", command=self._mq_disconnect,
                                       state=tk.DISABLED)
        self._mq_disc_btn.pack(side="left", padx=3)
        r3 = ttk.Frame(mq); r3.pack(fill=tk.X, pady=4)
        ttk.Label(r3, text="用户名:").pack(side="left")
        self.mq_user_var = tk.StringVar(value=CLOUD_MQTT_DEFAULTS["username"])
        ttk.Entry(r3, textvariable=self.mq_user_var, width=12).pack(side="left", padx=4)
        ttk.Label(r3, text="密码/Token:").pack(side="left")
        self.mq_pass_var = tk.StringVar(value=CLOUD_MQTT_DEFAULTS["password"])
        ttk.Entry(r3, textvariable=self.mq_pass_var, width=46).pack(side="left", padx=4)
        ttk.Label(r3, text="keepalive:").pack(side="left")
        self.mq_keep_var = tk.StringVar(value=str(CLOUD_MQTT_DEFAULTS["keepalive"]))
        ttk.Entry(r3, textvariable=self.mq_keep_var, width=5).pack(side="left", padx=4)
        r4 = ttk.Frame(mq); r4.pack(fill=tk.X, pady=4)
        ttk.Label(r4, text="Topic:").pack(side="left")
        self.mq_topic_var = tk.StringVar(
            value="report/55722339745601/robotruck_mock_truck/fault")
        ttk.Entry(r4, textvariable=self.mq_topic_var, width=52).pack(side="left", padx=4)
        ttk.Button(r4, text="发布(JSON payload 在下面)", command=self._mq_publish).pack(side="left", padx=4)
        r5 = ttk.Frame(mq); r5.pack(fill=tk.X, pady=4)
        self.mq_payload_text = tk.Text(r5, height=5, width=100, font=("Consolas", 9))
        self.mq_payload_text.pack(side="left", fill=tk.BOTH, expand=True)
        self.mq_payload_text.insert("1.0", json.dumps(
            {"faults": [{"code": "103060", "message": "开始任务失败"}],
             "timestamp": "@time", "in_task": 1}, indent=2))
        r6 = ttk.Frame(mq); r6.pack(fill=tk.X, pady=(6, 0))
        ttk.Label(r6, text="YAML 回放:").pack(side="left")
        self.mq_yaml_var = tk.StringVar()
        self.mq_yaml_combo = ttk.Combobox(r6, textvariable=self.mq_yaml_var,
                                          state="readonly", width=34)
        self.mq_yaml_combo.pack(side="left", padx=4)
        self._refresh_yaml_list()
        ttk.Button(r6, text="刷新", command=self._refresh_yaml_list).pack(side="left", padx=3)
        ttk.Button(r6, text="浏览...", command=self._yaml_browse).pack(side="left", padx=3)
        ttk.Button(r6, text="连接后回放", command=self._mq_replay).pack(side="left", padx=6)

        # ---------- TCP ----------
        tc = ttk.LabelFrame(body, text="TCP (json\\n 行协议)", padding="12 8 12 8")
        tc.pack(fill=tk.X, padx=12, pady=6)
        r7 = ttk.Frame(tc); r7.pack(fill=tk.X, pady=4)
        ttk.Label(r7, text="Host:").pack(side="left")
        self.tcp_host_var = tk.StringVar(value="106.14.223.60")
        ttk.Entry(r7, textvariable=self.tcp_host_var, width=16).pack(side="left", padx=4)
        ttk.Label(r7, text="Port:").pack(side="left")
        self.tcp_port_var = tk.StringVar(value="5555")
        ttk.Entry(r7, textvariable=self.tcp_port_var, width=8).pack(side="left", padx=4)
        self._tcp_status_var = tk.StringVar(value="未连接")
        ttk.Label(r7, textvariable=self._tcp_status_var, foreground="#555"
                  ).pack(side="left", padx=10)
        ttk.Button(r7, text="连接", command=self._tcp_connect).pack(side="left", padx=3)
        ttk.Button(r7, text="断开", command=self._tcp_disconnect,
                   state=tk.DISABLED).pack(side="left", padx=3)
        ttk.Label(r7, text="订阅topic:").pack(side="left", padx=(10, 0))
        self.tcp_sub_var = tk.StringVar(value="")
        ttk.Entry(r7, textvariable=self.tcp_sub_var, width=20).pack(side="left", padx=4)
        r8 = ttk.Frame(tc); r8.pack(fill=tk.X, pady=4)
        ttk.Label(r8, text="发送topic:").pack(side="left")
        self.tcp_topic_var = tk.StringVar(value="command/56955550355457/fz_c01/request/start_task")
        ttk.Entry(r8, textvariable=self.tcp_topic_var, width=40).pack(side="left", padx=4)
        ttk.Label(r8, text="payload:").pack(side="left", padx=(10, 0))
        self.tcp_payload_var = tk.StringVar(value="{}")
        ttk.Entry(r8, textvariable=self.tcp_payload_var, width=36).pack(side="left", padx=4)
        ttk.Button(r8, text="发送", command=self._tcp_send).pack(side="left", padx=4)

        # ---------- 日志 ----------
        log_frame = ttk.LabelFrame(body, text="日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=12, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("ok", foreground="#0a0")

    def _refresh_yaml_list(self):
        try:
            files = sorted([f for f in os.listdir(CLOUD_DEFAULT_YAML_DIR)
                            if f.endswith(".yaml") or f.endswith(".yml")])
        except Exception:
            files = []
        if self.mq_yaml_combo is not None:
            self.mq_yaml_combo["values"] = files
            if files:
                self.mq_yaml_var.set(files[0])
        self._yaml_dir = CLOUD_DEFAULT_YAML_DIR

    def _yaml_browse(self):
        from tkinter import filedialog
        p = filedialog.askopenfilename(initialdir=getattr(self, "_yaml_dir", "~"),
                                       filetypes=(("yaml", "*.yaml *.yml"), ("all", "*.*")))
        if p:
            self.mq_yaml_var.set("【自定义】" + p)
            self._custom_yaml = p

    # ============================== 日志 ==============================
    def _log_safe(self, message, tag="info"):
        try:
            self.root.after(0, lambda: self._update_log(message, tag))
        except Exception:
            pass

    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    # ============================== UDP ==============================
    def _udp_send_once(self):
        try:
            state = int(self.udp_state_var.get())
        except ValueError:
            self._log_safe("灯态必须是 1-4", "error")
            return
        self._udp_send_duration(state, 0)

    def _udp_send_duration(self, state, duration):
        ip = self.udp_ip_var.get().strip()
        try:
            port = int(self.udp_port_var.get())
            interval = max(0.1, float(self.udp_interval_var.get()))
        except ValueError:
            self._log_safe("端口/间隔格式错误", "error")
            return
        sn = self.udp_sn_var.get().strip()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        t0 = time.time()
        n = 0
        while True:
            ts = math.floor(time.time())
            content = ('1@{{"method": "rt_message", "params": '
                       '{{"sn": "{}", "light_state": {}, "timestamp": {}}}}}'.format(sn, state, ts))
            sock.sendto(content.encode("utf-8"), (ip, port))
            n += 1
            if duration <= 0 or time.time() - t0 >= duration or not self._running:
                break
            time.sleep(interval)
        sock.close()
        self._log_safe("已发送 {} 条灯态(green=1 red=2 off=3 yellow=4) -> {}:{}".format(n, ip, port), "ok")

    def _udp_start(self):
        self._udp_cycle = True
        self._udp_stop_btn.config(state=tk.NORMAL)
        threading.Thread(target=self._udp_cycle_loop, daemon=True).start()

    def _udp_cycle_loop(self):
        try:
            dur = float(self.udp_dur_var.get())
        except ValueError:
            dur = 0.0
        t0 = time.time()
        while self._running and self._udp_cycle:
            try:
                state = int(self.udp_state_var.get())
            except ValueError:
                state = 1
            try:
                interval = max(0.1, float(self.udp_interval_var.get()))
            except ValueError:
                interval = 1.0
            self._udp_send_duration(state, 0)
            if dur > 0 and time.time() - t0 >= dur:
                self._log_safe("持续发送已按设定时长({:.0f}s)自动结束".format(dur), "ok")
                break
            if not self._running or not self._udp_cycle:
                break
            time.sleep(interval)
        try:
            self.root.after(0, lambda: self._udp_stop_btn.config(state=tk.DISABLED))
        except Exception:
            pass

    def _udp_stop(self):
        self._udp_cycle = False
        self._udp_stop_btn.config(state=tk.DISABLED)
        self._log_safe("已停止 UDP 持续发送")

    # ============================== MQTT ==============================
    def _mq_connect(self):
        def worker():
            try:
                import paho.mqtt.client as mqtt
            except ImportError:
                self._log_safe("缺少 paho-mqtt: pip install paho-mqtt", "error")
                return
            try:
                host = self.mq_host_var.get().strip()
                port = int(self.mq_port_var.get())
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=self.mq_cid_var.get().strip())
            except Exception as e:
                self._log_safe("MQTT 配置错误: {}".format(e), "error")
                return
            user = self.mq_user_var.get().strip()
            pwd = self.mq_pass_var.get().strip()
            if user and pwd:
                client.username_pw_set(user, pwd)

            def on_connect(c, u, f, rc, props=None):
                ok = (rc == 0) or (hasattr(rc, "value") and rc.value == 0)
                if ok:
                    self._mq_connected = True
                    self._mq = c
                    self._log_safe("MQTT 已连接 -> {}:{}".format(host, port), "ok")
                else:
                    self._log_safe("MQTT 连接失败 rc={}".format(rc), "error")

            def on_disconnect(c, u, f, rc=0, props=None):
                self._mq_connected = False
                self._log_safe("MQTT 已断开 (rc={})".format(rc))

            def on_message(c, u, msg):
                try:
                    self._log_safe("[MQTT ↓] {} : {}".format(msg.topic, msg.payload.decode("utf-8", "ignore")))
                except Exception:
                    pass

            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message
            try:
                client.connect(host, port, keepalive=int(self.mq_keep_var.get() or 60))
                client.loop_start()
                self._mq = client
                self._gui_status(self._mq_conn_btn, True)
            except Exception as e:
                self._log_safe("MQTT 连接失败: {}".format(e), "error")
        threading.Thread(target=worker, daemon=True).start()

    def _gui_status(self, conn_btn, connected):
        def upd():
            self._mq_status_var.set("已连接" if connected else "未连接")
            try:
                conn_btn.config(state=tk.DISABLED if connected else tk.NORMAL)
                self._mq_disc_btn.config(state=tk.NORMAL if connected else tk.DISABLED)
            except Exception:
                pass
        try:
            self.root.after(0, upd)
        except Exception:
            pass

    def _mq_disconnect(self):
        def worker():
            try:
                if self._mq is not None:
                    self._mq.loop_stop()
                    self._mq.disconnect()
            except Exception as e:
                self._log_safe("断开异常: {}".format(e), "error")
            self._mq_connected = False
            self._mq = None
            self._gui_status(self._mq_conn_btn, False)
            self._log_safe("MQTT 已断开")
        threading.Thread(target=worker, daemon=True).start()

    def _load_payload(self):
        try:
            return json.loads(self.mq_payload_text.get("1.0", "end").strip())
        except Exception as e:
            self._log_safe("payload 不是合法 JSON: {}".format(e), "error")
            return None

    def _mq_publish(self):
        if not self._mq_connected or self._mq is None:
            self._log_safe("MQTT 未连接", "error")
            return
        payload = self._load_payload()
        if payload is None:
            return
        topic = self.mq_topic_var.get().strip()
        if "@time" in json.dumps(payload):
            self._replace_timestamp(payload)
        try:
            self._mq.publish(topic, json.dumps(payload))
            self._log_safe("已发布 {} : {}".format(topic, payload), "ok")
        except Exception as e:
            self._log_safe("发布失败: {}".format(e), "error")

    def _replace_timestamp(self, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if v == "@time":
                    obj[k] = int(time.time())
                else:
                    self._replace_timestamp(v)
        elif isinstance(obj, list):
            for item in obj:
                self._replace_timestamp(item)

    def _mq_replay(self):
        if not self._mq_connected or self._mq is None:
            self._log_safe("MQTT 未连接", "error")
            return
        try:
            import yaml
        except ImportError:
            self._log_safe("缺少 yaml: pip install pyyaml", "error")
            return
        sel = self.mq_yaml_var.get()
        if sel.startswith("【自定义】"):
            path = getattr(self, "_custom_yaml", "").replace("【自定义】", "")
        else:
            path = os.path.join(CLOUD_DEFAULT_YAML_DIR, sel) if sel else ""
        if not path or not os.path.exists(path):
            self._log_safe("请选择 yaml 文件", "error")
            return
        try:
            data = yaml.safe_load(open(path, encoding="utf-8"))
        except Exception as e:
            self._log_safe("读取 yaml 失败: {}".format(e), "error")
            return
        if isinstance(data, list):
            for item in data:
                topic = item.get("topic", "")
                payload = item.get("payload", "")
                if isinstance(payload, dict):
                    if isinstance(payload.get("params"), dict):
                        payload["params"]["send_at"] = int(time.time())
                    self._replace_timestamp(payload)
                    try:
                        self._mq.publish(topic, json.dumps(payload))
                        self._log_safe("回放 {} : {} {}".format(os.path.basename(path), topic, payload), "ok")
                    except Exception as e:
                        self._log_safe("回放发布失败: {}".format(e), "error")
                else:
                    try:
                        self._mq.publish(topic, "" if payload is None else str(payload))
                    except Exception as e:
                        self._log_safe("回放发布失败: {}".format(e), "error")

    # ============================== TCP ==============================
    def _tcp_connect(self):
        def worker():
            host = self.tcp_host_var.get().strip()
            try:
                port = int(self.tcp_port_var.get())
            except ValueError:
                self._log_safe("端口格式错误", "error")
                return
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(10)
                s.connect((host, port))
            except Exception as e:
                self._log_safe("TCP 连接失败: {}".format(e), "error")
                return
            self._tcp_sock = s
            self._tcp_connected = True
            self._tcp_thread = threading.Thread(target=self._tcp_recv_loop, daemon=True)
            self._tcp_thread.start()
            self._log_safe("TCP 已连接 -> {}:{}".format(host, port), "ok")
            self._tcp_gui(True)
        threading.Thread(target=worker, daemon=True).start()

    def _tcp_gui(self, connected):
        def upd():
            self._tcp_status_var.set("已连接" if connected else "未连接")
        try:
            self.root.after(0, upd)
        except Exception:
            pass

    def _tcp_recv_loop(self):
        buf = b""
        while self._running and self._tcp_connected:
            try:
                data = self._tcp_sock.recv(4096)
                if not data:
                    self._log_safe("TCP 连接已断开")
                    self._tcp_connected = False
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._log_safe("[TCP ↓] " + line.decode("utf-8", "ignore").strip())
            except socket.timeout:
                continue
            except Exception:
                break

    def _tcp_send(self):
        if not self._tcp_connected or self._tcp_sock is None:
            self._log_safe("TCP 未连接", "error")
            return
        try:
            topic = self.tcp_topic_var.get().strip()
            payload = self.tcp_payload_var.get().strip()
            message = json.dumps({"topic": topic, "payload": payload,
                                  "timestamp": int(time.time())}) + "\n"
            self._tcp_sock.sendall(message.encode("utf-8"))
            self._log_safe("已发送 {} : {}".format(topic, payload), "ok")
        except Exception as e:
            self._log_safe("TCP 发送失败: {}".format(e), "error")

    def _tcp_disconnect(self):
        if self._tcp_sock:
            try:
                self._tcp_sock.close()
            except Exception:
                pass
        self._tcp_connected = False
        self._tcp_sock = None
        self._tcp_gui(False)
        self._log_safe("TCP 已断开")

    def _on_back(self):
        self._running = False
        self._udp_cycle = False
        try:
            if self._mq is not None:
                self._mq.loop_stop()
                self._mq.disconnect()
        except Exception:
            pass
        if self._tcp_sock:
            try:
                self._tcp_sock.close()
            except Exception:
                pass
        self.on_back()


# ---------------------------------------------------------------------------
# GoalUpdatePage (from update_new_goal.py, 在容器内执行 rclpy 节点)
# ---------------------------------------------------------------------------

GOAL_NODE_SRC = r'''# -*- coding: utf-8 -*-
import math
import rclpy
from rclpy.node import Node
from robominer_msgs.msg import PlanGoal


class UpdateNewGoal(Node):

    def __init__(self):
        super().__init__('wenrui_test')
        self.goal_id = ''
        self.goal_x = 0.0
        self.goal_y = 0.0
        self.goal_z = 0.0
        self.goal_yaw = 0.0
        self.subscription = self.create_subscription(
            PlanGoal, '/guardian/dump_goal', self.goal_callback, 10)
        self.update_new_goal = self.create_publisher(
            PlanGoal, '/perception/new_dump_goal', 1)

    def goal_callback(self, data):
        self.goal_id = data.goal_id
        self.goal_x = data.goal_x
        self.goal_y = data.goal_y
        self.goal_z = data.goal_z
        self.goal_yaw = data.goal_yaw
        self.get_logger().info('goal_id: %s  point: %s' % (self.goal_id, (data.goal_x, data.goal_y, data.goal_z, data.goal_yaw)))

    def vehicle_2_world(self, xV, yV, zV, yawV, vx, vy, vz, vyaw):
        cyaw = math.cos(math.radians(vyaw))
        syaw = math.sin(math.radians(vyaw))
        xW = cyaw * xV - syaw * yV + vx
        yW = syaw * xV + cyaw * yV + vy
        zW = zV + vz
        yawW = (yawV + vyaw + 180.0) % 360.0 - 180.0
        return xW, yW, zW, yawW

    def work(self):
        while rclpy.ok():
            try:
                value = float(input())
                point = self.vehicle_2_world(
                    value, 0.0, 0.0, 0.0,
                    self.goal_x, self.goal_y, self.goal_z, self.goal_yaw)
                plan_goal = PlanGoal()
                plan_goal.goal_id = self.goal_id
                plan_goal.goal_x = point[0]
                plan_goal.goal_y = point[1]
                plan_goal.goal_z = point[2]
                plan_goal.goal_yaw = point[3]
                plan_goal.is_goal_valid = False
                self.update_new_goal.publish(plan_goal)
                self.get_logger().info('new point: %s' % (point,))
            except ValueError:
                self.get_logger().warn('input invalid')
            except Exception as e:
                self.get_logger().error('error: %s' % (e,))


def main(args=None):
    rclpy.init(args=args)
    node = UpdateNewGoal()
    import threading
    t = threading.Timer(0.5, function=node.work)
    t.daemon = True
    t.start()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
'''


class GoalUpdatePage:

    """ 目标点更新 (update_new_goal.py): 订阅 dump_goal, 平移后发布到 new_dump_goal """

    def __init__(self, root, on_back):
        self.root = root
        self.on_back = on_back
        self._running = True
        self._log_text = None
        self._proc = None
        self._reader = None

        self._create_gui()
        self._update_log("目标点更新页已启动 (容器内运行 rclpy 节点)")

    def _create_gui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        scroll = ScrollFrame(main_frame)
        scroll.pack(fill=tk.BOTH, expand=True)
        body = scroll.body

        title_frame = ttk.Frame(body)
        title_frame.pack(fill=tk.X, padx=12, pady=(10, 0))
        ttk.Button(title_frame, text="← 返回首页", command=self._on_back).pack(side=tk.LEFT)
        ttk.Label(title_frame, text="目标点更新",
                  font=("", 16, "bold")).pack(side=tk.LEFT, padx=20)
        ttk.Separator(body, orient="horizontal").pack(fill=tk.X, padx=12, pady=(8, 4))

        cfg = ttk.LabelFrame(body, text="运行配置", padding="12 8 12 8")
        cfg.pack(fill=tk.X, padx=12, pady=6)
        r0 = ttk.Frame(cfg); r0.pack(fill=tk.X, pady=4)
        ttk.Label(r0, text="容器:").pack(side="left")
        self.cont_var = tk.StringVar(value="fz1")
        ttk.Entry(r0, textvariable=self.cont_var, width=10).pack(side="left", padx=5)
        ttk.Label(r0, text="订阅: /guardian/dump_goal → 发布: /perception/new_dump_goal",
                  foreground="#555").pack(side="left", padx=12)
        self._start_btn = ttk.Button(r0, text="启动监听节点", command=self._start)
        self._start_btn.pack(side="right", padx=4)
        self._stop_btn = ttk.Button(r0, text="停止节点", command=self._stop,
                                    state=tk.DISABLED)
        self._stop_btn.pack(side="right", padx=4)
        self._stat_var = tk.StringVar(value="未启动")
        ttk.Label(r0, textvariable=self._stat_var, foreground="#888").pack(side="right", padx=8)

        ctrl = ttk.LabelFrame(body, text="目标点偏移控制", padding="12 8 12 8")
        ctrl.pack(fill=tk.X, padx=12, pady=6)
        r1 = ttk.Frame(ctrl); r1.pack(fill=tk.X, pady=4)
        ttk.Label(r1, text="车体系纵向偏移(米, 往后负/往前正):").pack(side="left")
        self.offset_var = tk.StringVar(value="6")
        ttk.Entry(r1, textvariable=self.offset_var, width=8).pack(side="left", padx=5)
        ttk.Button(r1, text="发送偏移", command=self._send_offset).pack(side="left", padx=4)
        ttk.Separator(ctrl, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(ctrl, text="-6", command=lambda: self._quick_offset(-6)).pack(side="left", padx=3)
        ttk.Button(ctrl, text="-1", command=lambda: self._quick_offset(-1)).pack(side="left", padx=3)
        ttk.Button(ctrl, text="+1", command=lambda: self._quick_offset(1)).pack(side="left", padx=3)
        ttk.Button(ctrl, text="+6", command=lambda: self._quick_offset(6)).pack(side="left", padx=3)

        log_frame = ttk.LabelFrame(body, text="节点日志", padding="12 8 12 8")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        self._log_text = tk.Text(log_frame, height=14, wrap=tk.WORD,
                                 state=tk.DISABLED, font=("Consolas", 9))
        self._log_text.pack(fill=tk.BOTH, expand=True)
        self._log_text.tag_configure("error", foreground="red")
        self._log_text.tag_configure("ok", foreground="#0a0")
        self._log_text.tag_configure("warn", foreground="#a60")

    # ============================== 运行 ==============================
    def _start(self):
        import subprocess
        if self._proc is not None and self._proc.poll() is None:
            self._update_log("节点已在运行", "warn")
            return
        cont = self.cont_var.get().strip() or "fz1"
        rc, out = _host_sh("docker ps --format '{{.Names}}'")
        if cont not in out.split():
            self._update_log("容器 {} 未运行".format(cont), "error")
            return
        # 1. 写入并拷贝节点脚本
        host_src = "/tmp/update_new_goal_host.py"
        with open(host_src, "w", encoding="utf-8") as f:
            f.write(GOAL_NODE_SRC)
        _host_sh("docker cp {} {}:/tmp/update_new_goal.py".format(host_src, cont))
        # 2. 启动
        cmd = ["docker", "exec", "-i", cont, "bash", "-lc",
               "source /opt/ros/humble/setup.bash; "
               "source /home/boonray/install/setup.bash; "
               "python3 /tmp/update_new_goal.py"]
        try:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT,
                                          text=True, bufsize=1)
        except Exception as e:
            self._update_log("启动失败: {}".format(e), "error")
            return
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stat_var.set("运行中")
        self._start_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        self._update_log("节点已启动 ({}): 等待 /guardian/dump_goal".format(cont), "ok")

    def _read_loop(self):
        for line in iter(self._proc.stdout.readline, ""):
            line = line.rstrip("\n")
            if not line:
                continue
            tag = "error" if ("ERROR" in line or "error" in line.lower()) else "info"
            self._log_safe(line, tag)
        self.root.after(0, self._proc_exited)

    def _proc_exited(self):
        try:
            self._stat_var.set("已退出")
            self._start_btn.config(state=tk.NORMAL)
            self._stop_btn.config(state=tk.DISABLED)
        except Exception:
            pass

    def _send_offset(self):
        try:
            value = float(self.offset_var.get().strip())
        except ValueError:
            self._update_log("偏移必须是数字 (米)", "error")
            return
        if self._proc is None or self._proc.poll() is not None:
            self._update_log("节点未运行, 先点「启动监听节点」", "warn")
            return
        try:
            self._proc.stdin.write("{}\n".format(value))
            self._proc.stdin.flush()
            self._update_log("已发送偏移 {:.2f} m".format(value), "ok")
        except Exception as e:
            self._update_log("发送失败: {}".format(e), "error")

    def _quick_offset(self, value):
        self.offset_var.set(str(value))
        self._send_offset()

    def _stop(self):
        if self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
        self._stat_var.set("已停止")
        self._start_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)
        self._update_log("节点已停止")

    def _log_safe(self, message, tag="info"):
        try:
            self.root.after(0, lambda: self._update_log(message, tag))
        except Exception:
            pass

    def _update_log(self, message, tag="info"):
        if self._log_text is None:
            return
        try:
            self._log_text.config(state=tk.NORMAL)
            self._log_text.insert(tk.END, time.strftime("[%H:%M:%S] ") + message + "\n", tag)
            self._log_text.see(tk.END)
            self._log_text.config(state=tk.DISABLED)
        except Exception:
            pass

    def _on_back(self):
        self._running = False
        self._stop()
        self.on_back()


if __name__ == "__main__":
    root = tk.Tk()
    app = MockToolsApp(root)
    root.mainloop()

    