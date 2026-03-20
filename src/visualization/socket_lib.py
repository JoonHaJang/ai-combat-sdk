"""
Socket library for Dogfight 2 network communication
Adapted from dogfight-sandbox-hg2/network_client_example/socket_lib.py
"""
import socket
import struct
import sys


class SocketConnection:
    """Dogfight 2 소켓 연결 관리"""
    
    def __init__(self):
        self.sock = None
        self.logger = ""
        
    def connect(self, host: str, port: int) -> bool:
        """Dogfight 2 서버에 연결
        
        Args:
            host: 서버 IP 주소
            port: 서버 포트
            
        Returns:
            bool: 연결 성공 여부
        """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((host, port))
            self.logger = f"Connected to {host}:{port}"
            return True
        except Exception as e:
            self.logger = f"Connection failed: {e}"
            return False
    
    def close(self):
        """소켓 연결 종료"""
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None
    
    def send_message(self, message: bytes):
        """메시지 전송
        
        Args:
            message: 전송할 메시지 (bytes)
        """
        if not self.sock:
            raise ConnectionError("Socket not connected")
        
        # 메시지 크기를 4바이트 빅엔디안으로 전송
        size = len(message)
        size_bytes = size.to_bytes(4, byteorder='big')
        self.sock.sendall(size_bytes + message)
    
    def get_answer_header(self) -> int:
        """응답 헤더(메시지 크기) 수신
        
        Returns:
            int: 수신할 메시지 크기
        """
        try:
            received = self.sock.recv(4)
            while len(received) > 0 and len(received) < 4:
                received += self.sock.recv(4 - len(received))
            
            if len(received) <= 0:
                return None
            
            size = int.from_bytes(received, "big")
            return size
        except Exception as e:
            self.logger = f"Error in get_answer_header: {e}"
            return None
    
    def get_answer(self, max_size_before_flush: int = -1) -> bytes:
        """응답 메시지 수신
        
        Args:
            max_size_before_flush: 최대 수신 크기 (-1이면 무제한)
            
        Returns:
            bytes: 수신한 메시지
        """
        try:
            size = self.get_answer_header()
            if size is None or (max_size_before_flush != -1 and size > max_size_before_flush):
                return None
            
            received = self.sock.recv(size)
            while len(received) < size:
                received += self.sock.recv(size - len(received))
            
            return received
        except Exception as e:
            self.logger = f"Error in get_answer: {e}"
            return None
