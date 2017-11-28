from JiYou.chap11.RPC import service

srv = service.Service()   # 创建RPC服务
srv.start()               # 启动RPC服务

while True:
    srv.drain_events()    # 监听RPC请求
