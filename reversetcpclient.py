import socket # 网络通信
import struct # 二进制数据处理
import random # 随机数生成
import os # 文件路径操作
import argparse # 命令行参数解析
import signal # 信号处理
import sys # 系统接口
from datetime import datetime # 日期时间处理

# 定义报文类型
INITIALIZATION = 1 #c->s：告知文本块数量
AGREE = 2 #s->c：确认初始化
REVERSE_REQUEST = 3 #c->s：发送待反转文本
REVERSE_ANSWER = 4 #s->c：返回反转结果

def get_formatted_time():
    """获取格式化的时间戳"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def create_packet(packet_type, data=None):
    """创建指定类型的报文"""
    if packet_type == INITIALIZATION: 
        # INITIALIZATION报文：Type（2字节）+ N（4字节）
        return struct.pack('!HI', INITIALIZATION, data)
        # !表示网络字节序（大端序，即高位字节在前）
        # H表示无符号短整型（2字节），用于存储报文类型（INITIALIZATION）
        # I表示无符号整形（4字节），用于存储数据（块数量N）
    elif packet_type == REVERSE_REQUEST:
        # REVERSE_REQUEST报文：Type（2字节）+ length（4字节）+ Data
        return struct.pack('!HI', REVERSE_REQUEST, len(data)) + data
    return None

def parse_packet(data):
    """解析接收到的报文""" 
    if len(data) < 2: # 最小报文长度至少2字节
        return None, None # 第一个：标志报文类型无效或未解析成功；第二个：表示报文中的数据不存在或无效。
    
    # 解析Type字段（2字节无符号短整型）
    packet_type = struct.unpack('!H', data[:2])[0]

    if packet_type == AGREE: 
        # AGREE报文：Type（2字节）
        return packet_type, None
    elif packet_type == REVERSE_ANSWER and len(data) >= 6:
        # REVERSE_ANSWER报文：Type（2字节）+Length（4字节）+ Data
        length = struct.unpack('!I', data[2:6])[0]
        if len(data) >= 6 + length:
            reversed_text = data[6:6+length].decode('ascii')
            return packet_type, reversed_text
    return None, None

def shutdown_client(signum, frame):
    """处理终止信号的回调函数"""
    print(f"\n[{get_formatted_time()}] 收到终止信号，正在关闭客户端...")
    sys.exit(0)

def main():
    """客户端主函数"""
    # argparser模块自动生成用法提示，当用户执行--help或参数错误时
    parser = argparse.ArgumentParser(description='TCP文本反转客户端')
    parser.add_argument('server_ip', help='服务器IP地址')
    parser.add_argument('server_port', type=int, help='服务器端口号(1024-65535)')
    parser.add_argument('input_file', help='输入文本文件')
    parser.add_argument('Lmin', type=int, help='最小块大小')
    parser.add_argument('Lmax', type=int, help='最大块大小')

    args = parser.parse_args()

    # 验证端口范围
    if args.server_port < 1024 or args.server_port > 65535:
        print("错误：端口号必须在1024-65535范围内")
        exit(1)

    # 验证参数
    if args.Lmin <= 0 or args.Lmax <= 0 or args.Lmin > args.Lmax:
        print("错误：无效的块大小参数")
        exit(1)

    # 检查文件是否存在
    if not os.path.exists(args.input_file):
        print(f"错误：文件 '{args.input_file}' 不存在")
        exit(1)

    # 注册信号处理（响应Ctrl+C）
    signal.signal(signal.SIGINT, shutdown_client)

    try:
        # 1. 读取文本内容
        with open(args.input_file, 'r') as f:
            content = f.read()

        # 2. 验证文件内容是否为可打印ASCII字符
        if not all(32 <= ord(c) <= 126 for c in content):
            print("错误：文件包含非可打印ASCII字符")
            exit(1)
        
        # 3. 生成随机大小的文本块
        blocks = []
        total_length = len(content)
        start_index = 0

        print(f"[{get_formatted_time()}] 文件大小：{total_length}字符")
        print(f"[{get_formatted_time()}] 分割范围：{args.Lmin}-{args.Lmax}字符/块")

        while start_index < total_length:
            block_size = random.randint(args.Lmin, args.Lmax)
            end_index = min(start_index + block_size, total_length)
            block = content[start_index:end_index]
            blocks.append(block)
            start_index = end_index

        n_blocks = len(blocks)
        reversed_blocks = [None] * n_blocks
        print(f"[{get_formatted_time()}] 文件分割为{n_blocks}个文本块")

        # 4. 连接服务器
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
            # 设置超时时间为5秒
            client_socket.settimeout(5.0)
            
            print(f"[{get_formatted_time()}] 正在连接服务器 {args.server_ip}:{args.server_port}...")
            
            try:
                client_socket.connect((args.server_ip, args.server_port)) # 连接服务器
                print(f"[{get_formatted_time()}] 已连接到服务器")
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                print(f"[{get_formatted_time()}] 错误：连接服务器失败 - {e}")
                return
            except Exception as e:
                print(f"[{get_formatted_time()}] 错误：连接服务器时发生未知异常 - {e}")
                return

            # 5. 发送初始化报文（6字节）：告知块数量
            try:
                init_packet = create_packet(INITIALIZATION, n_blocks)
                client_socket.sendall(init_packet)
                print(f"[{get_formatted_time()}] 已发送初始化报文，块数：{n_blocks}")
            except (socket.error, OSError) as e:
                print(f"[{get_formatted_time()}] 错误：发送初始化报文失败 - {e}")
                return
            except Exception as e:
                print(f"[{get_formatted_time()}] 错误：发送初始化报文时发生未知异常 - {e}")
                return

            # 6. 接收同意报文（2字节）：确认初始化
            try:
                data = client_socket.recv(2)
                if len(data) < 2:
                    print(f"[{get_formatted_time()}] 错误：接收AGREE报文失败，数据不完整")
                    return
                
                packet_type, _ = parse_packet(data)
                if packet_type != AGREE:
                    print(f"[{get_formatted_time()}] 错误：服务器未同意请求，收到无效报文类型")
                    return
                
                print(f"[{get_formatted_time()}] 已收到服务器同意报文")
            except (socket.timeout, socket.error, OSError) as e:
                print(f"[{get_formatted_time()}] 错误：接收AGREE报文失败 - {e}")
                return
            except Exception as e:
                print(f"[{get_formatted_time()}] 错误：处理AGREE报文时发生未知异常 - {e}")
                return

            # 7. 处理每个文本块
            for i, block in enumerate(blocks):
                try:
                    # 发送反转请求
                    request_data = create_packet(REVERSE_REQUEST, block.encode('ascii'))
                    client_socket.sendall(request_data)
                    print(f"[{get_formatted_time()}] 已发送块 {i+1}/{n_blocks}，长度：{len(block)}")
                except (socket.error, OSError) as e:
                    print(f"[{get_formatted_time()}] 错误：发送块 {i+1} 请求失败 - {e}")
                    break
                except Exception as e:
                    print(f"[{get_formatted_time()}] 错误：发送块 {i+1} 时发生未知异常 - {e}")
                    break

                # 接收响应头部（6字节）
                try:
                    header = client_socket.recv(6) # 读取Type+Length
                    if len(header) < 6:
                        print(f"[{get_formatted_time()}] 错误：接收块 {i+1} 响应头部不完整")
                        break
                except (socket.timeout, socket.error, OSError) as e:
                    print(f"[{get_formatted_time()}] 错误：接收块 {i+1} 响应头部失败 - {e}")
                    break
                except Exception as e:
                    print(f"[{get_formatted_time()}] 错误：接收块 {i+1} 响应头部时发生未知异常 - {e}")
                    break

                # 获取数据长度
                try:
                    length = struct.unpack('!I', header[2:6])[0]
                except struct.error:
                    print(f"[{get_formatted_time()}] 错误：解析块 {i+1} 长度失败")
                    break

                # 接收剩余数据：反转文本
                reversed_data = b''
                try:
                    client_socket.settimeout(10.0)  
                    while len(reversed_data) < length:
                        chunk = client_socket.recv(length - len(reversed_data))
                        if not chunk:
                            break
                        reversed_data += chunk
                    
                    if len(reversed_data) < length:
                        print(f"[{get_formatted_time()}] 错误：接收块 {i+1} 数据不完整（期望{length}字节，收到{len(reversed_data)}字节）")
                        break
                except (socket.timeout, socket.error, OSError) as e:
                    print(f"[{get_formatted_time()}] 错误：接收块 {i+1} 数据失败 - {e}")
                    break
                except Exception as e:
                    print(f"[{get_formatted_time()}] 错误：接收块 {i+1} 数据时发生未知异常 - {e}")
                    break

                # 解析响应
                try:
                    packet_type, reversed_text = parse_packet(header + reversed_data)
                    if packet_type != REVERSE_ANSWER:
                        print(f"[{get_formatted_time()}] 错误：块 {i+1} 收到无效响应报文，类型：{packet_type}")
                        break

                    reversed_blocks[i] = reversed_text
                    print(f"[{get_formatted_time()}] 块{i+1}/{n_blocks}: {reversed_text[:50]}{'...' if len(reversed_text) > 50 else ''}")
                except Exception as e:
                    print(f"[{get_formatted_time()}] 错误：解析块 {i+1} 响应时出错 - {e}")
                    break

            # 8. 生成最终反转文件
            if all(block is not None for block in reversed_blocks):
                output_file = os.path.splitext(args.input_file)[0] + "_reversed.txt"
                with open(output_file, 'w') as f:
                    for block in reversed_blocks:
                        f.write(block)
                print(f"[{get_formatted_time()}] 反转完成！结果已保存到：{output_file}")
            else:
                print(f"[{get_formatted_time()}] 错误：部分块处理失败，未生成完整反转文件")

    except socket.timeout as e:
        print(f"[{get_formatted_time()}] 网络超时错误：{e}")
    except (socket.error, OSError) as e:
        print(f"[{get_formatted_time()}] 网络错误：{e}")    
    except Exception as e:
        print(f"[{get_formatted_time()}] 客户端错误：{e}")

if __name__ == "__main__":
    main()