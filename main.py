from tools import tool_register

if __name__ == '__main__':
    print(tool_register.call_tool("http_request", {"method": "GET", "url": "http://www.baidu.com"}))