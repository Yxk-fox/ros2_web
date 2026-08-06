#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
红绿灯模拟器服务
"""

import os
import time
import json
import threading
import asyncio
import socket
import subprocess
from datetime import datetime

import requests
import paho.mqtt.client as mqtt

from logger import logger
from core.constants import CONFIG


class TrafficLightSender:
    """交通红绿灯模拟器，通过 MQTT 接收控制指令并通过 UDP 上报灯状态"""
    
    STATE_GREEN = 1
    STATE_RED = 2
    STATE_OFF = 3
    STATE_YELLOW = 4
    
    LIGHT_LABEL = {STATE_GREEN: "绿灯", STATE_RED: "红灯", STATE_OFF: "灭灯", STATE_YELLOW: "黄灯"}

    def __init__(self, config, log_callback=None):
        self.config = config
        self.sn = config.get('sn', 'hd_light')
        self.http_host = config.get('http_host', '139.196.75.44:8900')
        self.mqtt_host = config.get('mqtt_host', '139.196.75.44:1883')
        self.cloud_host = config.get('cloud_host', '139.196.75.44:1234')
        self.login_interval = config.get('login_interval', 60)
        self.report_interval = config.get('report_interval', 1)
        self._running = False
        self._thread = None
        self._mqtt_thread = None
        self._log_callback = log_callback
        self._token = ""
        self._manual_token = config.get('token', "")
        self._project_id = config.get('project_id', "")
        self._light_state = self.STATE_GREEN
        self._second_light_state = self.STATE_RED
        self._light_mode = 1
        self._mqtt_client = None
        self._mqtt_client_lock = threading.Lock()

    def _log(self, msg):
        if self._log_callback:
            self._log_callback(msg)

    def _send_udp(self, message):
        try:
            if message:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                addr, port = self.cloud_host.split(":")
                sock.sendto(message.encode(), (addr, int(port)))
                sock.close()
        except Exception as e:
            self._log(f"UDP发送失败: {e}")

    def _login(self):
        try:
            import requests
            data = {"sn": self.sn}
            headers = {"Content-Type": "application/json", "Connection": "keep-alive"}
            response = requests.post(url=f"http://{self.http_host}/shovel/api/v3/device/login/",
                                    headers=headers, data=json.dumps(data), timeout=3)
            res_data = response.json().get("data")
            self._token = res_data.get("token")
            self._project_id = res_data.get("project_id")
            if not self._token:
                self._log("token获取失败")
                return False
            else:
                self._log(f"登录成功 project_id={self._project_id}")
                return True
        except Exception as e:
            self._log(f"登录失败: {e}")
            return False

    def _on_connect(self, client, userdata, flags, rc, properties):
        if rc == 0:
            self._log("成功连接到MQTT代理")
            client.subscribe(f"command/{self._project_id}/{self.sn}/request/change_state")
        else:
            self._log(f"连接MQTT失败，返回码: {rc}")

    def _on_message(self, client, userdata, msg):
        if self._light_mode == 2:
            return
        if msg.topic == f"command/{self._project_id}/{self.sn}/request/change_state":
            self._log(f"接收到灯状态变更消息: {msg.payload.decode()}")
            try:
                payload = json.loads(msg.payload.decode())
                params = payload.get("params", {})
                self._light_state = params.get("light_state")
                self._second_light_state = params.get("second_light_state")
                self._log(f"解析到 light_state={self._light_state}, second_light_state={self._second_light_state}")
            except Exception as e:
                self._log(f"解析灯状态消息失败: {e}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self._log(f"MQTT连接断开，返回码: {reason_code}")

    def _mqtt_thread_func(self):
        """MQTT 线程函数，使用 loop_forever() 自动处理重连"""
        while self._running:
            if not self._token:
                self._log("等待登录成功...")
                time.sleep(2)
                continue
            try:
                import paho.mqtt.client as mqtt
                with self._mqtt_client_lock:
                    if self._mqtt_client:
                        try:
                            self._mqtt_client.disconnect()
                        except:
                            pass
                        self._mqtt_client = None
                
                client = mqtt.Client(
                    client_id=self.sn,
                    protocol=mqtt.MQTTv5,
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2
                )
                client.on_connect = self._on_connect
                client.on_message = self._on_message
                client.on_disconnect = self._on_disconnect
                client.username_pw_set(str(self._project_id), self._token)
                client.reconnect_delay_set(min_delay=1, max_delay=10)
                addr, port = self.mqtt_host.split(":")
                
                with self._mqtt_client_lock:
                    self._mqtt_client = client
                
                client.connect(addr, int(port), keepalive=60)
                client.loop_forever()
            except Exception as e:
                self._log(f"MQTT服务异常: {e}")
                with self._mqtt_client_lock:
                    self._mqtt_client = None
                time.sleep(3)

    def _report_thread_func(self):
        """上报线程函数，定期上报灯状态"""
        # 保存用户手动指定的 project_id 和 token（如果有的话）
        manual_project_id = self._project_id
        manual_token = self._manual_token

        # 若同时手动指定了 token 和 project_id，则跳过 HTTP 登录直接使用
        if manual_token and manual_project_id:
            self._token = manual_token
            self._log(f"使用手动指定的 token 和 project_id={self._project_id}，跳过 HTTP 登录")
        else:
            # 否则通过 HTTP 登录获取 token
            if not self._login():
                self._log("登录失败，无法启动服务")
                self._running = False
                return
            # 如果用户手动指定了 project_id，优先使用用户的
            if manual_project_id:
                self._project_id = manual_project_id
                self._log(f"使用手动指定的 project_id={self._project_id}")

        self._log(f"🚦 红绿灯模拟器启动 -> SN={self.sn}, ProjectID={self._project_id}, HTTP={self.http_host}, MQTT={self.mqtt_host}, Cloud={self.cloud_host}")

        last_login_time = time.time()
        while self._running:
            # 仅在非手动 token 模式下周期性重新登录
            if not (manual_token and manual_project_id):
                if time.time() - last_login_time > self.login_interval:
                    if self._login():
                        if manual_project_id:
                            self._project_id = manual_project_id
                        last_login_time = time.time()
                    else:
                        self._log("登录过期，重试失败")

            report_data = {
                "sn": self.sn,
                "timestamp": float("{:.0f}".format(time.time())),
                "light_state": self._light_state,
                "second_light_state": self._second_light_state,
                "light_mode": self._light_mode
            }
            json_str = "1@" + json.dumps({"method": "rt_message", "params": json.dumps(report_data)})
            self._send_udp(json_str)
            self._log(f"上报灯状态: 主灯={self.LIGHT_LABEL.get(self._light_state, '?')}({self._light_state}), 次灯={self.LIGHT_LABEL.get(self._second_light_state, '?')}({self._second_light_state})")

            time.sleep(self.report_interval)

    def start(self):
        if self._running:
            self._log("红绿灯模拟器已在运行中")
            return
        self._running = True
        # 重置状态，确保重新启动时状态干净（主灯绿、次灯红）
        self._token = ""
        self._light_state = self.STATE_GREEN
        self._second_light_state = self.STATE_RED
        self._light_mode = 1
        with self._mqtt_client_lock:
            self._mqtt_client = None
        # 启动上报线程
        self._thread = threading.Thread(target=self._report_thread_func, daemon=True)
        self._thread.start()
        # 启动MQTT线程
        self._mqtt_thread = threading.Thread(target=self._mqtt_thread_func, daemon=True)
        self._mqtt_thread.start()

    def stop(self):
        if not self._running:
            return
        self._running = False
        # 停止MQTT连接
        with self._mqtt_client_lock:
            if self._mqtt_client:
                try:
                    self._mqtt_client.disconnect()
                except:
                    pass
                self._mqtt_client = None
        # 等待线程结束
        if self._mqtt_thread:
            self._mqtt_thread.join(timeout=5.0)
        if self._thread:
            self._thread.join(timeout=5.0)
        self._log("🚦 红绿灯模拟器已停止")

    @property
    def is_running(self):
        return self._running

    def get_status(self):
        return {
            "running": self._running,
            "light_state": self._light_state,
            "second_light_state": self._second_light_state,
            "light_mode": self._light_mode,
            "mqtt_connected": self._mqtt_client is not None and self._mqtt_client.is_connected() if self._mqtt_client else False,
            "sn": self.sn,
            "project_id": self._project_id
        }

    def _publish_mqtt_state(self):
        """向 MQTT 发布当前灯状态，使云端管控平台同步"""
        with self._mqtt_client_lock:
            client = self._mqtt_client
        if client and client.is_connected():
            try:
                topic = f"command/{self._project_id}/{self.sn}/response/change_state"
                payload = json.dumps({
                    "params": {
                        "light_state": self._light_state,
                        "second_light_state": self._second_light_state,
                        "light_mode": self._light_mode
                    }
                })
                client.publish(topic, payload, qos=1)
                self._log(f"MQTT发布灯状态: light_state={self._light_state}, second_light_state={self._second_light_state}")
            except Exception as e:
                self._log(f"MQTT发布失败: {e}")

    def set_light_state(self, light_state=None, second_light_state=None):
        if light_state is not None:
            self._light_state = light_state
            self._log(f"手动设置主灯状态: {light_state}")
        if second_light_state is not None:
            self._second_light_state = second_light_state
            self._log(f"手动设置次灯状态: {second_light_state}")
        # 手动模式下，向 MQTT 发布状态以同步云端
        if self._light_mode == 2:
            self._publish_mqtt_state()

    def set_mode(self, mode):
        if mode in [1, 2]:
            self._light_mode = mode
            self._log(f"切换模式: {'自动' if mode == 1 else '手动'}")
            return True
        return False

class TimerTrafficLightSender:
    """计时红绿灯模拟器，参考 light.py，自动循环切换红/绿/黄灯"""

    LIGHT_LABEL = {0: "黄闪", 1: "黄", 2: "红", 3: "绿", 4: "绿闪", 5: "黑"}

    def __init__(self, config, log_callback=None):
        self.config = config
        self.sn = config.get('sn', 'js_light')
        self.udp_host = config.get('host', '192.168.9.252')
        self.udp_port = config.get('port', 1234)
        self.red_duration = config.get('red_duration', 15)
        self.green_duration = config.get('green_duration', 35)
        self.yellow_duration = config.get('yellow_duration', 5)
        self._running = False
        self._thread = None
        self._log_callback = log_callback

        self.phases = [
            {"count_light_state": 2, "duration": self.red_duration},
            {"count_light_state": 3, "duration": self.green_duration},
            {"count_light_state": 1, "duration": self.yellow_duration},
        ]

    def _log(self, msg):
        if self._log_callback:
            self._log_callback(msg)

    def _send_udp(self, message):
        try:
            if message:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.sendto(message.encode("utf-8"), (self.udp_host, self.udp_port))
                sock.close()
        except Exception as e:
            self._log(f"UDP发送失败: {e}")

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run(self):
        self._log(f"⏱️ 计时红绿灯模拟器启动 -> SN={self.sn}, UDP={self.udp_host}:{self.udp_port}")
        self._log(f"配置：红灯={self.red_duration}s  绿灯={self.green_duration}s  黄灯={self.yellow_duration}s")

        cycle = 0
        while self._running:
            cycle += 1
            for phase in self.phases:
                if not self._running:
                    break
                state = phase["count_light_state"]
                duration = phase["duration"]
                label = self.LIGHT_LABEL.get(state, str(state))

                for tick in range(duration, 0, -1):
                    if not self._running:
                        break
                    payload = {
                        "cycle": cycle,
                        "count_light_state": state,
                        "remain_time": tick,
                        "duration": duration,
                        "timestamp": int(time.time()),
                        "sn": self.sn
                    }
                    param = {
                        "method": "rt_message",
                        "params": payload,
                    }
                    data = json.dumps(param, ensure_ascii=False)
                    data = "1@" + data
                    self._send_udp(data)
                    self._log(f"[{label}({state})] cycle={cycle}  remain_time={tick}s")
                    time.sleep(1)

        self._log("🛑 计时红绿灯模拟器已停止")

# ========== 预留扩展区域（第151-200行） ==========
# 预留用于未来扩展，如容器编排、多集群管理等
# ===========================================

# ============================================================
# 6. 通用辅助函数
# ============================================================

