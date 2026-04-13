import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import socket
import time
from typing import Any

try:
    from pydivert import Packet
    PYDIVERT_AVAILABLE = True
except Exception:
    Packet = Any
    PYDIVERT_AVAILABLE = False

from injecter import TcpInjector
from monitor_connection import MonitorConnection


class FakeInjectiveConnection(MonitorConnection):
    def __init__(
        self,
        sock: socket.socket,
        src_ip: str,
        dst_ip: str,
        src_port: int,
        dst_port: int,
        fake_data: bytes,
        bypass_method: str,
        peer_sock: socket.socket,
    ):
        super().__init__(sock, src_ip, dst_ip, src_port, dst_port)
        self.fake_data = fake_data
        self.sch_fake_sent = False
        self.fake_sent = False
        self.t2a_event = asyncio.Event()
        self.t2a_msg = ""
        self.bypass_method = bypass_method
        self.peer_sock = peer_sock
        self.running_loop = asyncio.get_running_loop()


class FakeTcpInjector(TcpInjector):
    def __init__(
        self,
        w_filter: str,
        connections: dict[tuple, FakeInjectiveConnection],
        send_workers: int = 32,
        fake_send_delay_sec: float = 0.001,
        debug_unexpected_packets: bool = False,
        queue_len: int | None = None,
        queue_time_ms: int | None = None,
        queue_size_bytes: int | None = None,
        logger: logging.Logger | None = None,
    ):
        super().__init__(
            w_filter,
            queue_len=queue_len,
            queue_time_ms=queue_time_ms,
            queue_size_bytes=queue_size_bytes,
            logger=logger,
        )
        self.connections = connections
        self.send_executor = ThreadPoolExecutor(max_workers=max(1, int(send_workers)), thread_name_prefix="fake-send")
        self.fake_send_delay_sec = max(0.0, float(fake_send_delay_sec))
        self.debug_unexpected_packets = bool(debug_unexpected_packets)

    def _mark_unexpected_close(self, connection: FakeInjectiveConnection):
        connection.monitor = False
        connection.t2a_msg = "unexpected_close"
        connection.running_loop.call_soon_threadsafe(connection.t2a_event.set)

    def _close_connection_sockets(self, connection: FakeInjectiveConnection):
        try:
            connection.sock.close()
        except OSError:
            pass
        try:
            connection.peer_sock.close()
        except OSError:
            pass

    def fake_send_thread(self, packet: Packet, connection: FakeInjectiveConnection):
        if self.fake_send_delay_sec:
            time.sleep(self.fake_send_delay_sec)

        with connection.thread_lock:
            if not connection.monitor:
                return

            packet.tcp.psh = True
            packet.ip.packet_len = packet.ip.packet_len + len(connection.fake_data)
            packet.tcp.payload = connection.fake_data
            if packet.ipv4:
                packet.ipv4.ident = (packet.ipv4.ident + 1) & 0xFFFF

            if connection.bypass_method != "wrong_seq":
                self._mark_unexpected_close(connection)
                return

            packet.tcp.seq_num = (connection.syn_seq + 1 - len(packet.tcp.payload)) & 0xFFFFFFFF
            connection.fake_sent = True
            self.w.send(packet, True)

    def on_unexpected_packet(self, packet: Packet, connection: FakeInjectiveConnection, reason: str):
        if self.debug_unexpected_packets:
            self.logger.warning("%s: %s", reason, packet)
        self._close_connection_sockets(connection)
        self._mark_unexpected_close(connection)
        self.w.send(packet, False)

    def on_inbound_packet(self, packet: Packet, connection: FakeInjectiveConnection):
        if connection.syn_seq == -1:
            self.on_unexpected_packet(packet, connection, "unexpected inbound packet, no syn sent")
            return

        if packet.tcp.ack and packet.tcp.syn and (not packet.tcp.rst) and (not packet.tcp.fin) and (len(packet.tcp.payload) == 0):
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if connection.syn_ack_seq != -1 and connection.syn_ack_seq != seq_num:
                self.on_unexpected_packet(packet, connection, "unexpected inbound syn-ack packet, seq changed")
                return
            if ack_num != ((connection.syn_seq + 1) & 0xFFFFFFFF):
                self.on_unexpected_packet(packet, connection, "unexpected inbound syn-ack packet, ack mismatch")
                return

            connection.syn_ack_seq = seq_num
            self.w.send(packet, False)
            return

        if packet.tcp.ack and (not packet.tcp.syn) and (not packet.tcp.rst) and (not packet.tcp.fin) and (len(packet.tcp.payload) == 0) and connection.fake_sent:
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if connection.syn_ack_seq == -1 or ((connection.syn_ack_seq + 1) & 0xFFFFFFFF) != seq_num:
                self.on_unexpected_packet(packet, connection, "unexpected inbound ack packet, seq mismatch")
                return
            if ack_num != ((connection.syn_seq + 1) & 0xFFFFFFFF):
                self.on_unexpected_packet(packet, connection, "unexpected inbound ack packet, ack mismatch")
                return

            connection.monitor = False
            connection.t2a_msg = "fake_data_ack_recv"
            connection.running_loop.call_soon_threadsafe(connection.t2a_event.set)
            return

        self.on_unexpected_packet(packet, connection, "unexpected inbound packet")

    def on_outbound_packet(self, packet: Packet, connection: FakeInjectiveConnection):
        if connection.sch_fake_sent:
            self.on_unexpected_packet(packet, connection, "unexpected outbound packet after fake send")
            return

        if packet.tcp.syn and (not packet.tcp.ack) and (not packet.tcp.rst) and (not packet.tcp.fin) and (len(packet.tcp.payload) == 0):
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if ack_num != 0:
                self.on_unexpected_packet(packet, connection, "unexpected outbound syn packet, ack_num is not zero")
                return
            if connection.syn_seq != -1 and connection.syn_seq != seq_num:
                self.on_unexpected_packet(packet, connection, "unexpected outbound syn packet, seq mismatch")
                return

            connection.syn_seq = seq_num
            self.w.send(packet, False)
            return

        if packet.tcp.ack and (not packet.tcp.syn) and (not packet.tcp.rst) and (not packet.tcp.fin) and (len(packet.tcp.payload) == 0):
            seq_num = packet.tcp.seq_num
            ack_num = packet.tcp.ack_num
            if connection.syn_seq == -1 or ((connection.syn_seq + 1) & 0xFFFFFFFF) != seq_num:
                self.on_unexpected_packet(packet, connection, "unexpected outbound ack packet, seq mismatch")
                return
            if connection.syn_ack_seq == -1 or ack_num != ((connection.syn_ack_seq + 1) & 0xFFFFFFFF):
                self.on_unexpected_packet(packet, connection, "unexpected outbound ack packet, ack mismatch")
                return

            self.w.send(packet, False)
            connection.sch_fake_sent = True
            self.send_executor.submit(self.fake_send_thread, packet, connection)
            return

        self.on_unexpected_packet(packet, connection, "unexpected outbound packet")

    def inject(self, packet: Packet):
        if packet.is_inbound:
            c_id = (packet.ip.dst_addr, packet.tcp.dst_port, packet.ip.src_addr, packet.tcp.src_port)
            connection = self.connections.get(c_id)
            if connection is None:
                self.w.send(packet, False)
                return
            with connection.thread_lock:
                if not connection.monitor:
                    self.w.send(packet, False)
                    return
                self.on_inbound_packet(packet, connection)
            return

        if packet.is_outbound:
            c_id = (packet.ip.src_addr, packet.tcp.src_port, packet.ip.dst_addr, packet.tcp.dst_port)
            connection = self.connections.get(c_id)
            if connection is None:
                self.w.send(packet, False)
                return
            with connection.thread_lock:
                if not connection.monitor:
                    self.w.send(packet, False)
                    return
                self.on_outbound_packet(packet, connection)
            return

        self.logger.error("Packet direction is neither inbound nor outbound. Passing through.")
        self.w.send(packet, False)
