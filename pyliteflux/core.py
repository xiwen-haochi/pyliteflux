#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import socket
import signal
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import BaseRequestHandler, ThreadingTCPServer
from typing import (
    Dict,
    Any,
    Callable,
    Optional,
    Tuple,
    List,
    Iterator,
    Generator,
    Union,
)
from functools import partial
import traceback
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from queue import Queue
from threading import Thread
from typing import Callable, Any, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import time
import os
import platform
from abc import ABC, abstractmethod


class RequestContext:
    """请求上下文"""

    def __init__(self):
        self._storage: Dict[str, Any] = {}

    def __getattr__(self, name: str) -> Any:
        """获取属性"""
        try:
            return self._storage[name]
        except KeyError:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

    def __setattr__(self, name: str, value: Any) -> None:
        """设置属性"""
        if name == "_storage":
            super().__setattr__(name, value)
        else:
            self._storage[name] = value

    def __delattr__(self, name: str) -> None:
        """删除属性"""
        try:
            del self._storage[name]
        except KeyError:
            raise AttributeError(
                f"'{self.__class__.__name__}' object has no attribute '{name}'"
            )

    def clear(self) -> None:
        """清理所有数据"""
        self._storage.clear()


class GlobalContext:
    """全局上下文管理器"""

    def __init__(self):
        self._local = threading.local()

    @property
    def g(self) -> RequestContext:
        """获取当前请求的上下文"""
        if not hasattr(self._local, "g"):
            self._local.g = RequestContext()
        return self._local.g

    def clear_g(self) -> None:
        """清理当前请求的上下文"""
        if hasattr(self._local, "g"):
            self._local.g.clear()
            del self._local.g


# 创建全局上下文实例
ctx = GlobalContext()
g = ctx.g  # 全局可访问的g对象


class BackgroundTask:
    """后台任务管理器"""

    def __init__(self):
        self.tasks: List[Tuple[Callable, tuple, dict]] = []

    def add(self, func: Callable, *args, **kwargs) -> None:
        """
        添加任务到后台队列
        :param func: 要执行的函数
        :param args: 位置参数
        :param kwargs: 关键字参数
        """
        self.tasks.append((func, args, kwargs))

    def get_tasks(self) -> List[Tuple[Callable, tuple, dict]]:
        """获取并清空任务列表"""
        tasks = self.tasks.copy()
        self.tasks.clear()
        return tasks


@dataclass
class HTTPRequest:
    """HTTP请求数据封装"""

    path: str
    query_params: Dict[str, str]
    form_data: Dict[str, str]
    json_data: Optional[Dict[str, Any]]
    path_params: Dict[str, str]
    headers: Dict[str, str]
    bg: BackgroundTask = None

    def __post_init__(self):
        """确保bg属性总是有效"""
        if self.bg is None:
            self.bg = BackgroundTask()


# 基础响应类
class HTTPResponse:
    """HTTP响应基类"""

    def __init__(
        self, data: Any, status: int = 200, headers: Optional[Dict[str, str]] = None
    ):
        self.data = data
        self.status = status
        self.headers = headers or {}
        if "Content-Type" not in self.headers:
            self.headers["Content-Type"] = "text/plain"

    def get_response_headers(self) -> Dict[str, str]:
        """获取响应头"""
        return self.headers

    def get_body(self) -> bytes:
        """获取响应体"""
        return str(self.data).encode()


# JSON响应类
class HTTPJSONResponse(HTTPResponse):
    """JSON响应类"""

    def __init__(
        self, data: Any, status: int = 200, headers: Optional[Dict[str, str]] = None
    ):
        headers = headers or {}
        headers["Content-Type"] = "application/json"
        super().__init__(data, status, headers)

    def get_body(self) -> bytes:
        """获取JSON格式的响应体"""
        return json.dumps(self.data).encode()


class HTTPStreamResponse(HTTPResponse):
    """流式响应类"""

    def __init__(
        self,
        data: Union[Iterator, Generator],
        status: int = 200,
        headers: Optional[Dict[str, str]] = None,
    ):
        headers = headers or {}
        headers["Transfer-Encoding"] = "chunked"
        super().__init__(data, status, headers)
        self.is_stream = True

    def get_body(self) -> Iterator[bytes]:
        """获取响应体迭代器"""
        for chunk in self.data:
            if isinstance(chunk, str):
                chunk = chunk.encode()
            elif not isinstance(chunk, bytes):
                chunk = str(chunk).encode()
            # 按照分块传输编码格式：长度（16进制）+ \r\n + 数据 + \r\n
            yield f"{len(chunk):X}\r\n".encode() + chunk + b"\r\n"
        # 发送结束标记
        yield b"0\r\n\r\n"


class Config:
    """配置管理器"""

    def __init__(self):
        self.http_host = "127.0.0.1"
        self.http_port = 8000
        self.tcp_host = "127.0.0.1"
        self.tcp_port = 8001
        self.info = True  # 添加info参数，控制日志打印

    def validate_host(self, host: str) -> bool:
        """验证IP地址格式"""
        try:
            socket.inet_aton(host)
            return True
        except socket.error:
            return host in ["localhost", "127.0.0.1"]

    def validate_port(self, port: int) -> bool:
        """验证端口号"""
        return isinstance(port, int) and 0 < port < 65536

    def update(self, **kwargs):
        """更新配置"""
        for key, value in kwargs.items():
            if hasattr(self, key):
                if "host" in key and not self.validate_host(value):
                    raise ValueError(f"Invalid host: {value}")
                if "port" in key and not self.validate_port(value):
                    raise ValueError(f"Invalid port: {value}")
                setattr(self, key, value)


class Logger:
    """日志管理器"""

    # 日志级别
    DEBUG = 10
    INFO = 20
    WARNING = 30
    ERROR = 40

    # ANSI颜色代码
    COLORS = {
        "RESET": "\033[0m",
        "DEBUG": "\033[36m",  # 青色
        "INFO": "\033[32m",  # 绿色
        "WARNING": "\033[33m",  # 黄色
        "ERROR": "\033[31m",  # 红色
        "BOLD": "\033[1m",
        "TIME": "\033[90m",  # 灰色
    }

    # 日志级别到名称的映射
    LEVEL_NAMES = {DEBUG: "DEBUG", INFO: "INFO", WARNING: "WARNING", ERROR: "ERROR"}

    def __init__(self):
        # 在Windows系统上启用ANSI支持
        if platform.system() == "Windows":
            os.system("color")

    @classmethod
    def _format_message(cls, level: int, message: str) -> str:
        """格式化日志消"""
        from datetime import datetime

        level_name = cls.LEVEL_NAMES.get(level, "INFO")
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return (
            f"{cls.COLORS['TIME']}[{current_time}]{cls.COLORS['RESET']} "
            f"{cls.COLORS[level_name]}{cls.COLORS['BOLD']}[{level_name}]{cls.COLORS['RESET']} "
            f"{message}"
        )

    @classmethod
    def debug(cls, message: str, enable: bool = True):
        """输出DEBUG级别日志"""
        if enable:
            print(cls._format_message(cls.DEBUG, message))

    @classmethod
    def info(cls, message: str, enable: bool = True):
        """输出INFO级别日志"""
        if enable:
            print(cls._format_message(cls.INFO, message))

    @classmethod
    def warning(cls, message: str, enable: bool = True):
        """输出WARNING级别日志"""
        if enable:
            print(cls._format_message(cls.WARNING, message))

    @classmethod
    def error(cls, message: str, enable: bool = True):
        """输出ERROR级别日志"""
        if enable:
            print(cls._format_message(cls.ERROR, message))

    @classmethod
    def log(cls, message: str, level: int = INFO, enable: bool = True):
        """通用日志输出方法"""
        if enable:
            print(cls._format_message(level, message))


class Route:
    """管理器"""

    _routes: Dict[str, Dict[str, Dict[str, Callable]]] = {
        "http": {"GET": {}, "POST": {}, "PUT": {}, "DELETE": {}},
        "tcp": {},
    }

    @classmethod
    def register(cls, path: str, method: str = "GET", protocol: str = "http"):
        """路由注册装饰器"""

        def decorator(func: Callable) -> Callable:
            if protocol == "tcp":
                cls._routes[protocol][path] = func
            else:
                cls._routes[protocol][method.upper()][path] = func
            return func

        return decorator


class CustomHTTPServer(HTTPServer):
    """自定义HTTP服务器，支持任务队列"""

    def __init__(self, server_address, RequestHandlerClass, task_queue=None, info=True):
        super().__init__(server_address, RequestHandlerClass)
        self.task_queue = task_queue
        self.info = info


class CustomTCPServer(ThreadingTCPServer):
    """自定义TCP服务器，支持任务队列"""

    def __init__(self, server_address, RequestHandlerClass, task_queue=None, info=True):
        super().__init__(server_address, RequestHandlerClass)
        self.task_queue = task_queue
        self.info = info


class Middleware(ABC):
    """中间件基类"""

    @abstractmethod
    def process_request(self, request: Any) -> Optional[Any]:
        """
        处理请求
        :param request: HTTPRequest 或 TCPRequest
        :return: None继续处理，其他值直接返回响应
        """
        pass

    @abstractmethod
    def process_response(self, request: Any, response: Any) -> Any:
        """
        处理响应
        :param request: HTTPRequest 或 TCPRequest
        :param response: 响应对象
        :return: 修改后的响应
        """
        pass


class MiddlewareManager:
    """中间件管理器"""

    def __init__(self):
        self.http_middlewares: List[Middleware] = []
        self.tcp_middlewares: List[Middleware] = []

    def add_middleware(self, middleware: Middleware, protocol: str = "both"):
        """
        添加中间件
        :param middleware: 中间件实例
        :param protocol: 'http', 'tcp' 或 'both'
        """
        if protocol in ["both", "http"]:
            self.http_middlewares.append(middleware)
        if protocol in ["both", "tcp"]:
            self.tcp_middlewares.append(middleware)

    def process_request(self, request: Any, protocol: str) -> Optional[Any]:
        """
        处理请求
        :return: None继续处理，其他值直接返回响应
        """
        middlewares = (
            self.http_middlewares if protocol == "http" else self.tcp_middlewares
        )

        for middleware in middlewares:
            response = middleware.process_request(request)
            if response is not None:
                return response
        return None

    def process_response(self, request: Any, response: Any, protocol: str) -> Any:
        """处理响应"""
        middlewares = (
            self.http_middlewares if protocol == "http" else self.tcp_middlewares
        )

        for middleware in reversed(middlewares):
            response = middleware.process_response(request, response)
        return response


class Server:
    """服务器主类"""

    def __init__(self):
        self.config = Config()
        self._running = False
        self.http_server = None
        self.tcp_server = None
        self.task_queue = TaskQueue()
        self.middleware_manager = MiddlewareManager()  # 添加中间件管理器

    def handle_interrupt(self, signum, frame):
        """处理中断信号"""
        Logger.error("\nReceived interrupt signal, shutting down...", self.config.info)
        self.stop()

    def run(self, protocol="both", **kwargs):
        """运行服务器"""
        try:
            # 更新配置
            self.config.update(**kwargs)
            self._running = True

            # 启动任务队列
            self.task_queue.start()

            if protocol in ["both", "http"]:
                # 使用自定义HTTP服务器
                self.http_server = CustomHTTPServer(
                    (self.config.http_host, self.config.http_port),
                    partial(HTTPHandler, server_instance=self),
                    task_queue=self.task_queue,
                    info=self.config.info,
                )
                threading.Thread(
                    target=self.http_server.serve_forever, daemon=True
                ).start()
                Logger.info(
                    f"HTTP server started on {self.config.http_host}:{self.config.http_port}",
                    self.config.info,
                )

            if protocol in ["both", "tcp"]:
                # 使用自定义TCP服务器
                self.tcp_server = CustomTCPServer(
                    (self.config.tcp_host, self.config.tcp_port),
                    partial(TCPHandler, server_instance=self),
                    task_queue=self.task_queue,
                    info=self.config.info,
                )
                threading.Thread(
                    target=self.tcp_server.serve_forever, daemon=True
                ).start()
                Logger.info(
                    f"TCP server started on {self.config.tcp_host}:{self.config.tcp_port}",
                    self.config.info,
                )

            # 注册中断信号处理
            signal.signal(signal.SIGINT, self.handle_interrupt)

            # 主循环
            while self._running:
                time.sleep(1)

        except KeyboardInterrupt:
            Logger.warning("\nShutting down server...", self.config.info)
        except Exception as e:
            Logger.error(f"Server error: {str(e)}", self.config.info)
            Logger.error(traceback.format_exc(), self.config.info)
        finally:
            self.stop()

    def stop(self):
        """停止服务器"""
        self._running = False
        if self.http_server:
            self.http_server.shutdown()
        if self.tcp_server:
            self.tcp_server.shutdown()
        self.task_queue.stop()
        Logger.error("Server stopped", self.config.info)

    def add_middleware(self, middleware: Middleware, protocol: str = "both"):
        """添加中间件"""
        self.middleware_manager.add_middleware(middleware, protocol)


class HTTPHandler(BaseHTTPRequestHandler):
    def __init__(self, request, client_address, server, *, server_instance=None):
        self.server_instance = server_instance
        super().__init__(request, client_address, server)

    def parse_request_data(self) -> HTTPRequest:
        """解析请求数据"""
        # 解析URL和查询参数
        parsed_url = urlparse(self.path)
        query_params = {k: v[0] for k, v in parse_qs(parsed_url.query).items()}

        # 查找匹配的路由和路径参数
        path = parsed_url.path
        route_pattern, path_params = self.find_matching_route(path)

        # 解析表单数
        form_data = {}
        if self.headers.get("Content-Type") == "application/x-www-form-urlencoded":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            form_data = {k: v[0] for k, v in parse_qs(body).items()}

        # 解析JSON数据
        json_data = None
        if self.headers.get("Content-Type") == "application/json":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                json_data = json.loads(body) if body else None
            except json.JSONDecodeError:
                raise ValueError("Invalid JSON data")

        return HTTPRequest(
            path=path,
            query_params=query_params,
            form_data=form_data,
            json_data=json_data,
            path_params=path_params,
            headers=dict(self.headers),
        )

    def find_matching_route(self, path: str) -> Tuple[Optional[str], Dict]:
        """
        查找匹配的路由并提取路径参数
        返回: (路由模式, 路径参数字典)
        """
        method = self.command
        routes = Route._routes["http"][method]

        # 1. 首先尝试完全匹配（静态路由）
        if path in routes:
            return path, {}

        # 2. 然后尝试带参的路由
        for pattern in routes:
            # 跳过静态路由
            if not "{" in pattern:
                continue
            path_params = self.match_route_pattern(pattern, path)
            if path_params is not None:
                return pattern, path_params

        return None, {}

    def match_route_pattern(self, pattern: str, path: str) -> Optional[Dict[str, str]]:
        """
        匹配路由模式并提取参数
        返回: 路径参数字典 或 None(如果不匹配)
        """
        # 分割路径
        pattern_parts = pattern.split("/")
        path_parts = path.split("/")

        # 检查路径段是否相同
        if len(pattern_parts) != len(path_parts):
            return None

        # 提取参数
        params = {}
        for pattern_part, path_part in zip(pattern_parts, path_parts):
            # 检查是否是参数部分
            if pattern_part.startswith("{") and pattern_part.endswith("}"):
                param_name = pattern_part[1:-1]
                # 检查参数值是否为数字
                if not path_part.isdigit():
                    return None
                params[param_name] = int(path_part)  # 转换为整数
            # 检查是否是静态部分
            elif pattern_part != path_part:
                return None

        return params

    def send_response_data(self, response: HTTPResponse):
        """发送响应"""
        # 先发送状态码
        self.send_response(response.status)

        # 获取响应头
        headers = response.get_response_headers()

        # 如果没有 Content-Type，添加默认值
        if "Content-Type" not in headers:
            headers["Content-Type"] = "text/plain"

        # 发送所有响应头
        for header, value in headers.items():
            self.send_header(header, value)

        self.end_headers()

        # 处理流式响应
        if hasattr(response, "is_stream") and response.is_stream:
            try:
                for chunk in response.get_body():
                    self.wfile.write(chunk)
                    self.wfile.flush()  # 确保数据立即发送
            except (ConnectionError, BrokenPipeError) as e:
                Logger.error(f"Connection error during streaming: {e}", True)
                return
        else:
            # 普通响应
            self.wfile.write(response.get_body())

    def handle_request(self, method: str):
        try:
            info = self.server.info if hasattr(self.server, "info") else True
            Logger.info(
                f"{method} Request from {self.client_address[0]}:{self.client_address[1]}",
                info,
            )

            # 解析请求数据
            request = self.parse_request_data()

            # 处理中间件请求
            middleware_response = (
                self.server_instance.middleware_manager.process_request(request, "http")
            )
            if middleware_response is not None:
                if not isinstance(middleware_response, HTTPResponse):
                    middleware_response = HTTPResponse(middleware_response)
                self.send_response_data(middleware_response)
                return

            # 查匹配的路由和处理函数
            route_pattern, _ = self.find_matching_route(request.path)
            if route_pattern and route_pattern in Route._routes["http"][method]:
                handler = Route._routes["http"][method][route_pattern]
                result = handler(request)

                # 处理后台任务
                for task, args, kwargs in request.bg.get_tasks():
                    self.server_instance.task_queue.add_task(task, *args, **kwargs)

                if not isinstance(result, HTTPResponse):
                    result = HTTPResponse(result)

                # 处理中间件响应
                result = self.server_instance.middleware_manager.process_response(
                    request, result, "http"
                )
                self.send_response_data(result)
            else:
                response = HTTPResponse({"error": "Not Found"}, 404)
                response = self.server_instance.middleware_manager.process_response(
                    request, response, "http"
                )
                self.send_response_data(response)

        except Exception as e:
            response = HTTPResponse({"error": str(e)}, 500)
            try:
                response = self.server_instance.middleware_manager.process_response(
                    request, response, "http"
                )
            except:
                pass
            self.send_response_data(response)
            Logger.error(f"Error handling {method} request: {str(e)}", info)
            Logger.error(traceback.format_exc(), info)

    def do_GET(self):
        """处理GET请求"""
        self.handle_request("GET")

    def do_POST(self):
        """处理POST请求"""
        self.handle_request("POST")

    def do_PUT(self):
        """处理PUT请求"""
        self.handle_request("PUT")

    def do_DELETE(self):
        """处理DELETE请求"""
        self.handle_request("DELETE")

    def log_message(self, format, *args):
        """重写日志方法"""
        pass


@dataclass
class TCPRequest:
    """TCP请求数据封装"""

    command: str
    data: Any
    data_type: str  # 'raw', 'json', 'xml'
    client_address: tuple
    bg: BackgroundTask = None

    def __post_init__(self):
        """确保bg属性总是有效"""
        if self.bg is None:
            self.bg = BackgroundTask()


class TCPHandler(BaseRequestHandler):
    def __init__(self, request, client_address, server, *, server_instance=None):
        self.server_instance = server_instance
        super().__init__(request, client_address, server)

    def handle(self):
        try:
            info = self.server.info if hasattr(self.server, "info") else True
            Logger.info(
                f"TCP Request from {self.client_address[0]}:{self.client_address[1]}",
                info,
            )

            data = self.request.recv(1024).decode().strip()
            Logger.info(f"Received data: {data}", info)

            request = self.parse_request_data(data)

            # 处理中间件请求
            middleware_response = (
                self.server_instance.middleware_manager.process_request(request, "tcp")
            )
            if middleware_response is not None:
                response = self.format_response(middleware_response, request.data_type)
                self.request.sendall(response.encode())
                return

            if request.command in Route._routes["tcp"]:
                handler = Route._routes["tcp"][request.command]
                result = handler(request)

                # 处理后台任务
                for task, args, kwargs in request.bg.get_tasks():
                    self.server_instance.task_queue.add_task(task, *args, **kwargs)

                # 处理中间件响应
                result = self.server_instance.middleware_manager.process_response(
                    request, result, "tcp"
                )
                response = self.format_response(result, request.data_type)
                self.request.sendall(response.encode())
            else:
                error_response = {"error": "Command not found"}
                error_response = (
                    self.server_instance.middleware_manager.process_response(
                        request, error_response, "tcp"
                    )
                )
                response = self.format_response(error_response, request.data_type)
                self.request.sendall(response.encode())

        except Exception as e:
            Logger.error(f"Error handling TCP request: {str(e)}", info)
            Logger.error(traceback.format_exc(), info)
            try:
                error_response = {"error": str(e)}
                error_response = (
                    self.server_instance.middleware_manager.process_response(
                        request, error_response, "tcp"
                    )
                )
                response = self.format_response(error_response, "json")
                self.request.sendall(response.encode())
            except:
                pass

    def parse_request_data(self, data: str) -> TCPRequest:
        """解析TCP请求数据"""
        try:
            # 尝试解析为JSON
            json_data = json.loads(data)
            if isinstance(json_data, dict) and "command" in json_data:
                return TCPRequest(
                    command=json_data["command"],
                    data=json_data.get("data"),
                    data_type="json",
                    client_address=self.client_address,
                )
        except json.JSONDecodeError:
            pass

        try:
            # 尝试解析为XML
            import xml.etree.ElementTree as ET

            root = ET.fromstring(data)
            if root.tag == "request" and "command" in root.attrib:
                return TCPRequest(
                    command=root.attrib["command"],
                    data=ET.tostring(root, encoding="unicode"),
                    data_type="xml",
                    client_address=self.client_address,
                )
        except Exception:
            pass

        # 默认作为原始数据处理
        parts = data.split(maxsplit=1)
        command = parts[0]
        raw_data = parts[1] if len(parts) > 1 else None
        return TCPRequest(
            command=command,
            data=raw_data,
            data_type="raw",
            client_address=self.client_address,
        )

    def format_response(self, data: Any, data_type: str) -> str:
        """格式化响应数据"""
        if data_type == "json":
            return json.dumps(data)
        elif data_type == "xml":
            # 简单的XML格式化
            if isinstance(data, dict):
                xml_parts = ["<response>"]
                for key, value in data.items():
                    xml_parts.append(f"<{key}>{value}</{key}>")
                xml_parts.append("</response>")
                return "\n".join(xml_parts)
            return str(data)
        else:
            # 原始数据格式
            return str(data)


class TaskQueue:
    """任务队列管理器"""

    def __init__(self, max_workers: int = 5):
        self.queue = Queue()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running = False
        self._worker_thread = None

    def start(self):
        """启动任务处理线程"""
        self._running = True
        self._worker_thread = Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()
        Logger.info("Background task queue started", True)

    def stop(self):
        """停止任务处理"""
        self._running = False
        if self._worker_thread:
            self.queue.put(None)  # 送停止信号
            self._worker_thread.join()
        self.executor.shutdown()
        Logger.info("Background task queue stopped", True)

    def add_task(self, func: Callable, *args, **kwargs) -> None:
        """添加任务到队列"""
        self.queue.put((func, args, kwargs))

    def _process_queue(self):
        """处理队列中的任务"""
        while self._running:
            try:
                item = self.queue.get()
                if item is None:  # 停止信号
                    break

                func, args, kwargs = item
                self.executor.submit(func, *args, **kwargs)

            except Exception as e:
                Logger.error(f"Error processing task: {str(e)}", True)
                Logger.error(traceback.format_exc(), True)
            finally:
                self.queue.task_done()


# 在Middleware类后面添加ContextMiddleware
class ContextMiddleware(Middleware):
    """下文中间件，管理g对象的生命周期"""

    def process_request(self, request: Any) -> None:
        """初始化请求上下文"""
        # 确保每个请求都有新的上下文
        ctx.clear_g()

        # 设置基本信息
        g.request = request
        g.request_id = id(request)

        # 如果是HTTP请求，设置HTTP特定信息
        if hasattr(request, "headers"):
            g.auth_token = request.headers.get("Authorization")

        return None

    def process_response(self, request: Any, response: Any) -> Any:
        """清理请求上下文"""
        try:
            return response
        finally:
            ctx.clear_g()
