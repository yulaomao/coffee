"""MQTT 客户端占位实现。
若配置 MQTT_BROKER_URL 则可扩展连接并发布到 devices/{device_no}/commands。
本最小版本不强制启用。
"""
from __future__ import annotations
from typing import Optional

try:
    import paho.mqtt.client as mqtt  # type: ignore
except Exception:  # noqa: BLE001
    mqtt = None  # 占位


class MQTTClient:
    def __init__(self, broker_url: Optional[str]):
        self.broker_url = broker_url
        self.client = None
        if broker_url and mqtt is not None:
            # 可在此实现连接逻辑
            self.client = mqtt.Client()

    def publish_command(self, device_no: str, payload: str) -> None:
        if not self.client:
            return
        topic = f"devices/{device_no}/commands"
        self.client.publish(topic, payload)
