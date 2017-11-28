class RpcDispatcher(object):
    def __init__(self, callback):
        self.callback = callback

    def dispatch(self, method, **kwargs):
        # 如果manager对象定义了method方法，则执行method方法
        if hasattr(self.callback, method):
            return getattr(self.callback, method)(**kwargs)
        # 否则，报错
        print('No such RPC method: %s\n' % method)

