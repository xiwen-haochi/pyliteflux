# PyLiteFlux

PyLiteFlux 是一个轻量级的Python Web/TCP服务器框架，完全基于Python标准库实现，不依赖任何第三方包。它支持HTTP和TCP协议，提供了简单而强大的API来构建网络应用。适合用于学习和理解Python后端框架的概念和实现原理。

## 特性

- 支持HTTP和TCP服务器
- 支持TCP长连接和消息推送
- 支持后台任务处理
- 内置中间件系统
- 简单的路由注册
- 支持配置管理
- 支持请求上下文

## 安装

```bash
pip install pyliteflux
```

## 快速开始

### 基本使用

```python
from pyliteflux import Server, Route

server = Server()

@Route.register("/hello", method="GET")
def hello(request):
    return {"message": "Hello, World!"}

server.run()
```

### TCP长连接和消息推送示例

下面是一个简单的聊天系统示例，展示了如何使用TCP长连接和消息推送功能：

```python
from pyliteflux import Server, Route
import time

server = Server()
server.config.tcp_keep_alive = True  # 启用TCP长连接

# HTTP接口：发送消息给指定客户端
@Route.register("/hello", method="GET")
def hello(request):
    # 从查询参数中获取目标client_id
    target_client = request.query_params.get("client_id")
    
    def heavy_task():
        time.sleep(5)  # 模拟耗时操作
        server.push_message("Hello via HTTP GET!", target_client)
    
    request.bg.add(heavy_task)
    return {
        "message": "Hello via HTTP GET!",
        "target_client": target_client,
        "query_params": request.query_params
    }

# TCP接口：列出所有活跃连接
@Route.register("clients", protocol="tcp")
def list_clients(request):
    clients = list(server._active_connections.keys())
    return {
        "message": "Active TCP clients",
        "clients": clients,
        "count": len(clients)
    }

# TCP接口：订阅消息
@Route.register("subscribe", protocol="tcp")
def subscribe_tcp(request):
    client_id = f"{request.client_address[0]}:{request.client_address[1]}"
    return {"message": "subscribed", "client_id": client_id}

server.run()
```

## 主要功能

### HTTP服务器
- 支持GET、POST、PUT、DELETE方法
- 支持路由参数
- 支持查询参数
- 支持JSON和表单数据

### TCP服务器
- 支持长连接
- 支持消息推送
- 支持JSON和XML数据格式
- 支持自定义命令

### 后台任务
- 支持异步任务处理
- 任务队列管理
- 线程池执行

### 中间件系统
- 请求处理中间件
- 响应处理中间件
- 上下文管理中间件

### 中间件和全局上下文示例

#### 中间件使用

中间件可以处理请求和响应，实现认证、日志、性能监控等功能：

```python
from pyliteflux import Server, Route, Middleware

# 定义认证中间件
class AuthMiddleware(Middleware):
    def process_request(self, request):
        # 检查认证token
        token = request.headers.get("Authorization")
        if not token:
            return {"error": "Unauthorized"}
        
        # 将认证信息存储在g对象中
        g.user = self.validate_token(token)
        return None  # 继续处理请求
    
    def process_response(self, request, response):
        # 处理响应
        if isinstance(response, dict):
            response["authenticated"] = hasattr(g, "user")
        return response
    
    def validate_token(self, token):
        # 实际项目中这里应该验证token
        return {"id": 1, "name": "user1"}

# 定义日志中间件
class LogMiddleware(Middleware):
    def process_request(self, request):
        # 记录请求开始时间
        g.start_time = time.time()
        return None
    
    def process_response(self, request, response):
        # 计算请求处理时间
        duration = time.time() - g.start_time
        Logger.info(f"Request processed in {duration:.2f}s")
        return response

# 使用中间件
server = Server()
server.middleware_manager.add_middleware(AuthMiddleware())
server.middleware_manager.add_middleware(LogMiddleware())

# 在路由中使用g对象
@Route.register("/user", method="GET")
def get_user(request):
    if hasattr(g, "user"):
        return {
            "message": "User info",
            "user": g.user,
            "request_id": g.request_id  # 每个请求的唯一ID
        }
    return {"error": "User not found"}

server.run()
```

#### 全局上下文使用

g对象是请求级别的全局对象，可以在整个请求过程中共享数据：

```python
from pyliteflux import Server, Route, g

server = Server()

# 在中间件中设置数据
class DataMiddleware(Middleware):
    def process_request(self, request):
        g.db = Database()  # 假设的数据库连接
        g.cache = Cache()  # 假设的缓存连接
        return None
    
    def process_response(self, request, response):
        # 清理资源
        if hasattr(g, "db"):
            g.db.close()
        if hasattr(g, "cache"):
            g.cache.close()
        return response

# 在路由中使用g对象
@Route.register("/data", method="GET")
def get_data(request):
    # 使用g对象中的资源
    data = g.db.query("SELECT * FROM users")
    cached_data = g.cache.get("users")
    
    return {
        "data": data,
        "cached": cached_data,
        "request_id": g.request_id
    }

# 在后台任务中使用g对象
@Route.register("/async", method="GET")
def async_task(request):
    def background_job():
        # 注意：后台任务有自己的g对象实例
        g.task_id = uuid.uuid4()
        Logger.info(f"Background task {g.task_id} started")
        
    request.bg.add(background_job)
    return {"message": "Task scheduled"}

server.run()
```

#### 实际应用场景

1. 用户认证和授权：
```python
class AuthMiddleware(Middleware):
    def process_request(self, request):
        token = request.headers.get("Authorization")
        if token:
            g.user = self.authenticate(token)
            g.permissions = self.get_permissions(g.user)
        return None

@Route.register("/admin", method="GET")
def admin_panel(request):
    if not hasattr(g, "permissions") or "admin" not in g.permissions:
        return {"error": "Access denied"}, 403
    return {"message": "Welcome, admin!"}
```

2. 性能监控：
```python
class PerformanceMiddleware(Middleware):
    def process_request(self, request):
        g.start_time = time.time()
        g.sql_queries = []
        return None
    
    def process_response(self, request, response):
        duration = time.time() - g.start_time
        metrics = {
            "duration": duration,
            "sql_queries": len(g.sql_queries),
            "memory_usage": self.get_memory_usage()
        }
        Logger.info(f"Performance metrics: {metrics}")
        return response
```

3. 请求跟踪：
```python
class TracingMiddleware(Middleware):
    def process_request(self, request):
        g.trace_id = str(uuid.uuid4())
        g.span_id = str(uuid.uuid4())
        g.traces = []
        return None
    
    def process_response(self, request, response):
        if isinstance(response, dict):
            response["trace_id"] = g.trace_id
            response["traces"] = g.traces
        return response

@Route.register("/trace", method="GET")
def traced_endpoint(request):
    g.traces.append({"event": "processing", "time": time.time()})
    result = process_data()
    g.traces.append({"event": "completed", "time": time.time()})
    return {"data": result}
```

这些示例展示了中间件和g对象的强大功能：
1. 请求前后的处理
2. 资源的自动管理
3. 请求级别的数据共享
4. 性能监控和日志记录
5. 认证和授权
6. 请求跟踪和调试

中间件和g对象的组合使用可以大大提高开发效率和代码质量。

## 配置选项

```python
server = Server()
server.config.update(
    http_host="127.0.0.1",
    http_port=8000,
    tcp_host="127.0.0.1",
    tcp_port=8001,
    tcp_keep_alive=True,  # 启用TCP长连接
    info=True  # 启用日志
)
```

## API文档

### 路由装饰器
```python
@Route.register(path, method="GET", protocol="http")
```
- path: 路由路径
- method: HTTP方法（GET/POST/PUT/DELETE）
- protocol: 协议类型（http/tcp）

### 服务器方法
```python
server.run()  # 启动服务器
server.stop()  # 停止服务器
server.push_message(message, client_id=None)  # 推送消息
```

### 请求对象
```python
request.query_params  # 查询参数
request.form_data    # 表单数据
request.json_data    # JSON数据
request.headers      # 请求头
request.bg.add(task) # 添加后台任务
```

### 响应格式

PyLiteFlux支持多种响应格式，包括普通JSON响应、流式响应和自定义JSON响应：

#### 1. 普通JSON响应

````python
@Route.register("/hello", method="GET")
def hello(request):
    return {"message": "Hello, World!"}  # 自动转换为JSON响应
````

#### 2. 流式响应

流式响应适用于大数据传输或需要实时推送数据的场景：

````python
from pyliteflux import StreamResponse

@Route.register("/stream", method="GET")
def stream_data(request):
    def generate_data():
        for i in range(10):
            time.sleep(1)  # 模拟数据生成
            yield f"data: {i}\n\n"
    
    return StreamResponse(
        generate_data(),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
    )

# 带参数的流式响应
@Route.register("/download", method="GET")
def download_file(request):
    def file_reader():
        with open("large_file.txt", "rb") as f:
            while chunk := f.read(8192):
                yield chunk
    
    return StreamResponse(
        file_reader(),
        content_type="application/octet-stream",
        headers={
            "Content-Disposition": "attachment; filename=large_file.txt"
        }
    )
````

#### 3. HTTPJSONResponse响应

当需要更细粒度地控制JSON响应时，可以使用HTTPJSONResponse：

````python
from pyliteflux import HTTPJSONResponse

@Route.register("/api/user", method="GET")
def get_user(request):
    user_data = {"id": 1, "name": "John"}
    return HTTPJSONResponse(
        data=user_data,
        status=200,
        headers={
            "X-Custom-Header": "value",
            "Access-Control-Allow-Origin": "*"
        }
    )

# 错误响应示例
@Route.register("/api/error", method="GET")
def error_response(request):
    return HTTPJSONResponse(
        data={"error": "Not Found", "code": "404"},
        status=404,
        headers={"X-Error-Type": "NotFound"}
    )

# 自定义序列化示例
@Route.register("/api/custom", method="GET")
def custom_serialization(request):
    class CustomEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return super().default(obj)
    
    data = {
        "timestamp": datetime.now(),
        "message": "Custom serialization"
    }
    
    return HTTPJSONResponse(
        data=data,
        json_encoder=CustomEncoder,
        headers={"Content-Type": "application/json"}
    )
````

#### 4. 组合使用示例

````python
@Route.register("/api/complex", method="GET")
def complex_response(request):
    response_type = request.query_params.get("type", "json")
    
    if response_type == "stream":
        def stream():
            for i in range(5):
                yield json.dumps({"count": i}) + "\n"
        return StreamResponse(stream(), content_type="application/x-ndjson")
    
    elif response_type == "error":
        return HTTPJSONResponse(
            {"error": "Bad Request"},
            status=400,
            headers={"X-Error-Details": "Invalid type"}
        )
    
    else:
        return {"message": "Regular JSON response"}  # 自动转换为JSON
````



## 参数使用说明

### 服务器配置参数

服务器实例支持多种配置参数，可以通过config对象进行设置：

```python
from pyliteflux import Server

server = Server()

# 方式1：通过属性设置
server.config.http_host = "127.0.0.1"
server.config.http_port = 8000
server.config.tcp_keep_alive = True

# 方式2：通过update方法批量设置
server.config.update(
    http_host="127.0.0.1",
    http_port=8000,
    tcp_host="127.0.0.1",
    tcp_port=8001,
    tcp_keep_alive=True,
    info=True
)
```

配置参数说明：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| http_host | str | "127.0.0.1" | HTTP服务器主机地址 |
| http_port | int | 8000 | HTTP服务器端口 |
| tcp_host | str | "127.0.0.1" | TCP服务器主机地址 |
| tcp_port | int | 8001 | TCP服务器端口 |
| tcp_keep_alive | bool | False | 是否启用TCP长连接 |
| info | bool | True | 是否启用日志输出 |

### 路由参数

路由装饰器支持多种参数配置：

```python
from pyliteflux import Route

# HTTP路由
@Route.register("/hello", method="GET")  # 基本GET请求
@Route.register("/user", method="POST")  # POST请求
@Route.register("/user/{id}", method="GET")  # 带路径参数的路由
@Route.register("/files/*", method="GET")  # 通配符路由

# TCP路由
@Route.register("command", protocol="tcp")  # TCP命令路由
```

路由参数说明：
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| path | str | 必填 | 路由路径 |
| method | str | "GET" | HTTP方法（GET/POST/PUT/DELETE） |
| protocol | str | "http" | 协议类型（http/tcp） |

### 请求参数

HTTP请求可以通过多种方式传递参数：

```python
# 1. 查询参数
@Route.register("/search", method="GET")
def search(request):
    keyword = request.query_params.get("keyword")
    page = request.query_params.get("page", "1")
    return {"keyword": keyword, "page": page}

# 2. 路径参数
@Route.register("/user/{user_id}/posts/{post_id}", method="GET")
def get_post(request):
    user_id = request.path_params["user_id"]
    post_id = request.path_params["post_id"]
    return {"user_id": user_id, "post_id": post_id}

# 3. 表单数据
@Route.register("/upload", method="POST")
def upload(request):
    file_name = request.form_data.get("file_name")
    content = request.form_data.get("content")
    return {"file_name": file_name}

# 4. JSON数据
@Route.register("/api/data", method="POST")
def handle_json(request):
    data = request.json_data
    return {"received": data}
```

### TCP连接参数

TCP连接相关的参数和使用方式：

```python
# 1. 启用TCP长连接
server = Server()
server.config.tcp_keep_alive = True

# 2. 发送消息给特定客户端
@Route.register("/push", method="GET")
def push_message(request):
    client_id = request.query_params.get("client_id")
    message = request.query_params.get("message", "Hello!")
    server.push_message(message, client_id)
    return {"status": "sent"}

# 3. 广播消息给所有客户端
@Route.register("/broadcast", method="GET")
def broadcast(request):
    message = request.query_params.get("message", "Broadcast!")
    server.push_message(message)  # 不指定client_id则广播
    return {"status": "broadcasted"}
```

### 中间件参数

中间件可以通过process_request和process_response方法处理请求和响应：

```python
class CustomMiddleware(Middleware):
    def __init__(self, **options):
        self.options = options
    
    def process_request(self, request):
        # 处理请求
        request.custom_attr = self.options.get("custom_attr")
        return None
    
    def process_response(self, request, response):
        # 处理响应
        if isinstance(response, dict):
            response["processed_by"] = self.options.get("name", "CustomMiddleware")
        return response

# 使用中间件
server = Server()
server.middleware_manager.add_middleware(
    CustomMiddleware(
        name="MyMiddleware",
        custom_attr="custom_value"
    )
)
```

### 后台任务参数

后台任务支持参数传递：

```python
@Route.register("/task", method="GET")
def async_task(request):
    def background_job(user_id, task_type="default"):
        time.sleep(5)
        Logger.info(f"Processing {task_type} task for user {user_id}")
    
    # 添加带参数的后台任务
    user_id = request.query_params.get("user_id", "0")
    request.bg.add(
        background_job,
        user_id,  # 位置参数
        task_type="important"  # 关键字参数
    )
    
    return {"message": "Task scheduled"}
```

这些参数的使用示例展示了框架的灵活性和功能性。你可以根据需要组合使用这些参数来实现各种功能。所有参数都有合理的默认值，使框架既易于使用又足够灵活。

需要注意的是：
1. 参数名称区分大小写
2. 必填参数没有默认值时必须提供
3. 某些参数组合可能会相互影响
4. 建议遵循Python的命名规范


## 注意事项

1. TCP长连接需要显式启用：`server.config.tcp_keep_alive = True`
2. 后台任务会在独立的线程池中
3. 推送消息时如果不指定client_id，将广播给所有连接的客户端

## 许可证

MIT License