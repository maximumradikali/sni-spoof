import argparse
import asyncio
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import socket
import subprocess
import sys
import threading
from itertools import count

from fake_tcp import FakeInjectiveConnection, FakeTcpInjector, PYDIVERT_AVAILABLE
from utils.network_tools import get_default_interface_ipv4
from utils.packet_templates import ClientHelloMaker


def parse_cli_args():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--config", dest="config_path", default=None, help="Path to config.json")
    args, _ = parser.parse_known_args()
    return args


def get_exe_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CLI_ARGS = parse_cli_args()
CONFIG_PATH = os.path.abspath(CLI_ARGS.config_path) if CLI_ARGS.config_path else os.path.join(get_exe_dir(), "config.json")

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = json.load(f)


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


LISTEN_HOST = str(config.get("LISTEN_HOST", "0.0.0.0"))
LISTEN_PORT = int(config.get("LISTEN_PORT", 40443))
CONNECT_IPS = config.get("CONNECT_IPS", [])
if isinstance(CONNECT_IPS, str):
    CONNECT_IPS = [CONNECT_IPS]
CONNECT_IPS = [str(ip).strip() for ip in CONNECT_IPS if str(ip).strip()]
if not CONNECT_IPS:
    sys.exit("CONNECT_IPS must contain at least one IP.")
CONNECT_PORT = int(config.get("CONNECT_PORT", 443))
FAKE_SNI = str(config.get("FAKE_SNI", "auth.vercel.com")).encode()
BYPASS_METHOD = str(config.get("BYPASS_METHOD", "wrong_seq")).strip().lower()
if BYPASS_METHOD not in {"wrong_seq", "none"}:
    sys.exit("BYPASS_METHOD must be either 'wrong_seq' or 'none'.")

CONNECT_TIMEOUT_SEC = float(config.get("CONNECT_TIMEOUT_SEC", 8))
FAKE_ACK_TIMEOUT_SEC = float(config.get("FAKE_ACK_TIMEOUT_SEC", 3))
LISTEN_BACKLOG = int(config.get("LISTEN_BACKLOG", 1024))
CONNECT_RETRIES = max(1, int(config.get("CONNECT_RETRIES", 2)))
RETRY_DELAY_SEC = float(config.get("RETRY_DELAY_SEC", 0.15))
RELAY_BUFFER_SIZE = max(4096, int(config.get("RELAY_BUFFER_SIZE", 131072)))
SOCKET_BUFFER_BYTES = max(0, int(config.get("SOCKET_BUFFER_BYTES", 524288)))
MAX_ACTIVE_CONNECTIONS = max(0, int(config.get("MAX_ACTIVE_CONNECTIONS", 0)))
CONNECTION_SLOT_TIMEOUT_SEC = max(0.1, float(config.get("CONNECTION_SLOT_TIMEOUT_SEC", 1.5))
)

FAKE_SEND_DELAY_MS = max(0, int(config.get("FAKE_SEND_DELAY_MS", 1)))
FAKE_SEND_WORKERS = max(1, int(config.get("FAKE_SEND_WORKERS", 64)))
WINDIVERT_QUEUE_LEN = config.get("WINDIVERT_QUEUE_LEN", 8192)
WINDIVERT_QUEUE_TIME_MS = config.get("WINDIVERT_QUEUE_TIME_MS", 2048)
WINDIVERT_QUEUE_SIZE = config.get("WINDIVERT_QUEUE_SIZE", 16777216)

AUTO_ELEVATE_ADMIN = parse_bool(config.get("AUTO_ELEVATE_ADMIN", True), default=True)
ALLOW_DIRECT_FALLBACK = parse_bool(config.get("ALLOW_DIRECT_FALLBACK", True), default=True)
DEBUG_UNEXPECTED_PACKETS = parse_bool(config.get("DEBUG_UNEXPECTED_PACKETS", False), default=False)

LOG_LEVEL = str(config.get("LOG_LEVEL", "INFO")).upper()
LOG_FILE = str(config.get("LOG_FILE", "logs/sni-forwarder.log"))
LOG_TO_FILE = parse_bool(config.get("LOG_TO_FILE", True), default=True)
LOG_MAX_BYTES = max(1024, int(config.get("LOG_MAX_BYTES", 5 * 1024 * 1024)))
LOG_BACKUP_COUNT = max(1, int(config.get("LOG_BACKUP_COUNT", 3)))

fake_injective_connections: dict[tuple, FakeInjectiveConnection] = {}
connection_semaphore: asyncio.Semaphore | None = None
active_bypass_method = BYPASS_METHOD
upstream_targets: list[tuple[str, str]] = []
connection_counter = count(1)

logger = logging.getLogger("sni_forwarder")


def resolve_log_file_path():
    if not LOG_FILE:
        return ""
    if os.path.isabs(LOG_FILE):
        return LOG_FILE
    return os.path.join(get_exe_dir(), LOG_FILE)


def setup_logging():
    level = getattr(logging, LOG_LEVEL, logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if LOG_TO_FILE and LOG_FILE:
        file_path = resolve_log_file_path()
        file_dir = os.path.dirname(file_path)
        if file_dir:
            os.makedirs(file_dir, exist_ok=True)
        handlers.append(
            RotatingFileHandler(
                file_path,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )


def is_running_as_admin():
    if os.name != "nt":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin():
    if os.name != "nt" or is_running_as_admin():
        return
    try:
        if getattr(sys, "frozen", False):
            executable = sys.executable
            params = subprocess.list2cmdline(sys.argv[1:])
        else:
            executable = sys.executable
            params = subprocess.list2cmdline([os.path.abspath(sys.argv[0]), *sys.argv[1:]])
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            get_exe_dir(),
            1,
        )
        if rc <= 32:
            sys.exit(f"Administrator privileges are required. UAC launch failed ({rc}).")
        sys.exit(0)
    except Exception as exc:
        sys.exit(f"Administrator privileges are required. Relaunch failed: {exc!r}")


def close_socket_quietly(sock: socket.socket | None):
    if not sock:
        return
    try:
        sock.close()
    except OSError:
        pass


def safe_set_sockopt(sock: socket.socket, level: int, opt_name: str, value: int):
    opt = getattr(socket, opt_name, None)
    if opt is None:
        return
    try:
        sock.setsockopt(level, opt, value)
    except OSError:
        pass


def tune_stream_socket(sock: socket.socket):
    safe_set_sockopt(sock, socket.SOL_SOCKET, "SO_KEEPALIVE", 1)
    safe_set_sockopt(sock, socket.IPPROTO_TCP, "TCP_NODELAY", 1)
    if SOCKET_BUFFER_BYTES > 0:
        safe_set_sockopt(sock, socket.SOL_SOCKET, "SO_SNDBUF", SOCKET_BUFFER_BYTES)
        safe_set_sockopt(sock, socket.SOL_SOCKET, "SO_RCVBUF", SOCKET_BUFFER_BYTES)
    safe_set_sockopt(sock, socket.IPPROTO_TCP, "TCP_KEEPIDLE", 11)
    safe_set_sockopt(sock, socket.IPPROTO_TCP, "TCP_KEEPINTVL", 2)
    safe_set_sockopt(sock, socket.IPPROTO_TCP, "TCP_KEEPCNT", 3)


def unregister_fake_connection(fake_injective_conn: FakeInjectiveConnection):
    fake_injective_conn.monitor = False
    fake_injective_connections.pop(fake_injective_conn.id, None)


def build_upstream_targets():
    targets: list[tuple[str, str]] = []
    for ip in CONNECT_IPS:
        interface_ip = get_default_interface_ipv4(ip)
        if not interface_ip:
            logger.warning("No default IPv4 interface for upstream %s", ip)
            continue
        targets.append((ip, interface_ip))
    return targets


def build_windivert_filter(targets: list[tuple[str, str]]):
    clauses = []
    for target_ip, interface_ip in targets:
        clauses.append(
            "("
            + "(ip.SrcAddr == " + interface_ip + " and ip.DstAddr == " + target_ip + ")"
            + " or "
            + "(ip.SrcAddr == " + target_ip + " and ip.DstAddr == " + interface_ip + ")"
            + ")"
        )
    if not clauses:
        return "tcp and false"
    return "tcp and (" + " or ".join(clauses) + ")"


async def relay_main_loop(
    sock_1: socket.socket,
    sock_2: socket.socket,
    peer_task: asyncio.Task,
    first_prefix_data: bytes,
    conn_id: int,
    direction: str,
):
    loop = asyncio.get_running_loop()
    while True:
        try:
            data = await loop.sock_recv(sock_1, RELAY_BUFFER_SIZE)
            if not data:
                raise ValueError("eof")
            if first_prefix_data:
                data = first_prefix_data + data
                first_prefix_data = b""
            await loop.sock_sendall(sock_2, data)
        except Exception as exc:
            logger.debug("conn=%s relay(%s) stopped: %r", conn_id, direction, exc)
            close_socket_quietly(sock_1)
            close_socket_quietly(sock_2)
            peer_task.cancel()
            return


async def establish_outgoing_direct(loop: asyncio.AbstractEventLoop, conn_id: int):
    attempts_total = CONNECT_RETRIES * len(upstream_targets)
    for attempt in range(attempts_total):
        target_ip, interface_ipv4 = upstream_targets[attempt % len(upstream_targets)]
        outgoing_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        outgoing_sock.setblocking(False)
        outgoing_sock.bind((interface_ipv4, 0))
        tune_stream_socket(outgoing_sock)
        try:
            await asyncio.wait_for(
                loop.sock_connect(outgoing_sock, (target_ip, CONNECT_PORT)),
                CONNECT_TIMEOUT_SEC,
            )
            logger.info(
                "conn=%s connected (direct) upstream=%s:%s attempt=%s/%s",
                conn_id,
                target_ip,
                CONNECT_PORT,
                attempt + 1,
                attempts_total,
            )
            return outgoing_sock
        except Exception as exc:
            close_socket_quietly(outgoing_sock)
            logger.warning(
                "conn=%s direct connect failed upstream=%s:%s attempt=%s/%s reason=%r",
                conn_id,
                target_ip,
                CONNECT_PORT,
                attempt + 1,
                attempts_total,
                exc,
            )
            if (attempt + 1) < attempts_total and RETRY_DELAY_SEC > 0:
                await asyncio.sleep(RETRY_DELAY_SEC)
    return None


async def establish_outgoing_with_bypass(
    incoming_sock: socket.socket,
    loop: asyncio.AbstractEventLoop,
    conn_id: int,
):
    attempts_total = CONNECT_RETRIES * len(upstream_targets)
    for attempt in range(attempts_total):
        target_ip, interface_ipv4 = upstream_targets[attempt % len(upstream_targets)]
        fake_data = ClientHelloMaker.get_client_hello_with(
            os.urandom(32),
            os.urandom(32),
            FAKE_SNI,
            os.urandom(32),
        )

        outgoing_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        outgoing_sock.setblocking(False)
        outgoing_sock.bind((interface_ipv4, 0))
        tune_stream_socket(outgoing_sock)
        src_port = outgoing_sock.getsockname()[1]

        fake_injective_conn = FakeInjectiveConnection(
            outgoing_sock,
            interface_ipv4,
            target_ip,
            src_port,
            CONNECT_PORT,
            fake_data,
            active_bypass_method,
            incoming_sock,
        )
        fake_injective_connections[fake_injective_conn.id] = fake_injective_conn

        try:
            await asyncio.wait_for(
                loop.sock_connect(outgoing_sock, (target_ip, CONNECT_PORT)),
                CONNECT_TIMEOUT_SEC,
            )
            await asyncio.wait_for(fake_injective_conn.t2a_event.wait(), FAKE_ACK_TIMEOUT_SEC)
            if fake_injective_conn.t2a_msg != "fake_data_ack_recv":
                raise ValueError("fake ack did not complete")

            unregister_fake_connection(fake_injective_conn)
            logger.info(
                "conn=%s connected (bypass=%s) upstream=%s:%s attempt=%s/%s",
                conn_id,
                active_bypass_method,
                target_ip,
                CONNECT_PORT,
                attempt + 1,
                attempts_total,
            )
            return outgoing_sock
        except Exception as exc:
            unregister_fake_connection(fake_injective_conn)
            close_socket_quietly(outgoing_sock)
            logger.warning(
                "conn=%s bypass connect failed upstream=%s:%s attempt=%s/%s reason=%r",
                conn_id,
                target_ip,
                CONNECT_PORT,
                attempt + 1,
                attempts_total,
                exc,
            )
            if (attempt + 1) < attempts_total and RETRY_DELAY_SEC > 0:
                await asyncio.sleep(RETRY_DELAY_SEC)
    return None


async def handle(incoming_sock: socket.socket, incoming_remote_addr, conn_id: int):
    outgoing_sock = None
    try:
        loop = asyncio.get_running_loop()

        if active_bypass_method == "none":
            outgoing_sock = await establish_outgoing_direct(loop, conn_id)
        else:
            outgoing_sock = await establish_outgoing_with_bypass(incoming_sock, loop, conn_id)

        if outgoing_sock is None:
            logger.warning("conn=%s dropped: upstream connection could not be established", conn_id)
            close_socket_quietly(incoming_sock)
            return

        upstream_to_client_task = asyncio.create_task(
            relay_main_loop(outgoing_sock, incoming_sock, asyncio.current_task(), b"", conn_id, "upstream->client")
        )
        await relay_main_loop(incoming_sock, outgoing_sock, upstream_to_client_task, b"", conn_id, "client->upstream")
    except Exception:
        logger.exception("conn=%s handler crashed", conn_id)
    finally:
        close_socket_quietly(incoming_sock)
        close_socket_quietly(outgoing_sock)
        logger.debug("conn=%s closed peer=%s", conn_id, incoming_remote_addr)


async def handle_with_limit(incoming_sock: socket.socket, incoming_remote_addr, conn_id: int):
    if connection_semaphore is None:
        await handle(incoming_sock, incoming_remote_addr, conn_id)
        return

    try:
        await asyncio.wait_for(connection_semaphore.acquire(), CONNECTION_SLOT_TIMEOUT_SEC)
    except TimeoutError:
        logger.warning("conn=%s dropped: timed out waiting for connection slot", conn_id)
        close_socket_quietly(incoming_sock)
        return

    try:
        await handle(incoming_sock, incoming_remote_addr, conn_id)
    finally:
        connection_semaphore.release()


async def main():
    global connection_semaphore

    if MAX_ACTIVE_CONNECTIONS > 0:
        connection_semaphore = asyncio.Semaphore(MAX_ACTIVE_CONNECTIONS)

    mother_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    mother_sock.setblocking(False)
    safe_set_sockopt(mother_sock, socket.SOL_SOCKET, "SO_REUSEADDR", 1)
    if SOCKET_BUFFER_BYTES > 0:
        safe_set_sockopt(mother_sock, socket.SOL_SOCKET, "SO_RCVBUF", SOCKET_BUFFER_BYTES)
    mother_sock.bind((LISTEN_HOST, LISTEN_PORT))
    mother_sock.listen(LISTEN_BACKLOG)

    logger.info(
        "Server listening on %s:%s | bypass=%s | upstreams=%s",
        LISTEN_HOST,
        LISTEN_PORT,
        active_bypass_method,
        ",".join([ip for ip, _ in upstream_targets]),
    )

    loop = asyncio.get_running_loop()
    while True:
        incoming_sock, addr = await loop.sock_accept(mother_sock)
        incoming_sock.setblocking(False)
        tune_stream_socket(incoming_sock)
        conn_id = next(connection_counter)
        logger.debug("conn=%s accepted peer=%s", conn_id, addr)
        asyncio.create_task(handle_with_limit(incoming_sock, addr, conn_id))


def bootstrap():
    global active_bypass_method
    global upstream_targets

    if AUTO_ELEVATE_ADMIN:
        relaunch_as_admin()

    setup_logging()
    logger.info("Config loaded from %s", CONFIG_PATH)

    upstream_targets = build_upstream_targets()
    if not upstream_targets:
        sys.exit(f"No usable interface found for upstreams: {','.join(CONNECT_IPS)}")

    if active_bypass_method != "none" and (os.name != "nt" or not PYDIVERT_AVAILABLE):
        if ALLOW_DIRECT_FALLBACK:
            logger.warning(
                "Bypass mode '%s' is unavailable on this platform. Falling back to direct mode.",
                active_bypass_method,
            )
            active_bypass_method = "none"
        else:
            sys.exit("Bypass mode requires Windows + pydivert.")

    if active_bypass_method != "none":
        w_filter = build_windivert_filter(upstream_targets)
        fake_tcp_injector = FakeTcpInjector(
            w_filter,
            fake_injective_connections,
            send_workers=FAKE_SEND_WORKERS,
            fake_send_delay_sec=FAKE_SEND_DELAY_MS / 1000.0,
            debug_unexpected_packets=DEBUG_UNEXPECTED_PACKETS,
            queue_len=WINDIVERT_QUEUE_LEN,
            queue_time_ms=WINDIVERT_QUEUE_TIME_MS,
            queue_size_bytes=WINDIVERT_QUEUE_SIZE,
            logger=logging.getLogger("sni_forwarder.injector"),
        )
        threading.Thread(target=fake_tcp_injector.run, args=(), daemon=True, name="windivert").start()
        logger.info("WinDivert injector thread started.")

    logger.info("SNI forwarder started.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")


if __name__ == "__main__":
    bootstrap()
