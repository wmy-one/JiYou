from JiYou.chap11.RPC import rpc
TOPIC = 'sendout_request'         # 主题

msg = {'method': 'add',           # RPC调用的方法名
       'args':{'v1':2, 'v2':3}}   # 参数列表
rval = rpc.call(TOPIC, msg)       # 发送rpc.call请求
print('Succeed implementing RPC call. the return value is %d.\n' % rval)
