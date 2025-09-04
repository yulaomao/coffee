"""
Mock Redis for testing - implements the basic Redis operations needed
"""

class MockRedis:
    def __init__(self):
        self.data = {}
        self.sets = {}
        self.zsets = {}
        self.lists = {}
        self.streams = {}
    
    def hset(self, key, mapping=None, **kwargs):
        if key not in self.data:
            self.data[key] = {}
        if mapping:
            self.data[key].update(mapping)
        if kwargs:
            self.data[key].update(kwargs)
        return len(mapping) if mapping else len(kwargs)
    
    def hget(self, key, field):
        return self.data.get(key, {}).get(field)
    
    def hgetall(self, key):
        return self.data.get(key, {})
    
    def sadd(self, key, *values):
        if key not in self.sets:
            self.sets[key] = set()
        before = len(self.sets[key])
        self.sets[key].update(values)
        return len(self.sets[key]) - before
    
    def srem(self, key, *values):
        if key not in self.sets:
            return 0
        before = len(self.sets[key])
        self.sets[key] -= set(values)
        return before - len(self.sets[key])
    
    def smembers(self, key):
        return self.sets.get(key, set())
    
    def zadd(self, key, mapping):
        if key not in self.zsets:
            self.zsets[key] = {}
        self.zsets[key].update(mapping)
        return len(mapping)
    
    def zrangebyscore(self, key, min_score, max_score, **kwargs):
        if key not in self.zsets:
            return []
        items = [(score, member) for member, score in self.zsets[key].items() 
                if min_score <= score <= max_score]
        items.sort()
        return [member for score, member in items]
    
    def lpush(self, key, *values):
        if key not in self.lists:
            self.lists[key] = []
        for value in values:
            self.lists[key].insert(0, value)
        return len(self.lists[key])
    
    def rpop(self, key):
        if key not in self.lists or not self.lists[key]:
            return None
        return self.lists[key].pop()
    
    def lrange(self, key, start, end):
        if key not in self.lists:
            return []
        return self.lists[key][start:end+1 if end != -1 else None]
    
    def ltrim(self, key, start, end):
        if key not in self.lists:
            return
        self.lists[key] = self.lists[key][start:end+1]
    
    def get(self, key):
        return self.data.get(key)
    
    def set(self, key, value):
        self.data[key] = value
        return True
    
    def incr(self, key):
        current = int(self.data.get(key, 0))
        self.data[key] = str(current + 1)
        return current + 1
    
    def incrby(self, key, amount):
        current = int(self.data.get(key, 0))
        self.data[key] = str(current + amount)
        return current + amount
    
    def xadd(self, key, fields):
        if key not in self.streams:
            self.streams[key] = []
        self.streams[key].append(fields)
        return f"entry-{len(self.streams[key])}"
    
    def pipeline(self):
        return MockPipeline(self)


class MockPipeline:
    def __init__(self, redis_client):
        self.redis = redis_client
        self.commands = []
    
    def hset(self, key, mapping=None, **kwargs):
        self.commands.append(('hset', key, mapping, kwargs))
        return self
    
    def zadd(self, key, mapping):
        self.commands.append(('zadd', key, mapping))
        return self
    
    def sadd(self, key, *values):
        self.commands.append(('sadd', key, values))
        return self
    
    def srem(self, key, *values):
        self.commands.append(('srem', key, values))
        return self
    
    def lpush(self, key, *values):
        self.commands.append(('lpush', key, values))
        return self
    
    def incr(self, key):
        self.commands.append(('incr', key))
        return self
    
    def incrby(self, key, amount):
        self.commands.append(('incrby', key, amount))
        return self
    
    def execute(self):
        results = []
        for cmd in self.commands:
            if cmd[0] == 'hset':
                _, key, mapping, kwargs = cmd
                result = self.redis.hset(key, mapping, **kwargs)
                results.append(result)
            elif cmd[0] == 'zadd':
                _, key, mapping = cmd
                result = self.redis.zadd(key, mapping)
                results.append(result)
            elif cmd[0] == 'sadd':
                _, key, values = cmd
                result = self.redis.sadd(key, *values)
                results.append(result)
            elif cmd[0] == 'srem':
                _, key, values = cmd
                result = self.redis.srem(key, *values)
                results.append(result)
            elif cmd[0] == 'lpush':
                _, key, values = cmd
                result = self.redis.lpush(key, *values)
                results.append(result)
            elif cmd[0] == 'incr':
                _, key = cmd
                result = self.redis.incr(key)
                results.append(result)
            elif cmd[0] == 'incrby':
                _, key, amount = cmd
                result = self.redis.incrby(key, amount)
                results.append(result)
        return results