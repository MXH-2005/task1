import signal # 信号处理
import socket # 网络通信
import struct # 二进制数据处理
import sys # 系统接口
import threading
import argparse # 命令行参数解析
from datetime import datetime # 日期时间处理
import time

# 定义报文类型
INITIALIZATION = 1 #c->s：告知文本块数量
AGREE = 2 #s->c：确认初始化
REVERSE_REQUEST = 3 #c->s：发送待反转文本
REVERSE_ANSWER = 4 #s->c：返回反转结果

# 全局变量
client_threads = []  # 存储客户端活跃线程
client_connections = []  # 存储客户端连接
server_running = True  # 服务器运行标志

def get_formatted_time():
    """获取格式化的时间戳"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def create_packet(packet_type, data=None):
    """创建指定类型的报文（二进制格式）"""
    if packet_type == AGREE: 
        # AGREE报文：Type（2字节）
        return struct.pack('!H', AGREE)
    elif packet_type == REVERSE_ANSWER: #使用else无法区分REVERSE_REQUEST、AGREE等
        # REVERSE_ANSWER报文：Type（2字节）+ length（4字节）+ reverseData
        return struct.pack('!HI', REVERSE_ANSWER, len(data)) + data
    return None

def parse_packet(data):
    """解析接收到的报文（提取类型和数据）""" 
    if len(data) < 2: # 最小报文长度至少2字节
        return None, None # 第一个：标志报文类型无效或未解析成功；第二个：表示报文中的数据不存在或无效。
    
    # 解析Type字段（2字节无符号短整型）
    packet_type = struct.unpack('!H', data[:2])[0] # unpack返回元组(Type,)

    if packet_type == INITIALIZATION and len(data) >= 6: # INITIALIZATION报文：Type（2字节）+ N（4字节）
        n_blocks = struct.unpack('!I', data[2:6])[0] 
        return packet_type, n_blocks
    elif packet_type == REVERSE_REQUEST and len(data) >= 6: #REVERSE_REQUEST报文：Type（2字节）+Length（4字节）+ reverseData
        length = struct.unpack('!I', data[2:6])[0]
        if len(data) >= 6 + length:
            text = data[6:6+length].decode('ascii')
            return packet_type, text
    return None, None

def handle_client(conn, addr):
    """处理单个客户端连接"""
    now = get_formatted_time()
    print(f"[{now}] 客户端{addr}已连接")
    
    # 添加到连接列表
    client_connections.append(conn)
    
    try:
        # 1. 接收初始化报文（头部6字节）
        data = conn.recv(6)
        if not data or len(data) < 6:
            print(f"[{get_formatted_time()}] 来自{addr}的初始化报文不完整")
            return
        
        packet_type, n_blocks = parse_packet(data)
        if packet_type != INITIALIZATION:
            print(f"[{get_formatted_time()}] 来自{addr}的无效初始化报文")
            return
        
        print(f"[{get_formatted_time()}] 客户端{addr}请求反转{n_blocks}个文本块")
        
        # 2.发送同意报文（2字节）
        conn.send(create_packet(AGREE))

        # 3.处理每个文本块
        for block_index in range(n_blocks):
            # 检查服务器是否正在关闭
            if not server_running:
                print(f"[{get_formatted_time()}] 服务器正在关闭，终止客户端{addr}的处理")
                break
            
            # 接收反转请求头部（6字节）
            header = conn.recv(6)
            if len(header) < 6:
                print(f"[{get_formatted_time()}] 来自{addr}的请求头部不完整")
                break
            
            # 获取数据长度
            length = struct.unpack('!I', header[2:6])[0]

            # 接收剩余数据
            text_data = b''
            while len(text_data) < length:
                # 检查服务器是否正在关闭
                if not server_running:
                    print(f"[{get_formatted_time()}] 服务器正在关闭，终止客户端{addr}的处理")
                    break
                    
                chunk = conn.recv(length - len(text_data))
                if not chunk:
                    break
                text_data += chunk

            if len(text_data) < length:
                print(f"[{get_formatted_time()}] 来自{addr}的数据不完整（期望{length}字节，收到{len(text_data)}字节")
                break
            
            # 解析报文
            packet_type, text = parse_packet(header + text_data)
            if packet_type != REVERSE_REQUEST:
                print(f"[{get_formatted_time()}] 来自{addr}的无效请求报文")
                break
            
            # 反转文本并发送响应
            reversed_text = text[::-1].encode('ascii')
            # 处理每个块前休眠 0.5 秒
            time.sleep(0.5)  
            conn.send(create_packet(REVERSE_ANSWER, reversed_text))
            print(f"[{get_formatted_time()}] 已处理{addr}的第{block_index+1}/{n_blocks}个块")
    except Exception as e:
        print(f"[{get_formatted_time()}] 处理客户端{addr}时出错：{e}")
    finally:
        # 从连接列表移除
        if conn in client_connections:
            client_connections.remove(conn)
            
        conn.close()
        print(f"[{get_formatted_time()}] 客户端{addr}已断开连接")
        
        # 从线程列表移除
        if threading.current_thread() in client_threads:
            client_threads.remove(threading.current_thread())

def shutdown_server(signum, frame):
    """处理终止信号的回调函数（响应Ctrl+C）"""
    global server_running # 声明使用全局变量
    now = get_formatted_time()

    print(f"\n[{now}] 收到Ctrl+C终止信号，开始优雅关闭服务器...")
    
    # 1. 设置服务器关闭标志
    server_running = False
    print(f"[{now}] → 已设置服务器关闭标志")
    
    # 2. 主动关闭所有客户端连接
    print(f"[{now}] → 正在关闭 {len(client_connections)} 个活跃客户端连接")
    for conn in client_connections[:]:  # 创建副本避免迭代时修改原列表
        try:
            # 发送RST包强制关闭连接
            conn.shutdown(socket.SHUT_RDWR)
            conn.close()
            print(f"[{now}]    - 已关闭客户端连接")
        except Exception as e:
            print(f"[{now}]    - 关闭连接时出错：{e}")
    
    # 3. 等待客户端线程退出（设置超时）
    timeout_seconds = 5
    print(f"[{now}] → 等待最多 {timeout_seconds} 秒让客户端线程退出")
    for thread in client_threads[:]:  # 创建副本避免迭代时修改
        try:
            thread.join(timeout=timeout_seconds)
            if thread.is_alive():
                print(f"[{get_formatted_time()}]    - 线程 {thread.ident} 未在超时时间内退出")
            else:
                print(f"[{get_formatted_time()}]    - 线程 {thread.ident} 已成功退出")
        except Exception as e:
            print(f"[{get_formatted_time()}]    - 等待线程退出时出错：{e}")
    
    print(f"[{get_formatted_time()}] → 服务器资源已清理完毕")
    sys.exit(0)

def start_server(port):
    """启动TCP服务器"""
    signal.signal(signal.SIGINT, shutdown_server)  # 注册Ctrl+C信号处理
    now = get_formatted_time()
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(('0.0.0.0', port)) # 127.0.0.1
        server_socket.listen(5)
        print(f"[{now}] 反转服务器正在端口{port}上运行，等待连接...（Ctrl+C关闭服务器）")

        try:
            while server_running:
                # 设置超时，允许信号处理中断accept
                server_socket.settimeout(1.0)
                
                try:
                    conn, addr = server_socket.accept()
                    # 为每个客户端创建独立线程处理连接
                    client_thread = threading.Thread(target=handle_client, args=(conn, addr))
                    client_thread.start()
                    client_threads.append(client_thread)
                except socket.timeout:
                    # 超时继续循环，允许检查server_running标志
                    continue
                except Exception as e:
                    if server_running:  # 只在服务器正常运行时打印错误
                        print(f"[{get_formatted_time()}] 接受连接时出错：{e}")
                    continue
        except SystemExit:
            print(f"[{get_formatted_time()}] 服务器已成功关闭（优雅退出）")
        except Exception as e:
            print(f"[{get_formatted_time()}] 服务器异常退出：{e}")

if __name__ == "__main__":
    # argparser模块自动生成用法提示，当用户执行--help或参数错误时
    parser = argparse.ArgumentParser(description='TCP文本反转服务器')
    parser.add_argument('port', type=int, help='服务器端口号(1024-65535)')
    args = parser.parse_args()
    
    # 验证端口范围  
    if args.port < 1024 or args.port > 65535:
        print("错误：端口号必须在1024-65535范围内")
        exit(1)

    try:
        start_server(args.port)
    except Exception as e:
        print(f"[{get_formatted_time()}] 服务器启动失败：{e}")
        exit(1)