# -*- coding:utf-8 -*-

from JiYou.chap11.RPC import impl_kombu


def msg_reply(msg_id, reply):
    msg = {'result': reply}             # 构造消息体
    conn = impl_kombu.Connection()      # 建立连接
    conn.direct_send(msg_id, msg)       # 向直接交换器发送消息


class ProxyCallback(object):

    def __init__(self, proxy):
        self.proxy = proxy

    def __call__(self, message_data):
        method = message_data.get('method')       # 获取RPC调用的方法
        args = message_data.get('args', {})       # 获取参数列表
        msg_id = message_data.get('msg_id')       # 获取消息的ID
        print('Receive RPC request. method is %s.\n' % method)

        self._process_data(msg_id, method, args)  # 处理消息

    def _process_data(self, msg_id, method, args):
        rval = self.proxy.dispatch(method, **args)    # 调用RpcDispatcher的dispatch方法处理消息
        msg_reply(msg_id, rval)                       # 返回处理结果
