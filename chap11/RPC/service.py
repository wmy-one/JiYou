from JiYou.chap11.RPC import rpc
from JiYou.chap11.RPC import manager
from JiYou.chap11.RPC import dispatcher

TOPIC = 'sendout_request'

class Service(object):
    def __init__(self):
        self.topic = TOPIC         # 定义主题交换器的主体
        self.manager = manager.Manager()

    def start(self):
        self.conn = rpc.create_connection()                        # 创建RabbitMQ连接
        rpc_dispatcher = dispatcher.RpcDispatcher(self.manager)    # 创建分发器
        self.conn.create_consumer(self.topic, rpc_dispatcher)      # 创建主题消费者
        self.conn.consume()                                        # 激活主题消费者

    def drain_events(self):
        self.conn.drain_events()

