# -*- coding:utf-8 -*-
import functools
import itertools
import socket
import uuid
import time

import eventlet
import greenlet
import kombu
import kombu.connection
import kombu.entity
import kombu.messaging

from JiYou.chap11.RPC import rpc_amqp
from JiYou.chap11.RPC import rpc

rabbit_params = {
    'hostname':'10.239.131.181',      # RabbitMQ服务器所在节点的地址
    'port':5672,                      # RabbitMQ服务器监听的端口
    'userid': 'guest',                # 连接RabbitMQ服务器的用户名
    'password': 'guest',              # 连接RabbitMQ服务器的密码
    'virtual_host': '/',              # RabbitMQ服务器的虚拟目录
}

conf = {
    'interval_start': 1,
    'interval_stepping': 2,
    'interval_max': 30,
}

DIRECT = 'feedback_request_'


class ConsumerBase(object):

    def __init__(self, channel, callback, tag, **kwargs):
        self.callback = callback             # 处理RPC请求的回调函数
        self.tag = str(tag)                  # 消费者的tag
        self.kwargs = kwargs                 # 队列属性，包括durable、auto_delete等
        self.queue = None                    # 队列初始为空
        self.reconnect(channel)              # 创建并声明队列

    def reconnect(self, channel):
        self.channel = channel
        self.kwargs['channel'] = channel                 # 设置信道属性
        self.queue = kombu.entity.Queue(**self.kwargs)   # 创建队列
        self.queue.declare()                             # 声明队列

    def consume(self, *args, **kwargs):
        options = {'consumer_tag': self.tag}      # 设置消费者的tag属性
        options['nowait'] = False                # 是否等待响应

        def _callback(raw_message):
            message = self.channel.message_to_python(raw_message)
            try:
                msg = message.payload          # 获取消息体
                self.callback(msg)             # 处理消息
                message.ack()                  # 通知交换器消息处理完毕
            except Exception:
                print("Failed to process message... skipping it.\n")

        self.queue.consume(*args, callback=_callback, **options)

    def cancel(self):
        try:
            self.queue.cancel(self.tag)
        except KeyError as e:
            if str(e) != "u'%s'" % self.tag:
                raise
        self.queue = None

class DirectConsumer(ConsumerBase):
    def __init__(self, channel, msg_id, callback, tag, **kwargs):
        self.topic = msg_id
        options = {'durable': False,
                   'auto_delete': True,
                   'exclusive': False}
        options.update(kwargs)
        exchange = kombu.entity.Exchange(name=msg_id,
                                         type='direct',
                                         durable=options['durable'],
                                         auto_delete=options['auto_delete'])
        super(DirectConsumer, self).__init__(channel,
                                             callback,
                                             tag,
                                             name=msg_id,
                                             exchange=exchange,
                                             routing_key=msg_id,
                                                 **options)


class TopicConsumer(ConsumerBase):

    def __init__(self, channel, topic, callback, tag, **kwargs):
        self.topic = topic                    # 消费者主题
        options = {'durable': False,         # 交换器是否是持久的
                   'auto_delete': False,     # 交换器和队列是否自动删除
                   'exclusive': False}       # 队列是否互斥
        options.update(kwargs)

        # 创建主题交换器
        exchange = kombu.entity.Exchange(name=topic,
                                         type='topic',
                                         durable=options['durable'],
                                         auto_delete=options['auto_delete'])

        # 初始化父类，创建交换队列
        super(TopicConsumer, self).__init__(channel,
                                            callback,
                                            tag,
                                            name=topic,
                                            exchange=exchange,
                                            routing_key=topic,
                                            **options)


class Publisher(object):
    def __init__(self, channel, exchange_name, routing_key, **kwargs):
        self.exchange_name = exchange_name      # 交换器名
        self.routing_key = routing_key          # 对列名
        self.type = kwargs.pop('type')          # 交换器类型
        self.kwargs = kwargs                    # 其他属性
        self.reconnect(channel)                 # 创建Producer

    def reconnect(self, channel):
        # 创建交换器
        self.exchange = kombu.entity.Exchange(self.exchange_name,
                                              self.type,
                                              **self.kwargs)
        # 创建生产者
        self.producer = kombu.messaging.Producer(channel,
                                                 exchange=self.exchange)

    def send(self, msg):
        self.producer.publish(msg,
                              routing_key=self.routing_key)


class DirectPublisher(Publisher):
    def __init__(self, channel, msg_id, **kwargs):
        options = {'durable': False,
                   'auto_delete': True,
                   'exclusive': False}
        options.update(kwargs)
        super(DirectPublisher, self).__init__(channel, msg_id, msg_id,
                                              type='direct', **options)


class TopicPublisher(Publisher):
    def __init__(self, channel, topic, **kwargs):
        # 设置主题交换器属性
        options = {'durable': False,        # 是否持久化
                   'auto_delete': False,    # 是否自动删除
                   'exclusive': False}      # 是否互斥
        options.update(kwargs)
        super(TopicPublisher, self).__init__(channel, topic, topic,
                                             type='topic', **options)


class Connection(object):

    def __init__(self):
        self.consumers = []
        self.connection = None
        self.reconnect()

    def reconnect(self):
        sleep_time = conf.get('interval_start', 1)     # 初次重连的等待时间
        stepping = conf.get('interval_stepping', 2)    # 每次连接失败后增加的等待时间
        interval_max = conf.get('interval_max', 30)    # 重连的最大等待时间
        sleep_time -= stepping

        while True:
            try:
                self._connect()                  # 尝试连接RabbitMQ服务器
                return
            except Exception as e:              # python2.x版本语法： Exception, e:
                if 'timeout' not in str(e):     # 如果不是超时异常，则抛出
                    raise

            sleep_time += stepping
            sleep_time = min(sleep_time, interval_max)
            print("AMQP Server is unreachable,"
                  "trying to connect %d seconds later\n" % sleep_time)
            time.sleep(sleep_time)

    def _connect(self):
        hostname = rabbit_params.get('hostname')      # RabbitMQ服务器所在的主机名
        port = rabbit_params.get('port')              # RabbitMQ服务器的监听端口

        if self.connection:                           # 如果已经建立连接
            print("Reconnecting to AMQP Server on "
                  "%(hostname)s:%(port)d\n" % locals())
            self.connection.release()                 # 释放原来的连接
            self.connection = None

        # 创建BrokerConnection对象
        self.connection = kombu.connection.BrokerConnection(**rabbit_params)
        self.consumer_num = itertools.count(1)        # 重置消费者迭代器
        self.connection.connect()                     # 与RabbitMQ服务器连接
        self.channel = self.connection.channel()      # 获取连接的信道
        for consumer in self.consumers:
            consumer.reconnect(self.channel)          # 重置消费者的信道

    def create_consumer(self, topic, proxy):
        proxy_cb = rpc_amqp.ProxyCallback(proxy)      # ProxyCallback是一个可调用对象，用来处理消费者接收到的消息
        self.declare_topic_consumer(topic, proxy_cb)  # 创建主题消费者

    def declare_consumer(self, consumer_cls, topic, callback):
        def _declare_consumer():                             # 内部方法
            consumer = consumer_cls(self.channel, 
                                    topic, callback,
                                    self.consumer_num.next())   # 创建Consumer对象
            self.consumers.append(consumer)                     # 添加consumer对象
            print('Succed declaring consumer for topic %s\n' % topic)
            return consumer
        return self.ensure(_declare_consumer, topic)            # 不断执行_declare_consumer方法，直到执行成功

    def ensure(self, method, topic):
        while True:
            try:
                return method()
            except Exception as e:
                if 'timeout' not in str(e):
                    raise
                print('Failed to declare consumer for topic %s: '
                      '%s\n' % (topic, str(e)))

            self.reconnect()

    def declare_direct_consumer(self, topic, callback):
        print('declaring direct consumer for topic %s...\n' % topic)
        self.declare_consumer(DirectConsumer, topic, callback)

    def declare_topic_consumer(self, topic, callback):
        print('declaring topic consumer for topic %s...\n' % topic)
        self.declare_consumer(TopicConsumer, topic, callback)

    def consume(self, limit=None):
        for consumer in self.consumers:
            consumer.consume()

    def drain_events(self):
        if self.connection:
            return self.connection.drain_events()
        
    def publisher_send(self, cls, topic, msg, **kwargs):
        # 内部方法
        def _publish():
            # 创建publisher对象
            publisher = cls(self.channel, topic, **kwargs)
            publisher.send(msg)           # 向主题交换器发送消息

        self.ensure(_publish, topic)      # 调用内部方法

    def direct_send(self, msg_id, msg):
        self.publisher_send(DirectPublisher, msg_id, msg)

    def topic_send(self, topic, msg):
        self.publisher_send(TopicPublisher, topic, msg)

    def close(self):
        self.connection.release()
        self.connection = None

    def get_consumers(self):
        return self.consumers


class CallWaiter(object):
    def __init__(self, connection, timeout=None):
        self._connection = connection
        self._result = None

    def __call__(self, data):
        if data['result']:
            self._result = data['result']

    def wait_reply(self):
        self._connection.consume()            # 激活消费者
        self._connection.drain_events()       # 等待响应
        return self._result


def call(topic, msg, timeout):
    print('Making synchronous call on %s ...\n' % topic)
    msg_id = DIRECT + str(uuid.uuid4())       # 构造消息ID
    msg.update({'msg_id': msg_id})            # 将消息ID添加到消息体中
    print('MSG_ID is %s\n' % msg_id)

    conn = rpc.create_connection()            # 连接RabbitMQ服务器
    wait_msg = CallWaiter(conn)
    conn.declare_direct_consumer(msg_id, wait_msg)    # 声明直接交换器
    conn.topic_send(topic, msg)               # 向主题交换器发送消息
    return wait_msg.wait_reply()             # 等待RPC响应
