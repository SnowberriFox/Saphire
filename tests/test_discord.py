import json
import socket
import struct
import threading
import time

from sapphire import discord


def _recv_frame(conn):
    head = b""
    while len(head) < 8:
        head += conn.recv(8 - len(head))
    op, length = struct.unpack("<II", head)
    body = b""
    while len(body) < length:
        body += conn.recv(length - len(body))
    return op, json.loads(body)


def _send_frame(conn, op, data):
    body = json.dumps(data).encode()
    conn.sendall(struct.pack("<II", op, len(body)) + body)


def test_presence_handshake_and_activity(tmp_path, monkeypatch):
    sock_path = tmp_path / "discord-ipc-0"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    got = []

    def serve():
        conn, _ = server.accept()
        op, data = _recv_frame(conn)
        got.append((op, data))
        _send_frame(conn, discord.OP_FRAME, {"evt": "READY", "data": {"v": 1}})
        op, data = _recv_frame(conn)
        got.append((op, data))
        _send_frame(conn, discord.OP_FRAME, {"cmd": "SET_ACTIVITY", "data": {}, "evt": None})
        time.sleep(0.5)
        conn.close()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    monkeypatch.setattr(discord, "socket_candidates", lambda: [sock_path])
    p = discord.Presence("123456")
    p.update("Browsing mods", "4 mods active", large_image="https://x/y.png", buttons=[{"label": "Get", "url": "https://z"}])
    p.start()
    t.join(timeout=5)
    p.stop()
    assert got[0][0] == discord.OP_HANDSHAKE and got[0][1] == {"v": 1, "client_id": "123456"}
    op, frame = got[1]
    assert op == discord.OP_FRAME and frame["cmd"] == "SET_ACTIVITY"
    act = frame["args"]["activity"]
    assert act["details"] == "Browsing mods" and act["state"] == "4 mods active"
    assert act["assets"]["large_image"] == "https://x/y.png" and act["buttons"][0]["label"] == "Get"
    assert "start" in act["timestamps"] and frame["args"]["pid"] > 0


def test_presence_without_discord_is_quiet(tmp_path, monkeypatch):
    monkeypatch.setattr(discord, "socket_candidates", lambda: [tmp_path / "nope"])
    p = discord.Presence("1")
    p.update("x")
    p.start()
    time.sleep(0.3)
    p.stop()
    assert not p.connected
